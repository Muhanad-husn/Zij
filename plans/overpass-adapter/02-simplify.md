# Slice 02: Douglas-Peucker simplification + deterministic ≤5,000 drop priority

- **Feature:** overpass-adapter
- **Slice slug:** simplify
- **Issue:** #16
- **Branch:** feat/overpass-adapter/02-simplify
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer test **red** (strict-xfail, DEC-33) before implementation; **implementer** drives inner cycles, may not edit the outer test or `design/`; **test-author** removes the marker on green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

The Overpass adapter simplifies LineString/Polygon geometry via shapely Douglas-Peucker at
`simplify_tolerance_deg` (0.0005°) and, when the feature count still exceeds
`max_rendered_features` (5,000), drops lowest-value features first by the overpass.md
deterministic priority (primary → mainline rail → trunk; within a tier, shortest first),
**never** dropping motorway or any point anchor. Same input ⇒ same output (cacheable).

## INVEST check

- **Independent:** a pure function over a parsed feature list; no network.
- **Valuable:** the NFR4 render-perf guarantee (≤5,000 features) and cache reproducibility.
- **Small:** one shapely `simplify` call + a deterministic drop sort.
- **Testable:** synthetic over-cap feature lists make the drop order and cap exactly assertable.

## Acceptance criterion (outer loop — the failing integration test)

```gherkin
Given a synthetic parsed land feature set of 7,000 features (mixed motorway/trunk/primary roads, mainline rail, and point anchors) exceeding the 5,000 cap
When  simplification runs at tolerance 0.0005 with max_rendered_features 5,000
Then  the output has at most 5,000 features
And   every motorway way and every point anchor (border_control, aerodrome, port, station/yard) is retained
And   dropped features follow the priority primary→rail→trunk, shortest-within-tier first
And   running it twice on the same input yields identical feature sets (deterministic)
And   simplified LineStrings have strictly fewer vertices than their inputs
```

- **Boundary / endpoint:** the simplification path inside `OverpassAdapter.fetch` (exercised via the adapter or a directly-called internal function).
- **e2e test type:** integration/unit test with synthetic feature lists (no real fixture needed).
- **e2e test file (planned):** `backend/tests/test_overpass.py::test_simplify_and_cap`

## Inner loop — initial unit test list

- [ ] shapely `simplify(tolerance=0.0005, preserve_topology=False)` reduces vertex counts; points untouched.
- [ ] Under the cap: no features dropped.
- [ ] Over the cap: drop tiers applied in order primary→rail→trunk; motorway + point anchors never dropped.
- [ ] Within a tier, ascending geometry length drops shortest first.
- [ ] Deterministic: identical output across two runs on the same input.

## Out of scope (deferred)

- Changing the fetch/parse path (slice 01 owns it).
- Cache write-through (backend-api wiring persists the simplified result).

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1; strict-xfail DEC-33), seen red, now GREEN.
- [ ] Inner behaviours covered; `uv run pytest` green; `uv run ruff check` clean; refactor on green.
- [ ] CI (`tdd-ci`); evidence; PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-05 planned (sprint v0). Blocked-by: overpass-adapter/01.
