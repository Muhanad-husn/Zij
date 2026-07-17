"""Unit test for the fallback_snapshots nullable source_ts round-trip
(issue #40).

The acceptance test (test_store_fallback_acceptance.py) already exercises
schema round-trip, raw_payload exclusion, UTC-aware region_id/fetched_at
re-hydration, upsert-replace to one row per layer, and the CHECK(layer IN
('air','marine')) rejection of 'land'. The one real behaviour branch it never
touches is `LayerSnapshotMeta.timestamp_source` being nullable
(`datetime | None` on the model; `source_ts TEXT` carries no `NOT NULL` in
schema.sql, unlike `fetched_at`) -- `Store._put_fallback_sync` has an explicit
`is not None` branch for it (writing `NULL` into `source_ts`) that the
acceptance test's always-non-None `timestamp_source` snapshots never run. This
mirrors the matching test for the nullable `LandCacheRow.osm_base` branch in
test_store_unit.py. This test targets exactly the analogous `source_ts`
branch.
"""

from datetime import datetime, timezone

from backend.models import (
    Domain,
    Feature,
    FeatureStatus,
    GeometryType,
    LayerSnapshot,
    LayerSnapshotMeta,
    LayerStatus,
)
from backend.store import Store

FETCHED_AT = datetime(2026, 7, 5, 9, 0, 0, tzinfo=timezone.utc)


async def test_put_fallback_round_trips_null_source_ts(tmp_path, monkeypatch):
    monkeypatch.setenv("ZIJ_DB_PATH", str(tmp_path / "unit-store-fallback.db"))

    store = Store()
    await store.init()

    meta = LayerSnapshotMeta(
        layer=Domain.MARINE,
        region_id="hormuz",
        status=LayerStatus.LIVE,
        timestamp_fetched=FETCHED_AT,
        timestamp_source=None,
        cadence_s=10,
        stale_after_s=20,
        feature_count=1,
    )
    feature = Feature(
        domain=Domain.MARINE,
        source="aisstream",
        source_id="mmsi-1",
        label=None,
        lat=26.1,
        lon=56.4,
        geometry_type=GeometryType.POINT,
        geometry=None,
        timestamp_source=None,
        timestamp_fetched=FETCHED_AT,
        position_age_s=None,
        status=FeatureStatus.LIVE,
        integrity_flags=[],
        attrs={},
        raw_payload=None,
    )
    snapshot = LayerSnapshot(meta=meta, features=[feature])

    await store.put_fallback(snapshot)

    fetched = await store.get_fallback("marine")
    assert fetched is not None
    assert fetched.meta.timestamp_source is None

    # fetched_at is still required and still re-hydrates UTC-aware regardless.
    assert fetched.meta.timestamp_fetched is not None
    assert fetched.meta.timestamp_fetched.tzinfo is not None
    assert fetched.meta.timestamp_fetched == FETCHED_AT

    await store.close()
