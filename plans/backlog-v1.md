# Backlog — subproject `v1` (the monitor — browser app)

**Status: FILED — founder approved 2026-07-06. Issues #40–#62 created (D1→#40 … D23→#62, contiguous); every plan back-linked. #37/#38 closed as superseded by #54/#55.**

This is the review artifact for `/sprint-plan v1`. Each section below is one proposed GitHub
issue: title, body, acceptance criterion, blocked-by, labels, and its linked slice plan.
On approval the orchestrator files them in dependency order via the GitHub plugin (falling back
to `gh issue create` on a 403), records the real numbers here, and back-links each plan's
`Issue:` field. **`/sprint-plan` never merges and never opens a PR.**

## Scope

v1 = **all P0 requirements FR1–FR10 + NFR1–NFR6** (PRD §8–9, §11). The browser monitor: the
per-layer scheduler, FR9 integrity, the aisstream marine layer, the SQLite store completed, SSE +
the full HTTP surface, and the region-picker / toggles / badges / caveat-panel / marine+integrity
frontend. v2 (Tauri/Capacitor packaging, the FR11 preset+raw-payload *UI*) stays out — those
endpoints are contract-frozen now but their UI ships v2.

**23 new slices across 7 features** (consolidated from triage's 44-slice decomposition per the
founder's 2026-07-06 sizing decision — 80/20, one crisp outer acceptance test per slice):

| Feature | Slices | Plan dir |
|---|---|---|
| store (v1 additions) | 2 | `plans/store/` (02–03) |
| config (v1 additions) | 2 | `plans/config/` (02–03) |
| integrity | 2 | `plans/integrity/` |
| scheduler | 4 | `plans/scheduler/` |
| sources-marine | 3 | `plans/sources-marine/` |
| api-core | 4 | `plans/api-core/` |
| frontend | 6 | `plans/frontend/` |

## Filed issue numbers (draft ID → GitHub)

Filed in dependency order 2026-07-06; the mapping is contiguous, **Dn = #(39+n)**.

| D | Slice | # | · | D | Slice | # |
|---|---|---|---|---|---|---|
| D1 | store/fallback-snapshots | [#40](https://github.com/Muhanad-husn/Zij/issues/40) | · | D13 | scheduler/region-toggle | [#52](https://github.com/Muhanad-husn/Zij/issues/52) |
| D2 | store/config-presets | [#41](https://github.com/Muhanad-husn/Zij/issues/41) | · | D14 | api-core/sse-endpoint ⭐ | [#53](https://github.com/Muhanad-husn/Zij/issues/53) |
| D3 | config/sections | [#42](https://github.com/Muhanad-husn/Zij/issues/42) | · | D15 | api-core/region-endpoints | [#54](https://github.com/Muhanad-husn/Zij/issues/54) |
| D4 | integrity/flags | [#43](https://github.com/Muhanad-husn/Zij/issues/43) | · | D16 | api-core/controls-refresh | [#55](https://github.com/Muhanad-husn/Zij/issues/55) |
| D5 | integrity/caveats | [#44](https://github.com/Muhanad-husn/Zij/issues/44) | · | D17 | api-core/caveats-raw-presets | [#56](https://github.com/Muhanad-husn/Zij/issues/56) |
| D6 | scheduler/core-runtime ⭐ | [#45](https://github.com/Muhanad-husn/Zij/issues/45) | · | D18 | frontend/sse-client ⭐ | [#57](https://github.com/Muhanad-husn/Zij/issues/57) |
| D7 | config/precedence | [#46](https://github.com/Muhanad-husn/Zij/issues/46) | · | D19 | frontend/badges | [#58](https://github.com/Muhanad-husn/Zij/issues/58) |
| D8 | sources-marine/aisstream-core ⭐ | [#47](https://github.com/Muhanad-husn/Zij/issues/47) | · | D20 | frontend/region-selector | [#59](https://github.com/Muhanad-husn/Zij/issues/59) |
| D9 | *(cancelled — dropped from v1)* | — | · | D21 | frontend/toggles-refresh | [#60](https://github.com/Muhanad-husn/Zij/issues/60) |
| D10 | scheduler/status-write-path | [#49](https://github.com/Muhanad-husn/Zij/issues/49) | · | D22 | frontend/caveat-panel | [#61](https://github.com/Muhanad-husn/Zij/issues/61) |
| D11 | scheduler/backoff-stale | [#50](https://github.com/Muhanad-husn/Zij/issues/50) | · | D23 | frontend/marine-integrity | [#62](https://github.com/Muhanad-husn/Zij/issues/62) |
| D12 | sources-marine/aisstream-resilience | [#51](https://github.com/Muhanad-husn/Zij/issues/51) | · | | | |

## Already-filed v1 issues (do NOT re-file)

- **[#37](https://github.com/Muhanad-husn/Zij/issues/37)** — refactor: consolidate the air/land
  snapshot handlers into one `/api/layers/{domain}` route. **Absorbed into D15 = [#54](https://github.com/Muhanad-husn/Zij/issues/54).**
  **Closed 2026-07-06 as superseded by #54** (single-tracking); its route-merge is that slice's work.
- **[#38](https://github.com/Muhanad-husn/Zij/issues/38)** — feat: surface per-layer refresh
  failures (`POST /api/refresh`) via SSE `layer_status`. **Absorbed into D16 = [#55](https://github.com/Muhanad-husn/Zij/issues/55).
  Closed 2026-07-06 as superseded by #55.**
- **[#35](https://github.com/Muhanad-husn/Zij/issues/35)** — spec-drift: TESTING.md forbids browser
  automation but the frontend uses Playwright. Founder ruling (2026-07-05): **keep Playwright,
  reconcile TESTING.md.** This is a **spec-author task, not a build slice** — routed to the
  spec-author in a deliberate spec pass (S1 below), runs in parallel, blocks nothing.

## Labels

- Every issue carries **`sub:v1`** (exists).
- Type label **`enhancement`** on product slices.
- Workflow labels already exist (`spec-drift`, `blocked`, `needs-context`, `done-with-concerns`).
- **No new labels required.**

## Prerequisites & fixtures (founder / test-author, before the dependent slices build)

- **Landmask asset (OQ4, integrity/01):** `scripts/fetch_landmask.py` (written in D8) downloads
  Natural Earth 10 m land polygons once to the platformdirs data-dir. Public download, no key — a
  one-time setup step, **not** OQ1-gated. `integrity.py` fails fast if the asset is missing (FR9/NFR3).
- **aisstream fixture (marine/01):** a hand-authored `backend/tests/fixtures/aisstream_messages.jsonl`
  (schema per aisstream.md: `PositionReport` + `ShipStaticData` frames, including one on-land vessel
  for the spoof test and one implausible-kinematics pair) is the test-author's substrate — **no live
  key needed**, so the build does not wait on OQ1. A live capture is a later, OQ1-gated *verification*
  step, not a build blocker.
- **OQ1 (aisstream ToS / Gulf coverage / rate limits):** gates only wiring the **live** aisstream
  key at integration time. Founder to clear before the marine layer ships live. If it slips, v1 can
  ship with `[layers.marine].enabled = false` and enable post-clearance (FR5 makes the layer optional).

## Dependency graph & suggested filing / build order

Draft IDs D1–D23 (real GitHub numbers assigned on filing). ⭐ = walking skeleton.

```
LEVEL 1 (no new deps)
  D1  store/02 fallback_snapshots
  D2  store/03 config_presets
  D3  config/02 sections
  D4  integrity/01 flags        (+ scripts/fetch_landmask.py)
  D5  integrity/02 caveats
  D6  scheduler/01 core-runtime ⭐
LEVEL 2
  D7  config/03 precedence          ── D3, D2
  D8  sources-marine/01 aisstream-core ⭐ ── D3
  D10 scheduler/02 status-write-path ── D6, D4, D1
LEVEL 3
  D11 scheduler/03 backoff-stale    ── D10
  D12 sources-marine/02 aisstream-resilience ── D8
LEVEL 4
  D13 scheduler/04 region-toggle    ── D10, D2, D12
  D14 api-core/01 sse-endpoint ⭐    ── D10, D1
LEVEL 5
  D15 api-core/02 region-endpoints  ── D3, D13   (absorbs #37)
  D16 api-core/03 controls-refresh  ── D13, D14  (absorbs #38)
  D17 api-core/04 caveats-raw-presets ── D5, D2, D14
LEVEL 6 (frontend)
  D18 frontend/01 sse-client ⭐      ── D14
  D19 frontend/02 badges            ── D18
  D20 frontend/03 region-selector   ── D18, D15
  D21 frontend/04 toggles-refresh   ── D19, D16
  D22 frontend/05 caveat-panel      ── D19, D17
  D23 frontend/06 marine-integrity  ── D18, D4, D14
```

**Critical path:** D6 → D10 → D13 → D14 → D18 → D19 → D21/D22 (≈ 7 slices serial). Backend
runtime (store/config/integrity/scheduler/marine) parallelizes heavily inside each level;
frontend serializes after the SSE endpoint (D14) lands. `/sprint-start` picks the first unblocked
issue each iteration.

---

# Proposed issues

Grouped by feature. Bodies are the drafted GitHub issue text; each links its slice plan (the
locked contract the test-author encodes as the outer test, DEC-1).

## store (v1 additions)

### D1 — store: fallback_snapshots (one restart-resilience snapshot per mobile layer)
**Title:** `feat(store): fallback_snapshots table + upsert-one-row-per-layer (FR8)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** none new · **Plan:** `plans/store/02-fallback-snapshots.md`

> Extend `schema.sql` (idempotent) with `fallback_snapshots` (`layer` PK CHECK air/marine,
> `region_id`, `snapshot_json`, `source_ts`, `fetched_at`) and add `put_fallback`/`get_fallback`.
> Upsert `ON CONFLICT(layer)` keeps exactly one row per mobile layer (FR8) — enforced by the PK.
> Persist `model_dump_json()` (raw_payload excluded); `fetched_at` is the cold-start `cached-fallback`
> true-age basis. Land is not here (it lives in `land_cache`, NFR2).
>
> **Acceptance:** Given a fresh DB from `schema.sql`, `put_fallback(air)` then `get_fallback("air")`
> returns an equal snapshot (no raw_payload, UTC `fetched_at`); a second put replaces (one row);
> `get_fallback("marine")` is `None` when absent; `layer='land'` is rejected by the CHECK.

### D2 — store: config_presets (region presets + config overrides)
**Title:** `feat(store): config_presets table + preset CRUD + config_override rows (FR11)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** none new · **Plan:** `plans/store/03-config-presets.md`

> Add `config_presets` (`kind` region_preset|config_override, `name`, `payload_json`, timestamps,
> `UNIQUE(kind,name)`) and its CRUD: `list_presets`/`add_preset` (409 on duplicate)/`delete_preset`,
> plus `get`/`put_config_override` (the persisted `active_region` lives here). Backs `/api/presets`
> and the highest-precedence config layer.
>
> **Acceptance:** Given a fresh DB, a region preset round-trips; a duplicate `(kind,name)` raises the
> uniqueness error; `put_config_override("active_region", {region_id})` then `get` returns it;
> `delete_preset` removes the row.

## config (v1 additions)

### D3 — config: v1 sections (marine, aisstream, integrity, server)
**Title:** `feat(config): add [layers.marine]/[aisstream]/[integrity]/[server] + full /api/config shape`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** none new · **Plan:** `plans/config/02-sections.md`

> Add the v1 sections to bundled `config.toml` + `AppConfig` (values verbatim from config.md), expand
> `GET /api/config`'s `layers` to the full air/marine/land shape (api.md), and gate the
> `AISSTREAM_API_KEY` secret fail-fast on the marine layer being **enabled** (disabled → no secret, FR5).
>
> **Acceptance:** `load_config()` exposes the four sections with config.md defaults; `/api/config`
> returns the full three-domain layers shape and no secrets (NFR5); marine-enabled + missing key →
> fail-fast named error; marine-disabled → starts fine.

### D7 — config: precedence chain + active-region persistence
**Title:** `feat(config): user-TOML < ZIJ_ env < DB config_override precedence + active-region restore`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** D3, D2 · **Plan:** `plans/config/03-precedence.md`

> Implement the full ADR-6 precedence chain (code < bundled < user TOML < `ZIJ_` env < DB
> `config_override`), secrets env-only. Restore the persisted `active_region` override at startup,
> default-region fallback when absent.
>
> **Acceptance:** DB override beats env beats user-file beats bundle; a persisted `active_region` is
> restored, else the default region is used; `ZIJ_CONFIG_PATH` locates the user TOML; no secret is
> ever read from a TOML.

## integrity

### D4 — integrity: FR9 flags (landmask spoof-suspect + implausible kinematics)
**Title:** `feat(integrity): landmask point-in-polygon + kinematics flags + fetch_landmask script (FR9)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** none new · **Plan:** `plans/integrity/01-flags.md`

> Implement pure `Integrity.apply(features, prev)` — marine-on-land → `SPOOF_SUSPECT_ON_LAND` via a
> shapely STRtree; consecutive-report implied speed > 120 kn (marine) / 990 kn (air) →
> `IMPLAUSIBLE_KINEMATICS`, `dt<=0` skipped. Load Natural Earth 10 m landmask once, **fail fast if
> missing** (NFR3). Add `scripts/fetch_landmask.py`.
>
> **Acceptance:** a marine feature inside a land polygon gets spoof-suspect; a >120/>990 kn pair gets
> implausible-kinematics; a same-timestamp pair is skipped without error; an air-on-land feature is
> not flagged; a missing asset fails fast.

### D5 — integrity: static caveat text + active-flag counts
**Title:** `feat(integrity): per-domain CAVEATS text + active_flags counting (FR9)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** none new · **Plan:** `plans/integrity/02-caveats.md`

> The static per-domain `CAVEATS` bullets (verbatim, integrity.md) plus a helper counting live
> `integrity_flags` in a snapshot — the data `GET /api/layers/{domain}/caveats` serves.
>
> **Acceptance:** `CAVEATS[air|marine|land]` match the spec text verbatim; the counter returns the
> per-flag counts for a snapshot (e.g. 3 spoof-suspect vessels).

## scheduler

### D6 — scheduler: core runtime (poll loop + single-flight coalescing) ⭐
**Title:** `feat(scheduler): per-layer poll loop, cadence floors, single-flight coalescing (FR6)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** none new · **Plan:** `plans/scheduler/01-core-runtime.md`

> **Walking skeleton.** `Scheduler` opens an `asyncio.TaskGroup` with one `_poll_loop(domain)` per
> enabled poll layer; effective cadence `max(cadence_s, cadence_floor_s)`; `_wake` for manual kicks;
> `_do_fetch` single-flight per layer so a manual refresh joins an in-flight scheduled fetch (one
> upstream call, one credit, FR6). Disabled layer parks on `_wake` (zero spend, FR5).
>
> **Acceptance:** a refresh during an in-flight air fetch issues exactly one `adapter.fetch` and both
> callers get the same snapshot; changing land's cadence doesn't shift air's timing; a disabled layer
> issues zero fetches until re-enabled.

### D10 — scheduler: status ownership + the write path
**Title:** `feat(scheduler): sole LayerStatus writer + write path integrity→registry→SSE→fallback`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** D6, D4, D1 · **Plan:** `plans/scheduler/02-status-write-path.md`

> The scheduler becomes the only writer of `LayerStatus` (7-state machine, scheduler.md table) and
> runs the fixed ordered write path `integrity.apply → registry set → SSE publish → (air/marine)
> put_fallback`. Air `prev` derived from the outgoing registry snapshot; `raw_payload` never rides
> the published/persisted snapshot.
>
> **Acceptance:** a fresh fetch → `live` with integrity-before-registry-before-SSE order and an air
> fallback persisted (no raw_payload); an aged source → `stale`; a failure with a warm region-matched
> cache → `cached-fallback` (else `error`).

### D11 — scheduler: backoff per error class + event-driven stale timer
**Title:** `feat(scheduler): per-error-class backoff + event-driven stale timer (FR2/FR7)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** D10 · **Plan:** `plans/scheduler/03-backoff-stale.md`

> Map the error taxonomy to backoff (RateLimited→honor `retry_after`; Upstream→capped exponential;
> Auth/Parse→surface `error`, no retry) and schedule a one-shot `call_at(source_ts + stale_after_s)`
> that flips `live→stale` with no new data; a new fetch reschedules it.
>
> **Acceptance:** `RateLimitedError(retry_after=42)` → `rate-limited` and the next attempt defers ~42 s;
> repeated `UpstreamError` backs off and caps at `max_attempts`; the timer flips a layer to `stale` at
> `source_ts + 2×cadence` and emits a `layer_status` event with no new fetch.

### D13 — scheduler: region switch + enable/disable
**Title:** `feat(scheduler): region-switch sequence + enable/disable (FR1/FR5)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** D10, D2, D12 · **Plan:** `plans/scheduler/04-region-toggle.md`

> `activate_region` runs the ARCHITECTURE §4.2 sequence: cancel in-flight old-region fetches
> (generation bump), clear the registry + emit `region_changed`, repopulate from region-matched
> cache/fallback only, `stream.set_region`, persist `active_region`. `set_enabled` parks/stops for zero
> spend (FR5) and restarts with `loading`.
>
> **Acceptance:** activating region B cancels the in-flight A fetch, clears the registry, emits
> `region_changed`, re-subscribes the stream, persists B, and does **not** repopulate from an A-keyed
> fallback; disabling air stops all air fetches until re-enabled.

## sources-marine

### D8 — sources-marine: aisstream core (subscribe, MMSI table, snapshot) ⭐
**Title:** `feat(aisstream): websocket subscribe + latest-position-per-MMSI table + snapshot (FR3)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** D3 · **Plan:** `plans/sources-marine/01-aisstream-core.md`

> **Walking skeleton (first marine data).** `AisStreamAdapter` connects, sends the in-payload subscribe
> (bbox → `[[s,w],[n,e]]`, PositionReport+ShipStaticData), and maintains the MMSI `_table` +
> `_prev_pos`. Sync `snapshot()` returns `LayerSnapshot(MARINE)` with `position_age_s`, STALE past 30
> min, dropped past 2 h — no I/O, never raises. Uses the hand-authored `aisstream_messages.jsonl`
> fixture + mocked socket (no live key; OQ1 gates only live wiring).
>
> **Acceptance:** replaying a PositionReport then a ShipStaticData for one MMSI, `snapshot()` yields one
> enriched MARINE feature; `_prev_pos` holds the prior fix (FR9); a >30-min vessel is STALE and a >2-h
> one is excluded; `snapshot()` does no I/O and never raises.

### D12 — sources-marine: aisstream resilience (reconnect, eviction, set_region)
**Title:** `feat(aisstream): reconnect backoff+jitter + eviction sweep + set_region re-subscribe (FR3)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** D8 · **Plan:** `plans/sources-marine/02-aisstream-resilience.md`

> On drop, set `connected=False` and reconnect with exponential backoff + full jitter, retaining the
> table (natural aging); a periodic sweep evicts entries past `drop_after_s`; `set_region` re-subscribes
> the new bbox and clears `_table`/`_prev_pos`.
>
> **Acceptance:** a websocket drop flips `connected` False and reconnects with backing-off jitter while
> `snapshot()` keeps serving; entries past 2 h are evicted; after `set_region` no old-region vessels
> remain.

### D9 — sources-marine: AISHub dormant adapter *(cancelled)*

> Dropped from v1. AISHub gates API access behind contributing an owned AIS receiver feed, so it was
> never a viable sign-up source; aisstream.io is the marine source. Issue #48 closed as not-planned.

## api-core

### D14 — api-core: SSE endpoint with full-state-on-connect ⭐
**Title:** `feat(api): GET /api/events (sse-starlette) full-state-on-connect + EventBus + lifespan wiring`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** D10, D1 · **Plan:** `plans/api-core/01-sse-endpoint.md`

> **Walking skeleton (the push channel).** `GET /api/events` streams `snapshot`/`layer_status`/
> `region_changed` via an EventBus; on connect it first emits a `snapshot` per **enabled** layer from
> the registry, then incrementals (ADR-12); monotonic `id:`; raw_payload excluded; `ping` on
> `sse_ping_s`. Lifespan starts the scheduler + registry.
>
> **Acceptance:** a client connecting receives a `snapshot` per enabled layer before any incremental;
> a subsequent scheduler `layer_status` arrives without reconnect; every frame carries `event:`,
> valid JSON `data:`, and a monotonic `id:`.

### D15 — api-core: region endpoints (list, estimate, activate, active)
**Title:** `feat(api): /api/regions + estimate + activate + active; consolidate snapshot route (FR1, #37)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** D3, D13 · **Plan:** `plans/api-core/02-region-endpoints.md`

> `GET /api/regions`, `POST /api/regions/estimate` (server-side area/credit/cap math, 422 with a
> cap-naming message on violation), `POST /api/regions/activate` (predefined or re-validated custom →
> `scheduler.activate_region`), `GET /api/regions/active`. Consolidates the air/land snapshot handlers
> into one `/api/layers/{domain}/snapshot` route (**#37**).
>
> **Acceptance:** `/api/regions` lists costs; an in-cap estimate is 200 with `ok:true` caps; an
> over-cap one is 422 with a cap-naming message; `activate {region_id}` calls the scheduler and returns
> the active region; the unified snapshot route serves all three domains.

### D16 — api-core: layer controls (toggle + per-layer/global refresh)
**Title:** `feat(api): layer toggle + refresh + /api/refresh; refresh failures via SSE layer_status (FR5/FR6, #38)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** D13, D14 · **Plan:** `plans/api-core/03-controls-refresh.md`

> `POST /api/layers/{domain}/toggle` → `set_enabled`; `POST /api/layers/{domain}/refresh` →
> `202`+`refresh(domain)`; `POST /api/refresh` → `202`+`refresh_all`. Fire-and-forget; results ride SSE.
> A failed queued refresh surfaces as an SSE `layer_status` (error/rate-limited/cached-fallback), never
> a silent success (**#38**).
>
> **Acceptance:** toggle delegates and echoes `{layer,enabled}`; per-layer refresh → `202
> {queued:true}`; `/api/refresh` → `202 {queued:[enabled...]}`; a failed queued fetch emits a
> `layer_status` event with the mapped status + detail.

### D17 — api-core: caveats + raw-feature + presets
**Title:** `feat(api): /api/layers/{domain}/caveats (P0) + raw-feature + presets endpoints (P1)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** D5, D2, D14 · **Plan:** `plans/api-core/04-caveats-raw-presets.md`

> `GET /api/layers/{domain}/caveats` (P0) returns the static bullets + live `active_flags` counts;
> `GET /api/features/{domain}/{source_id}/raw` (P1) returns the untouched `raw_payload` (404 once
> rotated out); presets CRUD (P1) over `config_presets` (409 on duplicate, 204 on delete). Raw + presets
> are contract-frozen now; their UI ships v2.
>
> **Acceptance:** caveats returns verbatim bullets and correct `active_flags` counts; raw returns a live
> feature's payload and 404s a rotated-out id; a duplicate preset name → 409, delete → 204.

## frontend

### D18 — frontend: SSE client + connection banner ⭐
**Title:** `feat(frontend): EventSource client → store dispatch + connection-lost/failed banner`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** D14 · **Plan:** `plans/frontend/01-sse-client.md`

> **Walking skeleton.** One `EventSource('/api/events')` dispatching `snapshot`/`layer_status`/
> `region_changed` into the store (idempotent full replace); `connection ∈ {connecting,open,lost,failed}`
> drives a single banner (native reconnect for `lost`, manual Retry for `failed`).
>
> **Acceptance (Playwright):** on connect the store applies a `snapshot` per enabled layer; a
> `layer_status` event updates state without reconnect; a dropped stream shows the reconnecting banner;
> a fatal close shows Retry.

### D19 — frontend: 7-status badges
**Title:** `feat(frontend): per-domain badges — 7 LayerStatus states, both UTC timestamps, count (FR7)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** D18 · **Plan:** `plans/frontend/02-badges.md`

> One badge per domain rendering all seven `LayerStatus` colors/labels (frontend.md §4), both
> `timestamp_fetched`/`timestamp_source` as labeled UTC (NFR6), the feature count, and the always-present
> Toggle/Refresh/Caveats controls; updated imperatively on store events.
>
> **Acceptance (Playwright):** each status renders its color/label (incl. rate-limited countdown and the
> reconnecting/loading grouping); both timestamps show as `HH:MM:SS UTC`; the count updates on snapshot.

### D20 — frontend: region selector (predefined + custom bbox)
**Title:** `feat(frontend): region dropdown + custom-bbox draw/coords + estimate + activate (FR1)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** D18, D15 · **Plan:** `plans/frontend/03-region-selector.md`

> Predefined dropdown (`GET /api/regions`, cost inline) + custom bbox (draw-rectangle or four coord
> inputs) with a debounced `POST /api/regions/estimate` rendered verbatim (server-sourced area/cost/caps;
> cap violation disables Confirm with the cap message); Confirm → `activate`; `region_changed` clears the
> map. Restores the last region on load.
>
> **Acceptance (Playwright):** selecting a predefined region activates it; an over-cap custom bbox shows
> the cap-naming message and disables Confirm before activation; the credit estimate is server-sourced,
> not recomputed client-side.

### D21 — frontend: layer toggles + refresh controls
**Title:** `feat(frontend): per-domain toggle + per-badge/global refresh, loading via SSE (FR5/FR6)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** D19, D16 · **Plan:** `plans/frontend/04-toggles-refresh.md`

> Per-badge toggle (`POST .../toggle`; disabling clears the source + grays the badge, no further SSE
> expectation), per-badge + global refresh (`POST .../refresh`, `/api/refresh`); buttons reflect
> `loading` from SSE without polling and disable during the loading window.
>
> **Acceptance (Playwright):** toggling a domain off stops its rendering and grays the badge; a refresh
> click fires the POST and the badge rides `loading→live` from SSE (no client polling).

### D22 — frontend: caveat panel (non-dismissible)
**Title:** `feat(frontend): non-dismissible caveat panel reachable from every badge (FR9)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** D19, D17 · **Plan:** `plans/frontend/05-caveat-panel.md`

> One reused slide-in panel (right/desktop, bottom-sheet/mobile): domain-accent header, verbatim caveat
> bullets from `GET .../caveats`, active-flag counts in the footer. Reachable from every badge in every
> status; **no persistent-dismiss control anywhere** (FR9 acceptance).
>
> **Acceptance (Playwright):** the panel opens from each domain's badge (including an `error` layer's),
> shows the verbatim bullets + counts, and has no "don't show again" affordance.

### D23 — frontend: marine rendering + integrity markers + client-tick
**Title:** `feat(frontend): marine symbol layer + client-tick de-emphasis/drop + integrity rings (FR3/FR9)`
**Labels:** `sub:v1`, `enhancement` · **Blocked-by:** D18, D4, D14 · **Plan:** `plans/frontend/06-marine-integrity.md`

> Marine symbol layer (teal, `cog_deg`→`heading_deg` rotation, MMSI/SOG/COG popup); a ~5–10 s client
> tick re-derives air+marine age vs `deemphasize_after_s`/`drop_after_s` (de-emphasize; drop marine past
> 2 h; land exempt); two filtered circle overlays draw the spoof-suspect and implausible-kinematics
> rings, concentric and **never hidden** (NFR3).
>
> **Acceptance (Playwright):** vessels render as rotated teal glyphs with popups; a silent vessel
> de-emphasizes then drops on the client tick; a spoof-suspect vessel always shows its ring and names the
> flag in the popup.

---

## Spec-author task (parallel; not a build slice)

### S1 — spec-drift: reconcile TESTING.md with the Playwright decision (#35)
**Existing issue:** [#35](https://github.com/Muhanad-husn/Zij/issues/35) (`spec-drift`). Founder ruling
2026-07-05: **keep Playwright.** Route to the **spec-author** in a deliberate spec pass to update
`design/docs/TESTING.md` so it permits browser automation for web slices (aligning it with the frontend
slices' Playwright outer tests). Not a build slice; blocks nothing; can run any time this sprint. No new
issue to file — the spec-author resolves #35.

---

## On approval

The orchestrator will, in dependency order (D1→D23):
1. Confirm labels exist (`sub:v1`, `enhancement`, workflow labels — all present; no new labels).
2. Create issues D1–D23 via the GitHub plugin (`issue_write`; fall back to `gh issue create` on a 403).
   Decide at filing time whether to fold #37/#38 by closing them in favor of D15/D16 or to skip filing
   D15/D16 duplicates and let #37/#38 track those route/SSE items — either keeps the work single-tracked.
3. Record the real GitHub numbers in this file's dependency graph + issue headers.
4. Back-link each slice plan's `Issue:` field from `TBD` to `#<n>`, and record the mapping here.
5. Route #35 to the spec-author (S1) as a parallel spec pass.
6. Commit the plan/back-link changes on a working branch (tests-green hook runs — suite stays green).

Then `/sprint-start` picks the first unblocked issue (**D6 scheduler/core-runtime** or any Level-1 slice).
**No merge, no PR from `/sprint-plan`.**
