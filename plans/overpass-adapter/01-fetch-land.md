# Slice 01: fetch() parses the real Hormuz Overpass response into LayerSnapshot(LAND) ⭐

- **Feature:** overpass-adapter
- **Slice slug:** fetch-land
- **Issue:** #15
- **Branch:** feat/overpass-adapter/01-fetch-land
- **Project directory:** `.`
- **Status:** 🔬 in review — PR [#31](https://github.com/Muhanad-husn/Zij/pull/31) (done-with-concerns)
- **Walking skeleton?** **yes** (first real land data; validates payload size + parsing)

> **Zij roles (DEC-1):** **test-author** commits the outer test **red** (strict-xfail, DEC-33) before implementation; **implementer** drives inner cycles, may not edit the outer test or `design/`; **test-author** removes the marker on green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

`OverpassAdapter.fetch(hormuz)` runs the six whitelisted class queries (mocked to return
the recorded fixture), parses `elements` into `Feature`s — nodes/`out center` → POINT,
ways with geometry → LINESTRING (RFC 7946 `[lon,lat]`), closed areas → POLYGON with
centroid — dedupes by `source_id`, and stamps every feature's `timestamp_source` with the
response `osm3s.timestamp_osm_base` (oldest across responses). Returns `LayerSnapshot(LAND)`.

## INVEST check

- **Independent:** builds on `sources/base`; consumes the committed fixture (mock httpx).
- **Valuable:** THE land validation — real Overpass payload parsed, `osm_base` freshness proven (FR4).
- **Small:** six query templates + one parser + `osm_base` capture (simplification is slice 02).
- **Testable:** the committed fixture makes geometry types, dedup, and `osm_base` deterministic.

## Acceptance criterion (outer loop — the failing integration test)

```gherkin
Given the committed fixture overpass_hormuz.json and httpx mocked to return it for each class query
When  OverpassAdapter.fetch(hormuz_region) is awaited
Then  it returns a LayerSnapshot with meta.layer == LAND and a non-empty features list
And   a primary-road way becomes a LINESTRING Feature with GeoJSON coordinates in [lon,lat] order and attrs carrying the OSM tags verbatim
And   a port/aerodrome node becomes a POINT Feature (geometry=None, lat/lon set)
And   every feature's timestamp_source equals the fixture's osm3s.timestamp_osm_base parsed as UTC
And   meta.timestamp_source equals that same osm_base (not the fetch time)
And   a source_id matched by two class queries appears exactly once (deduped, first wins)
```

- **Boundary / endpoint:** `backend.sources.overpass.OverpassAdapter.fetch(region) -> LayerSnapshot` (adapter method; surfaced later by `GET /api/layers/land/snapshot`).
- **e2e test type:** integration test with the recorded fixture + respx.
- **e2e test file (planned):** `backend/tests/test_overpass.py::test_fetch_hormuz_land`

## Inner loop — initial unit test list

- [ ] `source_id` = `"{type}/{id}"`; `attrs` = OSM tags verbatim; `label` = `tags.name` or None.
- [ ] Node / `out center` → POINT (geometry None); way with geom → LINESTRING with `[lon,lat]`; closed area → POLYGON + centroid `lat/lon`.
- [ ] `osm_base` parsed to UTC; used as every feature's `timestamp_source`; oldest chosen across multiple responses.
- [ ] Dedup by `source_id` across classes (first wins).
- [ ] Only whitelisted classes are queried (§6.3): the built QL contains no secondary roads.
- [ ] `429`/`504` rotates mirror then (exhausted) ⇒ `UpstreamError`; malformed JSON ⇒ `ParseError`.

## Out of scope (deferred)

- Geometry simplification + the ≤5,000 drop priority (slice 02).
- Cache serve-vs-fetch policy (backend-api wiring).

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1; strict-xfail DEC-33), seen red, now GREEN.
- [ ] Inner behaviours covered; `uv run pytest` green; `uv run ruff check` clean; refactor on green.
- [ ] Walking-skeleton evidence: transcript showing the real-fixture feature counts + `osm_base`. CI (`tdd-ci`); PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-05 planned (sprint v0). Blocked-by: fixtures/01, opensky-adapter/01 (for `sources/base`).
- 2026-07-05 built + PR #31 into `main` (done-with-concerns). Outer test red (strict-xfail) →
  implementer greened → inner tests + marker removal → error-branch coverage. Suite 83 green,
  ruff clean. Walking-skeleton evidence: 8323 features parsed from the real fixture (138 point /
  7948 linestring / 237 polygon), `osm_base` 2026-07-05T17:59:00Z stamped uniformly. Reviewer:
  stage-1 spec-compliance passed. Concerns: spec-drift #30 filed (timeout failure-taxonomy
  self-contradiction; as-built rotate-on-timeout is defensible, routed to an issue per DEC-1);
  one deferred minor (wasted final-attempt backoff) folded into the #30 pass. Simplification +
  ≤5000 cap remain slice 02 (#16).
