# Spec — `integrity.py` (FR9 plausibility flags)

**Purpose.** FR9 (D6, NFR3): compute the two cheap plausibility flags — landmask point-in-polygon (marine-on-land → spoof-suspect) and implausible kinematics (implied speed between consecutive reports) — plus the static per-layer caveat text. **Pure:** Features in → Features with `integrity_flags` out; no I/O at flag time.

## Public interface
```python
class Integrity:
    def __init__(self, cfg: IntegrityCfg): ...     # cfg = [integrity] (config.md): landmask_path,
                                                   # max_speed_kn_marine, max_speed_kn_air.
                                                   # Loads Natural Earth 10m land polygons once.

    def apply(self, features: list[Feature],
              prev: dict[str, PrevPos]) -> list[Feature]:
        """Post-adapter, pre-registry (scheduler.md write path). Mutates/returns
        features with integrity_flags appended. No I/O. prev: source_id -> last
        (lat, lon, timestamp_source). Marine: adapter's _prev_pos (aisstream.md);
        air: scheduler-derived from the outgoing registry snapshot (scheduler.md)."""

CAVEATS: dict[Domain, list[str]]   # static text, served by GET /api/layers/{domain}/caveats
```
`IntegrityFlag` values are `SPOOF_SUSPECT_ON_LAND` and `IMPLAUSIBLE_KINEMATICS` (feature-schema.md — open enum, add conservatively).

## Internal design

### Landmask point-in-polygon (marine only)
- **Load once at startup:** Natural Earth **10 m land polygons** (OQ4 default, §7.3) into a shapely `STRtree` of land `Polygon`/`MultiPolygon` geometries. Prepared/indexed once; held in memory ([ADR-8](../docs/DECISIONS.md#adr-8--concurrency-pure-asyncio)).
- **Per marine feature:** build `Point(lon, lat)`; `STRtree.query(point)` → candidate polygons by bbox; test `polygon.contains(point)` on candidates. If any contains → append `SPOOF_SUSPECT_ON_LAND` (a vessel on land = GPS-jamming/spoof ghost, §6.2). STRtree makes it a bbox-index lookup + a few precise `contains` tests, not a linear scan of all land polygons.
- Applied to `domain == MARINE` only (air on land is normal; land features are land).

### Performance envelope
- Design target **<100 ms for 1000 vessels/snapshot** (NFR4 vessel budget). STRtree query is ~O(log n) candidates; per-point cost is microseconds (DECISIONS ADR-8). Measure, don't speculate — if a snapshot's landmask pass ever dominates a 60 s marine tick, wrap `apply` in `to_thread` behind the same call (no architectural change, ADR-8). Design keeps it in-loop by default.

### Implausible kinematics (marine + air)
- For each feature with a `prev[source_id]` and both timestamps present:
  - `dt = (ts_now - ts_prev).total_seconds()`. **Guard div-by-zero / same-timestamp: if `dt <= 0`, skip** (duplicate/out-of-order report — cannot compute, do not flag).
  - `dist_nm = haversine(prev_lat, prev_lon, lat, lon) / 1852`.
  - `implied_kn = dist_nm / (dt / 3600)`.
  - **Marine:** `implied_kn > cfg.max_speed_kn_marine` (120 kn) → `IMPLAUSIBLE_KINEMATICS` (FR9; `sog_kn` native, but the flag uses positional implied speed, not broadcast SOG — a spoof can lie about SOG).
  - **Air:** `implied_kn > cfg.max_speed_kn_air` (990 kn, Mach 3 ≈ 990 kn) → `IMPLAUSIBLE_KINEMATICS`. Air `prev` is supplied by the scheduler, derived from the outgoing registry snapshot at write-path step 2 (scheduler.md); an empty map (first fetch, region switch) yields no air flags.
- Uses positional implied speed (consecutive reports), independent of the broadcast velocity fields.

> Resolved: aisstream.md maintains `_prev_pos` per MMSI (marine `prev`); the scheduler derives the air `prev` map from the outgoing registry snapshot before replacing it (scheduler.md write-path step 2). Both maps thread into `apply`; an empty air map simply produces no air flags.

### Purity & placement
- Runs **post-adapter, pre-registry** in the scheduler write path (scheduler.md). No network, no DB, no clock-dependent side effects beyond reading `datetime.now(UTC)` for age (age is already on the feature). Deterministic given inputs → unit-testable in isolation.

### Static caveat text (per layer, FR9 / api.md caveats)
```python
CAVEATS = {
  Domain.AIR: [
    "Shows only aircraft broadcasting ADS-B/Mode S within receiver coverage.",
    "Military and state aircraft with transponders switched off are invisible here.",
    "Mode S-only aircraft broadcast no position; altitude/position gaps are expected.",
  ],
  Domain.MARINE: [
    "Terrestrial AIS coverage in the Persian Gulf is receiver-dependent and uneven.",
    "Dark-fleet vessels routinely disable AIS and will not appear.",
    "GPS jamming in the region produces on-land and circular ghost tracks; positions may be spoofed.",
  ],
  Domain.LAND: [
    "This layer is mapped infrastructure state, not live telemetry.",
    "Positions reflect OpenStreetMap data at the shown osm_base timestamp, not current ground truth.",
    "Absence of a feature means it is unmapped, not necessarily absent on the ground.",
  ],
}
```
Served by `GET /api/layers/{domain}/caveats` alongside live `active_flags` counts computed from the current registry snapshot (api.md). Panel is non-dismissible (FR9 acceptance) — a frontend property.

## Failure modes
- Landmask asset missing/corrupt at startup → **fail fast** with a named error (the FR9 spoof check is a P0 honesty requirement; NFR3 forbids shipping it silently disabled). Startup is the right place (asset fetched in §7.3 setup).
- A feature with null `lat`/`lon` cannot occur (schema requires them); null `timestamp_source` → skip kinematics for that feature (age unknown), landmask still applies.

## Configuration consumed
`[integrity]` (config.md): `landmask_path` (setup-provided, §7.3; empty → platformdirs data-dir default), `max_speed_kn_marine` (120), `max_speed_kn_air` (990). The thresholds are config-resolved rather than hardcoded so they are tunable and self-documenting, not magic numbers.

## Acceptance criteria
- [ ] **FR9** — a marine position inside a land polygon gets `spoof_suspect_on_land`; verified against a known on-land coordinate.
- [ ] **FR9** — a consecutive-report pair implying >120 kn (marine) / >Mach 3≈990 kn (air) gets `implausible_kinematics`; same-timestamp pairs (`dt<=0`) are skipped without error (no div-by-zero).
- [ ] **NFR4** — landmask pass over 1000 vessels completes <100 ms using the prepared STRtree (measured).
- [ ] **NFR3** — `apply` is pure (no I/O) and runs post-adapter/pre-registry; the same Features in always yield the same flags.
- [ ] **FR9** — per-layer caveat text matches the content above and is served via the caveats endpoint; panel non-dismissible.
