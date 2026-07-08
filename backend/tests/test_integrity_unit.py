"""Inner unit tests for integrity slice 01 (issue #43), transcribed from the
plan's "Inner loop — initial unit test list" (plans/integrity/01-flags.md):

  - STRtree query + `contains` flags a known on-land marine coordinate; an
    at-sea one is clean.
  - Haversine implied-speed math matches a hand-computed value for a known
    pair.
  - `dt <= 0` (same/out-of-order timestamp) is skipped -- no exception, no
    flag.
  - Marine threshold 120 kn vs air threshold 990 kn applied per `domain`
    (both sides of each boundary, plus a mid-range pair that crosses only
    the marine threshold).
  - Null `timestamp_source` -> kinematics skipped for that feature, but
    landmask still applies.
  - Purity: identical `(features, prev)` inputs always yield identical
    flags; no cross-call state leak on a reused `Integrity` instance.
  - Missing/corrupt landmask asset at construction raises `LandmaskError`
    (missing path, invalid JSON, and wrong-shape JSON).

The outer acceptance test (test_integrity.py) already proves the headline
behaviour end-to-end through `Integrity.apply` (spoof-suspect + implausible
kinematics + the dt<=0 guard + air-on-land is not spoof-flagged). These
tests go one level down: each plan bullet gets its own narrow, deterministic
proof, isolated from the others (mirrors test_scheduler_unit.py /
test_store_fallback_unit.py's split from their outer tests).

Fixture coordinates for the threshold-boundary tests are not picked
arbitrarily: each pair's implied speed is hand-derived from elementary
great-circle geometry (points on the same meridian, so distance = earth
radius x delta-latitude in radians -- no dependency on the general haversine
trig identity agreeing with itself) to land at a precise, independently
computed kn value just above/below each threshold. See the module-level
`_lat2_for_nm_at_1h` helper and its docstring.

Written by the test-author (DEC-1/DEC-34); the implementer is path-guarded
out of `backend/tests/` and may not edit this file.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.integrity import Integrity, IntegrityCfg, LandmaskError, PrevPos, haversine
from backend.models import Domain, Feature, GeometryType, IntegrityFlag

LANDMASK_FIXTURE = Path(__file__).parent / "fixtures" / "landmask_test.geojson"

# Inside the fixture's land square (lon [56.0, 56.5] x lat [26.0, 26.5]).
ON_LAND_LAT, ON_LAND_LON = 26.25, 56.25
AT_SEA_LAT, AT_SEA_LON = 10.0, 40.0  # nowhere near the fixture's land square

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
T0_PLUS_1H = T0 + timedelta(hours=1)

_EARTH_RADIUS_M = 6371000.0


def _lat2_for_nm_at_1h(lat1: float, target_nm: float) -> float:
    """Latitude that, held at a fixed longitude (a meridian = a great
    circle), is exactly `target_nm` nautical miles from `(lat1, lon)` --
    derived from elementary arc-length geometry (`distance_m = R * theta`),
    not from the general two-point haversine trig identity under test. Over
    a fixed 1 h window this makes the pair's implied speed equal
    `target_nm` kn exactly (nm / 1 h = kn)."""
    distance_m = target_nm * 1852
    theta_rad = distance_m / _EARTH_RADIUS_M
    return lat1 + math.degrees(theta_rad)


KIN_LON = 40.0  # fixed longitude for all threshold-boundary pairs (meridian)
KIN_LAT0 = 10.0

MARINE_UNDER_LAT2 = _lat2_for_nm_at_1h(KIN_LAT0, 119.9)  # < 120 kn marine threshold
MARINE_OVER_LAT2 = _lat2_for_nm_at_1h(KIN_LAT0, 120.1)  # > 120 kn marine threshold
AIR_UNDER_LAT2 = _lat2_for_nm_at_1h(KIN_LAT0, 989.9)  # < 990 kn air threshold
AIR_OVER_LAT2 = _lat2_for_nm_at_1h(KIN_LAT0, 990.1)  # > 990 kn air threshold
MID_LAT2 = _lat2_for_nm_at_1h(KIN_LAT0, 500.0)  # > marine (120), < air (990)


def _cfg(**overrides: object) -> IntegrityCfg:
    params: dict[str, object] = {
        "landmask_path": str(LANDMASK_FIXTURE),
        "max_speed_kn_marine": 120,
        "max_speed_kn_air": 990,
    }
    params.update(overrides)
    return IntegrityCfg(**params)  # type: ignore[arg-type]


def _feature(
    *,
    domain: Domain,
    source: str = "test-source",
    source_id: str,
    lat: float,
    lon: float,
    timestamp_source: datetime | None,
) -> Feature:
    return Feature(
        domain=domain,
        source=source,
        source_id=source_id,
        label=None,
        lat=lat,
        lon=lon,
        geometry_type=GeometryType.POINT,
        geometry=None,
        timestamp_source=timestamp_source,
        timestamp_fetched=datetime.now(timezone.utc),
        position_age_s=0.0,
    )


# ---------------------------------------------------------------------------
# STRtree query + contains: on-land vs at-sea.
# ---------------------------------------------------------------------------


def test_on_land_marine_coordinate_flagged_at_sea_coordinate_clean():
    integrity = Integrity(_cfg())

    on_land = _feature(
        domain=Domain.MARINE,
        source_id="on-land",
        lat=ON_LAND_LAT,
        lon=ON_LAND_LON,
        timestamp_source=T0,
    )
    at_sea = _feature(
        domain=Domain.MARINE,
        source_id="at-sea",
        lat=AT_SEA_LAT,
        lon=AT_SEA_LON,
        timestamp_source=T0,
    )

    result = integrity.apply([on_land, at_sea], {})
    by_id = {f.source_id: f for f in result}

    assert IntegrityFlag.SPOOF_SUSPECT_ON_LAND in by_id["on-land"].integrity_flags
    assert IntegrityFlag.SPOOF_SUSPECT_ON_LAND not in by_id["at-sea"].integrity_flags


# ---------------------------------------------------------------------------
# Haversine / implied-speed math vs a hand-computed value.
# ---------------------------------------------------------------------------


def test_haversine_matches_hand_computed_meridian_distance():
    # One degree of latitude along a meridian is an elementary great-circle
    # arc: distance = earth_radius * radians(1). This does not exercise the
    # general haversine trig identity (dlambda == 0 collapses it), so it is
    # an independent check on the radius/unit constants.
    expected_m = _EARTH_RADIUS_M * math.radians(1.0)
    assert math.isclose(haversine(0.0, 0.0, 1.0, 0.0), expected_m, rel_tol=1e-9)


def test_haversine_matches_hand_computed_equatorial_distance():
    # 90 degrees of longitude along the equator is likewise an elementary
    # arc: distance = earth_radius * radians(90) (a quarter of the
    # circumference). dphi == 0 collapses the general formula differently
    # than the meridian case above, covering both trig branches.
    expected_m = _EARTH_RADIUS_M * (math.pi / 2)
    assert math.isclose(haversine(0.0, 0.0, 0.0, 90.0), expected_m, rel_tol=1e-9)


def test_implied_speed_matches_hand_computed_value_for_known_pair():
    # MID_LAT2 was derived (via elementary arc-length inversion, not the
    # haversine formula) to be exactly 500 nm from KIN_LAT0 along the same
    # meridian. Over a fixed 1 h window, implied speed == distance in nm.
    dist_m = haversine(KIN_LAT0, KIN_LON, MID_LAT2, KIN_LON)
    dist_nm = dist_m / 1852
    dt_h = (T0_PLUS_1H - T0).total_seconds() / 3600
    implied_kn = dist_nm / dt_h

    assert math.isclose(implied_kn, 500.0, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# dt <= 0 guard.
# ---------------------------------------------------------------------------


def test_dt_zero_same_timestamp_pair_skipped_no_flag_no_exception():
    integrity = Integrity(_cfg())

    # Reuses the air-over-threshold jump's distance so this proves the dt<=0
    # guard specifically, not a coincidentally-small distance.
    curr = _feature(
        domain=Domain.AIR,
        source_id="dt-zero",
        lat=AIR_OVER_LAT2,
        lon=KIN_LON,
        timestamp_source=T0,  # same as prev -> dt == 0
    )
    prev = {"dt-zero": PrevPos(lat=KIN_LAT0, lon=KIN_LON, timestamp_source=T0)}

    result = integrity.apply([curr], prev)
    assert IntegrityFlag.IMPLAUSIBLE_KINEMATICS not in result[0].integrity_flags


def test_dt_negative_out_of_order_pair_skipped_no_flag_no_exception():
    integrity = Integrity(_cfg())

    curr = _feature(
        domain=Domain.AIR,
        source_id="dt-negative",
        lat=AIR_OVER_LAT2,
        lon=KIN_LON,
        timestamp_source=T0,  # earlier than prev -> dt < 0 (out-of-order report)
    )
    prev = {
        "dt-negative": PrevPos(lat=KIN_LAT0, lon=KIN_LON, timestamp_source=T0_PLUS_1H)
    }

    result = integrity.apply([curr], prev)
    assert IntegrityFlag.IMPLAUSIBLE_KINEMATICS not in result[0].integrity_flags


# ---------------------------------------------------------------------------
# Marine 120 kn / air 990 kn thresholds, both sides of each boundary.
# ---------------------------------------------------------------------------


def test_marine_speed_just_under_threshold_not_flagged():
    integrity = Integrity(_cfg())
    curr = _feature(
        domain=Domain.MARINE,
        source_id="m-under",
        lat=MARINE_UNDER_LAT2,
        lon=KIN_LON,
        timestamp_source=T0_PLUS_1H,
    )
    prev = {"m-under": PrevPos(lat=KIN_LAT0, lon=KIN_LON, timestamp_source=T0)}

    result = integrity.apply([curr], prev)
    assert IntegrityFlag.IMPLAUSIBLE_KINEMATICS not in result[0].integrity_flags


def test_marine_speed_just_over_threshold_flagged():
    integrity = Integrity(_cfg())
    curr = _feature(
        domain=Domain.MARINE,
        source_id="m-over",
        lat=MARINE_OVER_LAT2,
        lon=KIN_LON,
        timestamp_source=T0_PLUS_1H,
    )
    prev = {"m-over": PrevPos(lat=KIN_LAT0, lon=KIN_LON, timestamp_source=T0)}

    result = integrity.apply([curr], prev)
    assert IntegrityFlag.IMPLAUSIBLE_KINEMATICS in result[0].integrity_flags


def test_air_speed_just_under_threshold_not_flagged():
    integrity = Integrity(_cfg())
    curr = _feature(
        domain=Domain.AIR,
        source_id="a-under",
        lat=AIR_UNDER_LAT2,
        lon=KIN_LON,
        timestamp_source=T0_PLUS_1H,
    )
    prev = {"a-under": PrevPos(lat=KIN_LAT0, lon=KIN_LON, timestamp_source=T0)}

    result = integrity.apply([curr], prev)
    assert IntegrityFlag.IMPLAUSIBLE_KINEMATICS not in result[0].integrity_flags


def test_air_speed_just_over_threshold_flagged():
    integrity = Integrity(_cfg())
    curr = _feature(
        domain=Domain.AIR,
        source_id="a-over",
        lat=AIR_OVER_LAT2,
        lon=KIN_LON,
        timestamp_source=T0_PLUS_1H,
    )
    prev = {"a-over": PrevPos(lat=KIN_LAT0, lon=KIN_LON, timestamp_source=T0)}

    result = integrity.apply([curr], prev)
    assert IntegrityFlag.IMPLAUSIBLE_KINEMATICS in result[0].integrity_flags


def test_mid_range_speed_flagged_for_marine_but_not_for_air():
    # Same physical pair (~500 kn implied), just the domain differs: the
    # threshold applied must come from `feature.domain`, not be a single
    # global cutoff.
    integrity = Integrity(_cfg())

    marine_curr = _feature(
        domain=Domain.MARINE,
        source_id="mid-marine",
        lat=MID_LAT2,
        lon=KIN_LON,
        timestamp_source=T0_PLUS_1H,
    )
    air_curr = _feature(
        domain=Domain.AIR,
        source_id="mid-air",
        lat=MID_LAT2,
        lon=KIN_LON,
        timestamp_source=T0_PLUS_1H,
    )
    prev = {
        "mid-marine": PrevPos(lat=KIN_LAT0, lon=KIN_LON, timestamp_source=T0),
        "mid-air": PrevPos(lat=KIN_LAT0, lon=KIN_LON, timestamp_source=T0),
    }

    result = integrity.apply([marine_curr, air_curr], prev)
    by_id = {f.source_id: f for f in result}

    assert IntegrityFlag.IMPLAUSIBLE_KINEMATICS in by_id["mid-marine"].integrity_flags
    assert IntegrityFlag.IMPLAUSIBLE_KINEMATICS not in by_id["mid-air"].integrity_flags


# ---------------------------------------------------------------------------
# Null timestamp_source: kinematics skipped, landmask unaffected.
# ---------------------------------------------------------------------------


def test_null_current_timestamp_source_skips_kinematics_but_landmask_still_applies():
    integrity = Integrity(_cfg())

    # On-land marine feature with no source timestamp, but a prev entry that
    # *would* imply an enormous speed if kinematics ran on it.
    curr = _feature(
        domain=Domain.MARINE,
        source_id="null-ts-on-land",
        lat=ON_LAND_LAT,
        lon=ON_LAND_LON,
        timestamp_source=None,
    )
    prev = {
        "null-ts-on-land": PrevPos(lat=AT_SEA_LAT, lon=AT_SEA_LON, timestamp_source=T0)
    }

    result = integrity.apply([curr], prev)
    flags = result[0].integrity_flags

    assert IntegrityFlag.SPOOF_SUSPECT_ON_LAND in flags
    assert IntegrityFlag.IMPLAUSIBLE_KINEMATICS not in flags


def test_null_prev_timestamp_source_skips_kinematics_without_error():
    integrity = Integrity(_cfg())

    curr = _feature(
        domain=Domain.MARINE,
        source_id="null-prev-ts",
        lat=AIR_OVER_LAT2,
        lon=KIN_LON,
        timestamp_source=T0_PLUS_1H,
    )
    prev = {"null-prev-ts": PrevPos(lat=KIN_LAT0, lon=KIN_LON, timestamp_source=None)}

    result = integrity.apply([curr], prev)
    assert IntegrityFlag.IMPLAUSIBLE_KINEMATICS not in result[0].integrity_flags


# ---------------------------------------------------------------------------
# Purity: identical inputs -> identical outputs; no cross-call state leak.
# ---------------------------------------------------------------------------


def _build_feature_and_prev(source_id: str) -> tuple[Feature, dict[str, PrevPos]]:
    """Builds a fresh, independent (feature, prev) pair every call -- used to
    prove determinism without relying on `apply`'s in-place mutation of a
    single shared Feature object (which would make a second `apply` call on
    the *same* instance double-append rather than test purity)."""
    feature = _feature(
        domain=Domain.MARINE,
        source_id=source_id,
        lat=MARINE_OVER_LAT2,
        lon=KIN_LON,
        timestamp_source=T0_PLUS_1H,
    )
    prev = {source_id: PrevPos(lat=KIN_LAT0, lon=KIN_LON, timestamp_source=T0)}
    return feature, prev


def test_apply_is_pure_identical_inputs_yield_identical_flags():
    integrity = Integrity(_cfg())

    feature_a, prev_a = _build_feature_and_prev("purity-a")
    feature_b, prev_b = _build_feature_and_prev("purity-b")

    result_a = integrity.apply([feature_a], prev_a)
    result_b = integrity.apply([feature_b], prev_b)

    assert result_a[0].integrity_flags == result_b[0].integrity_flags
    assert result_a[0].integrity_flags == [IntegrityFlag.IMPLAUSIBLE_KINEMATICS]


def test_apply_has_no_cross_call_state_leak_on_reused_instance():
    integrity = Integrity(_cfg())

    on_land = _feature(
        domain=Domain.MARINE,
        source_id="leak-on-land",
        lat=ON_LAND_LAT,
        lon=ON_LAND_LON,
        timestamp_source=T0,
    )
    first_result = integrity.apply([on_land], {})
    assert first_result[0].integrity_flags == [IntegrityFlag.SPOOF_SUSPECT_ON_LAND]

    # A completely unrelated second call, same Integrity instance, an
    # at-sea feature with no prev entry.
    unrelated = _feature(
        domain=Domain.MARINE,
        source_id="leak-unrelated",
        lat=AT_SEA_LAT,
        lon=AT_SEA_LON,
        timestamp_source=T0,
    )
    second_result = integrity.apply([unrelated], {})

    # The unrelated feature picked up nothing from the first call.
    assert second_result[0].integrity_flags == []
    # The first call's feature is untouched by the second call (no double
    # append, no shared mutable state on the Integrity instance).
    assert first_result[0].integrity_flags == [IntegrityFlag.SPOOF_SUSPECT_ON_LAND]


# ---------------------------------------------------------------------------
# Fail-fast: missing/corrupt landmask asset at construction.
# ---------------------------------------------------------------------------


def test_missing_landmask_path_raises_landmask_error_with_path_in_message(tmp_path):
    missing_path = tmp_path / "does-not-exist.geojson"

    with pytest.raises(LandmaskError) as exc_info:
        Integrity(_cfg(landmask_path=str(missing_path)))

    assert str(missing_path) in str(exc_info.value)


def test_corrupt_json_landmask_raises_landmask_error_with_path_in_message(tmp_path):
    corrupt_path = tmp_path / "corrupt.geojson"
    corrupt_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(LandmaskError) as exc_info:
        Integrity(_cfg(landmask_path=str(corrupt_path)))

    assert str(corrupt_path) in str(exc_info.value)


def test_wrong_shape_landmask_raises_landmask_error_with_path_in_message(tmp_path):
    # Valid JSON, but not a GeoJSON FeatureCollection at all.
    wrong_shape_path = tmp_path / "wrong-shape.geojson"
    wrong_shape_path.write_text(
        json.dumps({"type": "Point", "coordinates": [0, 0]}), encoding="utf-8"
    )

    with pytest.raises(LandmaskError) as exc_info:
        Integrity(_cfg(landmask_path=str(wrong_shape_path)))

    assert str(wrong_shape_path) in str(exc_info.value)


def test_empty_feature_collection_landmask_raises_landmask_error(tmp_path):
    # A well-formed FeatureCollection shell with zero features -- valid
    # GeoJSON, but useless as a landmask (would silently disable the spoof
    # check, which NFR3 forbids).
    empty_path = tmp_path / "empty.geojson"
    empty_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8"
    )

    with pytest.raises(LandmaskError) as exc_info:
        Integrity(_cfg(landmask_path=str(empty_path)))

    assert str(empty_path) in str(exc_info.value)
