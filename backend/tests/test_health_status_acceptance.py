"""Locked outer acceptance test for health-status slice 01 (issue #6).

Given the backend.health module exists with a health_status() function
When  health_status() is called with no arguments
Then  it returns a dict with exactly the two keys "status" and "service"
And   status == "ok" and service == "zij"

This is the behavioral contract (DEC-1). It is authored and committed red by
the test-author before any implementation exists, guarded here by a strict
xfail (DEC-33). Do not weaken this assertion and do not remove the xfail
marker until the implementer has made it genuinely pass.
"""

import pytest


@pytest.mark.xfail(reason="health_status not yet implemented", strict=True)
def test_health_status_returns_exact_contract_dict():
    from backend.health import health_status

    result = health_status()

    assert result == {"status": "ok", "service": "zij"}
