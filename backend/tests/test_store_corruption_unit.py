"""Inner unit tests for the store corruption-recovery slice (issue #70).

The outer acceptance test (test_store_corruption_acceptance.py) locks the
one behavior named by the acceptance criterion: a corrupt DB file is
detected and delete-and-recreated with a logged warning. Per that outer
test's own scope note, and per issue #94, several real behavior branches in
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
3. The non-raising corruption trigger (issue #94, design/specs/store.md:44):
   a DB file that still connects and queries cleanly -- `sqlite3.connect()`
   and a plain `sqlite_master` query both succeed -- but whose `PRAGMA
   integrity_check` reports something other than 'ok'. The outer test's
   garbage-bytes fixture only ever exercises the raising
   `sqlite3.DatabaseError` trigger; this trigger needs its own fixture.

`backend.store` is imported inside each test body (never at module scope),
per the durable project convention.

Written by the test-author (DEC-1); the implementer is path-guarded out of
backend/tests/ and may not edit this file.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

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


def _build_page_corrupt_db(db_path: Path) -> None:
    """Build a syntactically valid SQLite file whose header + page 1
    (`sqlite_master`) are intact but whose page 2 (a `filler` table data
    page) is corrupted: `sqlite3.connect()` and a plain `SELECT name FROM
    sqlite_master` succeed (page 1 parses fine), while `PRAGMA
    integrity_check` detects the damaged b-tree page and reports non-'ok'.

    This is the trigger-2 case from design/specs/store.md:44 -- a file that
    connects and queries cleanly but is still corrupt -- as distinct from
    the garbage-bytes fixtures used elsewhere in this module (trigger 1:
    `sqlite3.DatabaseError` on connect/query).
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA page_size = 4096")
    conn.execute("CREATE TABLE filler (id INTEGER PRIMARY KEY, blob TEXT)")
    payload = "x" * 2000
    for i in range(300):
        conn.execute("INSERT INTO filler (blob) VALUES (?)", (payload + str(i),))
    conn.commit()
    conn.close()

    data = bytearray(db_path.read_bytes())
    page_size = 4096
    # Page 1 (bytes 0..page_size-1) holds the file header + sqlite_master
    # schema table and must stay intact. Page 2 (the second page on disk,
    # a `filler` data page) is battered across its b-tree page header and
    # cell-pointer array -- enough to break the tree structurally without
    # touching page 1.
    offset = 1 * page_size
    for i in range(offset, offset + 64):
        data[i] = 0xFF
    db_path.write_bytes(bytes(data))


async def test_page_corrupt_db_with_intact_header_is_recovered(tmp_path, caplog):
    """Trigger 2 (store.md:44): a DB file that still connects and queries
    cleanly -- `sqlite3.connect()` succeeds, `SELECT name FROM
    sqlite_master` succeeds -- but whose `PRAGMA integrity_check` reports
    something other than 'ok' must be recovered the same way as the
    raising-`DatabaseError` case: deleted, recreated from `schema.sql`, with
    a WARNING logged naming the path, and a clean round-trip afterward.

    The two preconditions (clean connect+query, non-'ok' integrity_check)
    are verified directly against the constructed file before `Store` ever
    touches it; if either doesn't hold on this platform's SQLite build, the
    fixture isn't exercising trigger 2 and this test skips rather than
    asserting something it didn't actually set up.
    """
    db_path = tmp_path / "page-corrupt-store.db"
    _build_page_corrupt_db(db_path)

    # --- Verify the fixture actually hits trigger 2, not trigger 1 ---
    probe = sqlite3.connect(str(db_path))
    try:
        names = probe.execute("SELECT name FROM sqlite_master").fetchall()
    except sqlite3.DatabaseError:
        probe.close()
        pytest.skip(
            "fixture connect/query raised DatabaseError -- this hits "
            "trigger 1 (already covered elsewhere), not the non-raising "
            "trigger 2 this test targets"
        )
    if not names:
        probe.close()
        pytest.skip("fixture's sqlite_master is unexpectedly empty")

    integrity_result = probe.execute("PRAGMA integrity_check").fetchone()
    probe.close()
    if integrity_result is not None and integrity_result[0] == "ok":
        pytest.skip(
            "fixture's PRAGMA integrity_check reported 'ok' on this "
            "platform's SQLite build -- the page-corruption recipe did not "
            "produce a detectable non-'ok' result here"
        )

    from backend.store import LandCacheRow, Store

    store = Store(db_path=db_path)

    # --- When: Store() is constructed and init() is called (mirrors the
    # outer acceptance test's flow, but against the page-corrupt fixture) ---
    with caplog.at_level(logging.WARNING):
        await store.init()  # Then: does NOT raise -- corruption is recovered

    # --- And: a WARNING-level log record names the DB path ---
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
