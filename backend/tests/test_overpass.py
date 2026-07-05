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

It is authored and committed red by the author before any
implementation exists (strict xfail, ): `backend/sources/overpass.py`
does not exist yet, so importing `OverpassAdapter` inside the test body (not
at module level, so collection itself stays green) raises `ModuleNotFoundError`
-- xfail's default (no `raises=` narrowing) treats any exception as the
expected failure, so this fails for that reason and xfails cleanly under the
tests-green gate.

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
from datetime import datetime
from pathlib import Path

import pytest
import respx
from httpx import Response

FIXTURES_DIR = Path(__file__).parent / "fixtures"
OVERPASS_FIXTURE = FIXTURES_DIR / "overpass_hormuz.json"

# way/4846466 -- highway=primary, "Al Maktoum Bridge" (Dubai), 6-vertex geometry.
PRIMARY_WAY_ID = 4846466
# node/2109558996 -- harbour=yes, "Al Hamriya Port" (Dubai), bare node.
PORT_NODE_ID = 2109558996


@pytest.mark.xfail(reason="overpass fetch not yet implemented", strict=True)
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
