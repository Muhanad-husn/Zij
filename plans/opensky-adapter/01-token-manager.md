# Slice 01: OAuth2 token manager — single-flight, proactive refresh

- **Feature:** opensky-adapter
- **Slice slug:** token-manager
- **Issue:** #13
- **Branch:** feat/opensky-adapter/01-token-manager
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer test **red** (strict-xfail, DEC-33) before implementation; **implementer** drives inner cycles, may not edit the outer test or `design/`; **test-author** removes the marker on green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

`OpenSkyAdapter.start()` prepares an OAuth2 client-credentials token manager that fetches a
bearer token once, caches it, refreshes proactively at `token_refresh_margin_s` before
expiry, and — under concurrent `fetch` callers — triggers **at most one** token request
(single-flight lock). A failed token acquisition raises `AuthError`.

This slice also introduces `backend/sources/base.py` (the `SourceAdapter`/`PollAdapter`
ABCs, `Region`, and the `AdapterError` taxonomy) — the first adapter needs it.

## INVEST check

- **Independent:** needs `models`, `config`, `sources/base`; no network fixture (mock the token endpoint).
- **Valuable:** correct token reuse is what keeps credit spend low (every needless token round-trip is latency, and credential handling is NFR5-sensitive).
- **Small:** token cache + one `asyncio.Lock` + expiry math.
- **Testable:** respx mocks the token endpoint; freezegun drives expiry; concurrency is assertable via the request count.

## Acceptance criterion (outer loop — the failing integration test)

```gherkin
Given an OpenSkyAdapter started with client credentials, the token endpoint mocked to return a token valid ~1800 s
When  three fetch-driven token acquisitions are awaited concurrently
Then  exactly one HTTP request is made to the token endpoint and all three see the same cached token
And   after advancing the clock to within token_refresh_margin_s of expiry, the next acquisition triggers exactly one refresh request
And   a non-2xx token response raises AuthError (no auto-retry)
```

- **Boundary / endpoint:** `backend.sources.opensky.OpenSkyAdapter.start()` + internal `_TokenManager` (adapter public lifecycle; the token endpoint is upstream OAuth, mocked).
- **e2e test type:** integration test with respx (HTTP mock) + freezegun (clock).
- **e2e test file (planned):** `backend/tests/test_opensky.py::test_token_manager_single_flight`

## Inner loop — initial unit test list

- [ ] First acquisition fetches + caches a token; a second within lifetime reuses it (0 new requests).
- [ ] N concurrent acquisitions on a cold cache trigger exactly one token request (single-flight lock).
- [ ] At `expires_at - token_refresh_margin_s` the token is treated as expired and refreshed proactively.
- [ ] Token endpoint non-2xx / connection error ⇒ `AuthError`.
- [ ] `sources/base.py` exposes `SourceAdapter`, `PollAdapter`, `Region`, and the error taxonomy per the contract.

## Out of scope (deferred)

- The `/states/all` fetch + parsing + credit accounting (slice 02).
- Scheduler-driven refresh cadence (v1).

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1; strict-xfail DEC-33), seen red, now GREEN.
- [ ] Inner behaviours covered; `uv run pytest` green; `uv run ruff check` clean; refactor on green.
- [ ] CI (`tdd-ci`); evidence; PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-05 planned (sprint v0). Adds runtime deps `httpx`, `websockets`(defer if unused) and dev deps `respx`, `freezegun`, `pytest-asyncio` if not already present.
