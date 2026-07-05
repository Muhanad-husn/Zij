# Slice 01: Health-status helper returns the fixed contract dict

- **Feature:** health-status
- **Slice slug:** health-status
- **Issue:** #6
- **Branch:** feat/health-status/01-health-status
- **Project directory:** `.`
- **Status:** ◐ in-progress
- **Walking skeleton?** no

> **Zij roles (DEC-1):** the **test-author** transcribes the Acceptance criterion below into the **locked outer acceptance test** and commits it **red** before any implementation (via `@pytest.mark.xfail(strict=True)` so the red commit passes the tests-green gate, DEC-33); the **implementer** then drives the inner unit list to green and **may not edit the outer test or `design/` specs**. When the behavior passes, the strict-xfail flips the suite red — the **test-author** removes the marker to land the final green commit. If the locked test looks wrong mid-build, raise a `spec-drift` issue — never edit it to force green.

## Goal — the minimum testable behaviour

Calling `backend.health.health_status()` with no arguments returns the exact contract
dict `{"status": "ok", "service": "zij"}`. It gives the pipeline one trivial,
verifiable behavior to carry from idea to a reviewed PR.

## INVEST check

- **Independent:** a standalone pure function; depends on nothing and blocks nothing.
- **Valuable:** validates that the whole build machine (roles + gates + harness) works end to end — the value is the proof, not the function.
- **Small:** one function, one return statement; minutes of work.
- **Testable:** one acceptance test asserting the exact dict; three inner unit checks.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given the backend.health module exists with a health_status() function
When  health_status() is called with no arguments
Then  it returns a dict with exactly the two keys "status" and "service"
And   status == "ok" and service == "zij"
```

- **Boundary / endpoint:** the public module function `backend.health.health_status` (deliberate dry-run exception to the real-endpoint rule — see README "Notes"; a real slice would use a FastAPI route/CLI).
- **e2e test type:** integration test calling the public module boundary (no FastAPI route — Playwright N/A; non-web transcript evidence).
- **e2e test file (planned):** `backend/tests/test_health_status_acceptance.py`

## Inner loop — initial unit test list

- [ ] `health_status()` returns a `dict` (not `None`/str/other).
- [ ] The returned dict has exactly the two keys `status` and `service` — no extras, none missing.
- [ ] The values are the fixed strings `ok` and `zij` respectively.

## Out of scope for this slice (deferred)

- FastAPI route / HTTP endpoint registration; wiring into `main.py`.
- Runtime deps beyond the standard library; env/config loading.
- Persistence, logging, or any side effect; external-service integration.

## Definition of done

- [ ] Outer acceptance test authored by **test-author** and committed **RED before any implementation** (DEC-1 ordering invariant; strict-xfail per DEC-33).
- [ ] Acceptance/e2e test seen to fail for the right reason, now GREEN (implementer drove inner cycles; outer test unchanged; marker removed by test-author on green).
- [ ] All seeded unit behaviours covered; full suite passes locally (`uv run pytest`); lint clean (`uv run ruff check`).
- [ ] Refactor pass complete (no duplication, clear names) with the bar green.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Evidence collected and PR opened into `main` (`safe-pr`).

## Status / progress log

- 2026-07-05 planned. Issue #6 filed; branch to be cut off `main`.
- 2026-07-05 red: test-author committed the outer acceptance test strict-xfail (`59496da`), `1 xfailed` → exit 0.
- 2026-07-05 green: implementer wrote `backend/health.py` (left uncommitted at XPASS); test-author removed the marker and landed the green commit (`8adc767`), `2 passed`, ruff clean.
- 2026-07-05 reviewed: reviewer two-stage DONE, no blocking findings.
- 2026-07-05 CI: `.github/workflows/ci.yml` added (`tdd-ci`). Evidence collected under `docs/tdd-evidence/`.
- 2026-07-05 PR: `safe-pr` opened PR #7 into `main`. Awaiting founder merge (Checkpoint 6).
