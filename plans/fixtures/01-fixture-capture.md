# Slice 01: Capture and commit the two real Hormuz payloads

- **Feature:** fixtures
- **Slice slug:** fixture-capture
- **Issue:** #12
- **Branch:** feat/fixtures/01-fixture-capture
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no (dev tooling, not product code)

> **Role note:** this is tooling under `scripts/`, not product code under `backend/`, so it
> is not a DEC-1 behavior-first product slice. The **test-author** still commits a small red
> check first (below); the **implementer** writes `scripts/fetch_fixtures.py`. The captured
> JSON fixtures are the deliverable that unblocks the two adapter walking skeletons.

## Goal — the minimum testable behaviour

`scripts/fetch_fixtures.py`, run with OpenSky credentials in the environment, fetches the
live `/states/all` response for the Hormuz bbox and the six-class Overpass response for the
same bbox, and writes them verbatim to `backend/tests/fixtures/opensky_states_all_hormuz.json`
and `backend/tests/fixtures/overpass_hormuz.json`. Both files are committed.

## INVEST check

- **Independent:** a standalone script; needs only the region bbox (config) and httpx.
- **Valuable:** the recorded fixtures ARE v0's real-data validation substrate; both walking skeletons depend on them.
- **Small:** one script, two HTTP calls, two file writes.
- **Testable:** a shape-check over the committed fixtures (below) runs in CI without any live call.

## Acceptance criterion (outer loop)

```gherkin
Given the committed fixtures backend/tests/fixtures/opensky_states_all_hormuz.json and overpass_hormuz.json
When  they are loaded as JSON in a test
Then  the OpenSky fixture has top-level "time" (int) and "states" (list), with each state vector 17 elements
And   the Overpass fixture has "osm3s.timestamp_osm_base" and a non-empty "elements" list covering node and way types
```

- **Boundary / endpoint:** the committed fixture files (validated by a shape test); the capture script itself is run manually by the founder (its live-network path is not CI-tested).
- **e2e test type:** integration test asserting the committed fixtures' shape (no live upstream).
- **e2e test file (planned):** `backend/tests/test_fixtures_shape.py`

## Inner loop — initial unit test list

- [ ] OpenSky fixture parses as JSON with `time:int` and `states:list`; first vector has 17 elements.
- [ ] Overpass fixture parses with `osm3s.timestamp_osm_base` present and ISO-parseable to UTC.
- [ ] Overpass `elements` is non-empty and includes at least one `type=="node"` and one `type=="way"`.

## Out of scope (deferred)

- Parsing the fixtures into `Feature`s (the adapter slices).
- Any scheduled/automated re-capture; marine fixtures (v1).
- Making the script's live-network path pass in CI (it needs secrets + live upstreams by design).

## Definition of done

- [x] `scripts/fetch_fixtures.py` written; capture run; both fixtures committed.
- [x] Shape test authored **red** first (strict-xfail, `7f1aed7`), now GREEN against the committed fixtures (`903090c`).
- [x] `uv run pytest` green (`44 passed`); `uv run ruff check` clean.
- [x] CI (`ci.yml`) runs `ruff` + `pytest` on the PR; PR #28 into `main` opened via `safe-pr`.

## Status / progress log

- 2026-07-05 planned (sprint v0). Founder-run capture step (needs OpenSky creds in `.env`).
- 2026-07-05 built green. Outer shape test red→green (`7f1aed7`→`903090c`). Capture script
  reuses the #13 token manager; identifying User-Agent added to fix Overpass HTTP 406
  (`0c64933`). Fixtures committed: OpenSky 20 vectors, Overpass 8,323 elements (~15 MB),
  osm_base `2026-07-05T17:59:00Z`. Two-stage review: Stage 1 PASS, Stage 2 done-with-concerns
  (private-attr reach-through, 15 MB fixture git footprint, broader-than-spec retry — all
  advisory). PR [#28](https://github.com/Muhanad-husn/Zij/pull/28) (label `done-with-concerns`),
  awaiting founder merge approval.
