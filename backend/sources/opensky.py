"""OpenSky PollAdapter (spec: design/specs/opensky.md).

Slice opensky-adapter/01 (issue #13) implemented the OAuth2 client-credentials
token manager: `OpenSkyCfg`, a minimal `CreditLedger`, and
`OpenSkyAdapter.start()`/`stop()` wired to an internal single-flight
`_TokenManager`. This slice (opensky-adapter/02, issue #14) implements
`fetch()` (the `/states/all` request + response parsing into a
`LayerSnapshot(domain=AIR)`) and extends `CreditLedger` with live spend
tracking, UTC-midnight rollover, and the `warn` threshold.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import httpx
from pydantic import BaseModel, ValidationError

from backend.config import Secrets, estimate_credits
from backend.models import (
    Domain,
    Feature,
    FeatureStatus,
    GeometryType,
    LayerSnapshot,
    LayerSnapshotMeta,
    LayerStatus,
)
from backend.sources.base import (
    AuthError,
    ParseError,
    PollAdapter,
    RateLimitedError,
    Region,
    UpstreamError,
)

# opensky.md "position_source int->label" (FR2 popup).
_POSITION_SOURCE_LABELS = {0: "ADS-B", 1: "ASTERIX", 2: "MLAT", 3: "FLARM"}


class OpenSkyCfg(BaseModel):
    """`[opensky]` table + `[layers.air]` (config.md). Constructed as
    `OpenSkyCfg(**cfg.opensky, **cfg.layers["air"].model_dump())`."""

    # [opensky]
    token_url: str
    states_url: str
    token_refresh_margin_s: float
    daily_credit_budget: int
    credit_warn_ratio: float

    # [layers.air] (LayerCfg.model_dump())
    enabled: bool = True
    cadence_s: int
    cadence_floor_s: int
    stale_multiplier: int = 2
    custom_bbox_cap_sq_deg: float
    deemphasize_after_s: int | None = None
    drop_after_s: int | None = None
    simplify_tolerance_deg: float | None = None
    max_rendered_features: int | None = None


class CreditLedger:
    """Shared daily-budget accountant (design/specs/opensky.md "Credit
    accounting"). A single instance backs both `estimate_credits` (FR1 UI) and
    live spend: `spend()` decrements `remaining` on each successful fetch,
    rolling over to a fresh `budget` at UTC midnight; `override_remaining()`
    lets a `fetch` response's `X-Rate-Limit-Remaining` header (server truth)
    supersede the local estimate. `warn_ratio` mirrors `[opensky]
    credit_warn_ratio` (0.5 default per opensky.md) for the `warn` property.
    """

    def __init__(self, budget: int, warn_ratio: float = 0.5) -> None:
        self.budget = budget
        self.remaining = budget
        self.warn_ratio = warn_ratio
        self._day: date = datetime.now(timezone.utc).date()

    def _rollover_if_needed(self, now: datetime) -> None:
        today = now.date()
        if today != self._day:
            self._day = today
            self.remaining = self.budget

    def spend(self, amount: int, *, now: datetime | None = None) -> None:
        """Decrement `remaining` by `amount` for a successful fetch,
        rolling over first if UTC midnight has passed since the last spend."""
        now = now or datetime.now(timezone.utc)
        self._rollover_if_needed(now)
        self.remaining -= amount

    def override_remaining(self, remaining: int, *, now: datetime | None = None) -> None:
        """Server truth (`X-Rate-Limit-Remaining`) supersedes the local
        estimate (opensky.md "Credit accounting")."""
        now = now or datetime.now(timezone.utc)
        self._rollover_if_needed(now)
        self.remaining = remaining

    @property
    def spent(self) -> int:
        return self.budget - self.remaining

    @property
    def warn(self) -> bool:
        if self.budget <= 0:
            return False
        return (self.spent / self.budget) > self.warn_ratio


class _TokenManager:
    """OAuth2 client-credentials token manager (design/specs/opensky.md
    "Token manager"). Single-flight: `_lock` re-checks validity inside the
    lock before fetching, so N concurrent acquisitions trigger at most one
    token request. Proactive refresh at `expires_at - token_refresh_margin_s`.
    """

    def __init__(self, cfg: OpenSkyCfg, secrets: Secrets, client: httpx.AsyncClient):
        self._cfg = cfg
        self._secrets = secrets
        self._client = client
        self._access_token: str | None = None
        self._expires_at: datetime | None = None
        self._lock = asyncio.Lock()

    def _is_valid(self, now: datetime) -> bool:
        if self._access_token is None or self._expires_at is None:
            return False
        margin = self._cfg.token_refresh_margin_s
        return now < self._expires_at - timedelta(seconds=margin)

    async def get_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._is_valid(now):
            return self._access_token  # type: ignore[return-value]
        async with self._lock:
            now = datetime.now(timezone.utc)
            if self._is_valid(now):
                return self._access_token  # type: ignore[return-value]
            await self._fetch_token(now)
        return self._access_token  # type: ignore[return-value]

    async def _fetch_token(self, now: datetime) -> None:
        try:
            response = await self._client.post(
                self._cfg.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._secrets.opensky_client_id,
                    "client_secret": self._secrets.opensky_client_secret,
                },
            )
        except httpx.HTTPError as exc:
            self._access_token = None
            self._expires_at = None
            raise AuthError("opensky token endpoint connection failure") from exc

        if response.status_code < 200 or response.status_code >= 300:
            self._access_token = None
            self._expires_at = None
            raise AuthError(
                f"opensky token endpoint returned {response.status_code}"
            )

        body = response.json()
        self._access_token = body["access_token"]
        self._expires_at = now + timedelta(seconds=body["expires_in"])

    def invalidate(self) -> None:
        """Drop the cached token so the next `get_token()` re-fetches
        (opensky.md failure table: 401/403 "invalidate cached token first so
        next attempt re-fetches")."""
        self._access_token = None
        self._expires_at = None


class OpenSkyAdapter(PollAdapter):
    domain = Domain.AIR
    source = "opensky"

    def __init__(self, cfg: OpenSkyCfg, secrets: Secrets, credits: CreditLedger):
        self._cfg = cfg
        self._secrets = secrets
        self._credits = credits
        self._client: httpx.AsyncClient | None = None
        self._token_manager: _TokenManager | None = None

    async def start(self) -> None:
        """Open the shared AsyncClient (idempotent) and prefetch a token.
        Concurrent `start()` calls race on the same `_TokenManager._lock`, so
        at most one token request is ever in flight."""
        opened_client = self._client is None
        opened_token_manager = self._token_manager is None
        if self._client is None:
            self._client = httpx.AsyncClient()
        if self._token_manager is None:
            self._token_manager = _TokenManager(
                self._cfg, self._secrets, self._client
            )
        try:
            await self._token_manager.get_token()
        except Exception:
            if opened_client:
                await self._client.aclose()
                self._client = None
            if opened_token_manager:
                self._token_manager = None
            raise

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch(self, region: Region) -> LayerSnapshot:
        """Fetch `/states/all` for `region.bbox` and parse it into a
        `LayerSnapshot(domain=AIR)` (design/specs/opensky.md "Request" +
        "Response parsing"). Reuses `start()`'s shared client/token manager if
        present, else opens them lazily (spec: "ensure the shared AsyncClient
        is open")."""
        if self._client is None:
            self._client = httpx.AsyncClient()
        if self._token_manager is None:
            self._token_manager = _TokenManager(
                self._cfg, self._secrets, self._client
            )

        now = datetime.now(timezone.utc)
        token = await self._token_manager.get_token()

        west, south, east, north = region.bbox
        try:
            response = await self._client.get(
                self._cfg.states_url,
                params={
                    "lamin": south,
                    "lomin": west,
                    "lamax": north,
                    "lomax": east,
                },
                headers={"Authorization": f"Bearer {token}"},
                timeout=30.0,
            )
        except httpx.TimeoutException as exc:
            raise UpstreamError("opensky states request timed out") from exc
        except httpx.TransportError as exc:
            raise UpstreamError("opensky states request transport error") from exc

        status = response.status_code
        if status == 429:
            retry_after_header = response.headers.get("Retry-After")
            retry_after: float | None = None
            if retry_after_header is not None:
                try:
                    retry_after = float(retry_after_header)
                except ValueError:
                    # RFC 7231 also allows an HTTP-date here; we don't parse
                    # that form. Falling back to None matches the spec's
                    # "header absent" semantics (scheduler uses config backoff).
                    retry_after = None
            raise RateLimitedError(retry_after=retry_after)
        if status in (401, 403):
            self._token_manager.invalidate()
            raise AuthError(f"opensky states endpoint returned {status}")
        if status >= 500 or status < 200 or status >= 300:
            raise UpstreamError(f"opensky states endpoint returned {status}")

        try:
            body = response.json()
        except ValueError as exc:
            raise ParseError("opensky states response was not valid JSON") from exc

        features, newest_source_ts = self._parse_states(body, now)

        snapshot = LayerSnapshot(
            meta=LayerSnapshotMeta(
                layer=Domain.AIR,
                region_id=region.id,
                status=LayerStatus.LIVE,
                timestamp_fetched=now,
                timestamp_source=newest_source_ts,
                cadence_s=self._cfg.cadence_s,
                stale_after_s=2 * self._cfg.cadence_s,
                feature_count=len(features),
            ),
            features=features,
        )

        # Credit accounting: decrement on success, then let server truth
        # (X-Rate-Limit-Remaining) override the estimate if present.
        self._credits.spend(self.estimate_credits(region.bbox), now=now)
        rate_limit_remaining = response.headers.get("X-Rate-Limit-Remaining")
        if rate_limit_remaining is not None:
            self._credits.override_remaining(int(rate_limit_remaining), now=now)

        return snapshot

    def _parse_states(
        self, body: object, now: datetime
    ) -> tuple[list[Feature], datetime | None]:
        """Parse the `{"time": int, "states": [...]}` body into `Feature`s
        per opensky.md's 17-element index map. Any schema/shape failure
        becomes a `ParseError` (2xx-but-invalid, opensky.md failure table)."""
        try:
            states = body["states"] or []  # type: ignore[index]
        except (TypeError, KeyError) as exc:
            raise ParseError(
                "opensky states response missing 'states' array"
            ) from exc

        deemphasize_after_s = self._cfg.deemphasize_after_s
        features: list[Feature] = []
        newest_source_ts: datetime | None = None

        for vector in states:
            try:
                lon = vector[5]
                lat = vector[6]
                if lat is None or lon is None:
                    continue  # opensky.md: "Null lat/lon -> drop the state"

                callsign = vector[1]
                label = callsign.strip() if callsign else None
                label = label or None

                time_position = vector[3]
                timestamp_source = (
                    datetime.fromtimestamp(time_position, tz=timezone.utc)
                    if time_position is not None
                    else None
                )
                position_age_s = (
                    (now - timestamp_source).total_seconds()
                    if timestamp_source is not None
                    else None
                )
                status = (
                    FeatureStatus.STALE
                    if (
                        position_age_s is not None
                        and deemphasize_after_s is not None
                        and position_age_s > deemphasize_after_s
                    )
                    else FeatureStatus.LIVE
                )

                position_source_raw = vector[16]
                position_source = (
                    _POSITION_SOURCE_LABELS.get(
                        position_source_raw, str(int(position_source_raw))
                    )
                    if position_source_raw is not None
                    else None
                )

                feature = Feature(
                    domain=Domain.AIR,
                    source=self.source,
                    source_id=vector[0],
                    label=label,
                    lat=lat,
                    lon=lon,
                    geometry_type=GeometryType.POINT,
                    geometry=None,
                    timestamp_source=timestamp_source,
                    timestamp_fetched=now,
                    position_age_s=position_age_s,
                    status=status,
                    attrs={
                        "origin_country": vector[2],
                        "altitude_m": vector[7],
                        "on_ground": vector[8],
                        "velocity_ms": vector[9],
                        "true_track_deg": vector[10],
                        "vertical_rate_ms": vector[11],
                        "geo_altitude_m": vector[13],
                        "squawk": vector[14],
                        "position_source": position_source,
                    },
                    # In-memory only (Feature.raw_payload: exclude=True); a
                    # state vector is a list, so it is wrapped in a dict here
                    # (raw_payload is typed dict | None) but the vector itself
                    # is carried through untouched.
                    raw_payload={"state_vector": vector},
                )
            except (IndexError, KeyError, TypeError, ValidationError) as exc:
                raise ParseError(
                    f"opensky state vector failed validation: {exc}"
                ) from exc

            features.append(feature)
            if timestamp_source is not None and (
                newest_source_ts is None or timestamp_source > newest_source_ts
            ):
                newest_source_ts = timestamp_source

        return features, newest_source_ts

    def estimate_credits(self, bbox: tuple[float, float, float, float]) -> int:
        return estimate_credits(bbox)
