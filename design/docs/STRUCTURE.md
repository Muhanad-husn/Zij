# Zij — Repository Structure

Source of truth for layout: [`zij_prd.md`](zij_prd.md) §10 (sketch), [`ARCHITECTURE.md`](ARCHITECTURE.md), [`DECISIONS.md`](DECISIONS.md) (ADR-1–12), [`design/contracts/`](../contracts/). This document expands the PRD's coarse sketch into the concrete tree a scaffold script or a first commit should produce. Companion doc: [`TESTING.md`](TESTING.md).

## 1. Full tree

```
D:\Zij/                              (repo root)
├── pyproject.toml                   # PEP 621; distribution name "zij", import package "backend" (see §2, ADR-4)
├── .gitignore
├── .env.example
├── README.md                        # currently empty — needs the pointer in §5
├── CLAUDE.md                        # dev principles (existing)
│
├── backend/                         # importable Python package (import root: `backend`)
│   ├── __init__.py
│   ├── main.py                      # FastAPI app: REST + SSE, wiring, startup/shutdown
│   ├── scheduler.py                 # per-layer cadence, coalescing, backoff, status FSM
│   ├── models.py                    # Feature / LayerSnapshot / enums (feature-schema.md, verbatim)
│   ├── store.py                     # SQLite wrapper: land_cache, fallback_snapshots, config_presets
│   ├── integrity.py                 # landmask point-in-polygon + kinematics plausibility flags
│   ├── config.py                    # AppConfig/Secrets loading, precedence chain (config.md)
│   ├── config.toml                  # bundled default config (ADR-6 layer 2; ships inside the package)
│   ├── schema.sql                   # DDL for the 3 tables (storage.md)
│   └── sources/
│       ├── __init__.py
│       ├── base.py                  # SourceAdapter / PollAdapter / StreamAdapter, Region, errors
│       ├── opensky.py                # OAuth2 token mgr, bbox states, credit accounting
│       ├── aisstream.py              # websocket client, latest-position table per MMSI
│       └── overpass.py               # whitelisted queries, DP-simplification, osm_base capture
│
├── backend/tests/                   # pytest — see §6 for the "why here" one-liner
│   ├── conftest.py
│   ├── fixtures/                    # RECORDED real payloads — commit these, do not gitignore
│   │   ├── opensky_states_all_hormuz.json
│   │   ├── aisstream_messages.jsonl
│   │   └── overpass_hormuz.json
│   ├── test_opensky.py
│   ├── test_aisstream.py
│   ├── test_overpass.py
│   ├── test_scheduler.py
│   ├── test_integrity.py
│   ├── test_store.py
│   └── test_api.py
│
├── frontend/                        # Vite + vanilla TS (ADR-3) — coarse only; design/specs/frontend.md owns detail
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts               # dev proxy /api, /api/events → FastAPI (ADR-7)
│   ├── index.html
│   ├── src/
│   │   ├── main.ts                  # entry: boot map, state, SSE client
│   │   ├── state/                   # layer toggles, last-snapshot-per-layer store
│   │   ├── sse/                     # EventSource client + event parsing (snapshot/layer_status/region_changed)
│   │   ├── map/                     # MapLibre init, per-domain source/layer render
│   │   ├── ui/                      # badges, caveat panel, region picker, popups
│   │   └── styles/
│   ├── tests/                       # vitest — state store + sse-client parsing ONLY (design/docs/TESTING.md)
│   └── dist/                        # `vite build` output — gitignored, served by StaticFiles in prod
│
├── design/                          # existing — specs, decisions, contracts
│   ├── docs/
│   │   ├── zij_prd.md               # PRD v2.1 (existing)
│   │   ├── PRODUCT.md               # PRD digest (existing)
│   │   ├── STRUCTURE.md             # this document
│   │   ├── ARCHITECTURE.md
│   │   ├── DECISIONS.md
│   │   └── TESTING.md               # new, this task
│   ├── contracts/
│   │   ├── feature-schema.md
│   │   ├── adapter-interface.md
│   │   ├── api.md
│   │   ├── storage.md
│   │   └── config.md
│   ├── specs/
│   │   └── frontend.md              # (not yet written) owns frontend/src/ fine structure
│   └── assets/                      # brand-source SVGs (§8; DECISIONS open items — resolved)
│       ├── zij_mark.svg
│       └── zij_lockup.svg
│
├── assets/                          # v2 scaffolding target — icon exports/app-bundled assets DERIVED
│   │                                 # from design/assets/ sources at packaging time; not yet populated
│   ├── icons/                       # (planned) generated app icons, per-platform sizes
│   └── ...                          # (planned) any other bundled/exported asset the shells need
│
├── packaging/                       # v2 — empty placeholders now
│   ├── tauri/
│   │   └── .gitkeep
│   └── capacitor/
│       └── .gitkeep
│
├── scripts/
│   └── fetch_landmask.py            # one-time: Natural Earth 10m land polygons → data/landmask/ (OQ4, §7.3)
│
└── data/                            # gitignored — runtime state, not source
    ├── zij.db                       # dev-only ZIJ_DB_PATH override; real default is platformdirs (storage.md)
    └── landmask/
        └── ne_10m_land.geojson      # fetched once by scripts/fetch_landmask.py, consumed by integrity.py
```

## 2. Package naming — decision

Distribution name (`[project].name` in pyproject.toml, what you'd `pip install`) is **`zij`**; the importable top-level package/directory is literally **`backend`** (`import backend.*`), matching every literal import in the contracts (e.g. `from backend.models import Domain, LayerSnapshot`) and the PRD §10 layout. This split is recorded and rationalized in [ADR-4](DECISIONS.md#adr-4--packaging) — an ordinary split (cf. `beautifulsoup4` → `import bs4`), justified by this being a single-app repo (not a published library) whose contracts anchor on `backend.*`.

## 3. Responsibility statements

### Top-level directories

| dir | owns | must not know about |
|---|---|---|
| `backend/` | All server-side logic: adapters, scheduling, storage, integrity, the HTTP+SSE surface. | Which shell (browser/Tauri/Capacitor) is attached ([ARCHITECTURE §6](ARCHITECTURE.md#6-the-shell-boundary-d1-no-rewrite-promise)). |
| `frontend/` | MapLibre rendering, layer toggle UI, badges, caveat panel, region picker, the SSE client and its parsed state. | Upstream source details, credentials, SQLite — it only ever sees `LayerSnapshot`/`LayerSnapshotMeta` JSON over `/api/*`. |
| `design/` | The PRD, ADRs, and contracts — the specification layer that code is checked against. Brand-source SVGs live at `design/assets/`. | Nothing code-shaped; pure documentation. |
| `assets/` (v2, not yet populated) | Derived icon exports for packaging, generated **from** `design/assets/`'s source SVGs (PRD §1.1). | Any app logic; must not duplicate/replace `design/assets/` as the source of truth for the brand SVGs themselves. |
| `packaging/` | v2 shell wrappers (Tauri Rust config, Capacitor project) that host the same backend/frontend unchanged. | Backend business logic — packaging must only configure hosting, per the shell-boundary rule. |
| `scripts/` | One-off setup tooling (landmask fetch) run manually during dev setup, never at runtime. | Anything imported by `backend/` at runtime — these are dev-time scripts, not app modules. |
| `data/` | Gitignored runtime state: the dev SQLite file and the fetched-once landmask GeoJSON. | Nothing — this directory holds no source, only generated/fetched artifacts. |
| `backend/tests/` | Contract-level and unit tests for the backend, plus recorded upstream fixtures. | Frontend test tooling (separate vitest config/toolchain). |

### Backend modules

| module | owns | must not know about |
|---|---|---|
| `models.py` | The `Feature`/`LayerSnapshot`/`LayerSnapshotMeta` schema and enums — the one shared vocabulary every other module speaks ([feature-schema.md](../contracts/feature-schema.md)). | Any specific source, SQLite, HTTP routing, or the scheduler. |
| `sources/base.py` | The `SourceAdapter`/`PollAdapter`/`StreamAdapter` ABCs, `Region`, and the `AdapterError` taxonomy ([adapter-interface.md](../contracts/adapter-interface.md)). | The registry, SQLite, status transitions (those are the scheduler's job). |
| `sources/opensky.py` | OAuth2 token lifecycle, `/states/all` fetch, per-call credit accounting against bbox area. | SQLite, the frontend, other adapters' internals. |
| `sources/aisstream.py` | The websocket connection, the in-memory latest-position-per-MMSI table, re-subscribe on region switch. | SQLite persistence (that's `store.py` via the scheduler), the frontend. |
| `sources/overpass.py` | Tag-whitelisted queries, mirror/backoff selection, Douglas-Peucker simplification, `osm_base` capture. | SQLite writes directly — it returns a snapshot; `store.py`/scheduler persists it. |
| `scheduler.py` | Per-layer cadence timers, manual-refresh coalescing, backoff, and **all** `LayerStatus` transitions ([ARCHITECTURE §5](ARCHITECTURE.md#5-failure-isolation-fr10-and-the-layer-status-state-machine)). | The wire format of the API (that's `main.py`); how a specific adapter talks to its upstream. |
| `integrity.py` | The FR9 landmask point-in-polygon and kinematics-jump checks, run at snapshot time. | Sources, SQLite, or the API — it is a pure function over features in, flagged features out. |
| `store.py` | The 3-table SQLite responsibility: `land_cache`, `fallback_snapshots`, `config_presets` (NFR2). **Never parses source payloads** — it only serializes/deserializes `Feature`/`LayerSnapshot` it's handed. | Overpass tags, OpenSky OAuth, aisstream messages — anything upstream-shaped. |
| `config.py` | Merging code defaults < bundled `config.toml` < user `config.toml` < env < `config_presets` overrides (ADR-6); secrets from env only. | Runtime application state (registry, scheduler tick state) — config is loaded once, not mutated by the app. |
| `main.py` | FastAPI app construction, route registration, SSE endpoint, startup/shutdown wiring — the only module allowed to import everything else. | — (it is the top; nothing constrains what it may import). |

`sources/` never touches SQLite or the UI; `store.py` never parses source payloads — these two rules are the ones most likely to be violated under time pressure and are worth restating verbatim from the task brief.

## 4. Dependency direction

| module | may import | must NOT import |
|---|---|---|
| `models.py` | stdlib, pydantic | `sources.*`, `store`, `scheduler`, `config`, `main` |
| `sources/base.py` | `models` | `store`, `scheduler`, `main` |
| `sources/{opensky,aisstream,overpass}.py` | `sources.base`, `models` | `store`, `scheduler`, `main`, each other |
| `integrity.py` | `models`, shapely | `sources.*`, `store`, `main` |
| `store.py` | `models` | `sources.*`, `scheduler`, `main` |
| `config.py` | `models` (Cfg types), pydantic-settings | `sources.*`, `store`, `scheduler`, `main` |
| `scheduler.py` | `sources.*`, `store`, `integrity`, `models`, `config` | `main` |
| `main.py` | everything above | — |
| *(nothing)* | | `main.py` — no module ever imports it |

This mirrors [ARCHITECTURE §6](ARCHITECTURE.md#6-the-shell-boundary-d1-no-rewrite-promise): the shell boundary is enforced the same way internally — lower layers never reach up.

## 5. Config/dotfiles at root

**`pyproject.toml`**
- `[project] name = "zij"` (distribution name; import package is `backend` — see §2, [ADR-4](DECISIONS.md#adr-4--packaging)), `requires-python = ">=3.13"`.
- Runtime deps: `fastapi`, `uvicorn`, `httpx`, `websockets`, `sse-starlette` ([ADR-2](DECISIONS.md#adr-2--sse-via-sse-starlette)), `pydantic`, `pydantic-settings`, `shapely`, **`platformdirs`** (not in the original brief's list but required by [storage.md](../contracts/storage.md#file-location-per-platform) — "suggest adding the dep" is explicit there; adding it here rather than re-deciding it).
- Dev deps: `pytest`, `pytest-asyncio`, `ruff`, `respx` (httpx mocking), `pyright` (advisory only, [ADR-5](DECISIONS.md#adr-5--tooling)), `freezegun` (scheduler clock control — justified in [TESTING.md](TESTING.md)).

**`.gitignore`** essentials: `node_modules/`, `frontend/dist/`, `*.db`, `*.sqlite*`, `.env`, `data/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/`.

**`.env.example`** — per [config.md](../contracts/config.md#secrets-env-only-nfr5), 4 env vars covering the PRD §7.1 table's 3 credentials (OpenSky is one credential expressed as a client_id/secret pair):
```
OPENSKY_CLIENT_ID=
OPENSKY_CLIENT_SECRET=
AISSTREAM_API_KEY=
```

**`README.md`** — currently an empty file (0 content lines). Needs at minimum: product one-liner + link to `design/docs/zij_prd.md`, `pip install -e .` / `uvicorn backend.main:app` quick-start, and the `design/assets/zij_lockup.svg` header image (now available; §8, [DECISIONS open items](DECISIONS.md#design-phase-open-items)).

## 6. Tests location — decision

**`backend/tests/`**, not a top-level `tests/`. One-line justification: colocating under the package keeps pytest's rootdir and fixture paths trivial (`backend/tests/fixtures/...`) and mirrors the one-module-per-file layout the contracts already assume; the frontend's vitest suite is a different language/toolchain entirely (`frontend/tests/`), so a shared top-level `tests/` would just be a directory that multiplexes two unrelated test runners for no benefit.

## 7. Phase mapping (staging the scaffold)

| exists at | items |
|---|---|
| **v0** (source-validation spike, PRD §11) | `backend/main.py` (direct adapter wiring, no scheduler yet — v0 is manual-refresh-only per roadmap), `backend/models.py`, `backend/config.py` (regions + opensky/overpass sections only), `backend/store.py` (land_cache table only — D4 makes this non-optional even at v0), `backend/sources/base.py`, `backend/sources/opensky.py`, `backend/sources/overpass.py`, a minimal `frontend/` (single static MapLibre page, Hormuz hardcoded), `backend/tests/` for opensky+overpass only. |
| **v1** (the monitor) | adds `backend/scheduler.py`, `backend/integrity.py`, `backend/sources/aisstream.py`, full `backend/store.py` (all 3 tables), full `config.toml` (all layers/regions), the full `frontend/src/{state,sse,map,ui}` structure, `design/docs/TESTING.md`'s complete backend suite, `frontend/tests/` (vitest), the CI workflow. |
| **v2** (installables) | `packaging/tauri/`, `packaging/capacitor/` gain real content; credential first-run flow; FR11 presets endpoints (designed in `api.md` now, but UI lands v2 alongside P1 popup depth). |

## 8. Notable gaps found while assembling this tree

- **Brand assets — resolved.** `design/assets/zij_mark.svg` and `design/assets/zij_lockup.svg` now exist (previously tracked in [DECISIONS.md § Design-phase open items](DECISIONS.md#design-phase-open-items)). The root `assets/` directory (icon exports derived from these sources for packaging) remains unpopulated, deferred to v2.
- **Landmask config key** — resolved: config.md now owns it via the `[integrity]` section (`landmask_path`, plus the FR9 kinematics thresholds). `scripts/fetch_landmask.py` writes the default path and `integrity.py` reads it from `[integrity]`.
