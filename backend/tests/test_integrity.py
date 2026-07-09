"""Locked outer acceptance test for integrity slice 01 (issue #43): the two
cheap FR9 plausibility flags -- landmask spoof-suspect and implausible
kinematics.

Given an Integrity loaded with a known landmask and configured thresholds
When  apply() runs over a marine feature whose lat/lon falls inside a land
      polygon
Then  that feature carries SPOOF_SUSPECT_ON_LAND
When  a consecutive-report pair implies >120 kn (marine) or >990 kn (air)
Then  the current feature carries IMPLAUSIBLE_KINEMATICS
And   a same-timestamp pair (dt<=0) is skipped without error (no
      div-by-zero, no flag)
And   an air feature over land is NOT flagged spoof-suspect

Transcribed from plans/integrity/01-flags.md ("Acceptance criterion (outer
loop)") and design/specs/integrity.md ("Public interface", "Landmask
point-in-polygon (marine only)", "Implausible kinematics (marine + air)").
Slice 02 (static caveat text + active-flag counting) and wiring `apply` into
the scheduler write path are out of scope and neither referenced nor
asserted here (plan: "Out of scope (deferred)").

**Landmask fixture (test-author's choice, per the task's "critical design
point")**: `backend/tests/fixtures/landmask_test.geojson` -- a GeoJSON
`FeatureCollection` of a single land `Polygon`, a trivial square covering
lon [56.0, 56.5] x lat [26.0, 26.5] (inside the `hormuz` region bbox,
config.md). This is a deliberately tiny, deterministic, in-repo stand-in for
the real Natural Earth 10m land-polygon asset (design/specs/integrity.md
"Load once at startup"); it is NOT that asset and is never meant to be. This
format is a shapely-loadable, natural choice (`shapely.geometry.shape` over
each GeoJSON `Feature.geometry`) -- the implementer's `Integrity.__init__`
is expected to load whatever file `IntegrityCfg.landmask_path` points at
with exactly this reader (GeoJSON `FeatureCollection` -> list of land
`Polygon`/`MultiPolygon` geometries -> `shapely.STRtree`).

**Public surface this test locks (test-author's chosen minimal shape for
the spec's `IntegrityCfg`/`PrevPos`, neither of which the full spec's
interface block spells out beyond the constructor/method signature
comments)**:

    class IntegrityCfg:
        landmask_path: str          # path to a GeoJSON FeatureCollection of
                                     # land polygons (see fixture above)
        max_speed_kn_marine: float  # FR9 threshold, marine (120 kn)
        max_speed_kn_air: float     # FR9 threshold, air (990 kn, Mach 3)

    class PrevPos:                  # design/specs/integrity.md: "prev:
                                     # source_id -> last (lat, lon,
                                     # timestamp_source)"
        lat: float
        lon: float
        timestamp_source: datetime

    class Integrity:
        def __init__(self, cfg: IntegrityCfg) -> None: ...
        def apply(self, features: list[Feature],
                  prev: dict[str, PrevPos]) -> list[Feature]: ...

`IntegrityCfg`/`PrevPos` are constructed here with keyword arguments only,
so the implementer is free to choose `@dataclass`, `NamedTuple`, or a
pydantic `BaseModel` for either -- whichever backs `IntegrityCfg`/`PrevPos`,
these keyword names and `Integrity`'s two-method public surface are what
this test locks (mirrors test_scheduler.py's "chosen minimal constructor
slice" precedent for a spec that under-specifies an internal type's exact
shape).

The kinematics fixture pairs below use large, unambiguous position jumps
(tens of km) over a 60 s window so the exact implied speed clears each
threshold by a wide margin (~327 kn for the marine pair against a 120 kn
threshold; ~1632 kn for the air pair against a 990 kn threshold) --
verified independently against a standard haversine great-circle distance
before being fixed in this file, so the assertions do not depend on the
implementation's own distance formula agreeing with itself. The marine
pair's speed (~327 kn) is also deliberately kept well under the *air*
threshold (990 kn): if the implementation ever applied the air threshold to
a marine feature by mistake, this pair would wrongly go unflagged and the
test would catch it.

It was authored and committed red by the test-author before any
implementation existed (strict xfail, DEC-33): `backend.integrity` did not
exist yet, so importing it inside the test body raised `ModuleNotFoundError`
and the test xfailed cleanly under the tests-green gate. The implementer has
since made this genuinely pass; the xfail marker has been removed to
finalize the contract (test-author's marker-removal pass, DEC-1).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.integrity import Integrity, IntegrityCfg, PrevPos
from backend.models import (
    Domain,
    Feature,
    GeometryType,
    IntegrityFlag,
    LayerSnapshot,
    LayerSnapshotMeta,
    LayerStatus,
)

LANDMASK_FIXTURE = Path(__file__).parent / "fixtures" / "landmask_test.geojson"

# Inside the fixture's land square (lon [56.0, 56.5] x lat [26.0, 26.5]).
ON_LAND_LAT, ON_LAND_LON = 26.25, 56.25

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
T0_PLUS_60S = T0 + timedelta(seconds=60)


def _haversine_kn(
    lat1: float, lon1: float, lat2: float, lon2: float, dt_s: float
) -> float:
    """Independent reference haversine (NOT imported from the implementation
    under test) used only to size the fixture pairs below -- so the chosen
    coordinates are verified, ahead of time, to clear each threshold by a
    wide margin, without this test depending on its own distance formula
    matching the implementation's."""
    r_m = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    dist_m = 2 * r_m * math.asin(math.sqrt(a))
    dist_nm = dist_m / 1852
    return dist_nm / (dt_s / 3600)


# Marine pair: ~327 kn implied (> 120 kn marine threshold, < 990 kn air
# threshold -- see module docstring).
MARINE_PREV_LAT, MARINE_PREV_LON = 25.0, 55.0
MARINE_CURR_LAT, MARINE_CURR_LON = 25.0, 55.1
assert (
    _haversine_kn(
        MARINE_PREV_LAT, MARINE_PREV_LON, MARINE_CURR_LAT, MARINE_CURR_LON, 60
    )
    > 120
)
assert (
    _haversine_kn(
        MARINE_PREV_LAT, MARINE_PREV_LON, MARINE_CURR_LAT, MARINE_CURR_LON, 60
    )
    < 990
)

# Air pair: ~1632 kn implied (> 990 kn air threshold).
AIR_PREV_LAT, AIR_PREV_LON = 25.0, 56.0
AIR_CURR_LAT, AIR_CURR_LON = 25.0, 56.5
assert _haversine_kn(AIR_PREV_LAT, AIR_PREV_LON, AIR_CURR_LAT, AIR_CURR_LON, 60) > 990


def _feature(
    *,
    domain: Domain,
    source: str,
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


def test_apply_flags_spoof_suspect_on_land_and_implausible_kinematics():
    # =========================================================================
    # Given: an Integrity loaded with a known (fixture) landmask and
    # configured thresholds.
    # =========================================================================
    cfg = IntegrityCfg(
        landmask_path=str(LANDMASK_FIXTURE),
        max_speed_kn_marine=120,
        max_speed_kn_air=990,
    )
    integrity = Integrity(cfg)

    marine_on_land = _feature(
        domain=Domain.MARINE,
        source="aisstream",
        source_id="111111111",
        lat=ON_LAND_LAT,
        lon=ON_LAND_LON,
        timestamp_source=T0,
    )
    air_on_land = _feature(
        domain=Domain.AIR,
        source="opensky",
        source_id="a1b2c3",
        lat=ON_LAND_LAT,
        lon=ON_LAND_LON,
        timestamp_source=T0,
    )
    marine_curr = _feature(
        domain=Domain.MARINE,
        source="aisstream",
        source_id="222222222",
        lat=MARINE_CURR_LAT,
        lon=MARINE_CURR_LON,
        timestamp_source=T0_PLUS_60S,
    )
    air_curr = _feature(
        domain=Domain.AIR,
        source="opensky",
        source_id="d4e5f6",
        lat=AIR_CURR_LAT,
        lon=AIR_CURR_LON,
        timestamp_source=T0_PLUS_60S,
    )
    marine_dt_zero = _feature(
        domain=Domain.MARINE,
        source="aisstream",
        source_id="333333333",
        lat=AIR_CURR_LAT,  # reuses the large air jump's distance --
        lon=AIR_CURR_LON,  # proves the dt<=0 guard, not a small-distance fluke
        timestamp_source=T0,  # same timestamp as its prev entry -> dt == 0
    )

    prev = {
        marine_curr.source_id: PrevPos(
            lat=MARINE_PREV_LAT, lon=MARINE_PREV_LON, timestamp_source=T0
        ),
        air_curr.source_id: PrevPos(
            lat=AIR_PREV_LAT, lon=AIR_PREV_LON, timestamp_source=T0
        ),
        marine_dt_zero.source_id: PrevPos(
            lat=AIR_PREV_LAT, lon=AIR_PREV_LON, timestamp_source=T0
        ),
        # marine_on_land / air_on_land deliberately have no prev entry: a
        # feature with no prior report must not crash apply() and must not
        # be kinematics-flagged.
    }

    features = [marine_on_land, air_on_land, marine_curr, air_curr, marine_dt_zero]

    # =========================================================================
    # When: apply() runs over this feature set.
    # =========================================================================
    result = integrity.apply(features, prev)
    by_source_id = {f.source_id: f for f in result}

    # =========================================================================
    # Then: the marine feature on land carries SPOOF_SUSPECT_ON_LAND.
    # =========================================================================
    assert (
        IntegrityFlag.SPOOF_SUSPECT_ON_LAND
        in by_source_id[marine_on_land.source_id].integrity_flags
    )

    # =========================================================================
    # And: an air feature over land is NOT flagged spoof-suspect.
    # =========================================================================
    assert (
        IntegrityFlag.SPOOF_SUSPECT_ON_LAND
        not in by_source_id[air_on_land.source_id].integrity_flags
    )

    # =========================================================================
    # Then: a consecutive-report pair implying >120 kn (marine) carries
    # IMPLAUSIBLE_KINEMATICS on the current feature.
    # =========================================================================
    assert (
        IntegrityFlag.IMPLAUSIBLE_KINEMATICS
        in by_source_id[marine_curr.source_id].integrity_flags
    )
    # And it is not wrongly spoof-flagged (its position is at sea, not on
    # the fixture's land square).
    assert (
        IntegrityFlag.SPOOF_SUSPECT_ON_LAND
        not in by_source_id[marine_curr.source_id].integrity_flags
    )

    # =========================================================================
    # And: the same holds for a pair implying >990 kn (air).
    # =========================================================================
    assert (
        IntegrityFlag.IMPLAUSIBLE_KINEMATICS
        in by_source_id[air_curr.source_id].integrity_flags
    )

    # =========================================================================
    # And: a same-timestamp pair (dt<=0) is skipped without error (no
    # div-by-zero, no flag) -- apply() above already had to run to
    # completion without raising for this assertion to even be reached.
    # =========================================================================
    assert (
        IntegrityFlag.IMPLAUSIBLE_KINEMATICS
        not in by_source_id[marine_dt_zero.source_id].integrity_flags
    )


# =============================================================================
# Slice 02 (issue #44): static per-layer caveat text (`CAVEATS`) + the
# active-flag counting helper backing `GET /api/layers/{domain}/caveats`
# (api.md: `{"domain":..., "caveats":[...], "active_flags": {...}}`).
#
# Given the integrity module
# When  CAVEATS[domain] is read for air, marine, and land
# Then  each returns the exact caveat bullet list from the spec (verbatim,
#       not paraphrased -- design/specs/integrity.md "Static caveat text")
# When  the active-flag counter runs over a snapshot with flagged features
# Then  it returns a count per known IntegrityFlag, tallied from those
#       features (plan: "{spoof_suspect_on_land: n, implausible_kinematics: m}")
# And   an empty (or unflagged) snapshot yields zero counts for every flag
# And   a feature carrying BOTH flags increments both counters
#
# Transcribed from plans/integrity/02-caveats.md ("Acceptance criterion
# (outer loop)") and design/specs/integrity.md ("Static caveat text (per
# layer, FR9 / api.md caveats)").
#
# **Design decision this test locks (test-author's choice, per the task's
# "critical design point")**: the counting helper is
#
#     def active_flag_counts(snapshot: LayerSnapshot) -> dict[str, int]: ...
#
# -- it takes the full `LayerSnapshot` (not a bare `list[Feature]`), because
# the caveats endpoint (api-core, out of scope here) will hold a
# `LayerSnapshot` straight from the registry and should be able to pass it
# through unchanged. The return dict is keyed by `IntegrityFlag.value`
# (plain strings: "spoof_suspect_on_land", "implausible_kinematics") rather
# than by the enum member itself, because that is exactly api.md's
# `active_flags` wire shape -- the implementer's future endpoint can return
# this dict as JSON with zero key translation. Every known `IntegrityFlag`
# is always present in the returned dict, at 0 if unflagged, so an empty or
# entirely-unflagged snapshot still yields a dict with a zero for every flag
# (not an empty dict) -- this matches the plan's "zero counts for every
# flag", not "no counts at all".
#
# It was authored and committed red by the test-author before any
# implementation existed (strict xfail, DEC-33): `CAVEATS` and
# `active_flag_counts` did not exist in `backend.integrity` yet, so importing
# them inside the test body raised `ImportError`/`AttributeError` and the
# tests xfailed cleanly under the tests-green gate. The implementer has since
# made these genuinely pass; the xfail markers have been removed to finalize
# the contract (test-author's marker-removal pass, DEC-1).
# =============================================================================


def _flagged_feature(
    *,
    domain: Domain,
    source: str,
    source_id: str,
    lat: float,
    lon: float,
    flags: list[IntegrityFlag],
) -> Feature:
    feature = _feature(
        domain=domain,
        source=source,
        source_id=source_id,
        lat=lat,
        lon=lon,
        timestamp_source=T0,
    )
    feature.integrity_flags = list(flags)
    return feature


def _snapshot(domain: Domain, features: list[Feature]) -> LayerSnapshot:
    return LayerSnapshot(
        meta=LayerSnapshotMeta(
            layer=domain,
            region_id="hormuz",
            status=LayerStatus.LIVE,
            timestamp_fetched=T0,
            timestamp_source=T0,
            cadence_s=60,
            stale_after_s=120,
            feature_count=len(features),
        ),
        features=features,
    )


def test_caveats_text_matches_spec_verbatim():
    from backend.integrity import CAVEATS

    # =========================================================================
    # Given the integrity module
    # When CAVEATS[domain] is read for air, marine, and land
    # Then each returns the exact caveat bullet list from the spec, verbatim
    # (design/specs/integrity.md "Static caveat text (per layer, FR9 /
    # api.md caveats)") -- not paraphrased, not reordered, not truncated.
    # =========================================================================
    assert CAVEATS[Domain.AIR] == [
        "Shows only aircraft broadcasting ADS-B/Mode S within receiver coverage.",
        "Military and state aircraft with transponders switched off are invisible here.",
        "Mode S-only aircraft broadcast no position; altitude/position gaps are expected.",
    ]
    assert CAVEATS[Domain.MARINE] == [
        "Terrestrial AIS coverage in the Persian Gulf is receiver-dependent and uneven.",
        "Dark-fleet vessels routinely disable AIS and will not appear.",
        "GPS jamming in the region produces on-land and circular ghost tracks; "
        "positions may be spoofed.",
    ]
    assert CAVEATS[Domain.LAND] == [
        "This layer is mapped infrastructure state, not live telemetry.",
        "Positions reflect OpenStreetMap data at the shown osm_base timestamp, "
        "not current ground truth.",
        "Absence of a feature means it is unmapped, not necessarily absent on the ground.",
    ]


def test_active_flag_counts_tallies_flags_across_a_snapshot():
    from backend.integrity import active_flag_counts

    # =========================================================================
    # Given a marine snapshot whose features carry a mix of integrity flags:
    # two flagged SPOOF_SUSPECT_ON_LAND only, one flagged
    # IMPLAUSIBLE_KINEMATICS only, one flagged with BOTH, and one unflagged.
    # =========================================================================
    spoof_only_1 = _flagged_feature(
        domain=Domain.MARINE,
        source="aisstream",
        source_id="111111111",
        lat=ON_LAND_LAT,
        lon=ON_LAND_LON,
        flags=[IntegrityFlag.SPOOF_SUSPECT_ON_LAND],
    )
    spoof_only_2 = _flagged_feature(
        domain=Domain.MARINE,
        source="aisstream",
        source_id="222222222",
        lat=ON_LAND_LAT,
        lon=ON_LAND_LON,
        flags=[IntegrityFlag.SPOOF_SUSPECT_ON_LAND],
    )
    kinematics_only = _flagged_feature(
        domain=Domain.MARINE,
        source="aisstream",
        source_id="333333333",
        lat=MARINE_CURR_LAT,
        lon=MARINE_CURR_LON,
        flags=[IntegrityFlag.IMPLAUSIBLE_KINEMATICS],
    )
    # A single feature carrying BOTH flags must increment both counters.
    both_flags = _flagged_feature(
        domain=Domain.MARINE,
        source="aisstream",
        source_id="444444444",
        lat=ON_LAND_LAT,
        lon=ON_LAND_LON,
        flags=[
            IntegrityFlag.SPOOF_SUSPECT_ON_LAND,
            IntegrityFlag.IMPLAUSIBLE_KINEMATICS,
        ],
    )
    unflagged = _flagged_feature(
        domain=Domain.MARINE,
        source="aisstream",
        source_id="555555555",
        lat=MARINE_PREV_LAT,
        lon=MARINE_PREV_LON,
        flags=[],
    )
    snapshot = _snapshot(
        Domain.MARINE,
        [spoof_only_1, spoof_only_2, kinematics_only, both_flags, unflagged],
    )

    # =========================================================================
    # When the active-flag counter runs over this snapshot
    # Then it returns a count per known IntegrityFlag, keyed by flag value
    # (api.md active_flags wire shape): 3 x spoof_suspect_on_land (2 solo +
    # 1 from the both-flags feature), 2 x implausible_kinematics (1 solo + 1
    # from the both-flags feature).
    # =========================================================================
    counts = active_flag_counts(snapshot)

    assert counts == {
        IntegrityFlag.SPOOF_SUSPECT_ON_LAND.value: 3,
        IntegrityFlag.IMPLAUSIBLE_KINEMATICS.value: 2,
    }


def test_active_flag_counts_empty_or_unflagged_snapshot_yields_zero_for_every_flag():
    from backend.integrity import active_flag_counts

    # =========================================================================
    # Given an entirely empty snapshot (no features at all)
    # Then the counter returns zero counts for EVERY known flag -- a dict
    # with a 0 for each IntegrityFlag, not an empty dict.
    # =========================================================================
    empty_snapshot = _snapshot(Domain.AIR, [])
    assert active_flag_counts(empty_snapshot) == {
        IntegrityFlag.SPOOF_SUSPECT_ON_LAND.value: 0,
        IntegrityFlag.IMPLAUSIBLE_KINEMATICS.value: 0,
    }

    # =========================================================================
    # And: a snapshot whose features carry no integrity flags at all yields
    # the same all-zero result.
    # =========================================================================
    unflagged_feature = _flagged_feature(
        domain=Domain.LAND,
        source="overpass",
        source_id="way/1",
        lat=25.0,
        lon=56.0,
        flags=[],
    )
    unflagged_snapshot = _snapshot(Domain.LAND, [unflagged_feature])
    assert active_flag_counts(unflagged_snapshot) == {
        IntegrityFlag.SPOOF_SUSPECT_ON_LAND.value: 0,
        IntegrityFlag.IMPLAUSIBLE_KINEMATICS.value: 0,
    }
