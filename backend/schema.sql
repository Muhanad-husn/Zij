-- SQLite schema for Zij's storage layer (design/contracts/storage.md).
-- Exactly three responsibilities; schema growth beyond them is a scope
-- alarm, not a feature (NFR2). Transcribed verbatim from the frozen
-- contract's DDL.

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
