# Slice 03: AISHub dormant PollAdapter — renderer-independence proof (FR3)

- **Feature:** sources-marine
- **Slice slug:** aishub-dormant
- **Issue:** #48
- **Branch:** feat/sources-marine/03-aishub-dormant
- **Project directory:** `backend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

`AisHubAdapter(PollAdapter)` is the dormant secondary marine source that proves the adapter
interface admits a polling marine implementation with **zero renderer change** (FR3 acceptance).
`fetch(region)` GETs the aishub `ws.php` bbox query (username from `Secrets`) and maps each record
to a `LayerSnapshot(domain=MARINE)` **byte-compatible with aisstream's** — `source_id`=MMSI,
`label`=NAME, `attrs` sog_kn/cog_deg/heading_deg/nav_status, `timestamp_source` from the record's
report time, `geometry_type=POINT`. It self-enforces a **1 request/minute floor** and maps errors
by the standard taxonomy (429→`RateLimitedError`, 5xx/timeout→`UpstreamError`, auth→`AuthError`,
bad JSON→`ParseError`). It is **absent from bundled config** — activation is a one-line wiring swap
plus `AISHUB_USERNAME`.

## INVEST check

- **Independent:** uses only `models` + `sources/base`; HTTP mocked with respx.
- **Valuable:** structurally proves FR3 (swap marine source with no frontend/scheduler change).
- **Small:** one poll adapter, the mapping, the 1/min throttle.
- **Testable:** respx-mocked aishub JSON; call-timing assertion for the floor.

## Acceptance criterion (outer loop — the failing test)

```gherkin
Given a mocked aishub ws.php JSON response for a region bbox
When  fetch(region) is awaited
Then  it returns a LayerSnapshot(domain=MARINE) shaped identically to an aisstream snapshot
And   a marine renderer would consume it with no change (same source_id/label/attrs keys)
When  fetch is called again within 60 s
Then  the adapter honours its own 1 request/minute floor rather than re-hitting upstream
```

- **Boundary:** `AisHubAdapter.fetch` over a respx-mocked endpoint.
- **test type:** pytest-asyncio integration; **file:** `backend/tests/test_aishub.py`.

## Inner loop — initial unit test list

- [ ] Record → `Feature` mapping matches aisstream's key set (source_id/label/attrs/timestamp_source).
- [ ] Self-enforced 1 req/min floor (second call within 60 s serves last / rejects, no 2nd GET).
- [ ] Error taxonomy: 429→RateLimitedError, 5xx/timeout→UpstreamError, auth→AuthError, bad JSON→ParseError.
- [ ] Dormant: not listed as the active marine source in bundled `config.toml`.

## Out of scope (deferred)

- Making AISHub the live marine source (operator wiring change, not a slice).
- Websocket / streaming behaviour (that is aisstream, slices 01–02).

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner units covered; `uv run pytest`, `uv run ruff` green; refactor on green.
- [ ] Evidence: pytest transcript (respx mock + floor timing). CI green; PR via `safe-pr`.

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: none new (v0 `sources/base`). Lowest priority (P0.10) — unblocks nothing.
