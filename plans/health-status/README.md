# Feature: Health-status helper (Phase-6 dry-run throwaway)

A pure, dependency-free `health_status()` helper whose only purpose is to exercise
the full agentic build pipeline end to end (spec → red outer test → implementer →
review → PR). It is **not** a real product feature and pulls in no runtime deps.

- **Slug:** health-status
- **Created:** 2026-07-05
- **Status:** done (PR prepared for Checkpoint 6)
- **New system?** no
- **Project directory:** `.`

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Goal (one line) | Status | PR |
|---|-------|-----------------|--------|----|
| 01 | [health-status](01-health-status.md) | `health_status()` returns the fixed contract dict `{"status":"ok","service":"zij"}` | ✅ done | [#7](https://github.com/Muhanad-husn/Zij/pull/7) |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## Out of scope (whole feature)

- FastAPI route / HTTP endpoint (would pull in a runtime dep deferred to the v0 sprint, DEC-12).
- Wiring into `main.py`, config/env loading, persistence, logging, or any side effect.
- Any external-service integration.

## Notes / open questions

- **Deliberate boundary exception:** the `tdd-plan` template requires the acceptance
  boundary to be a real external endpoint (HTTP/CLI), never an internal function. This
  throwaway intentionally uses the public module function `backend.health.health_status`
  as the boundary, because standing up a real FastAPI route would front-run the runtime
  dependency the design defers (DEC-12). Acceptable **only** because this slice exists
  solely to validate the pipeline; real slices must use a real endpoint.
- **Fate of `backend/health.py` (founder decides at Checkpoint 6):** this is a
  throwaway pipeline probe. Two clean options — (a) **merge** the PR and keep it as a
  harmless, tested first backend module (it imports nothing and is imported only by its
  test, so it violates no `STRUCTURE.md` boundary); or (b) **decline the merge** and
  discard the branch, treating the prepared-and-reviewed PR itself as the proof the
  machine works. Either is fine; the dry run's deliverable is the green, reviewed PR,
  not the module.
