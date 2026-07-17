"""Acceptance test for the fallback_snapshots round-trip (issue #40).

Given a fresh SQLite database initialised from backend/schema.sql
When  put_fallback(<LayerSnapshot air>) is called then get_fallback("air")
Then  it returns an equal LayerSnapshot with raw_payload absent and
      fetched_at preserved (UTC)
And   a second put_fallback for air replaces the row (still exactly one
      air row)
And   get_fallback("marine") returns None when no marine row exists
And   inserting layer='land' is rejected by the CHECK constraint

This acceptance test covers the fallback_snapshots round-trip: round-trip
identity, raw_payload exclusion, UTC-aware region_id/fetched_at re-hydration,
upsert-replace to exactly one row per layer, and CHECK(layer IN
('air','marine')) rejecting 'land'. It was written test-first and committed
red, as an xfail, before any implementation existed:
`Store.put_fallback`/`Store.get_fallback` did not exist, so the call below
raised `AttributeError`, xfail caught it, the suite reported `xfailed`, and
the red commit was allowed to land. The xfail
marker was removed once the suite went green.

Scope is held strictly to the fallback_snapshots round-trip for the "air"
layer plus the "marine" None-path and the "land" CHECK-constraint rejection
-- config_presets and the cold-start repopulation policy (handled by the
scheduler) are out of scope here.

`ZIJ_DB_PATH` points at a `tmp_path` file (never the real platformdirs
location), following the hermetic-DB convention set by
`test_store_acceptance.py`.

**Equality-assertion choice.** The round-tripped `LayerSnapshot` is compared
to the original via `model_dump()` on each side, but with the *expected*
side's `raw_payload` fields cleared to `None` first (since raw_payload is
`exclude=True` on `Feature` -- feature-schema.md -- so it can never survive
the JSON round-trip through `snapshot_json`). This is more robust than
comparing individual fields one by one (it catches any unintended field
drift across the whole nested model) while still correctly encoding that
raw_payload is *expected* to be absent, not an oversight.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

# --- "air" LayerSnapshot v1: one feature carrying a non-None raw_payload,
# so the "raw_payload absent after round-trip" assertion is meaningful. ---


def _make_air_snapshot_v1():
    from backend.models import (
        Domain,
        Feature,
        FeatureStatus,
        GeometryType,
        LayerSnapshot,
        LayerSnapshotMeta,
        LayerStatus,
    )

    meta = LayerSnapshotMeta(
        layer=Domain.AIR,
        region_id="hormuz",
        status=LayerStatus.LIVE,
        timestamp_fetched=datetime(2026, 7, 5, 9, 0, 0, tzinfo=timezone.utc),
        timestamp_source=datetime(2026, 7, 5, 8, 59, 30, tzinfo=timezone.utc),
        cadence_s=10,
        stale_after_s=20,
        feature_count=1,
    )
    feature = Feature(
        domain=Domain.AIR,
        source="opensky",
        source_id="abc123",
        label="UAE123",
        lat=26.5,
        lon=56.2,
        geometry_type=GeometryType.POINT,
        geometry=None,
        timestamp_source=datetime(2026, 7, 5, 8, 59, 30, tzinfo=timezone.utc),
        timestamp_fetched=datetime(2026, 7, 5, 9, 0, 0, tzinfo=timezone.utc),
        position_age_s=30.0,
        status=FeatureStatus.LIVE,
        integrity_flags=[],
        attrs={"velocity": 250.0},
        raw_payload={"icao24": "abc123", "velocity": 250},
    )
    return LayerSnapshot(meta=meta, features=[feature])


# --- "air" LayerSnapshot v2: a different feature_count/features for the
# SAME layer -- proves upsert-replace, not a second row. ---


def _make_air_snapshot_v2():
    from backend.models import (
        Domain,
        Feature,
        FeatureStatus,
        GeometryType,
        LayerSnapshot,
        LayerSnapshotMeta,
        LayerStatus,
    )

    meta = LayerSnapshotMeta(
        layer=Domain.AIR,
        region_id="hormuz",
        status=LayerStatus.LIVE,
        timestamp_fetched=datetime(2026, 7, 5, 9, 10, 0, tzinfo=timezone.utc),
        timestamp_source=datetime(2026, 7, 5, 9, 9, 45, tzinfo=timezone.utc),
        cadence_s=10,
        stale_after_s=20,
        feature_count=2,
    )
    feature_a = Feature(
        domain=Domain.AIR,
        source="opensky",
        source_id="abc123",
        label="UAE123",
        lat=26.6,
        lon=56.3,
        geometry_type=GeometryType.POINT,
        geometry=None,
        timestamp_source=datetime(2026, 7, 5, 9, 9, 45, tzinfo=timezone.utc),
        timestamp_fetched=datetime(2026, 7, 5, 9, 10, 0, tzinfo=timezone.utc),
        position_age_s=15.0,
        status=FeatureStatus.LIVE,
        integrity_flags=[],
        attrs={"velocity": 260.0},
        raw_payload={"icao24": "abc123", "velocity": 260},
    )
    feature_b = Feature(
        domain=Domain.AIR,
        source="opensky",
        source_id="def456",
        label="QTR456",
        lat=25.9,
        lon=55.8,
        geometry_type=GeometryType.POINT,
        geometry=None,
        timestamp_source=datetime(2026, 7, 5, 9, 9, 50, tzinfo=timezone.utc),
        timestamp_fetched=datetime(2026, 7, 5, 9, 10, 0, tzinfo=timezone.utc),
        position_age_s=10.0,
        status=FeatureStatus.LIVE,
        integrity_flags=[],
        attrs={"velocity": 300.0},
        raw_payload={"icao24": "def456", "velocity": 300},
    )
    return LayerSnapshot(meta=meta, features=[feature_a, feature_b])


async def test_fallback_snapshot_round_trips_upserts_and_enforces_layer_check(
    tmp_path, monkeypatch
):
    # --- Given: a fresh SQLite database (hermetic path, never the real
    # platformdirs location) initialised from backend/schema.sql ---
    db_path = tmp_path / "zij-store-fallback-test.db"
    monkeypatch.setenv("ZIJ_DB_PATH", str(db_path))

    from backend.store import Store

    store = Store()
    await store.init()

    assert Path(db_path).exists()

    # --- When: put_fallback(<LayerSnapshot air>) is called ---
    snapshot_v1 = _make_air_snapshot_v1()
    await store.put_fallback(snapshot_v1)

    # --- And: get_fallback("air") is then called ---
    fetched_v1 = await store.get_fallback("air")

    # --- Then: it returns an equal LayerSnapshot with raw_payload absent
    # and fetched_at (region_id, meta.timestamp_fetched) preserved UTC ---
    assert fetched_v1 is not None

    expected_v1 = snapshot_v1.model_copy(deep=True)
    for feature in expected_v1.features:
        feature.raw_payload = None
    assert fetched_v1.model_dump() == expected_v1.model_dump()

    # raw_payload is genuinely gone (not just excluded from model_dump()),
    # proving the persisted JSON never carried it (feature-schema.md
    # exclude=True) rather than the comparison merely ignoring the field.
    assert all(f.raw_payload is None for f in fetched_v1.features)

    # meta.timestamp_fetched round-trips UTC-aware and equal.
    assert fetched_v1.meta.timestamp_fetched is not None
    assert fetched_v1.meta.timestamp_fetched.tzinfo is not None
    assert fetched_v1.meta.timestamp_fetched.utcoffset().total_seconds() == 0
    assert fetched_v1.meta.timestamp_fetched == snapshot_v1.meta.timestamp_fetched

    assert fetched_v1.meta.region_id == "hormuz"

    # --- And: get_fallback("marine") returns None when no marine row
    # exists ---
    missing = await store.get_fallback("marine")
    assert missing is None

    # --- And: a second put_fallback for air replaces the row (still
    # exactly one air row) ---
    snapshot_v2 = _make_air_snapshot_v2()
    await store.put_fallback(snapshot_v2)

    fetched_v2 = await store.get_fallback("air")
    assert fetched_v2 is not None
    assert fetched_v2.meta.feature_count == 2
    assert len(fetched_v2.features) == 2
    assert {f.source_id for f in fetched_v2.features} == {"abc123", "def456"}
    assert fetched_v2.meta.timestamp_fetched == snapshot_v2.meta.timestamp_fetched

    await store.close()

    # Prove the upsert replaced rather than appended: exactly one
    # fallback_snapshots row exists for layer='air' (and in total),
    # inspected directly against the on-disk file this test pointed
    # ZIJ_DB_PATH at.
    raw_conn = sqlite3.connect(db_path)
    try:
        air_count = raw_conn.execute(
            "SELECT COUNT(*) FROM fallback_snapshots WHERE layer = ?", ("air",)
        ).fetchone()[0]
        assert air_count == 1

        total_count = raw_conn.execute(
            "SELECT COUNT(*) FROM fallback_snapshots"
        ).fetchone()[0]
        assert total_count == 1

        # --- And: inserting layer='land' is rejected by the CHECK
        # constraint. Proven directly against the DB (not via
        # put_fallback, which a mobile LayerSnapshot can never carry
        # layer=land for in practice) -- the DB CHECK is the guard under
        # test here. ---
        with pytest.raises(sqlite3.IntegrityError):
            raw_conn.execute(
                "INSERT INTO fallback_snapshots "
                "(layer, region_id, snapshot_json, fetched_at) "
                "VALUES ('land', 'hormuz', '{}', '2026-07-05T09:00:00Z')"
            )
    finally:
        raw_conn.close()
