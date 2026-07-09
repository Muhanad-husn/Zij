"""Inner unit tests for the store corruption-recovery slice (issue #70).

The outer acceptance test (test_store_corruption_acceptance.py) locks the
one behavior named by the acceptance criterion: a corrupt DB file is
detected and delete-and-recreated with a logged warning. Per that outer
test's own scope note, two real behavior branches in
`Store._open_healthy_connection` are deliberately left to inner unit tests:

1. The healthy-DB-is-a-no-op path: when `PRAGMA integrity_check` returns
   'ok', recovery must NOT run -- a pre-existing row must still be there
   after a fresh `Store` re-opens the same file. This is the regression
   that proves recovery is genuinely conditional, not an unconditional
   wipe-and-recreate that happens to also round-trip because the caller
   wrote a fresh row after `init()` (which is all the outer test could
   otherwise prove).
2. The WAL/SHM sidecar cleanup: `_open_healthy_connection` deletes
   `<path>-wal` and `<path>-shm` alongside the corrupt main file (schema.sql
   runs in WAL mode, per storage.md NFR1). The outer test's garbage file
   never has sidecars, so that branch is untouched without this test.

`backend.store` is imported inside each test body (never at module scope),
per the durable project convention.

Written by the test-author (DEC-1); the implementer is path-guarded out of
backend/tests/ and may not edit this file.
"""

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


async def test_healthy_db_preserves_data_across_reinit(tmp_path, monkeypatch):
    """A healthy DB is a no-op for `_open_healthy_connection`: re-opening the
    same file with a NEW `Store` instance must not delete or recreate it --
    a row written before close() must still round-trip after."""
    db_path = tmp_path / "healthy-store.db"
    monkeypatch.setenv("ZIJ_DB_PATH", str(db_path))

    from backend.store import LandCacheRow, Store

    first = Store()
    await first.init()
    row = LandCacheRow(
        region_id="hormuz",
        bbox=HORMUZ_BBOX,
        geojson=LAND_GEOJSON,
        feature_count=1234,
        osm_base=None,
        fetched_at=datetime(2026, 7, 5, 9, 0, 0, tzinfo=timezone.utc),
    )
    await first.put_land_cache(row)
    await first.close()

    assert db_path.exists(), "sanity: the DB file must exist on disk before reinit"

    # --- When: a brand-new Store() is init()-ed on the SAME path ---
    second = Store()
    await second.init()

    # --- Then: integrity_check passed ('ok') so recovery was a no-op -- the
    # pre-existing row is still there, not wiped and recreated empty ---
    fetched = await second.get_land_cache("hormuz")
    assert fetched is not None, (
        "healthy DB must be preserved across reinit -- recovery must not "
        "run against a non-corrupt file"
    )
    assert fetched.region_id == "hormuz"
    assert fetched.feature_count == 1234
    assert fetched.geojson == LAND_GEOJSON

    await second.close()


def test_corrupt_db_wal_and_shm_sidecars_are_cleaned_up(tmp_path):
    """When a corrupt main DB file is deleted, its `-wal`/`-shm` WAL-mode
    sidecars (storage.md NFR1: WAL enabled) must be deleted too -- leaving
    a stale sidecar next to a freshly recreated main file would reintroduce
    the exact corruption/mismatch this recovery exists to fix.

    This targets `Store._open_healthy_connection` directly (rather than
    going through `init()`/`_init_sync`) because `schema.sql` itself sets
    `PRAGMA journal_mode = WAL`, which recreates a *fresh* `-wal` file the
    instant the schema is applied -- confounding a post-`init()` existence
    check. Calling the recovery helper in isolation, before schema.sql
    runs, is the only way to observe the stale sidecars actually being
    removed rather than merely overwritten moments later."""
    db_path = tmp_path / "sidecar-store.db"
    db_path.write_bytes(b"garbage, not a sqlite database\x00\xff" * 32)
    wal_path = tmp_path / "sidecar-store.db-wal"
    shm_path = tmp_path / "sidecar-store.db-shm"
    wal_path.write_bytes(b"stale wal frames from a dead process\x00" * 8)
    shm_path.write_bytes(b"stale shm index\x00" * 8)

    from backend.store import Store

    store = Store(db_path=db_path)
    conn = store._open_healthy_connection()  # must not raise -- recovered

    assert not wal_path.exists(), "stale -wal sidecar must be deleted on recovery"
    assert not shm_path.exists(), "stale -shm sidecar must be deleted on recovery"

    conn.close()
