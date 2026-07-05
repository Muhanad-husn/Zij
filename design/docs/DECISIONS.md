# Zij — Architecture Decision Log

ADR-style. All dated **2026-07-05**. These record the **open technology choices** the PRD left to implementation. Product/strategy decisions **D1–D7 are locked in the PRD** ([`zij_prd.md` §2](zij_prd.md)) and are **not** restated here — this log references them.

Governing principles ([CLAUDE.md](../../CLAUDE.md)): 80/20 practicality, don't reinvent the wheel, measure don't speculate.

Index:
- [ADR-1 — Pydantic v2 for models & validation](#adr-1--pydantic-v2)
- [ADR-2 — SSE via sse-starlette](#adr-2--sse-via-sse-starlette)
- [ADR-3 — Frontend: Vite + vanilla TS + MapLibre](#adr-3--frontend-vite--vanilla-ts--maplibre)
- [ADR-4 — Packaging: pyproject + conda env `zij` (3.13)](#adr-4--packaging)
- [ADR-5 — Tooling: ruff + pytest; type-check non-blocking](#adr-5--tooling)
- [ADR-6 — Config format & precedence](#adr-6--config-format--precedence)
- [ADR-7 — Dev vs prod frontend serving](#adr-7--dev-vs-prod-frontend-serving)
- [ADR-8 — Concurrency: pure asyncio](#adr-8--concurrency-pure-asyncio)
- [ADR-9 — HTTP & websocket clients](#adr-9--http--websocket-clients)
- [ADR-10 — SQLite access: stdlib + to_thread](#adr-10--sqlite-access)
- [ADR-11 — Geometry wire format: GeoJSON](#adr-11--geometry-wire-format-geojson)
- [ADR-12 — SSE reconnection: full-state-on-connect](#adr-12--sse-reconnection)

---

## ADR-1 — Pydantic v2

**Status:** Accepted 2026-07-05.
**Context:** The common Feature schema (PRD §10) crosses every boundary — adapters, registry, SQLite JSON blobs, API, SSE. It needs one validating model layer.
**Decision:** Pydantic v2 for all models and validation. FastAPI already depends on it; `pydantic-settings` handles config ([ADR-6](#adr-6--config-format--precedence)). Field-level `exclude=True` gives `raw_payload` its in-memory-only behavior for free ([feature-schema.md](../contracts/feature-schema.md#raw_payload-handling)).
**Consequences:** Runtime validation at ingest (bad upstream payloads become `ParseError`, not silent corruption). v2 core is Rust-fast, irrelevant at our volumes but free. Serialization via `model_dump(mode="json")` is the single wire path.
**Rejected:** dataclasses/attrs (no validation, hand-rolled JSON); marshmallow (redundant with FastAPI's Pydantic dependency — reinventing the wheel).

## ADR-2 — SSE via sse-starlette

**Status:** Accepted.
**Context:** Backend→frontend push (PRD §10). PRD names "SSE/WebSocket"; we pick **SSE** — the flow is one-directional server→client, and SSE reconnects natively via `EventSource`, needs no framing protocol, and traverses proxies/Tauri/Capacitor trivially. WebSocket's bidirectionality buys nothing here (client→server is plain REST).
**Decision:** Use **sse-starlette** (`EventSourceResponse`) rather than a hand-rolled `StreamingResponse`.
**Consequences:** Get keep-alive pings, client-disconnect detection, and correct `text/event-stream` framing out of the box — the three things a hand-rolled version gets wrong first. One small dependency. Event contract in [api.md §SSE](../contracts/api.md#sse).
**Rejected:** Hand-rolled `StreamingResponse` async generator (must reimplement heartbeat + disconnect detection + `id:`/`event:` framing — reinventing the wheel for a solved problem, violates 80/20). WebSocket (bidirectional complexity unused; manual reconnect logic).

## ADR-3 — Frontend: Vite + vanilla TS + MapLibre

**Status:** Accepted.
**Context:** The product is **one map screen** with layer badges, a caveat panel, popups, and a region picker (PRD §10, FR1–FR9). "Staying small" is a load-bearing PRD principle (§1, §4).
**Decision:** **Vite + vanilla TypeScript + MapLibre GL JS**, no UI framework. MapLibre owns the map and all feature rendering; a thin TS state module holds layer toggles + last snapshot per layer and subscribes to the SSE stream; DOM for badges/panels is a handful of elements updated imperatively.
**Consequences:** No virtual DOM, no framework runtime, tiny bundle → helps NFR4 (≤15 s interactive) and the 5,000-feature render budget. TS gives editor-time safety over the API contract. Risk: imperative DOM for panels can sprawl; mitigation — the UI genuinely is small; revisit only if a second screen appears (scope alarm per §11).
**Rejected:** React/Vue/Svelte (framework runtime + build complexity for a single non-CRUD screen; MapLibre already imperative — the framework would wrap a canvas it doesn't control). Plain JS (loses contract-level type safety against [api.md](../contracts/api.md)).

## ADR-4 — Packaging

**Status:** Accepted.
**Context:** PRD §7.2 says Python 3.11+; we standardize on **3.13**. Single-developer, conda-based machine.
**Decision:** `pyproject.toml` (PEP 621) with a deliberate **name split: distribution name `zij`** (`[project].name`, what you'd `pip install`) but the **importable top-level package is literally `backend`** (the directory `backend/`, imported as `backend.*`). This is an ordinary split (cf. `beautifulsoup4` → `import bs4`), chosen because: this is a single-app repo, not a published library, so the distribution name is cosmetic; every contract file anchors its literal import code on `backend.*` (e.g. `from backend.models import Domain, LayerSnapshot` — more numerous and more specific than any one naming sentence), and matching them keeps the code samples true (PRD §10 uses the same `backend/` layout); 80/20 — renaming the import root to `zij.*` would mean editing every contract's code for no runtime benefit. Deps are **pip-installed into an existing conda env named `zij`, Python 3.13**. Conda provides the interpreter only; pip owns all Python deps. No conda-forge package pinning, no lockfile ceremony for v1 (a `requirements.txt`/`pip freeze` snapshot is the escape hatch if reproducibility bites).
**Consequences:** `pip install -e .` runs the browser app (NFR1). Targeting 3.13 lets us use `tomllib` (stdlib), modern typing (`X | None`), and `asyncio.TaskGroup`. Must keep deps within 3.13 wheel availability (shapely, httpx, websockets, pydantic all ship 3.13 wheels).
**Rejected:** Poetry/PDM (extra tooling, no payoff at this size). Pinning 3.11 (PRD floor, but we control the machine and 3.13 gives TaskGroup + tomllib cleanly). Conda-forge for Python deps (slower, mixes package managers).

## ADR-5 — Tooling

**Status:** Accepted.
**Context:** Lint, format, test, and the type-checking question for a one-dev repo.
**Decision:** **ruff** for both lint and format (single tool, replaces black+isort+flake8). **pytest** for tests. Type checking: **in but non-blocking** — `pyright` in *basic* mode as an editor/CI advisory, **not** a merge gate for v1. Pydantic already enforces the load-bearing invariants at runtime.
**Consequences:** One formatter/linter config. pytest with `pytest-asyncio` for adapter/scheduler tests; upstream calls mocked (respx for httpx). Type errors surface in the editor without blocking a solo dev mid-spike (80/20).
**Rejected:** black+isort+flake8 (three tools where ruff is one). mypy (fine, but pyright's editor integration is stronger for this workflow; either works — choice is non-load-bearing). Strict type gate for v1 (friction > payoff at spike stage; can tighten before v2).

## ADR-6 — Config format & precedence

**Status:** Accepted.
**Context:** Regions/cadences/caps/mirrors are structured tunables; secrets must never sit in a config file (NFR5). PRD needs file/env/default precedence.
**Decision:** **TOML** config file (`config.toml`), parsed with stdlib `tomllib`, loaded through **pydantic-settings** `BaseSettings`. Secrets come **only** from environment / `.env` (dev), never from TOML. Precedence, lowest→highest: **code defaults < bundled `config.toml` < user `config.toml` < environment variables < runtime overrides (`config_presets` table)**. Full schema in [config.md](../contracts/config.md).
**Consequences:** Non-secret tunables are human-editable and diffable; secrets stay out of the repo and out of bundles (NFR5). `tomllib` is stdlib on 3.13 (no dep). Runtime UI overrides (FR11) persist to SQLite and win at read time.
**Rejected:** YAML (extra dep, footguns). JSON (no comments — bad for an operator-edited region file). `.env`-only (can't express nested region tables cleanly). Secrets in TOML (violates NFR5 outright).

## ADR-7 — Dev vs prod frontend serving

**Status:** Accepted.
**Context:** MapLibre frontend built by Vite; backend is FastAPI. Two runtime modes.
**Decision:** **Dev:** Vite dev server (HMR) with a proxy — `/api` and `/api/events` proxied to the FastAPI process (`vite.config.ts` `server.proxy`). **Prod:** `vite build` emits static assets; FastAPI serves them via `StaticFiles` mounted at `/`, with `/api/*` taking precedence. Single origin in prod → no CORS, and SSE works without preflight.
**Consequences:** One command runs prod (NFR1: `pip install` + run serves the built app). Dev keeps HMR. The relative-origin rule ([ARCHITECTURE §6](ARCHITECTURE.md#6-the-shell-boundary-d1-no-rewrite-promise)) means the same build drops into Tauri/Capacitor.
**Rejected:** Serving the frontend from a separate static host (adds CORS + a second deployable, breaks NFR1's single-process story).

## ADR-8 — Concurrency: pure asyncio

**Status:** Accepted.
**Context:** Concurrent per-layer refresh + a persistent websocket, on one dev's machine (PRD §10).
**Decision:** **Pure asyncio, no threads or processes** for application logic. Adapters are asyncio tasks under an `asyncio.TaskGroup` in the scheduler. The only thread offloads are blocking libs that would stall the loop: SQLite (`asyncio.to_thread`, [ADR-10](#adr-10--sqlite-access)) and, *only if measured to matter*, the shapely landmask check.
**Consequences:** Simplest correct model for an I/O-bound workload; no locks, no GIL contention, no IPC. CPU work is bounded and small: land simplification runs once/24h; the marine landmask/kinematics check runs on ≤1,000 vessels per snapshot using a prepared shapely `STRtree` (microseconds each) — fits in a tick. Measure-don't-speculate: if the landmask check ever dominates a tick, wrap it in `to_thread` behind the existing integrity call — no architectural change.
**Rejected:** ThreadPool per adapter (needless locking around shared registry). multiprocessing (IPC + serialization cost, no CPU-bound justification). See [ARCHITECTURE §1](ARCHITECTURE.md#1-single-process-model).

## ADR-9 — HTTP & websocket clients

**Status:** Accepted.
**Context:** OpenSky/Overpass/AISHub are HTTP; aisstream is a websocket (PRD §6, §7.2 names httpx + websockets).
**Decision:** **httpx** (async) for all REST adapters — one shared `AsyncClient` per adapter with timeouts; handles OpenSky OAuth2 token refresh via an auth flow. **websockets** library for the aisstream `StreamAdapter`.
**Consequences:** Matches PRD prerequisites §7.2. httpx gives per-request timeouts and connection reuse (credit-cheap). Testable with respx.
**Rejected:** aiohttp (fine, but httpx is already the PRD's named dep and pairs with sync test clients). requests (sync, wrong for the loop).

## ADR-10 — SQLite access

**Status:** Accepted.
**Context:** SQLite is on the side (D4, NFR2): land cache read ~once/24h, one fallback-row write per air/marine refresh, rare preset writes. All small.
**Decision:** **stdlib `sqlite3` behind a ~20-line async wrapper using `asyncio.to_thread`**, not `aiosqlite`. Access is infrequent and tiny; a persistent async cursor abstraction is unwarranted.
**Consequences:** Zero added dependency; each call opens/uses a short-lived connection (or one module-level connection guarded by `check_same_thread=False` + serialized through `to_thread`). If profiling ever shows contention (it won't at this volume — measure don't speculate), swap to `aiosqlite` behind the *same* wrapper signature with no caller changes. DDL in [storage.md](../contracts/storage.md).
**Rejected:** `aiosqlite` (a fine, mature wheel — but it earns its place under sustained concurrent DB load we do not have; the wrapper stays swap-compatible so this is reversible). Raw blocking `sqlite3` on the loop (would stall SSE during a land write).

## ADR-11 — Geometry wire format: GeoJSON

**Status:** Accepted.
**Context:** Land features carry LineString/Polygon geometry; air/marine are points (PRD §6.3, §10).
**Decision:** Geometry on the wire is a **GeoJSON geometry object** (`{"type","coordinates"}`, coordinates in `[lon, lat]` per RFC 7946). Point features omit `geometry` (null) and rely on `lat`/`lon`; line/polygon features populate `geometry` and set `lat`/`lon` to a representative point for labeling/clustering. Details in [feature-schema.md](../contracts/feature-schema.md#geometry).
**Consequences:** MapLibre consumes GeoJSON natively — the renderer needs no geometry translation. `land_cache` stores a GeoJSON FeatureCollection directly ([storage.md](../contracts/storage.md)). Uniform `lat`/`lon` presence keeps the schema flat.
**Rejected:** WKT (needs parsing before render). Separate point vs. geometry models (breaks the single-Feature contract FR3 relies on).

## ADR-12 — SSE reconnection

**Status:** Accepted.
**Context:** `EventSource` reconnects automatically; we must define what state the client gets on (re)connect.
**Decision:** **Full-state-on-connect.** On every `/api/events` connection the server first emits the current `snapshot` for each enabled layer from the in-memory registry, then streams incremental events. `Last-Event-ID` is accepted but treated as advisory only — we do **not** maintain an event replay buffer.
**Consequences:** Reconnect logic is trivial and always correct: the registry *is* the latest projection (matches the "latest available projection" principle, PRD §1), so replaying history is meaningless — we only ever want current state. No server-side event log (aligns with the no-history non-goal, §4). Costs one snapshot burst per connect; cheap at our feature counts.
**Rejected:** `Last-Event-ID` replay buffer (implies retained history — contradicts §4 non-goals and NFR2; complexity with no user value for a latest-only monitor).

---

## Design-phase open items

Genuinely open items surfaced during the design pass, recorded once here (owner: the author unless noted). These are *not* ADRs — they are tracked gaps to close during implementation.

- **Brand assets — resolved 2026-07-05.** `assets/zij_mark.svg` and `assets/zij_lockup.svg`, referenced by [PRD §1.1](zij_prd.md) as shipping "with this document," now exist at `design/assets/zij_mark.svg` and `design/assets/zij_lockup.svg`. The README header ([STRUCTURE.md §5](STRUCTURE.md)) and packaging icon exports can now use them. Caveat still applies (PRD §1.1): text in the lockup must be converted to outlines before public release.
- **OpenSky credit tier table is inferred.** The bbox-area→credits table in [config.md](../contracts/config.md#predefined-regions-fr1) is derived from §6.1's "cost scales with area," not quoted verbatim from current OpenSky docs. Verify it during the v0 spike (it is already on [TESTING.md §8](TESTING.md#8-live-source-validation-the-v0-spike-doubles-as-this)'s measurement list).
- **aisstream fixture capture timing.** The recorded aisstream message fixture (`backend/tests/fixtures/aisstream_messages.jsonl`) cannot be captured during v0 — [PRD §11](zij_prd.md) scopes v0 to OpenSky + Overpass only. It needs its own short capture step early in **v1**, gated on **OQ1** (aisstream ToS/coverage) resolving first. See [TESTING.md §7](TESTING.md#7-ci).
- **OQ1 / OQ4 remain open** per [PRD §14](zij_prd.md): OQ1 (aisstream ToS/Gulf coverage/rate limits) blocks the v1 marine layer; OQ4 (landmask source/resolution — Natural Earth 10 m is the default candidate, wired via `[integrity].landmask_path`) is non-blocking, resolved during v1.
