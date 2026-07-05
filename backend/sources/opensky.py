"""OpenSky PollAdapter (spec: design/specs/opensky.md).

This slice (opensky-adapter/01, issue #13) implements only the OAuth2
client-credentials token manager: `OpenSkyCfg`, `CreditLedger` (minimal,
constructible only -- credit-spend behavior is step), and
`OpenSkyAdapter.start()`/`stop()` wired to an internal single-flight
`_TokenManager`. `fetch()` (the `/states/all` request + response parsing) is
out of scope for this slice and is deferred to opensky-adapter/02.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from pydantic import BaseModel

from backend.config import Secrets
from backend.models import Domain, LayerSnapshot
from backend.sources.base import AuthError, PollAdapter, Region


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
    accounting"). This slice only needs it to be trivially constructible with
    a `budget`; live spend tracking/`estimate_credits`/`warn` land in
    opensky-adapter/02."""

    def __init__(self, budget: int) -> None:
        self.budget = budget
        self.remaining = budget


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
        if self._client is None:
            self._client = httpx.AsyncClient()
        if self._token_manager is None:
            self._token_manager = _TokenManager(
                self._cfg, self._secrets, self._client
            )
        await self._token_manager.get_token()

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch(self, region: Region) -> LayerSnapshot:
        raise NotImplementedError(
            "OpenSkyAdapter.fetch is implemented in opensky-adapter/02"
        )

    def estimate_credits(self, bbox: tuple[float, float, float, float]) -> int:
        from backend.config import estimate_credits

        return estimate_credits(bbox)
