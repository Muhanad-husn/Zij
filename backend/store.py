"""SQLite storage layer (contract: design/contracts/storage.md; spec:
design/specs/store.md).

The only SQLite gateway (D4, NFR2, ADR-10): stdlib `sqlite3` behind a thin
`asyncio.to_thread` async wrapper over the three-table DDL in `schema.sql`,
keeping blocking DB work off the event loop. `store.py` never parses source
payloads (STRUCTURE.md) -- it only serializes/deserializes rows it is handed.

This slice (plans/store/01-land-cache.md, issue #11) implements only the
`land_cache` path: `Store.init`/`close`/`get_land_cache`/`put_land_cache` and
`LandCacheRow`. `fallback_snapshots`/`config_presets` methods are out of scope
here and land in later slices.
"""

from __future__ import annotations

import json
import os
import sqlite3
from asyncio import Lock, to_thread
from datetime import datetime
from pathlib import Path
from typing import Any

import platformdirs
from pydantic import BaseModel, ConfigDict, field_validator

from backend.models import _reject_naive_datetime

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _resolve_db_path() -> Path:
    """`ZIJ_DB_PATH` env override; otherwise
    `platformdirs.user_data_dir("zij")/zij.db` (storage.md "File location per
    platform")."""
    override = os.environ.get("ZIJ_DB_PATH")
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir("zij")) / "zij.db"


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
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        schema_sql = _SCHEMA_PATH.read_text()
        self._conn.executescript(schema_sql)

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
