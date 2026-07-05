# Backlog — subproject `v0` (source-validation spike)

**Status: FILED — founder approved 2026-07-05. Issues #9–#20 created; plans back-linked.**

This is the review artifact for `/sprint-plan v0`. Each section below is one filed GitHub
issue: title, body, acceptance criterion, blocked-by, labels, and its linked slice plan.
The "Issue N" section headers below are the drafting order; the real GitHub numbers are in
the mapping table (drafting order N → GitHub #N+8).

## Filed issue numbers (drafting order → GitHub)

| # | Issue | GitHub | Plan |
|---|-------|--------|------|
| 1 | models — Feature/LayerSnapshot schema | [#9](https://github.com/Muhanad-husn/Zij/issues/9) | `plans/models/01-feature-schema.md` |
| 2 | config — loader + secret isolation | [#10](https://github.com/Muhanad-husn/Zij/issues/10) | `plans/config/01-config-loader.md` |
| 3 | store — SQLite land_cache | [#11](https://github.com/Muhanad-husn/Zij/issues/11) | `plans/store/01-land-cache.md` |
| 4 | fixtures — capture script + payloads | [#12](https://github.com/Muhanad-husn/Zij/issues/12) | `plans/fixtures/01-fixture-capture.md` |
| 5 | opensky — token manager | [#13](https://github.com/Muhanad-husn/Zij/issues/13) | `plans/opensky-adapter/01-token-manager.md` |
| 6 | opensky — fetch AIR ⭐ | [#14](https://github.com/Muhanad-husn/Zij/issues/14) | `plans/opensky-adapter/02-fetch-states.md` |
| 7 | overpass — fetch LAND ⭐ | [#15](https://github.com/Muhanad-husn/Zij/issues/15) | `plans/overpass-adapter/01-fetch-land.md` |
| 8 | overpass — simplify + cap | [#16](https://github.com/Muhanad-husn/Zij/issues/16) | `plans/overpass-adapter/02-simplify.md` |
| 9 | api — app/health/config/static | [#17](https://github.com/Muhanad-husn/Zij/issues/17) | `plans/backend-api/01-app-health-config.md` |
| 10 | api — snapshots + refresh | [#18](https://github.com/Muhanad-husn/Zij/issues/18) | `plans/backend-api/02-data-endpoints.md` |
| 11 | frontend — static Hormuz map ⭐ | [#19](https://github.com/Muhanad-husn/Zij/issues/19) | `plans/frontend-map/01-map-init.md` |
| 12 | frontend — layers + refresh | [#20](https://github.com/Muhanad-husn/Zij/issues/20) | `plans/frontend-map/02-layers-refresh.md` |

⭐ walking skeleton. In-issue blocked-by references use the GitHub numbers above.

## Scope recap (the boundary these issues respect)

v0 = FastAPI + one static MapLibre page, **OpenSky + Overpass only**, **Hormuz hardcoded**,
**manual refresh only** (PRD §11; STRUCTURE §7). Purpose: validate credit math, Overpass
payload sizes, and render performance with real theater data. Everything here survives into v1.

**Founder decisions folded in (2026-07-05):**
- **REST-only, no SSE** for v0 (SSE + registry push land in v1 with the scheduler).
- **Fixtures via a capture script** (`scripts/fetch_fixtures.py`), run once by the founder;
  the recorded Hormuz payloads are committed and every test runs against them (no live upstream in CI).

**Trimmed out of v0 vs. the raw triage decomposition (deferred to v1, with rationale):**
- `integrity.py` / FR9 flags — STRUCTURE §7 lists integrity under **v1**, not the spike.
- `POST /api/regions/activate` + `/estimate`, layer toggles, caveat panel, region picker,
  custom-bbox flow — all FR1/FR9 v1 UI; Hormuz is hardcoded, so the spike needs none of them.
- Marine (aisstream) layer, scheduler, `fallback_snapshots`/`config_presets` tables — v1.

## Labels

- Every issue carries **`sub:v0`** (exists).
- Type label: **`enhancement`** on product slices; the fixtures issue is dev tooling (noted).
- Workflow labels already exist: `spec-drift`, `blocked`, `needs-context`, `done-with-concerns`.
- No new labels required.

## Dependency graph & suggested filing / build order

```
1 models
2 config ── needs 1
3 store  ── needs 1
4 fixtures (tooling; founder runs the script)
5 opensky/01 token ───── needs 1,2   (introduces sources/base.py)
6 opensky/02 fetch ⭐ ── needs 5,4
7 overpass/01 fetch ⭐ ─ needs 5(base),4
8 overpass/02 simplify ─ needs 7
9 api/01 app+health ──── needs 2
10 api/02 data+refresh ─ needs 9,6,7,3
11 frontend/01 map ⭐ ── needs nothing backend (parallelizable from day 1)
12 frontend/02 layers ── needs 11,10
```

⭐ walking skeleton. Critical path: 1 → 2 → 5 → 6/7 → 10 → 12.

---

## Issue 1 — models: Feature schema and enums

**Title:** `feat(models): Feature/LayerSnapshot schema and enums per contract`
**Labels:** `sub:v0`, `enhancement`
**Blocked-by:** none
**Plan:** `plans/models/01-feature-schema.md`

**Body:**
> Implement `backend/models.py` verbatim from `design/contracts/feature-schema.md`: the
> `Feature`, `LayerSnapshot`, `LayerSnapshotMeta` Pydantic v2 models and the `Domain`,
> `GeometryType`, `FeatureStatus`, `IntegrityFlag`, `LayerStatus` enums. Pure schema — no
> source/SQLite/HTTP knowledge (STRUCTURE §4). The shared vocabulary every other module speaks.
>
> **Acceptance:** Given `backend.models`, when a `Feature` is built from the air wire example
> and dumped, then it validates (UTC-aware datetimes, lat∈[-90,90], lon∈[-180,180],
> `extra="forbid"`), `raw_payload` is excluded from the dump, and a `LayerSnapshot` wrapping
> it round-trips through `model_validate()` unchanged.
>
> Out of scope: integrity-flag computation (v1); any I/O. Plan: `plans/models/01-feature-schema.md`.

---

## Issue 2 — config: loader with precedence + secret isolation

**Title:** `feat(config): load_config() with precedence, region registry, secret isolation`
**Labels:** `sub:v0`, `enhancement`
**Blocked-by:** #1 (models)
**Plan:** `plans/config/01-config-loader.md`

**Body:**
> Implement `backend/config.py` + bundled `backend/config.toml` per `design/contracts/config.md`
> and `design/specs/config-module.md`. v0 populates the 7 predefined regions and the
> `[opensky]`/`[overpass]`/`[layers.air]`/`[layers.land]` sections only. `load_config()`
> returns `(AppConfig, Secrets)`; secrets come from env/`.env` only and never appear in
> `AppConfig`. Exposes the aviation credit-tier estimate (config.md tier table).
>
> **Acceptance:** Given the bundled TOML with the 7 regions and OpenSky env vars set, when
> `load_config()` runs, then `hormuz` has bbox `[55.0,25.0,57.5,27.5]`, the Hormuz aviation
> credit estimate is 1, `Secrets` carries the OpenSky values, and dumping `AppConfig` to JSON
> exposes neither the client id nor the secret (NFR5).
>
> Out of scope: user-TOML/`ZIJ_` env/DB-override layers, marine/integrity sections, the
> custom-bbox activation UI (all v1). Plan: `plans/config/01-config-loader.md`.

---

## Issue 3 — store: SQLite land_cache round-trip

**Title:** `feat(store): SQLite land_cache table + round-trip`
**Labels:** `sub:v0`, `enhancement`
**Blocked-by:** #1 (models)
**Plan:** `plans/store/01-land-cache.md`

**Body:**
> Implement `backend/store.py` + `backend/schema.sql` for the `land_cache` table only (D4;
> STRUCTURE §7). `init_schema` is idempotent; `put_land_cache`/`get_land_cache` round-trip a
> region's render-ready GeoJSON with its `osm_base` and `fetched_at`. Never parses source
> payloads (STRUCTURE §3).
>
> **Acceptance:** Given a fresh DB from `schema.sql`, when a Hormuz row is put then got, then
> it returns the same `feature_count`/`geojson`, `osm_base` re-hydrates as UTC-aware equal to
> the stored value, and an unknown region returns `None`.
>
> Out of scope: `fallback_snapshots`/`config_presets` tables (v1); cache freshness policy
> (backend-api wiring). Plan: `plans/store/01-land-cache.md`.

---

## Issue 4 — fixtures: capture + commit the real Hormuz payloads (tooling)

**Title:** `chore(fixtures): capture script + recorded Hormuz OpenSky/Overpass payloads`
**Labels:** `sub:v0` (dev tooling — no `enhancement`)
**Blocked-by:** none (but the founder runs the script with OpenSky creds)
**Plan:** `plans/fixtures/01-fixture-capture.md`

**Body:**
> Add `scripts/fetch_fixtures.py`: run with OpenSky credentials in the environment, it fetches
> the live `/states/all` and six-class Overpass responses for the Hormuz bbox and writes them
> verbatim to `backend/tests/fixtures/opensky_states_all_hormuz.json` and `overpass_hormuz.json`
> (committed). These recorded payloads are v0's real-data substrate; the two walking-skeleton
> slices write their locked tests against them, so no slice depends on a live upstream.
>
> **Acceptance:** Given the committed fixtures, when loaded in a test, then the OpenSky fixture
> has `time:int` + `states:list` with 17-element vectors, and the Overpass fixture has
> `osm3s.timestamp_osm_base` + a non-empty `elements` list spanning node and way types.
>
> Note: dev-time tooling under `scripts/` (not product code), so it uses a lightweight shape
> check rather than the full DEC-1 endpoint ceremony; the tests-green gate still applies.
> OpenSky creds are already in `.env` (founder, 2026-07-05). Plan: `plans/fixtures/01-fixture-capture.md`.

---

## Issue 5 — opensky: OAuth2 token manager

**Title:** `feat(opensky): OAuth2 client-credentials token manager (single-flight, proactive refresh)`
**Labels:** `sub:v0`, `enhancement`
**Blocked-by:** #1 (models), #2 (config)
**Plan:** `plans/opensky-adapter/01-token-manager.md`

**Body:**
> Implement the OpenSky adapter's token manager per `design/specs/opensky.md`, and introduce
> `backend/sources/base.py` (the `SourceAdapter`/`PollAdapter` ABCs, `Region`, and the
> `AdapterError` taxonomy) — the first adapter needs it. `start()` fetches a bearer token once,
> caches it, refreshes at `token_refresh_margin_s` before expiry, and single-flights concurrent
> acquisitions to at most one token request.
>
> **Acceptance:** Given a started adapter with the token endpoint mocked, when three token
> acquisitions are awaited concurrently, then exactly one token request is made and all share
> the cached token; advancing to within the refresh margin triggers exactly one refresh; a
> non-2xx token response raises `AuthError` (no retry).
>
> Out of scope: the `/states/all` fetch + credit accounting (#6); scheduler cadence (v1).
> Plan: `plans/opensky-adapter/01-token-manager.md`.

---

## Issue 6 — opensky: fetch /states/all → LayerSnapshot(AIR) ⭐ walking skeleton

**Title:** `feat(opensky): fetch() parses real Hormuz /states/all into LayerSnapshot(AIR) + credit accounting`
**Labels:** `sub:v0`, `enhancement`
**Blocked-by:** #5 (token manager), #4 (fixtures)
**Plan:** `plans/opensky-adapter/02-fetch-states.md`

**Body:**
> Walking skeleton (first real upstream data; validates the credit math). Implement
> `OpenSkyAdapter.fetch(region)` per `design/specs/opensky.md`: parse each 17-element state
> vector into a `Feature` (documented index map, `position_source` int→label), drop null
> lat/lon, map null `time_position` to `timestamp_source=None`/`position_age_s=None`, keep
> `raw_payload` in-memory only. The `CreditLedger` estimates 1 credit for Hormuz and decrements
> on success.
>
> **Acceptance:** Given the committed OpenSky fixture (httpx mocked to return it), when
> `fetch(hormuz)` is awaited, then it returns `LayerSnapshot(AIR)` with `feature_count` = states
> with non-null position, a known vector maps correctly (incl. `position_source` label),
> null-position states are dropped, `estimate_credits(hormuz)==1` and the ledger drops by 1,
> and the dumped body carries no `raw_payload`.
>
> Errors: 429→`RateLimitedError`, 5xx/timeout→`UpstreamError`, bad JSON→`ParseError`. Out of
> scope: scheduler coalescing (v1). Plan: `plans/opensky-adapter/02-fetch-states.md`.

---

## Issue 7 — overpass: fetch land → LayerSnapshot(LAND) ⭐ walking skeleton

**Title:** `feat(overpass): fetch() parses real Hormuz Overpass into LayerSnapshot(LAND) + osm_base`
**Labels:** `sub:v0`, `enhancement`
**Blocked-by:** #5 (for `sources/base.py`), #4 (fixtures)
**Plan:** `plans/overpass-adapter/01-fetch-land.md`

**Body:**
> Walking skeleton (first real land data; validates payload size + parsing). Implement
> `OverpassAdapter.fetch(region)` per `design/specs/overpass.md`: run the six whitelisted class
> queries (mocked to the recorded fixture), parse `elements` into `Feature`s (node/`out center`
> → POINT; way → LINESTRING in `[lon,lat]`; closed area → POLYGON+centroid), dedupe by
> `source_id`, and stamp every feature's `timestamp_source` with `osm3s.timestamp_osm_base`
> (oldest across responses).
>
> **Acceptance:** Given the committed Overpass fixture (httpx mocked), when `fetch(hormuz)` is
> awaited, then it returns `LayerSnapshot(LAND)` with a primary road as a `[lon,lat]` LINESTRING
> carrying OSM tags verbatim, a port/aerodrome node as a POINT, every feature's `timestamp_source`
> == the fixture `osm_base` (UTC), `meta.timestamp_source` == that `osm_base` (not fetch time),
> and a doubly-matched `source_id` present once.
>
> Errors: 429/504 rotate mirror then `UpstreamError`; bad JSON→`ParseError`. Out of scope:
> simplification (#8); cache policy (backend-api). Plan: `plans/overpass-adapter/01-fetch-land.md`.

---

## Issue 8 — overpass: Douglas-Peucker simplify + ≤5,000 drop priority

**Title:** `feat(overpass): Douglas-Peucker simplification + deterministic ≤5000 feature cap`
**Labels:** `sub:v0`, `enhancement`
**Blocked-by:** #7 (overpass fetch)
**Plan:** `plans/overpass-adapter/02-simplify.md`

**Body:**
> Simplify land geometry via shapely Douglas-Peucker at `simplify_tolerance_deg` (0.0005°) and,
> over `max_rendered_features` (5,000), drop lowest-value features first by the overpass.md
> deterministic priority (primary→mainline rail→trunk; shortest-within-tier first), never
> dropping motorway or point anchors. Same input ⇒ same output (cacheable).
>
> **Acceptance:** Given a synthetic 7,000-feature set over the cap, when simplification runs at
> tol 0.0005 / cap 5,000, then output ≤5,000, every motorway + point anchor retained, drops
> follow primary→rail→trunk shortest-first, two runs are identical, and simplified LineStrings
> have fewer vertices.
>
> Out of scope: fetch/parse (#7); cache write-through (backend-api). Plan: `plans/overpass-adapter/02-simplify.md`.

---

## Issue 9 — api: FastAPI app, health, config, static

**Title:** `feat(api): FastAPI app serves /api/health, /api/config, and static frontend`
**Labels:** `sub:v0`, `enhancement`
**Blocked-by:** #2 (config)
**Plan:** `plans/backend-api/01-app-health-config.md`

**Body:**
> Stand up `backend/main.py` (FastAPI, REST-only — no SSE in v0). `GET /api/health` returns
> `{status,version,uptime_s}`; `GET /api/config` returns the effective `AppConfig` (regions +
> layers) and never secrets (NFR5); the built frontend mounts as static files at `/` with
> `/api/*` taking precedence. Unknown `/api/*` paths use the api.md error envelope.
>
> **Acceptance:** Given the app with loaded config, when `GET /api/health` then 200 with the
> three fields; `GET /api/config` returns the 7 regions + air/land layers and no OpenSky
> credentials; an unknown `/api/*` path returns the error envelope; `/` serves `index.html`.
>
> Out of scope: data/refresh endpoints (#10); SSE, activation, toggles, caveats (v1).
> Plan: `plans/backend-api/01-app-health-config.md`.

---

## Issue 10 — api: REST snapshot + manual refresh endpoints

**Title:** `feat(api): /api/layers/{air,land}/snapshot + POST /api/refresh (Hormuz, manual)`
**Labels:** `sub:v0`, `enhancement`
**Blocked-by:** #9 (app), #6 (opensky fetch), #7 (overpass fetch), #3 (store)
**Plan:** `plans/backend-api/02-data-endpoints.md`

**Body:**
> With Hormuz hardcoded, wire the adapters to REST: `GET /api/layers/air/snapshot` → OpenSky
> `LayerSnapshot(AIR)` (no `raw_payload`); `GET /api/layers/land/snapshot` → serve fresh
> `land_cache` else fetch Overpass + write-through; `POST /api/refresh` → force a fresh fetch of
> both, return `{"queued":[...]}`. Adapter errors map to the api.md envelope; one layer failing
> never blocks the other (FR10).
>
> **Acceptance:** Given the app with Hormuz active and both upstreams mocked to the fixtures,
> when `GET air/snapshot` then a `LayerSnapshot(AIR)` with matching `feature_count` and no
> `raw_payload`; `GET land/snapshot` serves a warm cache without re-calling Overpass;
> `POST /api/refresh` → 202 `{"queued":["air","land"]}`; a 429 on air surfaces `rate_limited`
> while land still succeeds (FR10).
>
> Out of scope: SSE, scheduler, region activation, marine (v1). Plan: `plans/backend-api/02-data-endpoints.md`.

---

## Issue 11 — frontend: static Hormuz map ⭐ walking skeleton

**Title:** `feat(frontend): interactive night-ink MapLibre map centered on Hormuz`
**Labels:** `sub:v0`, `enhancement`
**Blocked-by:** none (parallelizable from day 1; evidence uses the backend static mount)
**Plan:** `plans/frontend-map/01-map-init.md`

**Body:**
> Walking skeleton (first visible product; validates the Vite build + render perf). Stand up
> `frontend/` (Vite + vanilla TS + MapLibre, ADR-3). Opening the app boots one interactive
> `Map` centered on the Hormuz bbox in the night-ink identity style (bg `#101D30`), rendering
> OpenFreeMap vector tiles with a visible OSM + OpenFreeMap attribution control. No CDN.
>
> **Acceptance (Playwright):** Given the built frontend at `/`, when opened, then a MapLibre
> canvas mounts centered on Hormuz (~26.25N, 56.25E), the attribution shows OSM + OpenFreeMap,
> the background is night-ink (not the default light basemap), and no uncaught console error
> fires.
>
> Out of scope: layer data, badges, refresh, region picker (#12 / v1). Web slice: Playwright
> outer + Vitest inner. Plan: `plans/frontend-map/01-map-init.md`.

---

## Issue 12 — frontend: air + land layers, manual refresh, UTC freshness

**Title:** `feat(frontend): render air+land from REST, manual refresh, UTC freshness display`
**Labels:** `sub:v0`, `enhancement`
**Blocked-by:** #11 (map), #10 (data endpoints)
**Plan:** `plans/frontend-map/02-layers-refresh.md`

**Body:**
> On load, fetch the air + land snapshots and render them on the Hormuz map (one GeoJSON source
> per domain, `setData`): aircraft as heading-rotated brass symbols; land as dun roads
> (motorway/trunk/primary width steps) + dashed rail + point anchors. A "Refresh" button calls
> `POST /api/refresh` and re-pulls. Each layer shows `timestamp_source`/`timestamp_fetched` in
> labeled UTC (NFR6) + a feature count.
>
> **Acceptance (Playwright):** Given the backend serving Hormuz snapshots, when the page loads,
> then aircraft render rotated by `true_track_deg` in brass, land roads render as dun lines
> (motorway thickest) with point anchors, each layer shows both UTC timestamps + a count; when
> Refresh is clicked, `POST /api/refresh` fires and the layers re-render.
>
> Out of scope: region picker, caveat panel, integrity markers, toggles, SSE, marine (v1). Web
> slice: Playwright outer + Vitest inner. Plan: `plans/frontend-map/02-layers-refresh.md`.

---

## On approval

I will, in the order above: ensure labels exist (all do), create issues #1–#12 via the
GitHub plugin (`issue_write`; falling back to `gh issue create` on a 403), record their real
numbers here, and back-link each plan's `Issue:` field from `TBD`. Then `/sprint-start` picks
the first unblocked issue (models). **No merge, no PR from `/sprint-plan`.**
