"""Acceptance test for the land_cache round-trip (issue #11).

Given a fresh SQLite database initialised from backend/schema.sql
When  a LandCacheRow for "hormuz" is written via Store.put_land_cache()
      (region_id="hormuz", bbox, geojson=<FeatureCollection>,
      osm_base=2026-07-04T00:00:00Z, fetched_at=2026-07-05T09:00:00Z,
      feature_count=1234)
And   Store.get_land_cache("hormuz") is then called
Then  it returns the stored row with the same feature_count and geojson
And   osm_base comes back as a UTC-aware datetime equal to 2026-07-04T00:00:00Z
      (fetched_at likewise re-hydrates UTC-aware)
And   Store.get_land_cache("gulf-of-oman") returns None (no row)
And   calling Store.init() a second time is idempotent (no error, no dup)
And   a second put_land_cache() for the same region_id REPLACES the row
      (upsert: exactly one land_cache row for "hormuz", not two)

This acceptance test covers the land_cache round-trip: schema idempotency,
round-trip, UTC-aware re-hydration, upsert-replace, and unknown-region ->
None. It was written test-first and committed red, as an xfail, before any
implementation existed; the xfail marker was removed once the suite went
green.

**API surface note.** An earlier illustration used free functions
(`init_schema`/`put_land_cache(region_id, geojson, ...)`/
`get_land_cache(region_id)`). The spec (design/specs/store.md) and contract
(design/contracts/storage.md) instead mandate an async `class Store` with
`init()`/`close()`/`get_land_cache(region_id)`/`put_land_cache(row)`
taking/returning a `LandCacheRow`, backed by stdlib `sqlite3` via
`asyncio.to_thread` (ADR-10), WAL mode, and a path resolved via platformdirs
overridable by `ZIJ_DB_PATH`. This test adopts the spec shape --
`Store`/`LandCacheRow` -- since the api-wiring code (issue #18) consumes this
module unchanged and the spec is authoritative. This is a naming/shape
reconciliation, not a contradiction: both describe the same land_cache
round-trip; the spec is more specific and this test follows it. Scope is held
to the land_cache round-trip only -- fallback_snapshots/config_presets are
out of scope here.

`ZIJ_DB_PATH` points at a `tmp_path` file so the test is hermetic and never
touches the real platformdirs location. `geojson` is carried as a plain dict
(a valid GeoJSON FeatureCollection) on `LandCacheRow`; the TEXT column
round-trip (dict -> JSON text -> dict) is `Store`'s internal concern.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

HORMUZ_BBOX = (55.0, 25.0, 57.5, 27.5)

# First snapshot written for "hormuz".
LAND_GEOJSON_V1 = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [55.0, 25.0],
                        [57.5, 25.0],
                        [57.5, 27.5],
                        [55.0, 27.5],
                        [55.0, 25.0],
                    ]
                ],
            },
            "properties": {"osm_id": "way/123456789", "name": "Hormuz Island"},
        }
    ],
}
OSM_BASE_V1 = datetime(2026, 7, 4, 0, 0, 0, tzinfo=timezone.utc)
FETCHED_AT_V1 = datetime(2026, 7, 5, 9, 0, 0, tzinfo=timezone.utc)
FEATURE_COUNT_V1 = 1234

# Second snapshot for the SAME region_id -- proves upsert-replace, not a second row.
LAND_GEOJSON_V2 = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [55.0, 25.0],
                        [57.5, 25.0],
                        [57.5, 27.5],
                        [55.0, 27.5],
                        [55.0, 25.0],
                    ]
                ],
            },
            "properties": {"osm_id": "way/123456789", "name": "Hormuz Island"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [56.1, 26.9]},
            "properties": {"osm_id": "node/987654321", "name": "Quoin Island"},
        },
    ],
}
OSM_BASE_V2 = datetime(2026, 7, 5, 0, 0, 0, tzinfo=timezone.utc)
FETCHED_AT_V2 = datetime(2026, 7, 5, 10, 0, 0, tzinfo=timezone.utc)
FEATURE_COUNT_V2 = 5678


async def test_land_cache_round_trips_and_upserts(tmp_path, monkeypatch):
    # --- Given: a fresh SQLite database (hermetic path, never the real
    # platformdirs location) initialised from backend/schema.sql ---
    db_path = tmp_path / "zij-store-test.db"
    monkeypatch.setenv("ZIJ_DB_PATH", str(db_path))

    from backend.store import LandCacheRow, Store

    store = Store()
    await store.init()

    # --- And: schema init is idempotent -- calling it a second time raises
    # nothing and does not duplicate anything ---
    await store.init()

    assert Path(db_path).exists()

    # --- When: put_land_cache("hormuz", <FeatureCollection>, osm_base=...,
    # fetched_at=..., feature_count=1234) is called ---
    row_v1 = LandCacheRow(
        region_id="hormuz",
        bbox=HORMUZ_BBOX,
        geojson=LAND_GEOJSON_V1,
        feature_count=FEATURE_COUNT_V1,
        osm_base=OSM_BASE_V1,
        fetched_at=FETCHED_AT_V1,
    )
    await store.put_land_cache(row_v1)

    # --- And: get_land_cache("hormuz") is then called ---
    fetched_v1 = await store.get_land_cache("hormuz")

    # --- Then: it returns the stored row with the same feature_count and geojson ---
    assert fetched_v1 is not None
    assert fetched_v1.region_id == "hormuz"
    assert fetched_v1.feature_count == FEATURE_COUNT_V1
    assert fetched_v1.geojson == LAND_GEOJSON_V1
    assert tuple(fetched_v1.bbox) == HORMUZ_BBOX

    # --- And: osm_base comes back as a UTC-aware datetime equal to
    # 2026-07-04T00:00:00Z (fetched_at likewise re-hydrates UTC-aware, NFR6) ---
    assert fetched_v1.osm_base.tzinfo is not None
    assert fetched_v1.osm_base.utcoffset().total_seconds() == 0
    assert fetched_v1.osm_base == OSM_BASE_V1

    assert fetched_v1.fetched_at.tzinfo is not None
    assert fetched_v1.fetched_at.utcoffset().total_seconds() == 0
    assert fetched_v1.fetched_at == FETCHED_AT_V1

    # --- And: get_land_cache("gulf-of-oman") returns None (no row) ---
    missing = await store.get_land_cache("gulf-of-oman")
    assert missing is None

    # --- And: a second put_land_cache for the same region_id REPLACES the
    # row (upsert, one row per region) ---
    row_v2 = LandCacheRow(
        region_id="hormuz",
        bbox=HORMUZ_BBOX,
        geojson=LAND_GEOJSON_V2,
        feature_count=FEATURE_COUNT_V2,
        osm_base=OSM_BASE_V2,
        fetched_at=FETCHED_AT_V2,
    )
    await store.put_land_cache(row_v2)

    fetched_v2 = await store.get_land_cache("hormuz")
    assert fetched_v2 is not None
    assert fetched_v2.feature_count == FEATURE_COUNT_V2
    assert fetched_v2.geojson == LAND_GEOJSON_V2
    assert fetched_v2.osm_base == OSM_BASE_V2
    assert fetched_v2.fetched_at == FETCHED_AT_V2

    await store.close()

    # Prove the upsert replaced rather than appended: exactly one land_cache
    # row exists for "hormuz" (and in total), inspected directly against the
    # on-disk file this test pointed ZIJ_DB_PATH at.
    raw_conn = sqlite3.connect(db_path)
    try:
        hormuz_count = raw_conn.execute(
            "SELECT COUNT(*) FROM land_cache WHERE region_id = ?", ("hormuz",)
        ).fetchone()[0]
        assert hormuz_count == 1

        total_count = raw_conn.execute("SELECT COUNT(*) FROM land_cache").fetchone()[0]
        assert total_count == 1
    finally:
        raw_conn.close()
