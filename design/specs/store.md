# Spec — `store.py` (SQLite access layer)

**Purpose.** The only SQLite gateway (D4, NFR2, [ADR-10](../docs/DECISIONS.md#adr-10--sqlite-access)): stdlib `sqlite3` behind a thin `asyncio.to_thread` async wrapper over the three-table DDL in [storage.md](../contracts/storage.md). Keeps blocking DB work off the event loop.

## Public interface
```python
class Store:
    async def init(self) -> None                                  # open conn, apply schema.sql, WAL
    async def close(self) -> None

    async def get_land_cache(self, region_id: str) -> LandCacheRow | None
    async def put_land_cache(self, row: LandCacheRow) -> None      # upsert on region_id
    async def get_fallback(self, layer: Domain) -> LayerSnapshot | None
    async def put_fallback(self, snap: LayerSnapshot) -> None      # upsert, one row per layer
    async def list_presets(self) -> list[PresetRow]
    async def add_preset(self, name: str, bbox, label: str) -> int # raises ConflictError on UNIQUE clash
    async def delete_preset(self, preset_id: int) -> None
    async def get_config_overrides(self) -> dict[str, Any]         # kind='config_override' rows
    async def put_config_override(self, name: str, payload: dict) -> None
```
`LandCacheRow`/`PresetRow` are small pydantic/dataclass mirrors of the DDL columns. `ConflictError` maps to `409 conflict` (api.md presets).

## Internal design

### Connection lifecycle ([ADR-10](../docs/DECISIONS.md#adr-10--sqlite-access))
- **One module/instance-level `sqlite3.Connection`**, opened with `check_same_thread=False`, and **every** call funnels through `asyncio.to_thread(self._exec, ...)`. `to_thread` uses the default executor; since all DB work is serialized behind one short critical section and access is tiny/infrequent (storage.md), an `asyncio.Lock` around each `to_thread` call guarantees single-writer ordering without `sqlite3` cross-thread misuse.
- `init()` opens the conn, sets pragmas, applies `schema.sql`. `close()` closes it (ARCHITECTURE §4.4).
- Path resolution via **platformdirs** (`user_data_dir("zij")/zij.db`), overridable by `ZIJ_DB_PATH` (storage.md). No shell-specific branching (shell boundary).

### PRAGMAs / schema init
- `PRAGMA journal_mode=WAL` (concurrent readers + single writer), `foreign_keys=ON`, `user_version` checked on open (storage.md DDL).
- `init()` executes `schema.sql` (`CREATE TABLE IF NOT EXISTS ...`) idempotently — no-op on an existing DB.

### Query set (exact)
- **land_cache** — `get`: `SELECT ... WHERE region_id=?`. `put`: `INSERT INTO land_cache(...) VALUES(...) ON CONFLICT(region_id) DO UPDATE SET bbox=excluded.bbox, geojson=excluded.geojson, feature_count=excluded.feature_count, osm_base=excluded.osm_base, fetched_at=excluded.fetched_at`. `geojson` stored render-ready (single row read+parse = FR4 <2 s path). Displayed source ts = `osm_base` (FR4).
- **fallback_snapshots** — `get`: `SELECT snapshot_json, fetched_at FROM fallback_snapshots WHERE layer=?` → parse `LayerSnapshot.model_validate_json`; caller labels `cached-fallback` with age `now - fetched_at`. `put`: `INSERT ... ON CONFLICT(layer) DO UPDATE ...` using `snap.model_dump_json()` (raw_payload auto-excluded, feature-schema.md). PK on `layer` enforces "exactly one snapshot per layer" (FR8) — no cleanup code.
- **config_presets** — `list_presets`: `SELECT id,name,payload_json,created_at WHERE kind='region_preset'`. `add_preset`: `INSERT ...` catching `sqlite3.IntegrityError` on `UNIQUE(kind,name)` → `ConflictError`. `delete_preset`: `DELETE WHERE id=? AND kind='region_preset'`. Overrides: `get_config_overrides` selects `kind='config_override'`; `put_config_override` upserts on `UNIQUE(kind,name)`.
- All timestamps stored ISO-8601 UTC `Z` (NFR6).

### Schema versioning / migration (storage.md)
- `user_version` = 1. On open, if `user_version < CURRENT`, run an ordered list of migration steps keyed on the current version, then set the new version. v1 has none (schema is fresh). No migration framework (80/20).

### Corruption recovery
- On `init()`, if opening/querying raises `sqlite3.DatabaseError` ("file is not a database" / malformed) or `PRAGMA integrity_check` != `ok`: **this is a cache DB — delete the file and recreate from `schema.sql`.** Log a warning naming the path. Justified: every table is either a rebuildable cache (`land_cache` re-fetches from Overpass; `fallback_snapshots` re-populate on next refresh) or low-value presets (accepted small loss). No user data is authoritative here (registry is; ARCHITECTURE §3). State this recovery is intentional, not silent data loss of anything irreplaceable.

### Concurrency
`to_thread` + per-call `asyncio.Lock` keeps the loop unblocked during a land write (the largest payload) while preserving write ordering ([ADR-10](../docs/DECISIONS.md#adr-10--sqlite-access)). Swap-compatible with `aiosqlite` behind the same signatures if load ever justifies (it won't at this volume — measure).

## Failure modes
- DB locked/transient `sqlite3.OperationalError` → one retry after 100 ms, then raise (caller decides; a failed fallback write is non-fatal — the registry remains authoritative).
- Corruption → delete-and-recreate (above).
- `UNIQUE` clash on preset → `ConflictError` (`409`).

## Configuration consumed
`ZIJ_DB_PATH` env override; otherwise platformdirs. No `[…]` TOML section (path is env/derived).

## Acceptance criteria
- [ ] **NFR2** — exactly three tables; any fourth is a schema-change alarm, not added here.
- [ ] **FR4** — `get_land_cache` returns a render-ready GeoJSON row in a single read+parse (<2 s path).
- [ ] **FR8** — `put_fallback` upserts one row per layer (PK-enforced); `get_fallback` round-trips a `LayerSnapshot` with `raw_payload` absent.
- [ ] **NFR1/[ADR-10]** — all access via `to_thread`; no blocking `sqlite3` call on the event loop; WAL enabled.
- [ ] **FR11** — presets CRUD with `409` on duplicate name; config_override read/write for the highest-precedence config layer.
- [ ] Corruption is recovered by delete-and-recreate with a logged warning; app continues.
