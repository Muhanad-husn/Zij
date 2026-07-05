"""Inner unit tests for models slice 01 (issue #9): Feature/LayerSnapshot schema.

Covers the seeded inner-loop list in plans/models/01-feature-schema.md that the
outer acceptance test (test_models_acceptance.py) does not already exercise:
enum exhaustiveness and air nullability (timestamp_source/position_age_s both
None). A few of the other seeded behaviours are duplicated here in focused
form for fast, isolated failure signal, but the outer test remains the locked
contract -- these units may not weaken or replace it.

Written by the test-author (DEC-1); the implementer is path-guarded out of
backend/tests/ and may not edit this file.
"""

import pytest
from pydantic import ValidationError

from backend.models import (
    Domain,
    Feature,
    FeatureStatus,
    GeometryType,
    IntegrityFlag,
    LayerSnapshot,
    LayerSnapshotMeta,
    LayerStatus,
)

# A minimal, otherwise-valid air feature body to mutate per-test (mirrors the
# wire example at design/contracts/feature-schema.md lines 182-194).
BASE_AIR_FEATURE: dict = {
    "domain": "air",
    "source": "opensky",
    "source_id": "896451",
    "label": "IRA655",
    "lat": 26.61,
    "lon": 56.27,
    "geometry_type": "point",
    "geometry": None,
    "timestamp_source": "2026-07-05T09:11:58Z",
    "timestamp_fetched": "2026-07-05T09:12:03Z",
    "position_age_s": 5.0,
    "status": "live",
    "integrity_flags": [],
    "attrs": {},
}


# --- Enum exhaustiveness (contract lines 30-71) -----------------------------


def test_domain_enum_exhaustive():
    assert {member.name for member in Domain} == {"AIR", "MARINE", "LAND"}
    assert {member.value for member in Domain} == {"air", "marine", "land"}


def test_geometry_type_enum_exhaustive():
    assert {member.name for member in GeometryType} == {
        "POINT",
        "LINESTRING",
        "POLYGON",
    }
    assert {member.value for member in GeometryType} == {
        "point",
        "linestring",
        "polygon",
    }


def test_feature_status_enum_exhaustive():
    assert {member.name for member in FeatureStatus} == {
        "LIVE",
        "STALE",
        "CACHED_FALLBACK",
    }
    assert {member.value for member in FeatureStatus} == {
        "live",
        "stale",
        "cached-fallback",
    }


def test_integrity_flag_enum_exhaustive():
    assert {member.name for member in IntegrityFlag} == {
        "SPOOF_SUSPECT_ON_LAND",
        "IMPLAUSIBLE_KINEMATICS",
    }
    assert {member.value for member in IntegrityFlag} == {
        "spoof_suspect_on_land",
        "implausible_kinematics",
    }


def test_layer_status_enum_exhaustive():
    assert {member.name for member in LayerStatus} == {
        "LIVE",
        "STALE",
        "LOADING",
        "RATE_LIMITED",
        "ERROR",
        "CACHED_FALLBACK",
        "RECONNECTING",
    }
    assert {member.value for member in LayerStatus} == {
        "live",
        "stale",
        "loading",
        "rate-limited",
        "error",
        "cached-fallback",
        "reconnecting",
    }


# --- Air nullability (contract nullability table, "air" column) ------------


def test_air_feature_allows_null_timestamp_source_and_position_age():
    # Mode-S gap: timestamp_source and position_age_s are null together, per the
    # nullability table ("position_age_s | null iff timestamp_source null").
    feature = Feature.model_validate(
        {**BASE_AIR_FEATURE, "timestamp_source": None, "position_age_s": None}
    )
    assert feature.timestamp_source is None
    assert feature.position_age_s is None
    # timestamp_fetched remains required and non-null regardless.
    assert feature.timestamp_fetched.tzinfo is not None


# --- Additional focused unit coverage (fast supplements) --------------------


def test_feature_rejects_out_of_range_lat_lon():
    with pytest.raises(ValidationError):
        Feature.model_validate({**BASE_AIR_FEATURE, "lat": 91})
    with pytest.raises(ValidationError):
        Feature.model_validate({**BASE_AIR_FEATURE, "lat": -91})
    with pytest.raises(ValidationError):
        Feature.model_validate({**BASE_AIR_FEATURE, "lon": 181})
    with pytest.raises(ValidationError):
        Feature.model_validate({**BASE_AIR_FEATURE, "lon": -181})


def test_feature_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        Feature.model_validate({**BASE_AIR_FEATURE, "not_a_real_field": 1})


def test_feature_rejects_naive_datetime():
    with pytest.raises(ValidationError):
        Feature.model_validate(
            {**BASE_AIR_FEATURE, "timestamp_fetched": "2026-07-05T09:12:03"}
        )


def test_feature_accepts_aware_utc_datetime():
    feature = Feature.model_validate(BASE_AIR_FEATURE)
    assert feature.timestamp_fetched.tzinfo is not None
    assert feature.timestamp_fetched.utcoffset().total_seconds() == 0


def test_raw_payload_excluded_from_dump_but_kept_in_memory():
    raw = {"icao24": "896451"}
    feature = Feature.model_validate({**BASE_AIR_FEATURE, "raw_payload": raw})

    assert feature.raw_payload == raw
    assert "raw_payload" not in feature.model_dump()
    assert "raw_payload" not in feature.model_dump_json()


def test_layer_snapshot_round_trip_carries_stale_after_s():
    meta = LayerSnapshotMeta.model_validate(
        {
            "layer": "air",
            "region_id": "hormuz",
            "status": "live",
            "timestamp_fetched": "2026-07-05T09:12:03Z",
            "timestamp_source": "2026-07-05T09:11:58Z",
            "cadence_s": 600,
            "stale_after_s": 1200,
            "feature_count": 1,
            "retry_after_s": None,
            "detail": None,
        }
    )
    feature = Feature.model_validate(BASE_AIR_FEATURE)
    snapshot = LayerSnapshot(meta=meta, features=[feature])

    round_tripped = LayerSnapshot.model_validate(snapshot.model_dump())

    assert round_tripped.meta.stale_after_s == 1200
    assert round_tripped.meta.cadence_s == 600
