# Zij (زيج) — Product Working Reference

## Product Statement

Zij is a lightweight, installable application that projects the most recent available aviation, marine, and land-logistics data over a map for regions affected by the Iranian conflict. Designed for a single analyst working a select-region → fetch → inspect → refresh loop. Core design principle: **latest available projection** — freshness differs by source, and the application shows each layer's real timestamp rather than pretending all sources are equally live.

## What Zij Is NOT (Non-goals from §4)

| Out of Scope | Reason |
|---|---|
| Historical storage and replay | Keeps architecture single-tier; single-analyst tool stays small. |
| Trend analysis, anomaly detection, graph analytics | Separate product; Neo4All/G-Lab is the home for that work. |
| Entity resolution beyond source identifiers | ICAO24 and MMSI displayed as-is; no cross-source identity fusion. |
| Alerting, forecasting, sanctions-network modeling | Intelligence-platform territory, not a projection monitor. |
| Multi-tenancy, billing, accounts | Single-analyst tool; non-commercial licensing constraint (OpenSky, aisstream terms). |

## Locked Decisions (D1–D7)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Web-first: FastAPI + MapLibre GL JS → Tauri (desktop) + Capacitor (mobile) | Same codebase across all platforms. |
| D2 | Marine primary: aisstream.io websocket | AISHub requires owned hardware; cannot block v1. |
| D3 | Per-layer cadence: aviation 10 min, marine snapshot 60 s, land 24 h | Three domains have different operational tempos. |
| D4 | SQLite: standard for land cache + fallback mobile snapshots | Overpass queries expensive; cache daily updates. |
| D5 | OpenSky: OAuth2 client credentials with credit budget | OAuth2 now mandatory; cost scales with bbox area. |
| D6 | Data-integrity caveats as P0 (FR9) | Position honesty (spoofs, jamming, dark vessels) = freshness honesty. |
| D7 | Product name: Zij (زيج), segmented-scope logomark | Semantic fit; clean namespace. |

## Data Sources at a Glance

| Source | Auth | Cadence | Key Constraint |
|--------|------|---------|-----------------|
| OpenSky `/states/all` | OAuth2 client credentials | 10 min (default) | 4,000 credits/day (registered); ≤2 credits per call; predefined regions fit within budget + manual refresh headroom. |
| aisstream.io | API key (free sign-up) | Continuous; snapshot every 60 s | Verify Gulf coverage & current ToS (OQ1); websocket stream held in-memory. |
| AISHub | Owned receiver (≥10-vessel, 90% uptime) | 1 req/min max | Dormant secondary adapter; only if receiver commissioned (OQ2). |
| Overpass (OSM) | None (public, IP-rate-limited) | ≤24 h per region | Tag whitelist enforced; query partitioned; exponential backoff on 429/504. |
| Vector base tiles | None (OpenFreeMap) | Static | MapLibre GL JS; attribution per OSM license. |

## P0 Functional Requirements (FR1–FR10)

| ID | Name | Essence |
|----|------|---------|
| FR1 | Region selection | Predefined regions (Strait of Hormuz, Persian Gulf, Gulf of Oman, Iraq/Syria corridors, E. Mediterranean, Suez); capped custom bboxes; estimated aviation credit cost shown before activation. |
| FR2 | Aviation projection | Latest OpenSky state vectors, heading-oriented icons; popup: ICAO24, callsign, altitude, velocity, vertical rate, position source, age. De-emphasized if > 60 s old. 429 → "rate-limited" badge. |
| FR3 | Marine projection | Latest-position table per MMSI from aisstream.io subscription; popup: MMSI, name/callsign, SOG, COG, age. Auto-reconnect on disconnect. De-emphasized > 30 min; dropped > 2 h. |
| FR4 | Land context projection | Roads (motorway/trunk/primary), mainline rail, borders, ports, airports per whitelist; served from SQLite, refreshed ≤24 h. First load shows progress; subsequent < 2 s. Displays Overpass `osm_base` timestamp. |
| FR5 | Layer control | Independent toggles for aviation, marine, land. Disabled layers consume zero API budget. |
| FR6 | Refresh model | Per-layer cadence (aviation floor 60 s, marine instant snapshot, land floor 1 h); "Refresh now" triggers immediate poll-based fetches + instant marine snapshot. Manual refresh during in-flight fetch coalesces. |
| FR7 | Freshness visibility | Layer badges: status ∈ {live, stale, loading, rate-limited, error, cached-fallback} + fetch timestamp + data-source timestamp. **Stale = data > 2× configured cadence.** |
| FR8 | Session snapshots & fallback cache | In-memory current per layer; last successful mobile layer snapshot (aviation, marine) persisted to SQLite, labeled `cached-fallback` with true age. Restart resilience only (one snapshot per layer). |
| FR9 | Data integrity caveats (theater-specific) | Persistent one-tap caveat panel per layer listing what it cannot show (e.g., transponder-silent military; dark tankers; jamming artifacts). Two plausibility flags at render: spoof-suspect (marine on-land), implausible-kinematics (> 120 kn marine or Mach 3 aviation). |
| FR10 | Failure isolation | Layers fetch independently; one failure never blocks others. Failed fetch + warm fallback cache → show cached snapshot labeled as such; failed fetch + no cache → error state, map continues with remaining layers. |

## Non-Functional Requirements (NFR1–NFR6)

| ID | One-liner |
|----|-----------|
| NFR1 | One FastAPI process + static frontend; no managed database, no broker, no orchestration. `pip install` + one command runs the browser app. |
| NFR2 | SQLite only, three tables max: land-region cache, fallback snapshots, config/presets. Schema growth beyond that is a scope alarm. |
| NFR3 | Dual transparency mandatory: freshness honesty (FR7) + position honesty (FR9). Never imply land layer is telemetry; never render spoof-suspect position without its marker. |
| NFR4 | Warm-cache start to interactive map ≤15 s; full manual refresh ≤15 s under normal conditions; interactive at 5k land features + 500 aircraft + 1k vessels on mid-range hardware. |
| NFR5 | OpenSky credentials and aisstream key from environment or OS keychain, never committed/embedded. Installable builds prompt for credentials on first run. |
| NFR6 | All timestamps in UTC, labeled as such; no local-time rendering anywhere in UI. |

## Roadmap & Scope Rule

| Phase | Deliverable |
|-------|------------|
| **v0** | Source validation spike: FastAPI + static MapLibre, OpenSky & Overpass only, Hormuz hardcoded, manual refresh. Validate credit math, Overpass payloads, render perf with real data. |
| **v1** | The monitor (browser app): all P0 requirements, aisstream.io marine layer, per-layer scheduler, SQLite store, all 7 predefined regions, capped custom bboxes. |
| **v2** | Installables: Tauri desktop bundling, Capacitor mobile builds, credential onboarding, P1 features (presets, popup depth). |
| **Scope rule** | Any addition requires removal or explicit phase extension. Non-goals list (PRD §4) is the reference every proposed addition is tested against. |

## Success Criteria (evaluated 4 weeks post-v1)

1. Warm start ≤ 15 s, ≥90% of sessions.
2. Full manual refresh ≤ 15 s under normal conditions, ≥90% of refreshes.
3. Zero sessions terminated by single-source failure (FR10 verified in practice).
4. Aviation credit consumption ≤50% of daily allowance in typical monitoring day.
5. Stale badge and integrity markers each fired correctly ≥1 time against real data (honesty machinery verified non-decorative).
6. No hosted database, broker, or cloud dependency in default deployment.

## Open Questions (OQ1–OQ5)

| ID | Question | Blocks |
|----|----------|--------|
| OQ1 | Confirm aisstream.io ToS, Persian Gulf coverage, key rate and connection limits vs. current docs. | v1 marine layer |
| OQ2 | Commission owned AIS receiver (NL siting) + ADS-B feeder to unlock AISHub and raise OpenSky allowance to 8k credits/day? | Non-blocking; improves both budgets |
| OQ3 | Mobile service architecture: bundle Python on-device (offline-capable) or thin client consuming personal backend (requires a host)? | v2 mobile only |
| OQ4 | Landmask source and resolution for FR9 point-in-polygon check (Natural Earth 10 m is candidate). | Non-blocking; resolve in v1 |
| OQ5 | Formal name and trademark clearance for "Zij" beyond software-collision scan. | Blocks public distribution (v2), not development |

---

**Authoritative source:** [`zij_prd.md`](zij_prd.md) — this file is a digest; on conflict the PRD wins.
