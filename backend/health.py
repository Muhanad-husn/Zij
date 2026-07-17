"""Health-status helper: a pure, dependency-free status contract.

The health-status feature (issue #6). No side effects, no runtime
dependencies beyond the standard library.
"""


def health_status() -> dict[str, str]:
    """Return the fixed health-status contract dict."""
    return {"status": "ok", "service": "zij"}
