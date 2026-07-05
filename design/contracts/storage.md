# Contract — SQLite Storage

Implements D4 and NFR2. **Exactly three responsibilities; schema growth beyond them is a scope alarm, not a feature** (NFR2). Access model in [ADR-10](../docs/DECISIONS.md#adr-10--sqlite-access). This is `backend/store.py` + `schema.sql`.

The three tables map 1:1 to the three responsibilities:

| table | responsibility | PRD |
|---|---|---|
| `land_cache` | land-layer region cache | D4, FR4, §6.3 |
| `fallback_snapshots` | one restart-resilience snapshot per mobile layer | FR8 |
| `config_presets` | user presets + config overrides | FR11, §10 |

## DDL (`schema.sql`)

```sql
PRAGMA journal_mode = WAL;      -- single writer + concurrent readers; fine for our volume
PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;        -- schema version; bump only on a real migration

-- 1. Land cache (D4). One row per region. Simplified GeoJSON served for 24h (floor 1h).
CREATE TABLE IF NOT EXISTS land_cache (
    region_id       TEXT    PRIMARY KEY,          -- "hormuz" | "custom:<hash>"
    bbox            TEXT    NOT NULL,              -- JSON [west,south,east,north]
    geojson         TEXT    NOT NULL,             -- simplified FeatureCollection (<=5000 feats)
    feature_count   INTEGER NOT NULL,
    osm_base        TEXT,                          -- Overpass osm_base, ISO-8601 UTC (source ts)
    fetched_at      TEXT    NOT NULL               -- when Zij fetched it, ISO-8601 UTC
);

-- 2. Fallback snapshots (FR8). EXACTLY one row per mobile layer. PK enforces it.
CREATE TABLE IF NOT EXISTS fallback_snapshots (
    layer           TEXT    PRIMARY KEY
                            CHECK (layer IN ('air','marine')),  -- land is cached above
    region_id       TEXT    NOT NULL,
    snapshot_json   TEXT    NOT NULL,             -- LayerSnapshot.model_dump_json() (raw_payload excluded)
    source_ts       TEXT,                          -- representative source ts, ISO-8601 UTC
    fetched_at      TEXT    NOT NULL               -- true age basis for the cached-fallback badge
);

-- 3. Presets + config overrides (FR11, §10).
CREATE TABLE IF NOT EXISTS config_presets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT    NOT NULL CHECK (kind IN ('region_preset','config_override')),
    name            TEXT    NOT NULL,
    payload_json    TEXT    NOT NULL,             -- region_preset: {bbox,label}; override: {key:value}
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    UNIQUE (kind, name)
);
```

That is the whole schema. No `features` table, no history table, no per-fetch log — those would contradict the no-history non-goal (§4) and NFR2. If a fourth responsibility ever seems necessary, it is a scope decision requiring a PRD change, not a migration.

## Semantics & rules

### land_cache (D4, FR4, §6.3)
- **Keyed by `region_id`.** Upsert on fetch: `INSERT ... ON CONFLICT(region_id) DO UPDATE`.
- **Refresh cadence:** serve from cache if `now - fetched_at < 24h` (config `land.cadence_s`, floor 1h). Older → re-fetch Overpass, re-simplify (Douglas-Peucker, ≤5000 features §6.3), replace the row.
- **Displayed source timestamp is `osm_base`, not `fetched_at`** (FR4 acceptance). Both are stored; the land badge shows `osm_base`.
- **Eviction:** none by count (7 predefined + a handful of custom is tiny). Optional: drop `custom:*` rows unused >30 days — deferred, not v1.
- `geojson` is stored render-ready so the FR4 "<2 s from cache" path is a single row read + parse.

### fallback_snapshots (FR8)
- **Exactly one row per layer**, guaranteed by the `layer` primary key. Written via upsert after every successful air/marine refresh: `INSERT ... ON CONFLICT(layer) DO UPDATE`. This *is* "exactly one snapshot per layer is retained" (FR8) — enforced by the schema, not by cleanup code.
- **`raw_payload` excluded** automatically: we persist `model_dump_json()`, and the field is `exclude=True` ([feature-schema.md](feature-schema.md#raw_payload-handling)).
- **`fetched_at` is the true-age basis:** on cold start the layer loads from here labeled `cached-fallback` with age `now - fetched_at` (FR8, [ARCHITECTURE §4.1](../docs/ARCHITECTURE.md#41-startup--warm-cache-path-15-s-to-interactive-nfr4)).
- Land is **not** here — it lives in `land_cache` (avoids double-storing land; NFR2).

### config_presets (FR11, §10)
- `region_preset`: `payload_json = {"bbox":[w,s,e,n],"label":"..."}`. Backs `GET/POST/DELETE /api/presets` ([api.md](api.md)).
- `config_override`: runtime UI tweaks (e.g. a per-layer cadence override) and the persisted last active region (`name='active_region'`, `payload_json={"region_id":...}`, written on region switch and read at startup) — the highest-precedence config layer ([config.md](config.md#precedence), [ADR-6](../docs/DECISIONS.md#adr-6--config-format--precedence)).

## Access pattern

Stdlib `sqlite3` behind a thin async wrapper (`asyncio.to_thread`), **not** aiosqlite ([ADR-10](../docs/DECISIONS.md#adr-10--sqlite-access)). Access is small and infrequent: one land read on region activation, one fallback upsert per air/marine refresh, rare preset writes. All DB calls go through `store.py` so the wrapper is swap-compatible if load ever justifies aiosqlite (measure, don't speculate).

```python
# store.py shape (illustrative)
async def get_land_cache(region_id: str) -> LandCacheRow | None: ...
async def put_land_cache(row: LandCacheRow) -> None: ...
async def get_fallback(layer: Domain) -> LayerSnapshot | None: ...
async def put_fallback(snap: LayerSnapshot) -> None: ...       # upsert, one row/layer
async def list_presets() -> list[PresetRow]: ...
async def add_preset(name: str, bbox, label) -> int: ...       # 409 on UNIQUE clash
async def delete_preset(preset_id: int) -> None: ...
```
WAL mode + serialized writes through `to_thread` keep the loop unblocked during a land write.

## Migration (v1 — trivially simple)

- Apply `schema.sql` at startup: `CREATE TABLE IF NOT EXISTS` is idempotent (no-op on an existing DB).
- Version tracked by `PRAGMA user_version` (=1). A v2 change bumps it and runs an ordered list of `ALTER`/backfill steps keyed on the current `user_version`. No Alembic, no migration framework for three tables (80/20).

## File location per platform

`store.py` resolves the DB path via **platformdirs** (suggest adding the dep — the correct wheel for cross-platform app data dirs; don't hand-roll `%APPDATA%`/`~/.local/share`):

| target | path |
|---|---|
| browser dev (v1) | `platformdirs.user_data_dir("zij")/zij.db`, override via `ZIJ_DB_PATH` |
| Tauri desktop (v2) | app data dir the Tauri shell exposes → same env override |
| Capacitor mobile (v2) | on-device app data dir (OQ3-dependent) → same env override |

The path is config, never a shell-specific branch in `store.py` (shell boundary, [ARCHITECTURE §6](../docs/ARCHITECTURE.md#6-the-shell-boundary-d1-no-rewrite-promise)).
