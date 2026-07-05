"""Locked outer acceptance test for overpass-adapter step (issue #15):
fetch() parses the real Hormuz Overpass response into LayerSnapshot(LAND).

Given the committed fixture overpass_hormuz.json and httpx mocked to return
      it for each class query
When  OverpassAdapter.fetch(hormuz_region) is awaited
Then  it returns a LayerSnapshot with meta.layer == LAND and a non-empty
      features list
And   a primary-road way becomes a LINESTRING Feature with GeoJSON
      coordinates in [lon,lat] order and attrs carrying the OSM tags
      verbatim
And   a port/aerodrome node becomes a POINT Feature (geometry=None,
      lat/lon set)
And   every feature's timestamp_source equals the fixture's
      osm3s.timestamp_osm_base parsed as UTC
And   meta.timestamp_source equals that same osm_base (not the fetch time)
And   a source_id matched by two class queries appears exactly once
      (deduped, first wins)

This is the behavioral contract (), transcribed from
plans/overpass-adapter/01-fetch-land.md ("Acceptance criterion") and
design/specs/overpass.md ("Parsing -> Feature" + "osm_base capture (FR4)"),
honoring the error taxonomy and Region/LayerSnapshot shapes fixed by
design/contracts/adapter-interface.md and backend/models.py.

RECONCILED for slice overpass-adapter/02 (issue #16): `fetch()` now runs its
parsed+deduped features through `simplify_and_cap` (Douglas-Peucker + the
<=5000 cap, design/specs/overpass.md "Geometry simplification") before
building the `LayerSnapshot`. That is a legitimate, in-scope change to this
slice's own post-condition -- geometry is simplified, and drop-tier-eligible
features exceeding the cap are removed -- so two assertions from the
original (step) test no longer hold as written and are replaced here,
by the author, per 's follow-up/reconciliation pass:
  - Way `4846466` (`highway=primary`) is drop-tier-eligible (tier 1, the
    first tier drained) and the ~8300-element fixture pushes the parsed
    count over the 5000 cap, so this fixture's real `fetch()` now legitimately
    drops it. The LINESTRING/`[lon,lat]`/attrs-verbatim assertions originally
    pinned to that way are replaced below with the same shape of assertions
    against way `4009554` (`highway=motorway`, "Sheikh Mohammed Bin Zayed
    Road" / ref E311) -- a `highway=motorway` way, which `simplify_and_cap`
    never drops regardless of the cap -- so it is guaranteed to survive.
    Because Douglas-Peucker may (and for this 33-vertex way, does) change
    the vertex count, the coordinate list is no longer pinned verbatim
    against the fixture's raw `geometry` array; instead the test asserts
    structure (LineString, `[lon, lat]` numeric pairs, longitude in the
    Hormuz band) and that `attrs` still carries every OSM tag verbatim
    (simplification touches only `geometry`, never `attrs`).
  - A new assertion is added: `len(snapshot.features) <= 5000`, pinning the
    cap itself now visibly enforced through the full `fetch()` path (the
    fixture has ~8300 elements pre-cap).
Every assertion not touched by simplification (meta.layer, region_id,
non-empty features, feature_count == len(features), the port node's POINT
shape + verbatim attrs + dedup/first-wins, every feature's/meta's
timestamp_source == osm_base) is preserved unchanged below -- those are
step's real intent and simplification does not touch them (POINT
anchors are never dropped, and dedup/osm_base happen before
`simplify_and_cap` runs).

It was authored and committed red by the author before any
implementation existed (strict xfail, ): `backend/sources/overpass.py`
did not exist yet, so importing `OverpassAdapter` inside the test body (not
at module level, so collection itself stayed green) raised
`ModuleNotFoundError` -- xfail's default (no `raises=` narrowing) treats any
exception as the expected failure, so this failed for that reason and
xfailed cleanly under the tests-green gate. the developer has since made
it genuinely pass; the xfail marker has been removed to finalize the
contract.

Below the outer test are inner unit tests (), authored against the
now-built `OverpassAdapter` from the plan's ("Inner loop -- initial unit test
list", plans/overpass-adapter/01-fetch-land.md): each covers a gap the outer
test deliberately leaves unexercised (the source_id/attrs/label mapping in
isolation, every geometry edge case, "oldest osm_base wins" across genuinely
differing responses, dedup with differing tags proving "first wins" isn't
an accident, the whitelist actually sent over the wire, and the 429/504
rotate-then-exhaust + malformed-JSON failure paths) rather than duplicating
the outer test's single-fixture happy path.

Why this is not satisfiable by a stub: the committed fixture is mocked, via
a single respx route matched on URL only (any HTTP method, any query
string -- verified against respx's default `url=` lookup, which ignores
query params unless the pattern itself carries one), to answer literally
every one of the six whitelisted class-query requests `fetch()` makes
identically. That means every element in the ~8300-element fixture is, by
construction, served under (in fact six, not merely two) separate class
queries -- so a naive implementation that just concatenates all six
responses' `elements` into Features without deduplicating by `source_id`
would produce SIX Feature objects for the primary way and the port node
picked below, not one. The `== 1` assertions on those two picked source_ids
therefore fail against exactly that "return everything, don't dedup" stub,
not merely a "return nothing" one. The LINESTRING coordinate list, tag
dict, POINT lat/lon, and `osm_base` values are all pinned against the real
recorded fixture content read at test time (not hardcoded literals prone to
silently drifting from the fixture), so a stub returning a differently
shaped/ordered geometry or dropping/mangling `attrs` also fails.

Names this test requires the developer to provide (spec-fixed unless
noted "author's plumbing choice"):
  - backend.sources.overpass.OverpassAdapter(cfg): domain=Domain.LAND,
    source="overpass", async fetch(region) -> LayerSnapshot
    (design/specs/overpass.md "Public interface"). The single-argument
    constructor signature `OverpassAdapter(cfg)` is this author's
    plumbing choice (overpass.md does not fix a constructor signature the
    way opensky.md fixes `OpenSkyAdapter(cfg, secrets, credits)` --
    Overpass has no auth and no credit ledger, so no secrets/credits
    collaborator is needed).
  - backend.sources.overpass.OverpassCfg, constructible from the merged
    `[overpass]` + `[layers.land]` config tables (mirroring the established
    `OpenSkyCfg` pattern in backend/sources/opensky.py); this test merges
    `cfg.overpass` and `cfg.layers["land"].model_dump()` as kwargs, so
    `OverpassCfg` must accept that combined key set and expose `mirrors`
    (a list of mirror base URLs, config.md/overpass.md "Configuration
    consumed") as an attribute. The class NAME `OverpassCfg` is this
    author's plumbing choice (not spec-fixed).
  - Feature/LayerSnapshot/LayerSnapshotMeta/Domain/GeometryType shapes are
    all spec-fixed by backend/models.py (feature-schema.md), transcribed
    verbatim there; this test uses only the real field/enum names defined
    in that module.

Assumptions made about fixture content (verified by inspection, not
invented): `backend/tests/fixtures/overpass_hormuz.json` is a single,
already-merged Overpass API JSON response (`version`/`generator`/`osm3s`/
`elements`) with `osm3s.timestamp_osm_base == "2026-07-05T17:59:00Z"` and
8323 elements (8223 ways, 100 nodes). Way `4846466` carries
`tags.highway == "primary"` (Al Maktoum Bridge) with a 6-vertex `geometry`
list of `{"lat":..., "lon":...}` objects (Overpass `out geom` shape) --
drop-tier-eligible (tier 1) and, as reconciled above for step, no
longer asserted present with raw geometry (this fixture's parsed count
exceeds the 5000 cap, so it is legitimately dropped). Node `2109558996`
carries `tags.harbour == "yes"` (Al Hamriya Port) with direct top-level
`lat`/`lon` (a bare node, not an `out center` result -- the plan's
"port/aerodrome node" wording covers this: any node-shaped element from the
whitelisted point classes, of which `harbour` is one, per overpass.md
query #3) -- a POINT anchor, never drop-tier-eligible, so it still survives
unchanged. Way `4009554` carries `tags.highway == "motorway"` ("Sheikh
Mohammed Bin Zayed Road" / `ref=E311`) with a 33-vertex `geometry` list --
a `highway=motorway` way, never drop-tier-eligible regardless of the cap,
used below (in place of the now-dropped primary way) to prove the
LINESTRING/`[lon,lat]`/attrs-verbatim shape on a feature guaranteed to
survive `simplify_and_cap`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from httpx import Response

FIXTURES_DIR = Path(__file__).parent / "fixtures"
OVERPASS_FIXTURE = FIXTURES_DIR / "overpass_hormuz.json"

# way/4846466 -- highway=primary, "Al Maktoum Bridge" (Dubai), 6-vertex
# geometry. Drop-tier-eligible (tier 1); this fixture's parsed count exceeds
# the step 5000 cap, so it is legitimately dropped by `simplify_and_cap`
# inside `fetch()`. Kept here only as a fixture-content sanity check (that
# the tags this author inspected are still what's on disk), not as an
# output assertion.
PRIMARY_WAY_ID = 4846466
# node/2109558996 -- harbour=yes, "Al Hamriya Port" (Dubai), bare node.
# A POINT anchor -- never drop-tier-eligible -- so it still survives.
PORT_NODE_ID = 2109558996
# way/4009554 -- highway=motorway, "Sheikh Mohammed Bin Zayed Road" / E311,
# 33-vertex geometry. `highway=motorway` ways are never drop-tier-eligible
# regardless of the cap, so this way is guaranteed to survive
# `simplify_and_cap` -- used in place of the now-dropped primary way to
# prove the LINESTRING/[lon,lat]/attrs-verbatim shape survives fetch().
MOTORWAY_WAY_ID = 4009554


async def test_fetch_hormuz_land():
    """Slice overpass-adapter/02 (issue #16) reconciliation note: `fetch()`
    now runs parsed+deduped features through `simplify_and_cap` before
    building the LayerSnapshot (Douglas-Peucker simplify + the <=5000 drop
    cap). That legitimately changes this fixture's real output: way
    `4846466` (highway=primary, tier 1) is now dropped because the ~8300
    parsed elements exceed the 5000 cap. The primary-way LINESTRING pin is
    therefore replaced with the same shape of assertions against way
    `4009554` (highway=motorway -- never drop-tier-eligible, so guaranteed
    to survive), and a new `len(features) <= 5000` assertion pins the cap
    itself. Every other assertion (meta shape, the port POINT anchor's
    verbatim attrs/geometry=None, osm_base stamping, dedup/first-wins) is
    unchanged from step's original intent -- simplification does not
    touch any of it.
    """
    # --- Given: the committed fixture, inspected for the three concrete
    # elements this test pins its assertions to ---
    fixture_body = json.loads(OVERPASS_FIXTURE.read_text(encoding="utf-8"))
    elements_by_key = {
        (element["type"], element["id"]): element
        for element in fixture_body["elements"]
    }
    primary_way = elements_by_key[("way", PRIMARY_WAY_ID)]
    port_node = elements_by_key[("node", PORT_NODE_ID)]
    motorway_way = elements_by_key[("way", MOTORWAY_WAY_ID)]
    assert primary_way["tags"]["highway"] == "primary"
    assert port_node["tags"].get("harbour") == "yes"
    assert motorway_way["tags"]["highway"] == "motorway"

    expected_osm_base = datetime.fromisoformat(
        fixture_body["osm3s"]["timestamp_osm_base"].replace("Z", "+00:00")
    )

    from backend.config import load_config
    from backend.models import Domain, GeometryType
    from backend.sources.base import Region
    from backend.sources.overpass import OverpassAdapter, OverpassCfg

    cfg, _secrets = load_config()
    overpass_cfg = OverpassCfg(**cfg.overpass, **cfg.layers["land"].model_dump())
    mirror_url = overpass_cfg.mirrors[0]

    hormuz_bbox = (55.0, 25.0, 57.5, 27.5)
    hormuz_region = Region(id="hormuz", label="Strait of Hormuz", bbox=hormuz_bbox)

    async with respx.mock() as respx_mock:
        # Matched on URL only (any HTTP method, any query string) -- every
        # one of the six whitelisted class queries (§6.3) hits this same
        # mocked mirror and receives the SAME fixture body.
        respx_mock.route(url=mirror_url).mock(
            return_value=Response(200, json=fixture_body)
        )

        adapter = OverpassAdapter(overpass_cfg)
        await adapter.start()

        # --- When ---
        snapshot = await adapter.fetch(hormuz_region)

        await adapter.stop()

    # --- Then: LayerSnapshot(meta.layer == LAND), non-empty features ---
    assert snapshot.meta.layer == Domain.LAND
    assert snapshot.meta.region_id == "hormuz"
    assert len(snapshot.features) > 0
    assert snapshot.meta.feature_count == len(snapshot.features)

    # --- And (step): the cap is enforced through the full fetch() path
    # -- the fixture's ~8300 parsed elements are capped to <=5000 ---
    assert len(snapshot.features) <= 5000

    # --- And: the primary-road way is now dropped (tier 1, over-cap) ---
    primary_matches = [
        f for f in snapshot.features if f.source_id == f"way/{PRIMARY_WAY_ID}"
    ]
    assert len(primary_matches) == 0

    # --- And: a motorway way (never drop-tier-eligible) survives as a
    # LINESTRING, [lon,lat] order, attrs carrying the OSM tags verbatim.
    # Simplification may reduce its vertex count, so the coordinate list is
    # NOT pinned verbatim against the fixture's raw geometry -- only the
    # structure (LineString, [lon,lat] numeric pairs, Hormuz longitude band)
    # is asserted ---
    motorway_matches = [
        f for f in snapshot.features if f.source_id == f"way/{MOTORWAY_WAY_ID}"
    ]
    assert len(motorway_matches) == 1
    motorway_feature = motorway_matches[0]
    assert motorway_feature.geometry_type == GeometryType.LINESTRING
    assert motorway_feature.geometry["type"] == "LineString"
    coordinates = motorway_feature.geometry["coordinates"]
    assert len(coordinates) >= 2
    for coordinate in coordinates:
        assert len(coordinate) == 2
        lon, lat = coordinate
        assert isinstance(lon, (int, float))
        assert isinstance(lat, (int, float))
        # Hormuz region bbox is (55.0, 25.0, 57.5, 27.5) -- lon > lat holds
        # throughout this band, distinguishing [lon,lat] from [lat,lon].
        assert lon > lat
    assert motorway_feature.attrs == motorway_way["tags"]

    # --- And: a port node -> POINT (geometry=None, lat/lon set) -- POINT
    # anchors are never dropped, so this survives unchanged ---
    port_matches = [
        f for f in snapshot.features if f.source_id == f"node/{PORT_NODE_ID}"
    ]
    assert len(port_matches) == 1
    port_feature = port_matches[0]
    assert port_feature.geometry_type == GeometryType.POINT
    assert port_feature.geometry is None
    assert port_feature.lat == port_node["lat"]
    assert port_feature.lon == port_node["lon"]
    assert port_feature.attrs == port_node["tags"]

    # --- And: every feature's timestamp_source == the fixture's osm_base,
    # parsed as UTC ---
    assert all(f.timestamp_source == expected_osm_base for f in snapshot.features)

    # --- And: meta.timestamp_source == that same osm_base (not fetch time) ---
    assert snapshot.meta.timestamp_source == expected_osm_base

    # --- And: a source_id matched by (all six, hence at least two) class
    # queries appears exactly once -- deduped, not concatenated six-fold.
    # (The primary way is dropped by the cap, not by dedup, so it can no
    # longer serve as this proof; the surviving motorway way and port node
    # both serve it identically -- if dedup were broken, the shared fixture
    # answering all six class queries identically would produce 6 copies of
    # each, not 1.) ---
    assert len(motorway_matches) == 1
    assert len(port_matches) == 1


# ---------------------------------------------------------------------------
# overpass-adapter/01 (issue #15) inner units ().
# ---------------------------------------------------------------------------


async def _no_op_sleep(*args, **kwargs):
    """Patched over `backend.sources.overpass.asyncio.sleep` in the
    full-`fetch()` inner tests below to eliminate the real 0.5 s
    per-class delay (5 sleeps = 2.5 s of dead time per test) -- these tests
    exercise only the successful-response parsing/dedup/osm_base paths, not
    the delay itself (which the outer test already runs through once)."""
    return None


def _make_overpass_cfg(**overrides):
    """Minimal `OverpassCfg` for inner unit tests (author's plumbing
    choice for placeholder values; `OverpassCfg`'s required field set is
    spec-fixed, transcribed from `backend/config.toml`'s `[overpass]` +
    `[layers.land]` defaults)."""
    from backend.sources.overpass import OverpassCfg

    defaults = dict(
        mirrors=["https://overpass.example.test/api/interpreter"],
        timeout_s=180.0,
        maxsize_bytes=536870912,
        backoff_base_s=5.0,
        backoff_max_s=300.0,
        max_attempts=4,
        cadence_s=86400,
        cadence_floor_s=3600,
        custom_bbox_cap_sq_deg=40.0,
    )
    defaults.update(overrides)
    return OverpassCfg(**defaults)


def test_source_id_attrs_verbatim_and_label_from_name_or_none():
    """Inner unit (plan item 1): `source_id = f"{type}/{id}"`; `attrs`
    mirrors `element.tags` verbatim; `label` is `tags["name"]` when present,
    else `None` -- pinned against a tag dict that genuinely lacks the "name"
    key (not merely an empty tags dict), so a naive `tags.get("name", "")`
    couldn't slip an empty string past this assertion."""
    from backend.sources.overpass import OverpassAdapter

    cfg = _make_overpass_cfg()
    adapter = OverpassAdapter(cfg)
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    osm_base = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)

    named_node = {
        "type": "node",
        "id": 2109558996,
        "lat": 25.30,
        "lon": 55.35,
        "tags": {"harbour": "yes", "name": "Al Hamriya Port"},
    }
    source_id = adapter._source_id(named_node)
    assert source_id == "node/2109558996"
    feature = adapter._feature_from_element(named_node, source_id, now, osm_base)
    assert feature.source_id == "node/2109558996"
    assert feature.attrs == {"harbour": "yes", "name": "Al Hamriya Port"}
    assert feature.label == "Al Hamriya Port"

    unnamed_way = {
        "type": "way",
        "id": 4846466,
        "tags": {"highway": "trunk"},
        "center": {"lat": 1.0, "lon": 2.0},
    }
    unnamed_source_id = adapter._source_id(unnamed_way)
    assert unnamed_source_id == "way/4846466"
    unnamed_feature = adapter._feature_from_element(
        unnamed_way, unnamed_source_id, now, osm_base
    )
    assert unnamed_feature.attrs == {"highway": "trunk"}
    assert unnamed_feature.label is None


def test_geometry_bare_node_and_out_center_both_yield_point():
    """Inner unit (plan item 2): a bare node (`out;`, top-level lat/lon) and
    an `out center` result (a way carrying a `center` sub-object) both map
    to POINT with `geometry=None` -- two distinct wire shapes collapsing to
    the same Feature shape."""
    from backend.models import GeometryType
    from backend.sources.overpass import OverpassAdapter

    cfg = _make_overpass_cfg()
    adapter = OverpassAdapter(cfg)
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    osm_base = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)

    bare_node = {"type": "node", "id": 1, "lat": 10.5, "lon": 20.5, "tags": {}}
    bare_feature = adapter._feature_from_element(bare_node, "node/1", now, osm_base)
    assert bare_feature.geometry_type == GeometryType.POINT
    assert bare_feature.geometry is None
    assert bare_feature.lat == 10.5
    assert bare_feature.lon == 20.5

    center_way = {
        "type": "way",
        "id": 2,
        "tags": {"aeroway": "aerodrome"},
        "center": {"lat": 30.5, "lon": 40.5},
    }
    center_feature = adapter._feature_from_element(center_way, "way/2", now, osm_base)
    assert center_feature.geometry_type == GeometryType.POINT
    assert center_feature.geometry is None
    assert center_feature.lat == 30.5
    assert center_feature.lon == 40.5


def test_geometry_way_with_geometry_yields_linestring_lonlat_order_and_midpoint():
    """Inner unit (plan item 2): a way with `geometry` (out geom shape, not
    closed) maps to LINESTRING, coordinates in `[lon, lat]` order (RFC 7946),
    and the representative lat/lon is the MIDDLE vertex (`vertices[len//2]`),
    not the first or last -- pinned with a 5-vertex way where every vertex is
    numerically distinct, so a wrong index can't hide behind a coincidental
    match."""
    from backend.models import GeometryType
    from backend.sources.overpass import OverpassAdapter

    cfg = _make_overpass_cfg()
    adapter = OverpassAdapter(cfg)
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    osm_base = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)

    vertices = [
        {"lat": 25.0, "lon": 55.0},
        {"lat": 25.1, "lon": 55.2},
        {"lat": 25.2, "lon": 55.4},  # middle vertex (index 2 of 5)
        {"lat": 25.3, "lon": 55.6},
        {"lat": 25.4, "lon": 55.8},
    ]
    way = {
        "type": "way",
        "id": 4846466,
        "tags": {"highway": "primary"},
        "geometry": vertices,
    }
    feature = adapter._feature_from_element(way, "way/4846466", now, osm_base)

    assert feature.geometry_type == GeometryType.LINESTRING
    assert feature.geometry == {
        "type": "LineString",
        "coordinates": [[v["lon"], v["lat"]] for v in vertices],
    }
    assert feature.lat == 25.2
    assert feature.lon == 55.4


def test_geometry_closed_way_yields_polygon_with_centroid():
    """Inner unit (plan item 2): a CLOSED way (first vertex == last) with
    inline `geometry` maps to POLYGON, not LINESTRING, with lat/lon set to
    the area-weighted centroid (not a vertex) -- pinned against a unit
    square whose centroid is the exact geometric center (0.5, 0.5), which no
    vertex of the square equals."""
    from backend.models import GeometryType
    from backend.sources.overpass import OverpassAdapter

    cfg = _make_overpass_cfg()
    adapter = OverpassAdapter(cfg)
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    osm_base = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)

    square = [
        {"lat": 0.0, "lon": 0.0},
        {"lat": 0.0, "lon": 1.0},
        {"lat": 1.0, "lon": 1.0},
        {"lat": 1.0, "lon": 0.0},
        {"lat": 0.0, "lon": 0.0},  # closes the ring
    ]
    area = {"type": "way", "id": 99, "tags": {"landuse": "port"}, "geometry": square}
    feature = adapter._feature_from_element(area, "way/99", now, osm_base)

    assert feature.geometry_type == GeometryType.POLYGON
    assert feature.geometry == {
        "type": "Polygon",
        "coordinates": [[[v["lon"], v["lat"]] for v in square]],
    }
    assert feature.lat == pytest.approx(0.5)
    assert feature.lon == pytest.approx(0.5)


async def test_osm_base_parsed_to_utc_and_oldest_wins_across_responses(monkeypatch):
    """Inner unit (plan item 3): `osm3s.timestamp_osm_base` is parsed to a
    UTC-aware datetime, and when the six class queries return SIX DISTINCT
    `osm_base` values (as six real, independently-timestamped Overpass
    responses would), the snapshot's `meta.timestamp_source` (and hence every
    feature's `timestamp_source`) is the OLDEST of the six -- the most
    conservative freshness claim (overpass.md "osm_base capture (FR4)"). The
    outer test's single shared fixture answers every class query with the
    identical timestamp, so it can never exercise "oldest wins"; this
    constructs six responses with six distinct timestamps, deliberately
    placing the oldest THIRD (neither first nor last), so a 'first-seen' or
    'last-seen' bug in place of an actual min-reduction would be caught."""
    from backend.sources.base import Region
    from backend.sources.overpass import OverpassAdapter

    monkeypatch.setattr("backend.sources.overpass.asyncio.sleep", _no_op_sleep)

    cfg = _make_overpass_cfg(mirrors=["https://overpass.test/api/interpreter"])
    region = Region(
        id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
    )

    # Six distinct osm_base timestamps, NOT in ascending order; the oldest
    # (2026-07-01) sits third.
    timestamps = [
        "2026-07-05T10:00:00Z",
        "2026-07-03T10:00:00Z",
        "2026-07-01T10:00:00Z",  # oldest -- must win
        "2026-07-04T10:00:00Z",
        "2026-07-06T10:00:00Z",
        "2026-07-02T10:00:00Z",
    ]
    responses = [
        Response(200, json={"osm3s": {"timestamp_osm_base": ts}, "elements": []})
        for ts in timestamps
    ]
    expected_oldest = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)

    async with respx.mock() as respx_mock:
        respx_mock.route(url=cfg.mirrors[0]).mock(side_effect=responses)
        adapter = OverpassAdapter(cfg)
        await adapter.start()
        snapshot = await adapter.fetch(region)
        await adapter.stop()

    assert snapshot.meta.timestamp_source == expected_oldest
    assert snapshot.meta.timestamp_source.tzinfo is not None


async def test_dedup_by_source_id_first_wins_across_classes(monkeypatch):
    """Inner unit (plan item 4): when the SAME `source_id` is returned by two
    different class queries with DIFFERING tags (proving they are genuinely
    two separate wire elements, not one server-side dedup), the adapter
    keeps only the FIRST one seen, in class-query order -- not the last
    (overpass.md "Parsing -> Feature": "keep first")."""
    from backend.sources.base import Region
    from backend.sources.overpass import OverpassAdapter

    monkeypatch.setattr("backend.sources.overpass.asyncio.sleep", _no_op_sleep)

    cfg = _make_overpass_cfg(mirrors=["https://overpass.test/api/interpreter"])
    region = Region(
        id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
    )
    same_ts = "2026-07-05T10:00:00Z"

    first_class_body = {
        "osm3s": {"timestamp_osm_base": same_ts},
        "elements": [
            {
                "type": "way",
                "id": 555,
                "tags": {"seen_in": "first-class-query"},
                "center": {"lat": 1.0, "lon": 2.0},
            }
        ],
    }
    second_class_body = {
        "osm3s": {"timestamp_osm_base": same_ts},
        "elements": [
            {
                "type": "way",
                "id": 555,
                "tags": {"seen_in": "second-class-query"},
                "center": {"lat": 9.0, "lon": 9.0},
            }
        ],
    }
    empty_body = {"osm3s": {"timestamp_osm_base": same_ts}, "elements": []}

    responses = [
        Response(200, json=first_class_body),
        Response(200, json=second_class_body),
        Response(200, json=empty_body),
        Response(200, json=empty_body),
        Response(200, json=empty_body),
        Response(200, json=empty_body),
    ]

    async with respx.mock() as respx_mock:
        respx_mock.route(url=cfg.mirrors[0]).mock(side_effect=responses)
        adapter = OverpassAdapter(cfg)
        await adapter.start()
        snapshot = await adapter.fetch(region)
        await adapter.stop()

    matches = [f for f in snapshot.features if f.source_id == "way/555"]
    assert len(matches) == 1
    assert matches[0].attrs == {"seen_in": "first-class-query"}
    assert matches[0].lat == 1.0
    assert matches[0].lon == 2.0


async def test_only_whitelisted_classes_queried_no_secondary_roads(monkeypatch):
    """Inner unit (plan item 5, §6.3): the six queries actually sent over the
    wire cover the whitelisted highway (`motorway|trunk|primary`) and railway
    (`rail` / `station|yard`) classes and never mention 'secondary' (or
    lower) roads -- inspecting the literal request bodies `fetch()` posts,
    not merely the module constant, so this proves what is actually sent."""
    from backend.sources.base import Region
    from backend.sources.overpass import OverpassAdapter

    monkeypatch.setattr("backend.sources.overpass.asyncio.sleep", _no_op_sleep)

    cfg = _make_overpass_cfg(mirrors=["https://overpass.test/api/interpreter"])
    region = Region(
        id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
    )
    empty_body = {
        "osm3s": {"timestamp_osm_base": "2026-07-05T10:00:00Z"},
        "elements": [],
    }

    async with respx.mock() as respx_mock:
        route = respx_mock.route(url=cfg.mirrors[0]).mock(
            return_value=Response(200, json=empty_body)
        )
        adapter = OverpassAdapter(cfg)
        await adapter.start()
        await adapter.fetch(region)
        await adapter.stop()

    assert route.call_count == 6
    sent_bodies = [
        parse_qs(call.request.content.decode())["data"][0] for call in route.calls
    ]
    combined = "\n".join(sent_bodies)

    assert "secondary" not in combined
    assert 'highway"~"^(motorway|trunk|primary)$"' in combined
    assert 'railway"="rail"' in combined
    assert 'railway"~"^(station|yard)$"' in combined


async def test_429_504_rotates_mirrors_then_exhausts_to_upstream_error():
    """Inner unit (plan item 6): 429/504 responses rotate through
    `cfg.mirrors` with backoff, and once `cfg.max_attempts` is exhausted
    across mirrors, the adapter raises `UpstreamError` -- not a raw
    `httpx.HTTPStatusError`, and not an infinite retry. Two mirrors,
    alternating 429 then 504, prove BOTH statuses trigger rotation (not just
    one), and the exact per-mirror call counts pin the round-robin order."""
    from backend.sources.base import UpstreamError
    from backend.sources.overpass import OverpassAdapter

    mirror_a = "https://mirror-a.test/api/interpreter"
    mirror_b = "https://mirror-b.test/api/interpreter"
    cfg = _make_overpass_cfg(
        mirrors=[mirror_a, mirror_b],
        backoff_base_s=0.001,
        backoff_max_s=0.001,
        max_attempts=3,
    )

    async with respx.mock() as respx_mock:
        route_a = respx_mock.post(mirror_a).mock(return_value=Response(429))
        route_b = respx_mock.post(mirror_b).mock(return_value=Response(504))
        adapter = OverpassAdapter(cfg)
        await adapter.start()

        with pytest.raises(UpstreamError):
            await adapter._fetch_class("way[highway=primary](0,0,1,1);out geom;")

        await adapter.stop()

    # max_attempts=3, round-robin over 2 mirrors: mirror-a, mirror-b, mirror-a.
    assert route_a.call_count == 2
    assert route_b.call_count == 1
    assert route_a.call_count + route_b.call_count == cfg.max_attempts


async def test_malformed_json_raises_parse_error_without_retrying():
    """Inner unit (plan item 6): a 2xx response whose body is not valid JSON
    raises `ParseError` immediately -- NOT treated as a 429/504-style
    retryable condition (a malformed 2xx body is a parse failure, not a
    rate limit), so exactly one request is made, not `cfg.max_attempts` of
    them."""
    from backend.sources.base import ParseError
    from backend.sources.overpass import OverpassAdapter

    mirror = "https://overpass.test/api/interpreter"
    cfg = _make_overpass_cfg(mirrors=[mirror])

    async with respx.mock() as respx_mock:
        route = respx_mock.post(mirror).mock(
            return_value=Response(200, text="not valid json{")
        )
        adapter = OverpassAdapter(cfg)
        await adapter.start()
        with pytest.raises(ParseError):
            await adapter._fetch_class("node[barrier=border_control](0,0,1,1);out;")
        await adapter.stop()

    assert route.call_count == 1


async def test_timeout_rotates_mirrors_then_exhausts_to_upstream_error():
    """Inner unit (plan item 6 addendum -- reviewer-flagged coverage gap,
    issue #15): every attempt across BOTH mirrors raising
    `httpx.TimeoutException` rotates round-robin (mirroring
    `test_429_504_rotates_mirrors_then_exhausts_to_upstream_error` above) and,
    once `cfg.max_attempts` is exhausted across mirrors, raises
    `UpstreamError` -- not an infinite retry, and not a raw
    `httpx.TimeoutException` escaping to the caller.

    NOTE (spec discrepancy, issue #30): `design/specs/overpass.md` is internally
    inconsistent about timeout handling -- one passage groups timeout with
    429/504 as a retryable, rotate-and-backoff condition, another lists
    timeout under "immediate UpstreamError" alongside transport errors. This
    test pins the adapter's AS-BUILT behavior: timeout is retryable (rotate +
    backoff), same as 429/504. It is the interim resolution while #30 is open.
    If the maintainer adjudicates #30 toward immediate-UpstreamError-on-timeout,
    this test must be updated alongside the adapter in that same
    drift-resolution pass.
    """
    from backend.sources.base import UpstreamError
    from backend.sources.overpass import OverpassAdapter

    mirror_a = "https://mirror-a.test/api/interpreter"
    mirror_b = "https://mirror-b.test/api/interpreter"
    cfg = _make_overpass_cfg(
        mirrors=[mirror_a, mirror_b],
        backoff_base_s=0.001,
        backoff_max_s=0.001,
        max_attempts=3,
    )

    async with respx.mock() as respx_mock:
        route_a = respx_mock.post(mirror_a).mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        route_b = respx_mock.post(mirror_b).mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        adapter = OverpassAdapter(cfg)
        await adapter.start()

        with pytest.raises(UpstreamError):
            await adapter._fetch_class("way[highway=primary](0,0,1,1);out geom;")

        await adapter.stop()

    # max_attempts=3, round-robin over 2 mirrors: mirror-a, mirror-b, mirror-a.
    assert route_a.call_count == 2
    assert route_b.call_count == 1
    assert route_a.call_count + route_b.call_count == cfg.max_attempts


async def test_transport_error_raises_immediate_upstream_error_without_retry():
    """Inner unit (plan item 6 addendum -- reviewer-flagged coverage gap,
    issue #15): a connection-level failure (`httpx.ConnectError`, a
    `TransportError` subclass) is NOT treated as retryable the way
    timeout/429/504 are -- it raises `UpstreamError` immediately, with
    exactly one request made (no backoff, no mirror rotation), pinning the
    `except httpx.TransportError` branch in `_fetch_class`."""
    from backend.sources.base import UpstreamError
    from backend.sources.overpass import OverpassAdapter

    mirror = "https://overpass.test/api/interpreter"
    cfg = _make_overpass_cfg(mirrors=[mirror])

    async with respx.mock() as respx_mock:
        route = respx_mock.post(mirror).mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        adapter = OverpassAdapter(cfg)
        await adapter.start()
        with pytest.raises(UpstreamError):
            await adapter._fetch_class("node[barrier=border_control](0,0,1,1);out;")
        await adapter.stop()

    assert route.call_count == 1


async def test_other_5xx_raises_immediate_upstream_error_without_retry():
    """Inner unit (plan item 6 addendum -- reviewer-flagged coverage gap,
    issue #15): a 5xx status that is NOT 429/504 (e.g. 503) is not one of the
    retryable statuses -- it raises `UpstreamError` immediately, with exactly
    one request made (no backoff, no mirror rotation), pinning the
    `status >= 500` (non-429/504) branch in `_fetch_class`."""
    from backend.sources.base import UpstreamError
    from backend.sources.overpass import OverpassAdapter

    mirror = "https://overpass.test/api/interpreter"
    cfg = _make_overpass_cfg(mirrors=[mirror])

    async with respx.mock() as respx_mock:
        route = respx_mock.post(mirror).mock(return_value=Response(503))
        adapter = OverpassAdapter(cfg)
        await adapter.start()
        with pytest.raises(UpstreamError):
            await adapter._fetch_class("node[barrier=border_control](0,0,1,1);out;")
        await adapter.stop()

    assert route.call_count == 1


# ---------------------------------------------------------------------------
# overpass-adapter/02 (issue #16) outer acceptance test ().
# ---------------------------------------------------------------------------
#
# This is the locked behavioral contract for step, transcribed from
# plans/overpass-adapter/02-simplify.md ("Acceptance criterion") and
# design/specs/overpass.md ("Geometry simplification (Douglas-Peucker)"): the
# adapter simplifies LineString/Polygon geometry via shapely Douglas-Peucker
# at `simplify_tolerance_deg` (0.0005 deg) and, if the result still exceeds
# `max_rendered_features` (5000), drops lowest-value features first by the
# deterministic priority primary -> mainline rail -> trunk (shortest-within-
# tier first), NEVER dropping motorway ways or any point anchor. Same input
# must yield the same output (cacheable).
#
# Per the plan's boundary note ("the simplification path inside
# OverpassAdapter.fetch, exercised via the adapter or a directly-called
# internal function") and "no real fixture needed", this test targets a
# directly-callable, pure, module-level function rather than reconstructing a
# 7000-element Overpass HTTP fixture -- there is no behavior here that
# depends on the network/parsing path step already covers.
#
# Name/signature this test requires the developer to provide (test-
# author's plumbing choice; overpass.md fixes the ALGORITHM -- shapely
# Douglas-Peucker at a given tolerance, the 5000 cap, the primary/rail/trunk
# drop priority, shortest-first within a tier, never dropping motorway or
# points -- but does not fix a function name or signature):
#   backend.sources.overpass.simplify_and_cap(
#       features: list[Feature], tolerance: float, max_features: int
#   ) -> list[Feature]
# the developer is expected to also call this from inside `fetch()` (per
# overpass.md, `fetch` returns simplified output) as a separate wiring change;
# this outer test exercises the pure function directly with synthetic data,
# per the plan's boundary note.
#
# Scenario construction (all deterministic, no randomness):
#   - 4 point anchors (border_control, aerodrome, port, station) -- always
#     kept, regardless of the cap.
#   - 496 motorway ways -- always kept, regardless of length or the cap.
#   - 800 primary ways (tier 1) -- fully dropped: alone they don't cover the
#     2000-feature excess (7000 - 5000), so the drop cascades into tier 2.
#   - 700 mainline-rail ways (tier 2) -- fully dropped: primary+rail
#     (800+700=1500) still doesn't cover the excess (2000), so the drop
#     cascades into tier 3.
#   - 5000 trunk ways (tier 3) -- only PARTIALLY dropped: exactly the 500
#     shortest (of 5000) are dropped, the 4500 longest are kept. This is the
#     tier that actually pins "shortest-within-tier-first" as an ORDERING
#     rule, not merely "this tier gets touched" -- tiers 1 and 2 are fully
#     drained either way, so a buggy implementation that ignored length
#     entirely within a tier could still pass those two checks by accident;
#     it cannot pass the trunk-tier check, because that requires excluding
#     precisely the 500 lowest-length trunk ways and no others.
#   Total input = 4 + 496 + 800 + 700 + 5000 = 7000 (matches the plan's
#   Gherkin "7,000 features" and its 5000 cap exactly, so the expected
#   output size is exactly 5000, not merely "<=5000" -- a stronger,
#   fully-pinned assertion than the cap alone would require).
#
# Each way's geometry is a 3-vertex LineString: two endpoints separated by a
# length proportional to its index within its tier (so ascending index means
# ascending length, letting "shortest first" be checked by index), plus one
# midpoint offset perpendicular to the line by 0.0001 deg -- strictly INSIDE
# the 0.0005 deg simplify tolerance, so Douglas-Peucker is expected to drop
# that midpoint (proving "fewer vertices after simplification") while
# changing the line's overall length by a negligible amount (~1e-8 deg,
# many orders of magnitude below the 0.001 deg spacing between distinct
# lengths in a tier) -- so the length-ordering assumption above holds
# whether "geometry length" is measured on the pre- or post-simplification
# geometry.
#
# Assumptions about Feature construction (this author's choices, not
# spec-fixed): `domain=Domain.LAND`, `source="overpass"`; way features use
# `geometry_type=GeometryType.LINESTRING` with a GeoJSON
# `{"type": "LineString", "coordinates": [[lon, lat], ...]}` dict (ADR-11
# order, matching step's parsing); point anchors use
# `geometry_type=GeometryType.POINT` with `geometry=None` (feature-schema.md
# "Points ... geometry=None"). The discriminating tags mirror overpass.md's
# whitelist verbatim: `highway` in {motorway, primary, trunk} for road ways,
# `railway="rail"` for mainline-rail ways (distinct from the point classes'
# `railway` in {station, yard}, which never carries LineString geometry),
# `barrier="border_control"` / `aeroway="aerodrome"` / `harbour="yes"` for
# the three non-rail point anchors.
#
# Red mechanism (), as originally committed: `backend.sources.
# overpass.simplify_and_cap` did not exist yet, so `from backend.sources.
# overpass import simplify_and_cap` inside the test body raised
# `ImportError` (module-level imports elsewhere in this file stayed
# untouched, so collection itself stayed green -- mirroring step's outer
# test). `shapely` was also not yet an installed dependency at that point,
# but this test never imports it directly (vertex counts and lengths are
# computed by inspecting the plain GeoJSON coordinate lists this test itself
# constructs and receives back, not via shapely) -- so no separate shapely
# import guard was needed; the strict-xfail covered the `ImportError`. The
# developer has since built `simplify_and_cap` and wired it into
# `fetch()`; this test now genuinely passes and the xfail marker has been
# removed to finalize the contract.

_SIMPLIFY_TOLERANCE_DEG = 0.0005
_MAX_RENDERED_FEATURES = 5000

_N_POINT_ANCHORS = 4
_N_MOTORWAY = 496
_N_PRIMARY = 800
_N_RAIL = 700
_N_TRUNK = 5000
_TOTAL_FEATURES = _N_POINT_ANCHORS + _N_MOTORWAY + _N_PRIMARY + _N_RAIL + _N_TRUNK


def _simplify_now_and_osm_base():
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    osm_base = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
    return now, osm_base


def _synthetic_line_feature(source_id: str, attrs: dict, length_deg: float, lat_row: float):
    """A 3-vertex LINESTRING way: two endpoints `length_deg` apart, plus one
    midpoint offset 0.0001 deg perpendicular to the line -- strictly inside
    the 0.0005 deg simplify tolerance (see module-level rationale above)."""
    from backend.models import Domain, Feature, FeatureStatus, GeometryType

    now, osm_base = _simplify_now_and_osm_base()
    lon0, lat0 = 0.0, lat_row
    lon1 = lon0 + length_deg
    mid_lon = (lon0 + lon1) / 2.0
    mid_lat = lat_row + 0.0001
    coordinates = [[lon0, lat0], [mid_lon, mid_lat], [lon1, lat0]]
    return Feature(
        domain=Domain.LAND,
        source="overpass",
        source_id=source_id,
        label=None,
        lat=lat0,
        lon=mid_lon,
        geometry_type=GeometryType.LINESTRING,
        geometry={"type": "LineString", "coordinates": coordinates},
        timestamp_source=osm_base,
        timestamp_fetched=now,
        position_age_s=(now - osm_base).total_seconds(),
        status=FeatureStatus.LIVE,
        attrs=dict(attrs),
    )


def _synthetic_point_feature(source_id: str, attrs: dict, lat: float, lon: float):
    from backend.models import Domain, Feature, FeatureStatus, GeometryType

    now, osm_base = _simplify_now_and_osm_base()
    return Feature(
        domain=Domain.LAND,
        source="overpass",
        source_id=source_id,
        label=None,
        lat=lat,
        lon=lon,
        geometry_type=GeometryType.POINT,
        geometry=None,
        timestamp_source=osm_base,
        timestamp_fetched=now,
        position_age_s=(now - osm_base).total_seconds(),
        status=FeatureStatus.LIVE,
        attrs=dict(attrs),
    )


def _build_synthetic_land_features() -> list:
    """Fresh, independent feature list on every call (never shared/mutated
    across calls) -- so the two `simplify_and_cap` invocations in the
    determinism check below are proven independent of any accidental
    aliasing or in-place mutation of a shared input."""
    features = []

    features.append(
        _synthetic_point_feature(
            "node/border-control-1", {"barrier": "border_control"}, 24.0, 54.0
        )
    )
    features.append(
        _synthetic_point_feature(
            "node/aerodrome-1", {"aeroway": "aerodrome"}, 25.0, 55.0
        )
    )
    features.append(
        _synthetic_point_feature("node/port-1", {"harbour": "yes"}, 26.0, 56.0)
    )
    features.append(
        _synthetic_point_feature(
            "node/station-1", {"railway": "station"}, 27.0, 57.0
        )
    )

    for i in range(_N_MOTORWAY):
        features.append(
            _synthetic_line_feature(
                f"way/motorway-{i}", {"highway": "motorway"}, 0.001 * (i + 1), 10.0
            )
        )
    for i in range(_N_PRIMARY):
        features.append(
            _synthetic_line_feature(
                f"way/primary-{i}", {"highway": "primary"}, 0.001 * (i + 1), 20.0
            )
        )
    for i in range(_N_RAIL):
        features.append(
            _synthetic_line_feature(
                f"way/rail-{i}", {"railway": "rail"}, 0.001 * (i + 1), 30.0
            )
        )
    for i in range(_N_TRUNK):
        features.append(
            _synthetic_line_feature(
                f"way/trunk-{i}", {"highway": "trunk"}, 0.001 * (i + 1), 40.0
            )
        )

    return features


def test_simplify_and_cap():
    from backend.models import GeometryType
    from backend.sources.overpass import simplify_and_cap

    # --- Given: a synthetic parsed land feature set of 7,000 features
    # (mixed motorway/trunk/primary roads, mainline rail, and point anchors)
    # exceeding the 5,000 cap ---
    reference_features = _build_synthetic_land_features()
    assert len(reference_features) == _TOTAL_FEATURES == 7000
    reference_by_id = {f.source_id: f for f in reference_features}

    excess = _TOTAL_FEATURES - _MAX_RENDERED_FEATURES
    assert excess > 0
    remaining_after_primary = excess - _N_PRIMARY
    # Primary alone doesn't cover the excess -- the drop must cascade into
    # rail (tier 2), which is exactly what this scenario is built to prove.
    assert remaining_after_primary > 0
    remaining_after_rail = remaining_after_primary - _N_RAIL
    # Primary+rail together still don't cover the excess -- the drop must
    # cascade into trunk (tier 3) too.
    assert remaining_after_rail > 0
    n_trunk_dropped = remaining_after_rail
    # Trunk is only PARTIALLY drained: this is the tier whose drop set
    # actually pins "shortest-within-tier-first" as an ordering rule.
    assert 0 < n_trunk_dropped < _N_TRUNK

    # --- When: simplification runs at tolerance 0.0005 with
    # max_rendered_features 5000 (twice, on independently-built but
    # conceptually identical input, to check determinism) ---
    output_run_1 = simplify_and_cap(
        _build_synthetic_land_features(),
        _SIMPLIFY_TOLERANCE_DEG,
        _MAX_RENDERED_FEATURES,
    )
    output_run_2 = simplify_and_cap(
        _build_synthetic_land_features(),
        _SIMPLIFY_TOLERANCE_DEG,
        _MAX_RENDERED_FEATURES,
    )

    # --- Then: the output has at most 5000 features (exactly 5000, given
    # this scenario's construction) ---
    assert len(output_run_1) <= _MAX_RENDERED_FEATURES
    assert len(output_run_1) == _MAX_RENDERED_FEATURES

    output_ids_1 = {f.source_id for f in output_run_1}

    # --- And: every motorway way and every point anchor is retained ---
    motorway_ids = {f"way/motorway-{i}" for i in range(_N_MOTORWAY)}
    point_anchor_ids = {
        "node/border-control-1",
        "node/aerodrome-1",
        "node/port-1",
        "node/station-1",
    }
    assert motorway_ids <= output_ids_1
    assert point_anchor_ids <= output_ids_1

    # --- And: dropped features follow the priority primary -> rail ->
    # trunk, shortest-within-tier first ---
    primary_ids = {f"way/primary-{i}" for i in range(_N_PRIMARY)}
    rail_ids = {f"way/rail-{i}" for i in range(_N_RAIL)}
    # Tier 1 (primary) is fully drained before tier 2 is touched at all.
    assert primary_ids.isdisjoint(output_ids_1)
    # Tier 2 (rail) is fully drained too, before tier 3 is touched.
    assert rail_ids.isdisjoint(output_ids_1)
    # Tier 3 (trunk): exactly the shortest `n_trunk_dropped` (ascending
    # index == ascending length) are dropped; the rest are kept.
    expected_dropped_trunk_ids = {f"way/trunk-{i}" for i in range(n_trunk_dropped)}
    expected_retained_trunk_ids = {
        f"way/trunk-{i}" for i in range(n_trunk_dropped, _N_TRUNK)
    }
    assert expected_dropped_trunk_ids.isdisjoint(output_ids_1)
    assert expected_retained_trunk_ids <= output_ids_1

    # --- And: running it twice on the same input yields identical feature
    # sets (deterministic, cacheable) ---
    dump_1 = {f.source_id: f.model_dump() for f in output_run_1}
    dump_2 = {f.source_id: f.model_dump() for f in output_run_2}
    assert dump_1 == dump_2

    # --- And: simplified LineStrings have strictly fewer vertices than
    # their (3-vertex) inputs; points are untouched ---
    for line_id in motorway_ids | expected_retained_trunk_ids:
        feature = next(f for f in output_run_1 if f.source_id == line_id)
        assert feature.geometry_type == GeometryType.LINESTRING
        original_vertex_count = len(reference_by_id[line_id].geometry["coordinates"])
        simplified_vertex_count = len(feature.geometry["coordinates"])
        assert simplified_vertex_count < original_vertex_count

    for point_id in point_anchor_ids:
        feature = next(f for f in output_run_1 if f.source_id == point_id)
        assert feature.geometry_type == GeometryType.POINT


# ---------------------------------------------------------------------------
# overpass-adapter/02 (issue #16) inner units ().
# ---------------------------------------------------------------------------
#
# Authored against the now-built `simplify_and_cap` (plans/overpass-adapter/
# 02-simplify.md, "Inner loop -- initial unit test list"), each isolating a
# single behaviour the 7,000-feature outer test exercises only at scale --
# small, fully-named synthetic sets here so every survivor/drop is asserted
# explicitly rather than via subset checks.


def test_simplify_reduces_vertex_count_and_points_pass_through_untouched():
    """Inner unit (plan item 1): shapely `simplify(tolerance=0.0005,
    preserve_topology=False)` reduces the vertex count of a near-collinear-
    midpoint LineString (the midpoint's 0.0001 deg perpendicular offset is
    well inside the 0.0005 deg tolerance, so Douglas-Peucker drops it), while
    a POINT feature's geometry stays `None` (untouched) -- both under the
    cap, so no drop logic runs at all here, isolating simplification itself
    from the drop/cap behaviour covered by other inner tests below."""
    from backend.models import GeometryType
    from backend.sources.overpass import simplify_and_cap

    line_feature = _synthetic_line_feature(
        "way/motorway-simplify-1", {"highway": "motorway"}, 0.01, 10.0
    )
    point_feature = _synthetic_point_feature(
        "node/anchor-simplify-1", {"barrier": "border_control"}, 24.0, 54.0
    )

    output = simplify_and_cap(
        [line_feature, point_feature], _SIMPLIFY_TOLERANCE_DEG, max_features=10
    )
    output_by_id = {f.source_id: f for f in output}

    simplified_line = output_by_id["way/motorway-simplify-1"]
    assert simplified_line.geometry_type == GeometryType.LINESTRING
    original_vertex_count = len(line_feature.geometry["coordinates"])
    simplified_vertex_count = len(simplified_line.geometry["coordinates"])
    assert simplified_vertex_count < original_vertex_count
    assert simplified_vertex_count == 2  # the near-collinear midpoint is dropped

    simplified_point = output_by_id["node/anchor-simplify-1"]
    assert simplified_point.geometry_type == GeometryType.POINT
    assert simplified_point.geometry is None


def test_under_cap_nothing_dropped_only_simplified():
    """Inner unit (plan item 2): when the input count does not exceed
    `max_features`, every feature survives -- only geometry simplification
    applies, no drop logic runs -- pinned with `max_features` strictly
    greater than the input count and every input source_id checked present
    in the output."""
    from backend.sources.overpass import simplify_and_cap

    features = [
        _synthetic_point_feature(
            "node/anchor-1", {"barrier": "border_control"}, 24.0, 54.0
        ),
        _synthetic_line_feature("way/primary-1", {"highway": "primary"}, 0.002, 20.0),
        _synthetic_line_feature("way/trunk-1", {"highway": "trunk"}, 0.001, 40.0),
    ]

    output = simplify_and_cap(features, _SIMPLIFY_TOLERANCE_DEG, max_features=10)

    assert {f.source_id for f in output} == {f.source_id for f in features}
    assert len(output) == len(features)


def test_over_cap_drops_primary_then_rail_before_trunk_never_motorway_or_point():
    """Inner unit (plan item 3): over the cap, the primary tier (tier 1) is
    fully drained before the rail tier (tier 2) is touched at all, and a
    motorway way / a point anchor are never eligible for drop regardless of
    length -- a small, fully-named six-feature set where every surviving and
    every dropped source_id is asserted explicitly, not merely checked as a
    subset of a much larger scenario."""
    from backend.sources.overpass import simplify_and_cap

    point = _synthetic_point_feature(
        "node/anchor-1", {"aeroway": "aerodrome"}, 25.0, 55.0
    )
    motorway = _synthetic_line_feature(
        "way/motorway-1", {"highway": "motorway"}, 0.0001, 10.0
    )
    primary_a = _synthetic_line_feature(
        "way/primary-a", {"highway": "primary"}, 0.001, 20.0
    )
    primary_b = _synthetic_line_feature(
        "way/primary-b", {"highway": "primary"}, 0.002, 20.0
    )
    rail = _synthetic_line_feature("way/rail-1", {"railway": "rail"}, 0.001, 30.0)
    trunk = _synthetic_line_feature("way/trunk-1", {"highway": "trunk"}, 0.001, 40.0)

    features = [point, motorway, primary_a, primary_b, rail, trunk]
    # excess = 6 - 3 = 3: the primary tier (2 features) fully drains, then 1
    # more comes from the rail tier (its only member) -- trunk is never
    # touched, and motorway/point are never eligible regardless.
    output = simplify_and_cap(features, _SIMPLIFY_TOLERANCE_DEG, max_features=3)

    output_ids = {f.source_id for f in output}
    assert output_ids == {"node/anchor-1", "way/motorway-1", "way/trunk-1"}


def test_within_tier_ascending_length_drops_shortest_first():
    """Inner unit (plan item 4): within a single drop tier, ascending
    geometry length is the drop order -- the shortest is dropped first, the
    longest survives -- pinned against a single-tier (trunk-only) set of
    four distinct lengths so no cross-tier priority can mask the ordering
    (unlike the outer test's 5000-trunk-way scenario, every source_id here
    is individually named)."""
    from backend.sources.overpass import simplify_and_cap

    trunk_short = _synthetic_line_feature(
        "way/trunk-short", {"highway": "trunk"}, 0.001, 40.0
    )
    trunk_mid = _synthetic_line_feature(
        "way/trunk-mid", {"highway": "trunk"}, 0.002, 40.0
    )
    trunk_long = _synthetic_line_feature(
        "way/trunk-long", {"highway": "trunk"}, 0.003, 40.0
    )
    trunk_longest = _synthetic_line_feature(
        "way/trunk-longest", {"highway": "trunk"}, 0.004, 40.0
    )

    features = [trunk_short, trunk_mid, trunk_long, trunk_longest]
    output = simplify_and_cap(features, _SIMPLIFY_TOLERANCE_DEG, max_features=2)

    output_ids = {f.source_id for f in output}
    assert output_ids == {"way/trunk-long", "way/trunk-longest"}


def test_deterministic_two_runs_on_equivalent_input_yield_identical_output():
    """Inner unit (plan item 5): two independently-constructed but
    conceptually equivalent over-cap feature lists (fresh objects each call,
    no shared mutable state between runs) yield byte-for-byte identical
    output across two calls -- a small-scale, isolated mirror of the outer
    test's determinism check."""
    from backend.sources.overpass import simplify_and_cap

    def build():
        return [
            _synthetic_point_feature("node/anchor-1", {"harbour": "yes"}, 26.0, 56.0),
            _synthetic_line_feature(
                "way/motorway-1", {"highway": "motorway"}, 0.0005, 10.0
            ),
            _synthetic_line_feature(
                "way/primary-1", {"highway": "primary"}, 0.001, 20.0
            ),
            _synthetic_line_feature(
                "way/primary-2", {"highway": "primary"}, 0.002, 20.0
            ),
        ]

    output_1 = simplify_and_cap(build(), _SIMPLIFY_TOLERANCE_DEG, max_features=3)
    output_2 = simplify_and_cap(build(), _SIMPLIFY_TOLERANCE_DEG, max_features=3)

    dump_1 = {f.source_id: f.model_dump() for f in output_1}
    dump_2 = {f.source_id: f.model_dump() for f in output_2}
    assert dump_1 == dump_2


# ---------------------------------------------------------------------------
# overpass-adapter/02 (issue #16) reviewer-flagged coverage gaps.
# ---------------------------------------------------------------------------
#
# Two cheap gaps left unexercised by the outer test and the inner units
# above: (1) every existing test that builds a POLYGON feature
# (`test_geometry_closed_way_yields_polygon_with_centroid`) exercises only
# the parsing path (step), never `simplify_and_cap` -- a POLYGON with a
# `highway`/`railway` tag that would make it drop-tier-eligible is also
# unrepresented in practice, but here the polygon is untagged (hence
# undroppable via `_drop_tier`'s default), which isolates the *simplify*
# branch for Polygon geometry (Douglas-Peucker on a closed ring) from any
# drop/cap interaction; and (2) the `len(simplified) <= max_features`
# boundary condition itself (count == cap exactly) has no dedicated test --
# every existing over-cap test uses a count strictly greater than the cap.


def _synthetic_polygon_feature(source_id: str, attrs: dict, ring: list[list[float]]):
    """A closed-ring POLYGON way (`ring[0] == ring[-1]`, `[lon, lat]` pairs,
    Overpass `out geom` -> parsed-Polygon shape, mirroring
    `test_geometry_closed_way_yields_polygon_with_centroid` above) --
    author's plumbing choice for exercising `_simplify_geometry`'s
    Polygon branch directly (no existing helper in this file builds a
    Polygon feature for the `simplify_and_cap` path)."""
    from backend.models import Domain, Feature, FeatureStatus, GeometryType

    now, osm_base = _simplify_now_and_osm_base()
    lons = [p[0] for p in ring[:-1]]
    lats = [p[1] for p in ring[:-1]]
    return Feature(
        domain=Domain.LAND,
        source="overpass",
        source_id=source_id,
        label=None,
        lat=sum(lats) / len(lats),
        lon=sum(lons) / len(lons),
        geometry_type=GeometryType.POLYGON,
        geometry={"type": "Polygon", "coordinates": [ring]},
        timestamp_source=osm_base,
        timestamp_fetched=now,
        position_age_s=(now - osm_base).total_seconds(),
        status=FeatureStatus.LIVE,
        attrs=dict(attrs),
    )


def test_polygon_geometry_simplified_intact_and_still_closed():
    """Reviewer-flagged gap 1 (issue #16): a POLYGON feature's geometry runs
    through the SAME Douglas-Peucker `_simplify_geometry` path as LineString
    geometry (`simplify_and_cap`'s `geometry_type in (LINESTRING, POLYGON)`
    branch) -- no existing test drives a Polygon through `simplify_and_cap`
    at all. The ring here has a genuinely removable near-collinear vertex
    (0.0001 deg perpendicular deviation, strictly inside the 0.0005 deg
    tolerance -- the same margin `_synthetic_line_feature` uses above) so the
    vertex-count assertion is real, not vacuous; a companion polygon (chosen
    below) plus the point/motorway/etc. helpers keep total input count under
    `max_features`, isolating the simplify path from any drop-cap logic."""
    from backend.sources.overpass import simplify_and_cap

    # A rectangle with one edge-midpoint nudged 0.0001 deg off the straight
    # line between its neighbors -- collinear enough to be simplified away
    # at tolerance 0.0005, but the ring is otherwise an ordinary closed
    # quadrilateral (first == last coordinate).
    ring = [
        [0.0, 0.0],
        [1.0, 0.0001],  # near-collinear between [0,0] and [2,0] -- removable
        [2.0, 0.0],
        [2.0, 2.0],
        [0.0, 2.0],
        [0.0, 0.0],  # closes the ring
    ]
    polygon = _synthetic_polygon_feature(
        "way/polygon-1", {"landuse": "port"}, ring
    )
    # A couple of unrelated features alongside it, well under any realistic
    # cap, so nothing here is at risk of being drop-cap-eligible.
    companion_point = _synthetic_point_feature(
        "node/anchor-1", {"harbour": "yes"}, 26.0, 56.0
    )
    companion_line = _synthetic_line_feature(
        "way/motorway-1", {"highway": "motorway"}, 0.002, 10.0
    )

    output = simplify_and_cap(
        [polygon, companion_point, companion_line],
        _SIMPLIFY_TOLERANCE_DEG,
        max_features=10,
    )
    output_by_id = {f.source_id: f for f in output}
    assert set(output_by_id) == {
        "way/polygon-1",
        "node/anchor-1",
        "way/motorway-1",
    }

    simplified_geometry = output_by_id["way/polygon-1"].geometry

    # --- Still a Polygon with the same nesting depth: a list of rings, each
    # a list of [lon, lat] pairs (not flattened, not a bare LineString) ---
    assert simplified_geometry["type"] == "Polygon"
    coordinates = simplified_geometry["coordinates"]
    assert isinstance(coordinates, list)
    assert len(coordinates) == 1  # one ring, no holes
    simplified_ring = coordinates[0]
    assert isinstance(simplified_ring, list)

    # --- The ring is still closed after Douglas-Peucker ---
    assert simplified_ring[0] == simplified_ring[-1]

    # --- Coordinates are plain [lon, lat] numeric pairs -- plain lists (not
    # shapely tuples), so `==` against list literals holds ---
    for point in simplified_ring:
        assert type(point) is list
        assert len(point) == 2
        lon, lat = point
        assert isinstance(lon, (int, float))
        assert isinstance(lat, (int, float))

    # --- Vertex count did not increase, and the removable near-collinear
    # point is genuinely gone (simplification actually did something, not a
    # vacuous no-op) ---
    original_vertex_count = len(ring)
    simplified_vertex_count = len(simplified_ring)
    assert simplified_vertex_count <= original_vertex_count
    assert simplified_vertex_count < original_vertex_count
    assert [1.0, 0.0001] not in simplified_ring


def test_exact_at_cap_boundary_nothing_dropped():
    """Reviewer-flagged gap 2 (issue #16): `simplify_and_cap`'s cap check is
    `len(simplified) <= max_features: return simplified` -- every existing
    over-cap test uses an input count strictly GREATER than the cap, leaving
    the `==` boundary itself (count exactly equal to the cap) unexercised.
    Five features -- one of each kind (point anchor, motorway, and all three
    droppable tiers) -- called with `max_features` exactly equal to the
    input count: the `<=` boundary must keep everything, including the
    normally-droppable primary/rail/trunk features, proving the boundary
    check itself (not merely "some cap logic exists") is `<=` and not `<`."""
    from backend.sources.overpass import simplify_and_cap

    features = [
        _synthetic_point_feature(
            "node/anchor-1", {"barrier": "border_control"}, 24.0, 54.0
        ),
        _synthetic_line_feature("way/motorway-1", {"highway": "motorway"}, 0.001, 10.0),
        _synthetic_line_feature("way/primary-1", {"highway": "primary"}, 0.001, 20.0),
        _synthetic_line_feature("way/rail-1", {"railway": "rail"}, 0.001, 30.0),
        _synthetic_line_feature("way/trunk-1", {"highway": "trunk"}, 0.001, 40.0),
    ]
    max_features = len(features)
    assert max_features == 5

    output = simplify_and_cap(features, _SIMPLIFY_TOLERANCE_DEG, max_features)

    assert len(output) == max_features
    assert {f.source_id for f in output} == {f.source_id for f in features}


def test_one_over_cap_boundary_drops_exactly_one_shortest_primary():
    """Companion to the exact-at-cap test above: the SAME five-feature set
    plus one extra droppable primary (six features total, `max_features`
    still 5 -- one past the boundary) drops exactly one feature -- the
    shortest primary -- while every other feature (including the other
    primary, and every protected feature) survives. This shows the `<=`
    boundary above isn't accidentally permissive past the cap: crossing it
    by exactly one triggers exactly one drop, no more."""
    from backend.sources.overpass import simplify_and_cap

    point = _synthetic_point_feature(
        "node/anchor-1", {"barrier": "border_control"}, 24.0, 54.0
    )
    motorway = _synthetic_line_feature(
        "way/motorway-1", {"highway": "motorway"}, 0.001, 10.0
    )
    primary_shorter = _synthetic_line_feature(
        "way/primary-shorter", {"highway": "primary"}, 0.001, 20.0
    )
    primary_longer = _synthetic_line_feature(
        "way/primary-longer", {"highway": "primary"}, 0.002, 20.0
    )
    rail = _synthetic_line_feature("way/rail-1", {"railway": "rail"}, 0.001, 30.0)
    trunk = _synthetic_line_feature("way/trunk-1", {"highway": "trunk"}, 0.001, 40.0)

    features = [point, motorway, primary_shorter, primary_longer, rail, trunk]
    max_features = 5
    assert len(features) == max_features + 1

    output = simplify_and_cap(features, _SIMPLIFY_TOLERANCE_DEG, max_features)

    assert len(output) == max_features
    output_ids = {f.source_id for f in output}
    assert output_ids == {
        "node/anchor-1",
        "way/motorway-1",
        "way/primary-longer",
        "way/rail-1",
        "way/trunk-1",
    }
