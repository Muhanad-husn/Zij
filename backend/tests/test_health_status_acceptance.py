"""Acceptance test for health-status (issue #6).

Given the backend.health module exists with a health_status() function
When  health_status() is called with no arguments
Then  it returns a dict with exactly the two keys "status" and "service"
And   status == "ok" and service == "zij"

It was written test-first and committed red, as an xfail, before any
implementation existed; the xfail marker was removed once the suite went
green.
"""

from backend.health import health_status


def test_health_status_returns_exact_contract_dict():
    result = health_status()

    assert result == {"status": "ok", "service": "zij"}
