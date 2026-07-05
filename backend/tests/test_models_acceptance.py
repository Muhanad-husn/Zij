"""Locked outer acceptance test for models step (issue #9): Feature/LayerSnapshot schema.

Given the backend.models module
When  a Feature is built from the air wire example in feature-schema.md and dumped
      with model_dump()/model_dump_json()
Then  it validates (UTC-aware datetimes, lat in [-90,90], lon in [-180,180],
      extra="forbid")
And   raw_payload is excluded from the dumped output
And   a LayerSnapshot wrapping that Feature round-trips through model_validate()
      unchanged

This is the behavioral contract (), transcribed from
plans/models/01-feature-schema.md and design/contracts/feature-schema.md (the
air wire example at contract lines 173-195). It is authored and committed red
by the author before any implementation exists, guarded by a strict
xfail (). Do not weaken these assertions and do not remove the xfail
marker until the developer has made this genuinely pass.
"""

import json

import pytest

# The single air feature from the wire example (feature-schema.md lines 182-194).
AIR_FEATURE_WIRE = {
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
    "attrs": {
        "altitude_m": 10668.0,
        "geo_altitude_m": 10820.0,
        "velocity_ms": 231.5,
        "vertical_rate_ms": 0.0,
        "true_track_deg": 118.4,
        "position_source": "ADS-B",
        "on_ground": False,
    },
}

# The matching meta object (feature-schema.md lines 175-181).
AIR_META_WIRE = {
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

# An in-memory-only raw upstream record; must never appear in any dumped output.
RAW_PAYLOAD_EXAMPLE = {
    "icao24": "896451",
    "callsign": "IRA655   ",
    "raw_state_vector": [
        "896451", "IRA655", "Iran", 1751706718, 1751706723,
        56.27, 26.61, 10668.0, False, 231.5, 118.4, 0.0,
        None, 10820.0, None, False, 0,
    ],
}


@pytest.mark.xfail(reason="backend.models not yet implemented", strict=True)
def test_feature_and_layer_snapshot_schema_from_air_wire_example():
    from pydantic import ValidationError

    from backend.models import Feature, LayerSnapshot, LayerSnapshotMeta

    # --- Given: a Feature built from the air wire example, raw_payload populated in-memory ---
    feature = Feature.model_validate(
        {**AIR_FEATURE_WIRE, "raw_payload": RAW_PAYLOAD_EXAMPLE}
    )

    # --- Then: it validates ---

    # UTC-aware datetimes (NFR6, "no naive datetimes, ever").
    assert feature.timestamp_source is not None
    assert feature.timestamp_source.tzinfo is not None
    assert feature.timestamp_source.utcoffset().total_seconds() == 0
    assert feature.timestamp_fetched.tzinfo is not None
    assert feature.timestamp_fetched.utcoffset().total_seconds() == 0

    # A naive datetime must be rejected outright -- the contract permits no exceptions.
    with pytest.raises(ValidationError):
        Feature.model_validate(
            {**AIR_FEATURE_WIRE, "timestamp_fetched": "2026-07-05T09:12:03"}
        )

    # lat in [-90, 90], lon in [-180, 180].
    assert -90 <= feature.lat <= 90
    assert -180 <= feature.lon <= 180
    with pytest.raises(ValidationError):
        Feature.model_validate({**AIR_FEATURE_WIRE, "lat": 91})
    with pytest.raises(ValidationError):
        Feature.model_validate({**AIR_FEATURE_WIRE, "lon": 181})

    # extra="forbid": an unknown field must be rejected.
    with pytest.raises(ValidationError):
        Feature.model_validate({**AIR_FEATURE_WIRE, "unexpected_field": "nope"})

    # --- And: raw_payload is populated in-memory but excluded from dumped output ---
    assert feature.raw_payload == RAW_PAYLOAD_EXAMPLE

    dumped = feature.model_dump()
    assert "raw_payload" not in dumped

    dumped_json = feature.model_dump_json()
    assert "raw_payload" not in json.loads(dumped_json)
    assert "raw_payload" not in dumped_json  # not present as raw text in the wire body either

    # --- And: a LayerSnapshot wrapping that Feature round-trips through model_validate() unchanged ---
    meta = LayerSnapshotMeta.model_validate(AIR_META_WIRE)
    snapshot = LayerSnapshot(meta=meta, features=[feature])

    snapshot_dump = snapshot.model_dump()
    assert "raw_payload" not in snapshot_dump["features"][0]

    round_tripped = LayerSnapshot.model_validate(snapshot_dump)

    # Round-tripping is unchanged: re-dumping the round-tripped snapshot reproduces
    # the exact same wire body (raw_payload stays excluded on both sides of the trip).
    assert round_tripped.model_dump() == snapshot_dump

    # And the substantive fields carried through the trip intact.
    assert round_tripped.meta.region_id == "hormuz"
    assert round_tripped.meta.layer == meta.layer
    assert round_tripped.meta.timestamp_fetched == meta.timestamp_fetched
    assert round_tripped.meta.stale_after_s == 1200
    assert len(round_tripped.features) == 1
    assert round_tripped.features[0].source_id == "896451"
    assert round_tripped.features[0].lat == feature.lat
    assert round_tripped.features[0].lon == feature.lon
    assert round_tripped.features[0].timestamp_source == feature.timestamp_source
