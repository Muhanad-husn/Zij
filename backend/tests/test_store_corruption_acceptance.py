"""Locked outer acceptance test for store corruption recovery (issue #70).

Given a `ZIJ_DB_PATH` file that already exists on disk but is NOT a valid
      SQLite database (pre-filled with garbage bytes -- simulating a
      malformed/corrupt cache DB, e.g. truncated write, disk-full, bit rot)
When  a `Store()` is constructed and `await store.init()` is called
Then  `init()` does not raise -- the corruption is detected
      (`sqlite3.DatabaseError` / failed `PRAGMA integrity_check`) and
      recovered by deleting the file and recreating it from `schema.sql`
And   a WARNING-level log record is emitted naming the DB path (the recovery
      is a logged, intentional action -- never silent)
And   the recovered database is a genuinely fresh, working schema: a
      subsequent `put_land_cache`/`get_land_cache` round-trip succeeds,
      proving `land_cache` (and the other tables) exist and are queryable

This is the behavioral contract (), transcribed from
design/specs/store.md ("Corruption recovery" + "Failure modes: Corruption ->
delete-and-recreate" + acceptance criterion line 63: "Corruption is
recovered by delete-and-recreate with a logged warning; app continues.").
It was authored and committed red by the author before any
implementation existed, guarded by a strict xfail ().

the developer has since made this genuinely pass (`Store._init_sync`'s
`_open_healthy_connection()` helper: `PRAGMA integrity_check`, on
`sqlite3.DatabaseError`/non-'ok' logs a WARNING naming the path, deletes the
DB + `-wal`/`-shm` sidecars, recreates from `schema.sql`). The strict xfail
marker has been removed by the author () now that the suite is
genuinely green -- this finalizes the locked contract.

Scope note: this outer test locks the corruption-recovery path only. The
healthy-DB-is-preserved case (integrity_check == 'ok' -> recovery is a
no-op, no data loss) is deliberately left to an inner unit test authored
alongside the developer's slice, per the plan's unit list -- keeping this
outer contract focused on the one behavior named by the acceptance
criterion.

`ZIJ_DB_PATH` points at a `tmp_path` file so the test is hermetic and never
touches the real platformdirs location. `backend.store` is imported inside
the test body (never at module scope) so pytest collection stays
secret-gate-free (durable project lesson: an eager module-level
`backend.*` import fires `load_config()`'s secret gate before the session
conftest baseline fixture runs).
"""

import logging
from datetime import datetime, timezone

HORMUZ_BBOX = (55.0, 25.0, 57.5, 27.5)

LAND_GEOJSON = {
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


async def test_corrupt_db_is_recovered_by_delete_and_recreate(
    tmp_path, monkeypatch, caplog
):
    # --- Given: a ZIJ_DB_PATH file that already exists but is NOT a valid
    # SQLite database -- garbage bytes on disk, simulating corruption ---
    db_path = tmp_path / "zij-store-corrupt-test.db"
    db_path.write_bytes(b"this is not a sqlite database, it is garbage\x00\xff" * 32)
    monkeypatch.setenv("ZIJ_DB_PATH", str(db_path))

    from backend.store import LandCacheRow, Store

    store = Store()

    # --- When: Store() is constructed and init() is called ---
    with caplog.at_level(logging.WARNING):
        await store.init()  # Then: does NOT raise -- corruption is recovered

    # --- And: a WARNING-level log record names the DB path (recovery is
    # logged, intentional -- never silent data loss, per the spec) ---
    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
    ]
    assert any(str(db_path) in message for message in warning_messages), (
        f"expected a WARNING log naming {db_path!s}, got: {warning_messages!r}"
    )

    # --- And: the recovered DB round-trips normally -- a fresh, working
    # schema was recreated from schema.sql (not just an empty/broken file) ---
    row = LandCacheRow(
        region_id="hormuz",
        bbox=HORMUZ_BBOX,
        geojson=LAND_GEOJSON,
        feature_count=1234,
        osm_base=None,
        fetched_at=datetime(2026, 7, 5, 9, 0, 0, tzinfo=timezone.utc),
    )
    await store.put_land_cache(row)

    fetched = await store.get_land_cache("hormuz")
    assert fetched is not None
    assert fetched.region_id == "hormuz"
    assert fetched.feature_count == 1234
    assert fetched.geojson == LAND_GEOJSON

    await store.close()
