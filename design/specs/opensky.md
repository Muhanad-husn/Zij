# Spec — `sources/opensky.py` (OpenSky PollAdapter)

**Purpose.** Aviation `PollAdapter` (§6.1, D5): OAuth2-authenticated `/states/all` fetch for the active region's bbox, parsed into `Feature` points, with credit accounting for FR1's pre-activation estimate. Returns `LayerSnapshot(domain=AIR)` ([feature-schema.md](../contracts/feature-schema.md), [adapter-interface.md](../contracts/adapter-interface.md)).

Contracts honored: adapter never sets `LayerStatus`; raises the typed taxonomy; leaves `meta.status = LIVE` for the scheduler to overwrite.

## Public interface

```python
class OpenSkyAdapter(PollAdapter):
    domain = Domain.AIR
    source = "opensky"

    def __init__(self, cfg: OpenSkyCfg, secrets: Secrets, credits: CreditLedger): ...

    async def start(self) -> None                     # open AsyncClient, prefetch token
    async def stop(self) -> None                       # close AsyncClient
    async def fetch(self, region: Region) -> LayerSnapshot
    def estimate_credits(self, bbox: tuple[float,float,float,float]) -> int  # FR1, sync, no I/O
```

`OpenSkyCfg` = the `[opensky]` table + `[layers.air]` (config.md). `CreditLedger` is the shared daily-budget accountant (below); a single instance is injected so the same ledger backs both `estimate_credits` (FR1 UI) and live spend.

## Internal design

### Token manager (OAuth2 client-credentials)
- Endpoint `cfg.token_url`; body `grant_type=client_credentials`, `client_id`, `client_secret` (from `Secrets`, NFR5). Implemented as an httpx auth flow ([ADR-9](../docs/DECISIONS.md#adr-9--http--websocket-clients)) or an explicit `_TokenManager` awaited before each request — the latter is clearer; use it.
- State: `_access_token: str | None`, `_expires_at: datetime | None`, `_lock: asyncio.Lock`.
- Expiry ~30 min from the token response `expires_in`. **Proactive refresh:** treat the token as expired at `expires_at - cfg.token_refresh_margin_s` (120 s, config) — i.e. refresh at ≥~80% of lifetime with a 2-min floor margin.
- **Single-flight:** `async with self._lock:` re-checks validity inside the lock before fetching, so N concurrent `fetch` calls trigger at most one token request.
- Token fetch failure (any non-2xx, connection error) → `AuthError` (surfaces, no auto-retry per taxonomy).

### Request
- `GET cfg.states_url?lamin={s}&lomin={w}&lamax={n}&lomax={e}` with bbox from `region.bbox = [w,s,e,n]`; `Authorization: Bearer <token>`; httpx per-request timeout 30 s.
- One shared `AsyncClient` per adapter (connection reuse = credit-cheap, [ADR-9](../docs/DECISIONS.md#adr-9--http--websocket-clients)). `fetch` is pure awaits → cancellable; client closed in `stop()`/`finally`.

### Response parsing (17-element state vector)
Top-level `{"time": int, "states": [[...], ...]}`. Each state vector, indices:

| idx | field | maps to |
|---|---|---|
| 0 | icao24 | `source_id` |
| 1 | callsign | `label` (strip; `None` if blank) |
| 2 | origin_country | `attrs.origin_country` |
| 3 | time_position | `timestamp_source` (epoch→UTC; **null → `timestamp_source=None`**, Mode S gap) |
| 4 | last_contact | `attrs.last_contact` (used only if needed; not the source ts) |
| 5 | longitude | `lon` |
| 6 | latitude | `lat` |
| 7 | baro_altitude | `attrs.altitude_m` |
| 8 | on_ground | `attrs.on_ground` |
| 9 | velocity | `attrs.velocity_ms` |
| 10 | true_track | `attrs.true_track_deg` |
| 11 | vertical_rate | `attrs.vertical_rate_ms` |
| 12 | sensors | ignored |
| 13 | geo_altitude | `attrs.geo_altitude_m` |
| 14 | squawk | `attrs.squawk` |
| 15 | spi | ignored |
| 16 | position_source | `attrs.position_source` via label map below |

- **`position_source` int→label** (FR2 popup): `0→"ADS-B"`, `1→"ASTERIX"`, `2→"MLAT"`, `3→"FLARM"`; unknown→`str(int)`.
- **Null lat/lon → drop the state** (no position to render; §6.1 Mode S-only case).
- `timestamp_source`: use idx 3 `time_position` (position-fix time), **not** idx 4 `last_contact`. `position_age_s = (now - timestamp_source).total_seconds()` when non-null, else `None`.
- `geometry_type = POINT`, `geometry = None`. `raw_payload =` the untouched state array (in-memory only; excluded from wire, [feature-schema.md](../contracts/feature-schema.md#raw_payload-handling)).
- `status`: stamp `FeatureStatus.STALE` when `position_age_s > [layers.air].deemphasize_after_s` (60 s, FR2) at fetch time, else `FeatureStatus.LIVE`. Air state vectors rarely exceed 60 s at fetch time, but the rule is uniform across adapters (aisstream.md stamps identically against marine's `deemphasize_after_s`). The renderer additionally ages features client-side between snapshots (frontend.md §9): a feature is de-emphasized if wire `status == STALE` **OR** the client-computed age exceeds the same config threshold — so freshness is never coarser than the SSE cadence allows.
- Pydantic validation failure on any field → `ParseError` (bad upstream payload becomes typed, not silent corruption, [ADR-1](../docs/DECISIONS.md#adr-1--pydantic-v2)).
- `meta.timestamp_source` = newest non-null feature `timestamp_source` (representative). `meta.feature_count = len(features)`.

### Credit accounting (`CreditLedger`)
- **Cost estimate from bbox area** using the config.md tier table (`≤25→1, ≤100→2, ≤400→3, else 4`); `area_sq_deg = (e-w)*(n-s)`. `estimate_credits` returns this synchronously for FR1 and `POST /api/regions/estimate` ([api.md](../contracts/api.md#post-apiregionsestimate)).
- **Live tracking:** on each successful `fetch`, decrement `remaining` by the estimated cost; roll over at UTC midnight; `budget = cfg.daily_credit_budget` (4000). If a response carries `X-Rate-Limit-Remaining`, treat it as authoritative and overwrite the local counter (server truth > estimate). Expose `remaining`, `budget`, `warn` (`spent/budget > cfg.credit_warn_ratio`, 0.5) for `GET /api/config` / a status field.
- The ledger never blocks a fetch by itself; budget exhaustion manifests as an upstream `429` (below). Warn ratio is advisory (success criterion §13.4).

### Concurrency
Single adapter task per the scheduler; `fetch` reentrancy is the scheduler's coalescing concern, not the adapter's. Token lock is the only internal lock.

## Failure modes

| Condition | Raise |
|---|---|
| Token endpoint non-2xx / connection fail | `AuthError` |
| `401`/`403` on `/states/all` (token rejected) | `AuthError` (invalidate cached token first so next attempt re-fetches) |
| `429` | `RateLimitedError(retry_after=<Retry-After header, float>)`; if header absent, `retry_after=None` (scheduler falls back to config backoff) |
| `5xx`, timeout, `httpx.TransportError` | `UpstreamError` |
| 2xx but JSON/schema invalid | `ParseError` |

## Configuration consumed
`[opensky]` (`token_url`, `states_url`, `token_refresh_margin_s`, `daily_credit_budget`, `credit_warn_ratio`); `[layers.air]` (`custom_bbox_cap_sq_deg`, `deemphasize_after_s`); secrets `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET` (config.md).

## Acceptance criteria
- [ ] **FR2** — parses ≤500 states into `Feature`s with correct `position_source` labels and `position_age_s`; returns within budget for the ≤5 s render target (NFR4).
- [ ] **FR2** — a `429` raises `RateLimitedError` carrying `Retry-After`; scheduler surfaces `rate-limited` and honors it.
- [ ] **FR2** — states with null lat/lon are dropped; states with null `time_position` yield `timestamp_source=None`, `position_age_s=None`, still rendered.
- [ ] **FR1** — `estimate_credits(bbox)` matches the config.md tier table for all seven predefined regions and priced-before-activation for custom bboxes.
- [ ] **D5/§13.4** — daily spend tracked against 4000-credit budget; `warn` fires at 50%; `X-Rate-Limit-Remaining` overrides the local estimate when present.
- [ ] **NFR5** — credentials read only from env/`Secrets`; never logged, never in `raw_payload` or any wire body.
- [ ] Token refreshes proactively (≥~80% lifetime / 120 s margin); concurrent fetches trigger ≤1 token request (single-flight).
