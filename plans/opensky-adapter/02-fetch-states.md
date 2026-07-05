# Slice 02: fetch() parses the real Hormuz /states/all into LayerSnapshot(AIR) ⭐

- **Feature:** opensky-adapter
- **Slice slug:** fetch-states
- **Issue:** #14
- **Branch:** feat/opensky-adapter/02-fetch-states
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** **yes** (first real upstream data; validates the credit math)

> **Zij roles (DEC-1):** **test-author** commits the outer test **red** (strict-xfail, DEC-33) before implementation; **implementer** drives inner cycles, may not edit the outer test or `design/`; **test-author** removes the marker on green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

`OpenSkyAdapter.fetch(hormuz)` parses the recorded `/states/all` response into a
`LayerSnapshot(domain=AIR)`: each 17-element state vector → a `Feature` with the
opensky.md index mapping, `position_source` int→label, null lat/lon dropped, null
`time_position` → `timestamp_source=None`/`position_age_s=None`, `raw_payload` in-memory
only. The `CreditLedger` estimates **1** credit for the Hormuz bbox and decrements on the
successful fetch (validating v0's credit math against a real payload).

## INVEST check

- **Independent:** builds on slice 01's token + `sources/base`; consumes the committed fixture (mock httpx with it).
- **Valuable:** THE aviation validation — real state vectors parsed, credit tier proven correct against Hormuz.
- **Small:** one `fetch` method + a `CreditLedger`; parsing is a documented index map.
- **Testable:** the committed fixture makes counts, field mapping, and credit math deterministic.

## Acceptance criterion (outer loop — the failing integration test)

```gherkin
Given the committed fixture opensky_states_all_hormuz.json and httpx mocked to return it
When  OpenSkyAdapter.fetch(hormuz_region) is awaited
Then  it returns a LayerSnapshot with meta.layer == AIR and meta.feature_count == the number of states with non-null lat/lon
And   a known state vector maps correctly: icao24→source_id, callsign→label(stripped), lon/lat, attrs.velocity_ms/true_track_deg/altitude_m, and position_source int→label ("ADS-B"/"MLAT"/"FLARM"/"ASTERIX")
And   states with null lat/lon are absent; a null time_position yields timestamp_source=None and position_age_s=None
And   estimate_credits(hormuz_bbox) == 1 and the ledger's remaining decreased by 1 after the fetch
And   model_dump() of the snapshot contains no raw_payload
```

- **Boundary / endpoint:** `backend.sources.opensky.OpenSkyAdapter.fetch(region) -> LayerSnapshot` (adapter public method; surfaced over HTTP later by `GET /api/layers/air/snapshot`).
- **e2e test type:** integration test with the recorded fixture + respx.
- **e2e test file (planned):** `backend/tests/test_opensky.py::test_fetch_hormuz_states`

## Inner loop — initial unit test list

- [ ] 17-element index map is correct for every parsed field (opensky.md table).
- [ ] `position_source` int→label map (0→ADS-B, 1→ASTERIX, 2→MLAT, 3→FLARM; unknown→str).
- [ ] Null lat/lon states dropped; null `time_position` ⇒ `timestamp_source`/`position_age_s` None but feature kept.
- [ ] `FeatureStatus.STALE` stamped when `position_age_s > deemphasize_after_s` (60 s), else LIVE.
- [ ] `estimate_credits` returns the tier value; a successful fetch decrements the ledger; `warn` fires at 50%.
- [ ] `429` ⇒ `RateLimitedError(retry_after=<header>)`; `5xx`/timeout ⇒ `UpstreamError`; malformed JSON ⇒ `ParseError`.
- [ ] Credentials never appear in `raw_payload` or any dumped body (NFR5).

## Out of scope (deferred)

- Scheduler coalescing / cadence (v1). The API slice calls `fetch` directly on manual refresh.
- `X-Rate-Limit-Remaining` server-truth override is nice-to-have; cover if the fixture carries the header, else defer.

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1; strict-xfail DEC-33), seen red, now GREEN.
- [ ] Inner behaviours covered; `uv run pytest` green; `uv run ruff check` clean; refactor on green.
- [ ] Walking-skeleton evidence: a transcript showing real-fixture parse + the credit count. CI (`tdd-ci`); PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-05 planned (sprint v0). Blocked-by: fixtures/01, opensky-adapter/01.
