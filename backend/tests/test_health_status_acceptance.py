"""Locked outer acceptance test for health-status slice 01 (issue #6).

Given the backend.health module exists with a health_status() function
When  health_status() is called with no arguments
Then  it returns a dict with exactly the two keys "status" and "service"
And   status == "ok" and service == "zij"

This is the behavioral contract (DEC-1). It was authored and committed red by
the test-author before any implementation existed, guarded by a strict xfail
(DEC-33). The implementer has since made it genuinely pass; the xfail marker
has been removed to finalize the contract.
"""

from backend.health import health_status


def test_health_status_returns_exact_contract_dict():
    result = health_status()

    assert result == {"status": "ok", "service": "zij"}
