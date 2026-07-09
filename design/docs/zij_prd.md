# Product Requirements Document: Zij (زيج) — Regional Live Projection Monitor

**Version:** 2.1 (adds product name and visual identity)
**Status:** Draft for review
**Supersedes:** v1.0 (Streamlit single-process draft), v2.0 (unnamed)

---

## 1. Overview

Consider what an analyst actually does on the morning a strike is reported near Bandar Abbas: they want one map showing which aircraft are broadcasting over the Strait of Hormuz, which vessels are transmitting AIS in the approaches, and where the crossings, ports, and rail lines sit underneath that activity. They do not want a data warehouse, a replay slider, or an alerting engine. They want the latest available picture, honestly timestamped.

This document defines that product: a lightweight, installable application that projects the most recent available aviation, marine, and land-logistics data over a map for regions affected by the Iranian conflict. The core design principle remains **latest available projection**: freshness differs by source, and the application shows each layer's real timestamp rather than pretending all sources are equally live.

What this product is not: it is not a historical telemetry archive, not an analytics or graph platform, and not a commercial SaaS offering. Those exclusions are load-bearing. They keep the architecture small enough that one developer can ship and maintain it.

Two things changed between v1 and this revision. First, the end goal is now explicit: the product ships as an **installable application for desktop and mobile**, which rules out the v1 Streamlit architecture. Second, source-access research invalidated a v1 assumption (OpenSky as anonymous-friendly at useful rates), so the source strategy and refresh model have been rebuilt around how these services actually work.

### 1.1 Name and identity

The product is named **Zij** (زيج). A zij is an astronomical handbook from the Islamic scientific tradition: tabulated positions of moving celestial bodies, compiled from real observation and updated edition by edition, each superseding the last. That is this product's job description transposed eight centuries — the latest observed positions of moving craft, tabulated honestly, with no pretense of prediction or archive. The name's etymology reaches further back still, to a Middle Persian word for the cords of a loom, transferred to the rows and columns of tabulated data; a monitoring app is, in that older sense, exactly a weave of rows refreshed in place. Candidate names rejected: *Rasid* (راصد, "observer" — semantically apt but the namespace is occupied by fleet-tracking, QHSE, and phone-surveillance products, the last a disqualifying association) and *Marsad* (مرصد — held by several observatory-named organizations). A software-collision scan came back clean for Zij; formal trademark clearance has not been performed and is a prerequisite to any public distribution (OQ5).

The logomark encodes the product's principles rather than decorating them: a scope ring broken into three unequal arcs (amber air, teal marine, dun land) whose deliberate gaps state that coverage is partial (FR9 as geometry); a sweep wedge for the live observation; and a single position dot with a heading tick and **no trail**, because the product keeps no history. Palette: astrolabe brass (#D99A3B) on night ink (#101D30), with sea teal (#4E9DB4) and dun (#A38B62) carrying the other domains. Lockup typography is Archivo for the wordmark and Spline Sans Mono for the tagline ("latest available projection"), with زيج in amber naskh. Assets ship with this document as `zij_mark.svg` (app icon source) and `zij_lockup.svg` (README/docs header); the lockup's text must be converted to outlines before public release. Suggested repository name: `zij-monitor`.

---

## 2. Decision log

These decisions are locked for this version. Reopening any of them requires a documented reason, not drift.

| # | Decision | Rationale | Rejected alternative |
|---|----------|-----------|----------------------|
| D1 | **Web-first architecture: FastAPI backend + MapLibre GL JS frontend**, packaged later via Tauri (desktop) and Capacitor (mobile). | The same codebase serves browser, desktop, and mobile. Source adapters, schema, and cache carry across all three unchanged. | Streamlit (no mobile path, fragile background refresh, throwaway frontend); PWA-only (constrained background behavior on mobile, weaker install story). |
| D2 | **Marine source: aisstream.io websocket feed.** A free API-key sign-up streams AIS position reports filtered by subscribed bounding boxes. | A free websocket service fits the "latest available projection" model directly and carries no hardware or cost gate to block v1. | Commercial APIs such as Spire or Datalastic (cost unjustified at this scope). |
| D3 | **Per-layer refresh cadence** replaces the single 30-minute interval: aviation 10 min, marine continuous-with-snapshot, land 24 h. | The three domains have different tempos. A jet moves roughly 400 km in 30 minutes; a road network moves on a timescale of months. One interval is wrong for all three. | Uniform 30-minute refresh (v1). |
| D4 | **SQLite is the standard store for the land layer** and the fallback cache for mobile layers. It is no longer "optional." | Overpass queries for conflict-theater regions are expensive and slow; land data changes slowly. Fetch daily, serve from cache. | Purely in-memory land layer (re-fetches megabytes of unchanged geometry every session). |
| D5 | **OpenSky access via OAuth2 client credentials with an explicit credit budget.** | OAuth2 is mandatory for accounts created since March 2025. Credits are consumed per call scaled by bounding-box area; the app must budget, not hope. | Anonymous access (400 credits/day is insufficient for 10-minute aviation refresh across a session). |
| D6 | **Data-integrity caveats are a first-class UI requirement**, including cheap plausibility flags. | In this theater, GPS jamming, AIS spoofing, dark-fleet transponder silence, and military ADS-B absence make *position honesty* as important as *freshness honesty*. | Freshness-only transparency (v1 NFR3). |
| D7 | **Product name: Zij (زيج)**, with the segmented-scope logomark defined in §1.1. | Semantic fit (tabulated latest positions of moving bodies, updated in place), bilingual heritage without regional political baggage, and a clean software namespace. | Rasid (crowded namespace, spyware association); Marsad (held by existing observatory organizations). |

---

## 3. Problem statement

Analysts and researchers monitoring transport-relevant activity around the Iranian conflict currently choose between heavyweight commercial platforms (MarineTraffic, FlightRadar24 subscriptions, bespoke GEOINT tooling) and manual tab-juggling across free web viewers that cannot be combined into one regional picture. The cost of not solving this is not missing data — the data exists — but the friction of assembling it per session and the absence of honest freshness and integrity indicators when it is assembled by hand.

The primary user is a single analyst (initially the author) working a select-region → fetch → inspect → refresh loop, on a laptop at a desk or a phone in the field.

---

## 4. Goals and non-goals

### Goals

1. A user can select a predefined conflict-theater region and see combined aviation, marine, and land layers on one map within 15 seconds of app start (warm cache).
2. Every layer displays two timestamps: last successful fetch, and the source's own data timestamp, with a numerically defined stale state.
3. The application survives any single source failing, degrading to remaining layers with visible status.
4. One codebase ships as a browser app (v1), a desktop installable (v2), and a mobile installable (v2), with no rewrite between phases.
5. The default deployment requires no hosted database and no infrastructure beyond the app itself.

### Non-goals

What does staying small mean in practice? It means the following are explicitly out of scope, each for a stated reason:

- **Historical storage and replay** — this is the boundary that keeps the architecture single-tier; revisit only under demonstrated usage pressure.
- **Trend analysis, anomaly detection, graph analytics** — separate product; the author's Neo4All/G-Lab stack is the home for that class of work, not this monitor.
- **Entity resolution beyond source identifiers** — ICAO24 and MMSI are displayed as-is; no cross-source identity fusion.
- **Alerting, forecasting, sanctions-network modeling** — intelligence-platform territory, not a projection monitor.
- **Multi-tenancy, billing, accounts** — single-analyst tool; also see the licensing constraint in §12, which currently forbids commercial use of the aviation source.

---

## 5. Users and user stories

Ordered by priority:

1. As a conflict analyst, I want to select the Strait of Hormuz region and see current broadcasting aircraft and vessels over the logistics base map, so that I can assess transport activity in one view.
2. As a conflict analyst, I want each layer's freshness and integrity caveats visible at a glance, so that I never mistake a stale or spoof-contaminated picture for ground truth.
3. As a conflict analyst, I want to force an immediate refresh of enabled layers when conditions appear to have changed, so that the picture reflects my judgment about tempo, not just the schedule.
4. As a conflict analyst, I want the app to keep working with two layers when the third source is down, so that a single upstream failure does not end the session.
5. As a mobile user (v2), I want the last successful snapshot available on open even before new fetches complete, so that the app is useful on a degraded connection.
6. As the operator, I want my API credentials stored outside the codebase and never bundled into distributed binaries, so that shipping installers does not leak keys.

---

## 6. Source strategy

This section replaces the v1 data-sources table, which understated access friction on two of three sources.

### 6.1 Aviation — OpenSky Network REST API

OpenSky's `/states/all` endpoint returns current state vectors (ICAO24, callsign, position, baro/geo altitude, velocity, true track, vertical rate, position source) and supports bounding-box filtering.

Access realities that are now requirements rather than footnotes:

- **Authentication:** OAuth2 client credentials flow, mandatory for accounts created since mid-March 2025. Tokens live roughly 30 minutes; the adapter must refresh proactively.
- **Credit model:** anonymous users receive 400 API credits/day; registered users 4,000; active ADS-B-contributing users 8,000. Credit cost per call scales with bounding-box area. Exhaustion returns HTTP 429 with a retry-after header.
- **Budget math (registered tier):** predefined regions are sized so a `/states/all` call costs at most 2 credits. At a 10-minute cadence that is ≤ 288 credits/day per region — comfortably inside 4,000, with headroom for manual refreshes and a second concurrent region.
- **Coverage caveat:** OpenSky sees ADS-B (and FLARM) broadcasters within receiver coverage. Military aircraft with transponders off are invisible; Mode S-only aircraft have no position. The UI must say so (FR9).

### 6.2 Marine — aisstream.io

The marine source is **aisstream.io**: a free websocket service (API key via account sign-up) that streams AIS position reports filtered by subscribed bounding boxes. The websocket model inverts the fetch pattern — instead of polling, the marine adapter holds a subscription and maintains a rolling latest-position table per MMSI in memory, snapshotted to the UI on the marine layer's display cadence. This fits the "latest available projection" principle naturally: the table *is* the latest projection.

**Coverage caveat:** terrestrial AIS coverage in the Persian Gulf is receiver-dependent and uneven; dark-fleet tankers routinely disable AIS; GPS jamming in the region produces on-land and circular ghost tracks. See FR9.

### 6.3 Land context — Overpass API (OpenStreetMap), including railway data

The land layer is infrastructure state, not telemetry, and the PRD stops pretending otherwise anywhere in the UI. Per D4, it is fetched at most daily per region and served from SQLite.

Query discipline is a requirement because conflict-theater regions are large:

- **Tag whitelist per feature class:** nodes/small geometries for `barrier=border_control`, `aeroway=aerodrome`, `harbour=*` / `landuse=port`, rail stations and yards; ways restricted to `highway` in {motorway, trunk, primary} and `railway=rail` (mainline). Secondary roads and below are excluded by default.
- **Per-region query partitioning** with the Overpass `timeout` and `maxsize` parameters set explicitly, mirror selection configurable, and exponential backoff on 429/504.
- **Geometry simplification** (Douglas-Peucker or equivalent) before storage, with a target of ≤ 5,000 rendered features per region.
- **Freshness surfacing:** the `osm_base` timestamp from each Overpass response is stored and displayed as the land layer's source timestamp.

OpenRailwayMap-style rendering detail is out of scope; mainline rail from OSM tags is sufficient for logistics context.

### 6.4 Base map tiles

MapLibre GL JS renders vector tiles from a free provider (OpenFreeMap or Protomaps self-hosted extract as fallback), with attribution rendered per OSM requirements. Raw tile.openstreetmap.org raster usage is avoided: its usage policy is unfriendly to auto-refreshing applications, and vector tiles are the better fit for restyling conflict-relevant features.

---

## 7. Prerequisites

Everything the developer or operator must have in hand before v0 work starts (or, for the operator of a distributed build, before first run). None of these are code; all of them have lead time or approval loops, which is why they are listed here rather than discovered mid-build.

### 7.1 Accounts and API credentials

| Credential | Provider | How obtained | Needed from | Notes |
|------------|----------|--------------|-------------|-------|
| OpenSky `client_id` + `client_secret` | OpenSky Network | Create an account, then create an API client on the Account page | v0 | OAuth2 client credentials flow; registered tier grants 4,000 credits/day. Non-commercial terms apply (§12). |
| aisstream.io API key | aisstream.io | Account sign-up on the site | v1 | Free websocket access; verify current terms and Gulf coverage (OQ1) before relying on it. |
| Vector tile provider key (if required) | OpenFreeMap / Protomaps | OpenFreeMap needs no key; a self-hosted Protomaps extract needs a one-time download | v0 | Attribution per OSM requirements either way. |

Overpass requires no account or key; the public instances are rate-limited by IP, so the only prerequisite is respecting the query discipline in §6.3.

### 7.2 Developer environment

Python 3.11+ with the backend dependencies (FastAPI, uvicorn, httpx, websockets, shapely for the FR9 landmask check, sqlite3 from the standard library), and Node.js LTS for the MapLibre frontend build. v2 packaging additionally requires the Rust toolchain (Tauri) and the Android/iOS SDKs (Capacitor), but neither is needed before that phase.

### 7.3 Data assets fetched once

Two static assets are downloaded during setup, not at runtime: a coarse landmask (Natural Earth 10 m land polygons, pending OQ4) for the marine spoof-suspect check, and the base map tile extract if the self-hosted Protomaps route is chosen.

### 7.4 Operator prerequisites for distributed builds (v2)

An end user installing the desktop or mobile build needs their own OpenSky API client and aisstream.io key, entered through the first-run credential prompt (NFR5). The app ships with no embedded keys, so this is a hard onboarding step, and the first-run flow must link directly to both providers' sign-up pages.

## 8. Functional requirements

Requirements are tagged P0 (cannot ship without), P1 (fast follow), P2 (architectural insurance). Acceptance criteria are checklist-form and testable.

### FR1 — Region selection (P0)

Predefined regions: Strait of Hormuz, Persian Gulf, Gulf of Oman, Iraq corridor, Syria corridor, Eastern Mediterranean, Suez Canal. Custom bounding boxes are supported with a hard area cap per layer (aviation cap tied to the credit budget; land cap tied to Overpass payload limits), and the UI displays estimated aviation credit cost before a custom region is activated.

- [ ] Selecting a predefined region triggers fetches only for enabled layers.
- [ ] A custom bbox exceeding a layer's area cap is rejected with a message naming the cap.
- [ ] Custom bbox activation shows estimated OpenSky credit cost per refresh before confirming.

### FR2 — Aviation projection (P0)

Latest OpenSky state vectors for the active region, rendered with heading-oriented icons; popup shows ICAO24, callsign, altitude, velocity, vertical rate, position source (ADS-B/MLAT/FLARM), and position age.

- [ ] Aircraft render within 5 s of a successful fetch for ≤ 500 states.
- [ ] A state vector older than 60 s (per its own `time_position`) renders visually de-emphasized.
- [ ] 429 responses surface as layer status "rate-limited," with retry-after honored automatically.

### FR3 — Marine projection (P0)

Latest-position table per MMSI from the aisstream.io subscription, snapshotted to the map on the marine display cadence; popup shows MMSI, name/callsign where broadcast, SOG, COG, and position age.

- [ ] Websocket disconnects trigger automatic reconnection with backoff; layer status shows "reconnecting."
- [ ] Vessels not heard from in 30 minutes render de-emphasized; in 2 hours, they are dropped from the projection.
- [ ] The adapter interface admits an alternative marine polling implementation without changes to the renderer.

### FR4 — Land context projection (P0)

Roads (motorway/trunk/primary), mainline rail, border crossings, ports, airports per the §6.3 whitelist, served from the SQLite region cache, refreshed at most every 24 h.

- [ ] First-ever load of a region performs the Overpass fetch with a visible progress state; subsequent loads serve from cache in under 2 s.
- [ ] The land layer's displayed source timestamp is the Overpass `osm_base` value, not the fetch time alone.

### FR5 — Layer control (P0)

Independent toggles for aviation, marine, land; a combined view and single-domain quick-switch. Disabled layers consume no API budget.

### FR6 — Refresh model (P0)

Per-layer cadence with per-layer overrides in config: aviation default 10 min (floor 60 s), marine snapshot default 60 s over the continuous stream, land default 24 h (floor 1 h). "Refresh now" triggers immediate fetches for enabled poll-based layers and an immediate snapshot of the marine table.

- [ ] Cadences are independent; changing one does not affect others.
- [ ] A manual refresh during an in-flight scheduled fetch coalesces rather than double-spending credits.

### FR7 — Freshness visibility (P0)

Each layer badge shows status ∈ {live, stale, loading, rate-limited, error, cached-fallback} plus both timestamps. **Stale is defined numerically:** source data older than 2× the layer's configured cadence. Error means the last fetch attempt failed.

### FR8 — Session snapshots and fallback cache (P0)

In-memory current snapshot per layer, replaced on refresh. The last successful snapshot per mobile layer (aviation, marine) is written to SQLite so a restart or a degraded connection presents the cached picture immediately, labeled `cached-fallback` with its true age. This is restart resilience, not history: exactly one snapshot per layer is retained.

### FR9 — Data integrity caveats (P0)

This requirement is new and specific to the theater. Each layer carries a persistent, one-tap caveat panel stating what the layer cannot show: transponder-silent military aircraft and Mode S position gaps (aviation); dark vessels, uneven terrestrial coverage, and GPS-jamming artifacts (marine); mapped-state-not-telemetry (land). Two cheap plausibility flags are computed at render time, with no analytics pipeline behind them:

- [ ] A marine position falling on land (point-in-polygon against a coarse landmask) renders with a spoof-suspect marker.
- [ ] Any track implying > 120 kn (marine) or > Mach 3 (aviation) between consecutive reports renders with an implausible-kinematics marker.
- [ ] The caveat panel is reachable from every layer badge and is not dismissible permanently.

### FR10 — Failure isolation (P0)

Layers fetch independently; one source failing never blocks the others. On failure with a warm fallback cache, the cached snapshot is shown per FR8; without one, the layer shows error state and the map continues with remaining layers.

### FR11 — Saved region presets and popup inspection depth (P1)

User-defined named regions persisted to SQLite; richer popups (raw payload inspection toggle).

### FR12 — Packaging targets (P2 in this spec, v2 in roadmap)

Desktop installers (Windows/macOS/Linux) via Tauri bundling the FastAPI service; mobile builds via Capacitor consuming a hosted or on-device service (open question OQ3). Auto-update mechanism deferred to the v2 spec.

---

## 9. Non-functional requirements

**NFR1 — Portable lightweight deployment.** One FastAPI process plus static frontend assets; no managed database, no message broker, no container orchestration. `pip install` + one command runs the browser app.

**NFR2 — Storage discipline.** SQLite only, with three tables' worth of responsibility and no more: land-layer region cache, single-snapshot fallback per layer, and configuration/presets. Any schema growth beyond that is a scope alarm, not a feature.

**NFR3 — Dual transparency.** Freshness honesty (FR7) and position honesty (FR9) are both requirements. The UI never implies the land layer is telemetry and never renders a spoof-suspect position without its marker.

**NFR4 — Performance.** Warm-cache app start to interactive map ≤ 15 s; full manual refresh of all enabled layers ≤ 15 s under normal source conditions on a residential connection; map interactive at 5,000 land features + 500 aircraft + 1,000 vessels on mid-range hardware.

**NFR5 — Secrets handling.** OpenSky client credentials and the aisstream.io key are loaded from environment or an OS keychain, never committed and never embedded in distributed binaries. Installable builds prompt for credentials on first run.

**NFR6 — Time convention.** All timestamps stored and displayed in UTC, labeled as such; no local-time rendering anywhere in the UI.

---

## 10. Technical architecture

```
frontend/            MapLibre GL JS, layer state, badges, caveat panel
backend/
  main.py            FastAPI app: REST for snapshots, SSE/WebSocket for push
  scheduler.py       per-layer cadence, coalescing, backoff
  sources/
    base.py          adapter interface (fetch → List[Feature])
    opensky.py       OAuth2 token manager, bbox states, credit accounting
    aisstream.py     websocket client, latest-position table per MMSI
    overpass.py      whitelisted queries, simplification, osm_base capture
  models.py          common Feature schema (below)
  store.py           SQLite: land cache, fallback snapshots, presets, config
  integrity.py       landmask point-in-polygon, kinematics flags
  config.py          regions, cadences, caps, mirrors
packaging/           tauri/ and capacitor/ shells (v2)
assets/              zij_mark.svg, zij_lockup.svg, icon exports
```

The backend pushes layer updates to the frontend over server-sent events, so the browser, the Tauri shell, and the Capacitor shell all consume identical interfaces. Nothing in `sources/`, `models.py`, or `store.py` knows which shell is attached — that is the property that makes D1's no-rewrite promise credible.

### Common feature schema

Unchanged in spirit from v1, with two additions (integrity flags, position age):

`domain` (air | marine | land) · `source` · `source_id` · `label` · `lat` · `lon` · `geometry_type` · `timestamp_source` · `timestamp_fetched` · `position_age_s` · `status` · `integrity_flags[]` · `attrs{}` (domain-specific: altitude/velocity/track for air; SOG/COG/heading for marine; OSM tags for land) · `raw_payload` (in-memory only, popup inspection).

---

## 11. Roadmap

**v0 — source validation spike.** FastAPI + one static MapLibre page. OpenSky and Overpass adapters only, Hormuz region hardcoded, manual refresh only. Purpose: validate credit math, Overpass payload sizes, and render performance with real theater data. Everything written here survives into v1.

**v1 — the monitor (browser app).** All P0 requirements: aisstream.io marine layer, per-layer scheduler, SQLite store, freshness and integrity UI, failure isolation, all seven predefined regions plus capped custom bboxes.

**v2 — installables.** Tauri desktop bundles; Capacitor mobile builds; credential onboarding flow; P1 features (presets, popup depth). A separate short spec governs auto-update and the mobile service-hosting decision (OQ3).

Scope rule across all phases: any addition requires a removal or an explicit phase extension, and the non-goals list in §4 is the reference every proposed addition is tested against.

---

## 12. Risks and constraints

**Licensing is a shipping constraint, not fine print.** OpenSky's API is free for personal, research, and non-profit use; any commercial use requires their consent. Distributing an installable app is compatible with non-commercial use, but monetizing it in any form is not, absent an agreement. aisstream.io carries its own terms to verify (OQ1). This constraint is recorded now so a future distribution decision does not trip over it.

**Coverage asymmetry is permanent.** The most operationally interesting actors (military aircraft, sanctioned tankers) are systematically the least visible in these feeds. FR9 exists so the product never launders that asymmetry into false confidence. The monitor shows the broadcasting picture; the caveat panel says exactly that.

**Upstream volatility.** OpenSky states its access policies and rate limits may change to protect system performance; aisstream.io is a free community service without an SLA. The adapter interface (one file per source, common schema) is the mitigation: swapping a source is a bounded task.

**Overpass load.** The public Overpass instances throttle aggressively. Daily cadence, tag whitelisting, and mirror configurability are the mitigations; a self-hosted Overpass extract is the escape hatch if throttling becomes chronic (P2, not planned).

---

## 13. Success criteria

Evaluated four weeks after v1 completion, from the operator's own usage log:

1. Warm start to interactive combined map in ≤ 15 s, measured on the target laptop; ≥ 90% of sessions.
2. Full manual refresh in ≤ 15 s under normal source conditions; ≥ 90% of refreshes.
3. Zero sessions terminated by a single-source failure (FR10 verified in practice, not just tests).
4. Aviation credit consumption ≤ 50% of daily allowance in a typical monitoring day, leaving manual-refresh headroom.
5. The stale badge and integrity markers have each fired correctly at least once against real data (verifying the honesty machinery is not decorative).
6. No hosted database, broker, or cloud dependency in the default deployment.

---

## 14. Open questions

| ID | Question | Owner | Blocking? |
|----|----------|-------|-----------|
| OQ1 | Confirm aisstream.io terms of service, message coverage in the Persian Gulf, and key rate/connection limits against current documentation. | Author | Blocks v1 marine layer (not v0) |
| OQ2 | Commission an ADS-B feeder to raise the OpenSky allowance to 8,000 credits/day? Hardware cost vs. benefit. | Author | Non-blocking; improves the aviation budget |
| OQ3 | Mobile architecture: bundle the Python service on-device (heavier, offline-capable) vs. a personally hosted backend the mobile app consumes (thin client, requires a host)? | Author | Blocks v2 only |
| OQ4 | Landmask source and resolution for the FR9 point-in-polygon check (Natural Earth 10 m is the default candidate). | Author | Non-blocking; resolve during v1 |
| OQ5 | Formal name/trademark clearance for "Zij" beyond the informal software-collision scan. | Author | Blocks public distribution (v2), not development |

---

## 15. Future considerations

If usage pressure ever justifies growth, the ordered next steps remain modest: multi-snapshot short history (a tail, not an archive), configurable watch-notes per region, and richer land-feature filtering. Historical storage, alerting, and graph analytics stay outside this product's walls; if they become necessary, they belong in a separate system that consumes this one's snapshots rather than a rewrite of this one. The monitor's job is to show the latest honest picture and nothing else — the moment it tries to remember, it has become a different product, and that product deserves its own PRD.
