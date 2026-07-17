"""Acceptance test for the committed Hormuz OpenSky/Overpass payload shape
(issue #12).

Given the committed fixtures
      backend/tests/fixtures/opensky_states_all_hormuz.json and
      backend/tests/fixtures/overpass_hormuz.json
When  they are loaded as JSON in a test
Then  the OpenSky fixture has top-level "time" (int) and "states" (list),
      with each state vector 17 elements
And   the Overpass fixture has "osm3s.timestamp_osm_base" and a non-empty
      "elements" list covering node and way types

This acceptance test covers the committed fixture shape: OpenSky
time/states/17-element vectors, Overpass osm3s.timestamp_osm_base ISO-parseable
to UTC, and a non-empty elements list covering node and way types. It was
written test-first and committed red, as an xfail, before the fixtures
existed. `scripts/fetch_fixtures.py` has since been run and both fixture files
committed; the xfail marker was removed and this test now genuinely passes.
"""

import json
from datetime import datetime
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
OPENSKY_FIXTURE = FIXTURES_DIR / "opensky_states_all_hormuz.json"
OVERPASS_FIXTURE = FIXTURES_DIR / "overpass_hormuz.json"


def test_fixtures_shape():
    # --- Given: the committed fixtures exist on disk ---
    assert OPENSKY_FIXTURE.exists(), f"missing fixture: {OPENSKY_FIXTURE}"
    assert OVERPASS_FIXTURE.exists(), f"missing fixture: {OVERPASS_FIXTURE}"

    # --- When: they are loaded as JSON ---
    opensky = json.loads(OPENSKY_FIXTURE.read_text(encoding="utf-8"))
    overpass = json.loads(OVERPASS_FIXTURE.read_text(encoding="utf-8"))

    # --- Then: the OpenSky fixture has top-level "time" (int) and "states"
    # (list), with each state vector 17 elements ---
    assert isinstance(opensky["time"], int)
    assert isinstance(opensky["states"], list)
    assert len(opensky["states"]) > 0
    for state_vector in opensky["states"]:
        assert len(state_vector) == 17

    # --- And: the Overpass fixture has "osm3s.timestamp_osm_base" and a
    # non-empty "elements" list covering node and way types ---
    timestamp_osm_base = overpass["osm3s"]["timestamp_osm_base"]
    parsed = datetime.fromisoformat(timestamp_osm_base.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0

    elements = overpass["elements"]
    assert isinstance(elements, list)
    assert len(elements) > 0
    element_types = {element["type"] for element in elements}
    assert "node" in element_types
    assert "way" in element_types
