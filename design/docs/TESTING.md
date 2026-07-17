# Zij — Test Strategy

Proportionate to a one-developer project (80/20, measure don't speculate). No test-pyramid essay — this is a backlog and a set of concrete test files. Companion doc: [`STRUCTURE.md`](STRUCTURE.md). References ADRs in [DECISIONS.md](DECISIONS.md), contracts in [contracts/](../contracts/).

## 1. Philosophy

Contract-level tests over unit micro-tests: a test earns its keep by exercising the boundary a contract file defines (adapter → `LayerSnapshot`, scheduler → status transitions, store → round-trip), not by covering every private helper. The PRD's FR1–FR10 acceptance checklists (§8) **are** the test backlog — each checkbox is either an automatable assertion or an operational/manual observation, never both pretend-tested.

The §13 success criteria are explicitly **not** a CI target: they're timing/behavior measurements "evaluated four weeks after v1 completion, from the operator's own usage log" (PRD §13) — i.e. observational, not a pytest assertion. Treat them as a checklist to look at in production, not a gate.

## 2. FR backlog: automatable vs. manual

| FR | Automatable (pytest/vitest) | Manual / observational |
|---|---|---|
| FR1 Region selection | Bbox cap rejection, credit-estimate math, "enabled layers only fetch" (API tests) | — |
| FR2 Aviation projection | OpenSky fixture parsing, de-emphasis at >60s (pure function of `position_age_s`), 429→rate-limited mapping | Visual: icons render heading-oriented within 5s (needs a browser) |
| FR3 Marine projection | Reconnect/backoff logic (fake server), 30min de-emphasis / 2h drop windows (time-injected) | Visual: popup content, actual websocket behavior against the live aisstream service |
| FR4 Land context | Cache-hit path <2s (store timing assertion), `osm_base` stored/displayed distinct from `fetched_at`, DP-simplification feature-count cap | First-load progress UI (visual) |
| FR5 Layer control | Toggle API stops/starts scheduling, disabled layer makes zero adapter calls | — |
| FR6 Refresh model | Coalescing: manual refresh during in-flight fetch triggers exactly one upstream call (fake adapter call-counter) | — |
| FR7 Freshness visibility | `stale = source_ts > 2×cadence` as a pure function; independence of per-layer cadence changes | Badge color/legibility (visual) |
| FR8 Session snapshots | SQLite round-trip; cold-start reads `fallback_snapshots` and labels `cached-fallback` with correct age | Actual restart/degraded-connection UX |
| FR9 Integrity caveats | Landmask point-in-polygon on synthetic points; kinematics threshold (>120kn / >Mach 3) on synthetic tracks | Caveat panel reachability/non-dismissibility (visual) |
| FR10 Failure isolation | Scheduler test: one fake adapter raises, others still update (independent try/except per layer) | "Zero sessions terminated" (§13.3 — production log only) |
| FR11 Presets (P1) | CRUD API tests incl. `409` on duplicate name | — |
| FR12 Packaging (v2) | Build-succeeds smoke check only | Everything else — out of scope until v2 |
| §13 success criteria | — | All 6 are operational measurements from usage logs, not CI (see §1) |

## 3. Backend — pytest + pytest-asyncio

Fixtures live in `backend/tests/fixtures/`, populated with **real recorded payloads** captured once (OpenSky `/states/all` for Hormuz, Overpass response for Hormuz, a run of aisstream messages) — see §7 on when each is captured, and the NOTE below on a scheduling gap in that plan.

| module under test | the 3–6 tests that matter |
|---|---|
| `sources/opensky.py` | (1) parses a recorded `states/all` fixture into valid `Feature`s; (2) OAuth2 token refresh triggers before ~30min expiry (respx-mocked token endpoint); (3) 429 with `Retry-After` raises `RateLimitedError(retry_after=...)`; (4) credit cost computed matches the area-tier table in [config.md](../contracts/config.md#predefined-regions-fr1); (5) malformed response raises `ParseError`, not a crash. |
| `sources/overpass.py` | (1) parses a recorded Overpass response, respects the tag whitelist (§6.3) — non-whitelisted tags dropped; (2) `osm_base` extracted and distinct from fetch time; (3) simplification keeps feature count ≤ configured `max_rendered_features`; (4) mirror fallback: first mirror 504s (respx), second succeeds; (5) exhausting `max_attempts` raises `UpstreamError`. |
| `sources/aisstream.py` | (1) feeding a recorded message stream into the read loop populates the MMSI table correctly; (2) `snapshot()` applies 30min de-emphasis / 2h drop against an injected `now`; (3) `connected` flips False on simulated disconnect, True after reconnect; (4) `set_region()` clears the table and re-sends a subscription; (5) `snapshot()` never performs I/O (asserted via a no-network fixture/fake socket). Use a **fake server** (a local asyncio websocket server or an injected async message iterator) rather than mocking the `websockets` library internals — cheaper and closer to real behavior. |
| `scheduler.py` | (1) status FSM: `loading→live`, `live→stale` purely from elapsed time (no new data) using **freezegun** to advance the clock past `2×cadence`; (2) `RateLimitedError` → `rate-limited`, honors `retry_after_s` before next attempt; (3) failure + warm `fallback_snapshots` row → `cached-fallback`, not `error`; (4) manual refresh coalesces onto an in-flight fetch (call-counter fake adapter, assert exactly one upstream call); (5) one fake adapter raising never stops another's tick (FR10 independence). **Clock control: freezegun**, not manual `now_fn` threading — the stale/backoff logic already calls `datetime.now(UTC)` directly per the contracts' code samples, and monkeypatching time is the smaller, more standard change (adding a clock-injection parameter through scheduler/adapter signatures would touch more of the contract's literal code for no extra safety). |
| `integrity.py` | (1) a marine point inside a synthetic land polygon (tiny fixture polygon, **not** the full Natural Earth landmask) → `spoof_suspect_on_land`; (2) a point in open water → no flag; (3) a synthetic marine track >120kn between consecutive reports → `implausible_kinematics`; (4) a synthetic air track >Mach 3 → same flag; (5) flags computed use native units per the [feature-schema.md units table](../contracts/feature-schema.md#units-decision) (sog_kn vs velocity_ms) — a unit-mixup regression test. |
| `store.py` | (1) `land_cache` upsert-on-conflict round-trips a GeoJSON blob on a `tmp_path` SQLite file; (2) `fallback_snapshots` PRIMARY KEY enforces exactly one row per layer (second write replaces, not appends); (3) `config_presets` UNIQUE(kind,name) raises on duplicate (409 mapping tested at the API layer, not here); (4) schema apply (`schema.sql`) is idempotent — running it twice against an existing DB is a no-op. |

Upstream HTTP calls are mocked with **respx** (already an ADR-5 dev dep). The websocket adapter is tested against a fake server/injected stream, not a mocked `websockets.connect`.

## 4. SSE / API — FastAPI TestClient + one SSE smoke test

- REST surface (`backend/tests/test_api.py`): region activate/estimate cap-rejection (FR1), layer toggle stops/starts scheduling (FR5), refresh coalescing returns `202` (FR6), error envelope shape/codes match [api.md](../contracts/api.md#error-envelope), raw-payload endpoint 404s once a feature rotates out.
- **One SSE smoke test**: connect to `/api/events` with `httpx-asgi` (or starlette's `TestClient` streaming support), assert the **first** events received are `snapshot` for each enabled layer (full-state-on-connect, [ADR-12](DECISIONS.md#adr-12--sse-reconnection)), then assert a `layer_status` event appears after a forced status change. Not a full SSE test matrix — one smoke test that the framing/ordering contract holds is enough at this scale.

## 5. Frontend — minimal and honest

**vitest** covers exactly two things, per [ADR-3](DECISIONS.md#adr-3--frontend-vite--vanilla-ts--maplibre)'s "small UI, no framework" stance:
1. The **state store** (`frontend/src/state/`): toggling a layer updates state correctly; applying a `snapshot` event replaces that layer's features; `region_changed` clears all layers.
2. The **SSE-client parsing** (`frontend/src/sse/`): raw `EventSource` message text → typed `LayerSnapshot`/`LayerSnapshotMeta` objects; malformed JSON doesn't crash the client.

**A thin Playwright e2e is the acceptance test for each frontend increment.** Each ships one Playwright test written and committed **red** before its implementation — the acceptance test the code then greens. Every such test asserts the invariant shell (the map mounts, MapLibre attribution is present, the night-ink background is applied, the page raises zero console errors) plus that increment's own behavioral clauses (a badge appears, a toggle hides a layer, the caveat panel opens, and so on). CI runs these on chromium (§7). It is deliberately *thin*: it exercises behavior a headless browser can assert cheaply, never pixel-level styling.

Interactions a browser test won't economically cover (real-network behavior, visual legibility, popup content) stay on a **manual smoke checklist** (run once per meaningful frontend change, referencing FR IDs):

1. [ ] FR1 — Select Hormuz; only enabled layers fetch (check network tab).
2. [ ] FR1 — Enter an oversized custom bbox; rejection message names the cap.
3. [ ] FR2 — Aircraft render heading-oriented within ~5s of a fetch; an old state vector looks de-emphasized.
4. [ ] FR3 — Kill network briefly; marine badge shows "reconnecting," then recovers.
5. [ ] FR4 — First Hormuz load shows a progress state; reload is near-instant from cache.
6. [ ] FR5 — Toggle land off; confirm no Overpass request fires on next refresh.
7. [ ] FR7 — Badge shows both timestamps; wait past 2×cadence with no data and confirm it flips to "stale."
8. [ ] FR8 — Restart the app; last snapshot appears immediately labeled "cached-fallback" with a plausible age.
9. [ ] FR9 — Caveat panel opens from every layer badge and cannot be permanently dismissed.
10. [ ] FR10 — Disable network access to one upstream only (e.g. block Overpass); confirm the other two layers keep working.

## 6. Deliberately NOT tested (and why)

| Not tested | Why |
|---|---|
| Pixel-level MapLibre style correctness (exact colors, glyph placement, icon rasterization) | MapLibre is a mature, externally-tested library; we only feed it GeoJSON. The Playwright test asserts the map *mounts* and behaves (§5); exact rendered pixels stay on the manual checklist's visual checks. |
| Upstream API liveness (OpenSky/aisstream/Overpass actually being up) | Not this project's to guarantee; adapters are tested against recorded fixtures, and the v0 spike (§7) is where real-service behavior gets *measured*, not asserted in CI. |
| Tauri/Capacitor shells | Don't exist until v2 (PRD §11); testing them now would be testing vaporware. When v2 starts, the shell-boundary contract ([ARCHITECTURE §6](ARCHITECTURE.md#6-the-shell-boundary-d1-no-rewrite-promise)) means the existing backend/frontend test suites carry over unchanged — only shell-hosting smoke tests get added. |
| §13 success criteria as CI assertions | Operational/usage-log measurements, not deterministic test conditions (§1). |

## 7. CI

Single GitHub Actions workflow, e.g. `.github/workflows/ci.yml`:

```
jobs:
  backend:
    runs-on: ubuntu-latest      # fine despite Windows dev machine — no OS-specific code paths (pure asyncio, stdlib sqlite3, no filesystem assumptions beyond platformdirs)
    steps:
      - setup Python 3.13
      - pip install -e ".[dev]"
      - ruff check .
      - ruff format --check .
      - pyright --outputjson || true    # advisory only, ADR-5 — never fails the job
      - pytest backend/tests

  frontend-unit:
    runs-on: ubuntu-latest
    steps:
      - setup Node LTS
      - npm ci --prefix frontend
      - npm run typecheck --prefix frontend
      - npm run test --prefix frontend    # vitest, §5
      - npm run build --prefix frontend

  frontend-e2e:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - setup Node LTS
      - npm ci --prefix frontend
      - npx playwright install --with-deps chromium
      - npm run test:e2e --prefix frontend        # the Playwright acceptance tests, §5
      - upload-artifact (if: always()): playwright-report/ + test-results/   # evidence, 14-day retention
```

The `frontend-e2e` job runs the Playwright acceptance tests (§5) on chromium: it installs the chromium browser with `playwright install --with-deps`, runs `npm run test:e2e`, and always uploads `playwright-report/` + `test-results/` as a build artifact so a red run's trace is inspectable. It is bounded by `timeout-minutes` because a hung headless browser must fail the job rather than idle the runner.

`ubuntu-latest` is fine for CI even though dev happens on Windows 11/conda — nothing in the stack (pure asyncio, stdlib `sqlite3`, `platformdirs` for paths) has an OS-specific branch; the one thing worth double-checking once is that `tomllib`/`pathlib` path handling in `config.py`/`store.py` doesn't assume `/`-style paths anywhere (it shouldn't, using `pathlib.Path` throughout).

## 8. Live-source validation (the v0 spike doubles as this)

PRD §11 defines v0's purpose as validating credit math, Overpass payload sizes, and render performance with real theater data — i.e. this is where "measure, don't speculate" actually happens. Record these during the v0 spike, not later:

| Measurement | Why it matters | Compares against |
|---|---|---|
| Actual OpenSky credits consumed per `/states/all` call, Hormuz bbox | Validates the area-tier credit table is right, not just plausible | [config.md](../contracts/config.md#predefined-regions-fr1) tier table (expects 1 credit at 6.25 sq°) |
| `/states/all` response size + latency, Hormuz, typical time-of-day | Feeds NFR4's 15s refresh budget | NFR4 |
| Overpass response size (pre- and post-simplification) + feature count, Hormuz | Validates the ≤5,000-feature target and `maxsize` setting | §6.3, [config.md](../contracts/config.md#overpass-63) |
| Overpass fetch latency against the configured `timeout_s` | Confirms 180s timeout has headroom, not just "usually works" | [config.md](../contracts/config.md#overpass-63) |
| `osm_base` actual staleness (how old is OSM's own data for this region) | Sets expectation for what the land badge will show on day one | FR4 |
| Render frame time at real (not synthetic) Hormuz feature counts | Sanity-checks the 5,000+500+1,000 NFR4 budget before marine/land are both live | NFR4 |
| Warm-start time-to-interactive, real laptop | Direct NFR4/§13.1 measurement, done early rather than assumed | NFR4, §13.1 |

> NOTE (scheduling): the aisstream recorded-message fixture cannot be captured during v0 — PRD §11 scopes v0 to OpenSky + Overpass only (marine is a v1 layer). It needs its own short capture step early in v1, gated on OQ1. Tracked in [DECISIONS.md § Design-phase open items](DECISIONS.md#design-phase-open-items).

## 9. Contradictions and gaps found while writing this doc

These were surfaced during this doc pass and have since been reconciled:

- The `zij` (distribution) vs `backend` (import package) split is now recorded in [ADR-4](DECISIONS.md#adr-4--packaging) / [STRUCTURE.md §2](STRUCTURE.md#2-package-naming--decision) — no longer a contradiction.
- Brand assets (`design/assets/*.svg`) are resolved (previously tracked in [DECISIONS.md § Design-phase open items](DECISIONS.md#design-phase-open-items)); the landmask config key is resolved via config.md's `[integrity]` section ([STRUCTURE.md §8](STRUCTURE.md#8-notable-gaps-found-while-assembling-this-tree)).
- The aisstream v0-vs-v1 fixture-timing gap (§7) is tracked in the same DECISIONS open-items list.
