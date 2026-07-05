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
design/contracts/adapter-interface.md and backend/models.py. Geometry
simplification (Douglas-Peucker, the <=5000 cap) is explicitly out of scope
for this slice (deferred to step) and is NOT asserted here: this test
pins the raw, unsimplified vertex list straight off the fixture's `geometry`
array for the chosen way.

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
list of `{"lat":..., "lon":...}` objects (Overpass `out geom` shape). Node
`2109558996` carries `tags.harbour == "yes"` (Al Hamriya Port) with direct
top-level `lat`/`lon` (a bare node, not an `out center` result -- the plan's
"port/aerodrome node" wording covers this: any node-shaped element from the
whitelisted point classes, of which `harbour` is one, per overpass.md
query #3).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

import pytest
import respx
from httpx import Response

FIXTURES_DIR = Path(__file__).parent / "fixtures"
OVERPASS_FIXTURE = FIXTURES_DIR / "overpass_hormuz.json"

# way/4846466 -- highway=primary, "Al Maktoum Bridge" (Dubai), 6-vertex geometry.
PRIMARY_WAY_ID = 4846466
# node/2109558996 -- harbour=yes, "Al Hamriya Port" (Dubai), bare node.
PORT_NODE_ID = 2109558996


async def test_fetch_hormuz_land():
    # --- Given: the committed fixture, inspected for the two concrete
    # elements this test pins its assertions to ---
    fixture_body = json.loads(OVERPASS_FIXTURE.read_text(encoding="utf-8"))
    elements_by_key = {
        (element["type"], element["id"]): element
        for element in fixture_body["elements"]
    }
    primary_way = elements_by_key[("way", PRIMARY_WAY_ID)]
    port_node = elements_by_key[("node", PORT_NODE_ID)]
    assert primary_way["tags"]["highway"] == "primary"
    assert port_node["tags"].get("harbour") == "yes"

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

    # --- And: a primary-road way -> LINESTRING, [lon,lat] order, attrs
    # carrying the OSM tags verbatim ---
    primary_matches = [
        f for f in snapshot.features if f.source_id == f"way/{PRIMARY_WAY_ID}"
    ]
    assert len(primary_matches) == 1
    primary_feature = primary_matches[0]
    assert primary_feature.geometry_type == GeometryType.LINESTRING
    expected_coordinates = [
        [vertex["lon"], vertex["lat"]] for vertex in primary_way["geometry"]
    ]
    assert primary_feature.geometry == {
        "type": "LineString",
        "coordinates": expected_coordinates,
    }
    assert primary_feature.attrs == primary_way["tags"]

    # --- And: a port node -> POINT (geometry=None, lat/lon set) ---
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
    # queries appears exactly once -- deduped, not concatenated six-fold ---
    assert len(primary_matches) == 1
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
