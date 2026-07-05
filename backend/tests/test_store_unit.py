"""Inner unit test for store step (issue #11): land_cache round-trip.

The outer acceptance test (test_store_acceptance.py) already exercises every
item in the plan's inner unit list (plans/store/01-land-cache.md): schema
idempotency, round-trip, UTC-aware re-hydration, upsert-replace, and
unknown-region -> None. The one real behaviour branch it never touches is
`LandCacheRow.osm_base` being nullable (`datetime | None` on the model;
`osm_base TEXT` carries no `NOT NULL` in schema.sql, unlike `fetched_at`) --
both `Store._put_land_cache_sync` and `Store._get_land_cache_sync` have an
explicit `is not None` branch for it that a non-null-only outer test never
runs. This test targets exactly that branch.

Written by the author (); the developer is separated out of
backend/tests/ and may not edit this file.
"""

from datetime import datetime, timezone

from backend.store import LandCacheRow, Store

BBOX = (55.0, 25.0, 57.5, 27.5)
GEOJSON = {"type": "FeatureCollection", "features": []}
FETCHED_AT = datetime(2026, 7, 5, 9, 0, 0, tzinfo=timezone.utc)


async def test_put_land_cache_round_trips_null_osm_base(tmp_path, monkeypatch):
    monkeypatch.setenv("ZIJ_DB_PATH", str(tmp_path / "unit-store.db"))

    store = Store()
    await store.init()

    row = LandCacheRow(
        region_id="custom:no-osm-base",
        bbox=BBOX,
        geojson=GEOJSON,
        feature_count=0,
        osm_base=None,
        fetched_at=FETCHED_AT,
    )
    await store.put_land_cache(row)

    fetched = await store.get_land_cache("custom:no-osm-base")
    assert fetched is not None
    assert fetched.osm_base is None
    # fetched_at is still required and still re-hydrates UTC-aware regardless.
    assert fetched.fetched_at.tzinfo is not None
    assert fetched.fetched_at == FETCHED_AT

    await store.close()
