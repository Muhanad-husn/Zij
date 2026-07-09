"""SQLite storage layer (contract: design/contracts/storage.md; spec:
design/specs/store.md).

The only SQLite gateway (D4, NFR2, ADR-10): stdlib `sqlite3` behind a thin
`asyncio.to_thread` async wrapper over the three-table DDL in `schema.sql`,
keeping blocking DB work off the event loop. `store.py` never parses source
payloads (STRUCTURE.md) -- it only serializes/deserializes rows it is handed.

step (plans/store/01-land-cache.md, issue #11) implements the
`land_cache` path: `Store.init`/`close`/`get_land_cache`/`put_land_cache` and
`LandCacheRow`. step (plans/store/02-fallback-snapshots.md, issue #40)
adds the `fallback_snapshots` path: `Store.put_fallback`/`get_fallback`
(FR8). step (plans/store/03-config-presets.md, issue #41) adds the
`config_presets` path: `Store.list_presets`/`add_preset`/`delete_preset`/
`get_config_overrides`/`put_config_override`, `PresetRow`, and
`ConflictError` (FR11).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from asyncio import Lock, to_thread
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import platformdirs
from pydantic import BaseModel, ConfigDict, field_validator

from backend.models import LayerSnapshot, _reject_naive_datetime

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_logger = logging.getLogger(__name__)


def _resolve_db_path() -> Path:
    """`ZIJ_DB_PATH` env override; otherwise
    `platformdirs.user_data_dir("zij")/zij.db` (storage.md "File location per
    platform")."""
    override = os.environ.get("ZIJ_DB_PATH")
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir("zij")) / "zij.db"


class ConflictError(Exception):
    """Raised on a `UNIQUE(kind, name)` clash in `config_presets` (e.g. a
    duplicate preset name). Maps to `409 conflict` (api.md presets); the HTTP
    mapping itself is out of scope here (store.py stays transport-agnostic)."""


class LandCacheRow(BaseModel):
    """Mirrors the `land_cache` DDL columns (storage.md). `bbox` and
    `geojson` are carried as plain Python values on the model; `store.py`
    owns the TEXT-column JSON (de)serialization internally."""

    model_config = ConfigDict(extra="forbid")

    region_id: str
    bbox: tuple[float, float, float, float]
    geojson: dict[str, Any]
    feature_count: int
    osm_base: datetime | None
    fetched_at: datetime

    @field_validator("osm_base", "fetched_at")
    @classmethod
    def _validate_utc_aware(cls, value: datetime | None) -> datetime | None:
        return _reject_naive_datetime(value)


class PresetRow(BaseModel):
    """Mirrors the `config_presets` DDL columns for a `kind='region_preset'`
    row (storage.md). `payload_json` is unpacked into `bbox`/`label` on the
    model; `store.py` owns the TEXT-column JSON (de)serialization
    internally."""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    bbox: tuple[float, float, float, float]
    label: str
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _validate_utc_aware(cls, value: datetime) -> datetime:
        return _reject_naive_datetime(value)


class Store:
    """The only SQLite gateway (ADR-10). One instance-level
    `sqlite3.Connection`, opened `check_same_thread=False`, every call
    funneled through `asyncio.to_thread` behind a per-instance
    `asyncio.Lock` for write ordering."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else _resolve_db_path()
        self._conn: sqlite3.Connection | None = None
        self._lock = Lock()

    async def init(self) -> None:
        """Open the connection (if not already open), set PRAGMAs, and apply
        `schema.sql`. Idempotent -- safe to call more than once."""
        async with self._lock:
            await to_thread(self._init_sync)

    def _init_sync(self) -> None:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = self._open_healthy_connection()
        schema_sql = _SCHEMA_PATH.read_text()
        self._conn.executescript(schema_sql)

    def _open_healthy_connection(self) -> sqlite3.Connection:
        """Open `self._db_path`, verifying it is not corrupt (storage.md
        "Corruption recovery"). A `sqlite3.DatabaseError` on connect/query, or
        a non-'ok' `PRAGMA integrity_check`, is treated as corruption: the
        file (and any WAL sidecars) is deleted and a fresh connection is
        opened so the caller can recreate the schema from scratch. A
        healthy existing DB is left intact (no-op recovery)."""
        conn: sqlite3.Connection | None = None
        healthy = False
        try:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            result = conn.execute("PRAGMA integrity_check").fetchone()
            healthy = result is not None and result[0] == "ok"
        except sqlite3.DatabaseError:
            healthy = False

        if healthy:
            assert conn is not None
            return conn

        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass

        _logger.warning(
            "Corrupt/malformed SQLite database detected at %s -- deleting "
            "and recreating from schema.sql (every table is a rebuildable "
            "cache or low-value preset; no authoritative data is lost)",
            self._db_path,
        )
        for suffix in ("", "-wal", "-shm"):
            sidecar = Path(f"{self._db_path}{suffix}")
            if sidecar.exists():
                sidecar.unlink()

        return sqlite3.connect(str(self._db_path), check_same_thread=False)

    async def close(self) -> None:
        async with self._lock:
            await to_thread(self._close_sync)

    def _close_sync(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    async def get_land_cache(self, region_id: str) -> LandCacheRow | None:
        async with self._lock:
            return await to_thread(self._get_land_cache_sync, region_id)

    def _get_land_cache_sync(self, region_id: str) -> LandCacheRow | None:
        assert self._conn is not None, "Store.init() must be called first"
        cursor = self._conn.execute(
            "SELECT region_id, bbox, geojson, feature_count, osm_base, fetched_at "
            "FROM land_cache WHERE region_id = ?",
            (region_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        region_id_, bbox_json, geojson_json, feature_count, osm_base, fetched_at = row
        return LandCacheRow(
            region_id=region_id_,
            bbox=tuple(json.loads(bbox_json)),
            geojson=json.loads(geojson_json),
            feature_count=feature_count,
            osm_base=datetime.fromisoformat(osm_base) if osm_base is not None else None,
            fetched_at=datetime.fromisoformat(fetched_at),
        )

    async def put_land_cache(self, row: LandCacheRow) -> None:
        async with self._lock:
            await to_thread(self._put_land_cache_sync, row)

    def _put_land_cache_sync(self, row: LandCacheRow) -> None:
        assert self._conn is not None, "Store.init() must be called first"
        self._conn.execute(
            """
            INSERT INTO land_cache
                (region_id, bbox, geojson, feature_count, osm_base, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(region_id) DO UPDATE SET
                bbox=excluded.bbox,
                geojson=excluded.geojson,
                feature_count=excluded.feature_count,
                osm_base=excluded.osm_base,
                fetched_at=excluded.fetched_at
            """,
            (
                row.region_id,
                json.dumps(list(row.bbox)),
                json.dumps(row.geojson),
                row.feature_count,
                row.osm_base.isoformat().replace("+00:00", "Z")
                if row.osm_base is not None
                else None,
                row.fetched_at.isoformat().replace("+00:00", "Z"),
            ),
        )
        self._conn.commit()

    async def put_fallback(self, snap: LayerSnapshot) -> None:
        """Upsert the single fallback snapshot for `snap.meta.layer` (FR8:
        one fallback row per layer, replaced on each successful fetch)."""
        async with self._lock:
            await to_thread(self._put_fallback_sync, snap)

    def _put_fallback_sync(self, snap: LayerSnapshot) -> None:
        assert self._conn is not None, "Store.init() must be called first"
        meta = snap.meta
        source_ts = (
            meta.timestamp_source.isoformat().replace("+00:00", "Z")
            if meta.timestamp_source is not None
            else None
        )
        fetched_at = (
            meta.timestamp_fetched.isoformat().replace("+00:00", "Z")
            if meta.timestamp_fetched is not None
            else None
        )
        self._conn.execute(
            """
            INSERT INTO fallback_snapshots
                (layer, region_id, snapshot_json, source_ts, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(layer) DO UPDATE SET
                region_id=excluded.region_id,
                snapshot_json=excluded.snapshot_json,
                source_ts=excluded.source_ts,
                fetched_at=excluded.fetched_at
            """,
            (
                meta.layer.value,
                meta.region_id,
                snap.model_dump_json(),
                source_ts,
                fetched_at,
            ),
        )
        self._conn.commit()

    async def get_fallback(self, layer: str) -> LayerSnapshot | None:
        """Fetch the fallback snapshot for `layer` ('air' or 'marine'), if
        one exists (FR8: cold-start/outage fallback data)."""
        async with self._lock:
            return await to_thread(self._get_fallback_sync, layer)

    def _get_fallback_sync(self, layer: str) -> LayerSnapshot | None:
        assert self._conn is not None, "Store.init() must be called first"
        cursor = self._conn.execute(
            "SELECT snapshot_json FROM fallback_snapshots WHERE layer = ?",
            (layer,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        (snapshot_json,) = row
        return LayerSnapshot.model_validate_json(snapshot_json)

    async def list_presets(self) -> list[PresetRow]:
        """List every `kind='region_preset'` row (FR11)."""
        async with self._lock:
            return await to_thread(self._list_presets_sync)

    def _list_presets_sync(self) -> list[PresetRow]:
        assert self._conn is not None, "Store.init() must be called first"
        cursor = self._conn.execute(
            "SELECT id, name, payload_json, created_at FROM config_presets "
            "WHERE kind = 'region_preset'"
        )
        rows = cursor.fetchall()
        presets = []
        for row_id, name, payload_json, created_at in rows:
            payload = json.loads(payload_json)
            presets.append(
                PresetRow(
                    id=row_id,
                    name=name,
                    bbox=tuple(payload["bbox"]),
                    label=payload["label"],
                    created_at=datetime.fromisoformat(created_at),
                )
            )
        return presets

    async def add_preset(
        self, name: str, bbox: tuple[float, float, float, float], label: str
    ) -> int:
        """Insert a `kind='region_preset'` row; raise `ConflictError` on a
        `UNIQUE(kind, name)` clash (FR11, api.md `409`)."""
        async with self._lock:
            return await to_thread(self._add_preset_sync, name, bbox, label)

    def _add_preset_sync(
        self, name: str, bbox: tuple[float, float, float, float], label: str
    ) -> int:
        assert self._conn is not None, "Store.init() must be called first"
        now = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
        payload_json = json.dumps({"bbox": list(bbox), "label": label})
        try:
            cursor = self._conn.execute(
                "INSERT INTO config_presets "
                "(kind, name, payload_json, created_at, updated_at) "
                "VALUES ('region_preset', ?, ?, ?, ?)",
                (name, payload_json, now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"preset {name!r} already exists") from exc
        self._conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    async def delete_preset(self, preset_id: int) -> None:
        """Delete a `kind='region_preset'` row by id. A missing id is a
        no-op (FR11)."""
        async with self._lock:
            await to_thread(self._delete_preset_sync, preset_id)

    def _delete_preset_sync(self, preset_id: int) -> None:
        assert self._conn is not None, "Store.init() must be called first"
        self._conn.execute(
            "DELETE FROM config_presets WHERE id = ? AND kind = 'region_preset'",
            (preset_id,),
        )
        self._conn.commit()

    async def get_config_overrides(self) -> dict[str, Any]:
        """Every `kind='config_override'` row, keyed by `name` (config.md
        precedence: the highest-precedence config layer)."""
        async with self._lock:
            return await to_thread(self._get_config_overrides_sync)

    def _get_config_overrides_sync(self) -> dict[str, Any]:
        assert self._conn is not None, "Store.init() must be called first"
        cursor = self._conn.execute(
            "SELECT name, payload_json FROM config_presets WHERE kind = 'config_override'"
        )
        return {
            name: json.loads(payload_json) for name, payload_json in cursor.fetchall()
        }

    async def put_config_override(self, name: str, payload: dict[str, Any]) -> None:
        """Upsert a `kind='config_override'` row on `UNIQUE(kind, name)`."""
        async with self._lock:
            await to_thread(self._put_config_override_sync, name, payload)

    def _put_config_override_sync(self, name: str, payload: dict[str, Any]) -> None:
        assert self._conn is not None, "Store.init() must be called first"
        now = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
        self._conn.execute(
            """
            INSERT INTO config_presets (kind, name, payload_json, created_at, updated_at)
            VALUES ('config_override', ?, ?, ?, ?)
            ON CONFLICT(kind, name) DO UPDATE SET
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (name, json.dumps(payload), now, now),
        )
        self._conn.commit()
