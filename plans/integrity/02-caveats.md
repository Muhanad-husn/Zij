# Slice 02: Integrity caveats — static per-layer text + active-flag counts

- **Feature:** integrity
- **Slice slug:** caveats
- **Issue:** #44
- **Branch:** feat/integrity/02-caveats
- **Project directory:** `backend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

Provide the static `CAVEATS: dict[Domain, list[str]]` — the verbatim per-domain caveat
bullets from `design/specs/integrity.md` (air: ADS-B/Mode-S coverage, transponder-silent
military, Mode-S position gaps; marine: uneven terrestrial coverage, dark-fleet AIS silence,
GPS-jamming ghost tracks; land: mapped-state-not-telemetry, `osm_base` not ground truth,
absence≠absent) — plus a helper that counts active `integrity_flags` across a snapshot's
features. Together these back `GET /api/layers/{domain}/caveats` (static bullets + live
`active_flags` counts). The panel's non-dismissibility is a frontend property, not here.

## INVEST check

- **Independent:** static data + a pure counter over `Feature`s; no other v1 module needed.
- **Valuable:** the FR9 caveat content the persistent panel renders — "what this layer cannot show."
- **Small:** one dict constant, one counting helper.
- **Testable:** pytest unit — verbatim text match + counts over a hand-built snapshot.

## Acceptance criterion (outer loop — the failing test)

```gherkin
Given the integrity module
When  CAVEATS[domain] is read for air, marine, and land
Then  each returns the exact caveat bullet list from the spec (verbatim, not paraphrased)
When  the active-flag counter runs over a snapshot with flagged features
Then  it returns {spoof_suspect_on_land: n, implausible_kinematics: m} counted from those features
And   an empty (or unflagged) snapshot yields zero counts for every flag
```

- **Boundary:** `CAVEATS` constant + the active-flag counting helper.
- **test type:** pytest unit; **file:** `backend/tests/test_integrity.py`.

## Inner loop — initial unit test list

- [ ] `CAVEATS[Domain.AIR]` / `[MARINE]` / `[LAND]` match the spec bullets verbatim.
- [ ] Counter tallies each `IntegrityFlag` value separately across a mixed snapshot.
- [ ] Empty snapshot / features with no flags → all-zero counts.
- [ ] A feature carrying both flags increments both counters.

## Out of scope (deferred)

- The HTTP `GET /api/layers/{domain}/caveats` endpoint itself (api-core/04).
- Flag computation (slice 01); panel rendering / non-dismissibility (frontend/05).

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner units covered; `uv run pytest`, `uv run ruff` green; refactor on green.
- [ ] Evidence: pytest transcript (verbatim-text + count assertions). CI green; PR via `safe-pr`.

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: none.
