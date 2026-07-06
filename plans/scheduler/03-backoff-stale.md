# Slice 03: Backoff per error class + event-driven stale timer

- **Feature:** scheduler
- **Slice slug:** backoff-stale
- **Issue:** #50
- **Branch:** feat/scheduler/03-backoff-stale
- **Project directory:** `backend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

Each layer's retry loop maps the adapter-interface error taxonomy to a backoff policy:
`RateLimitedError` → honor `retry_after` (else default backoff) then retry; `UpstreamError` →
exponential `min(base * 2**n, max)` capped at `max_attempts`, then resume normal cadence;
`AuthError`/`ParseError` → surface as `error` with `detail`, **no auto-retry**, keep the last
good snapshot. Independently, the **event-driven stale timer** schedules a one-shot
`loop.call_at(timestamp_source + stale_after_s)` after each successful write; when it fires with
no newer data it flips `live → stale` and emits a `layer_status` event. A new successful fetch
cancels/reschedules the timer; attempt counters reset on any success; backoff on one layer never
blocks another (each loop independent, FR10).

## INVEST check

- **Independent:** extends slice 02's update path; error taxonomy from v0 `sources/base`.
- **Valuable:** FR2 (rate-limit honoring) + FR7 (time-derived stale, exact, no idle polling).
- **Small:** the per-class backoff branch and one `TimerHandle` per layer.
- **Testable:** freezegun advances the clock; a mocked adapter raises each error class in turn.

## Acceptance criterion (outer loop — the failing test)

```gherkin
Given a layer whose adapter raises RateLimitedError(retry_after=42)
When  the scheduler handles it
Then  the layer shows `rate-limited` and the next attempt is deferred ~42s (not sooner)
When  the adapter raises UpstreamError repeatedly
Then  retries back off exponentially and cap at max_attempts before resuming cadence
Given a layer that fetched live data with no subsequent update
When  the clock reaches source_ts + 2×cadence
Then  the layer flips to `stale` via the timer and emits a layer_status event (no new fetch)
```

- **Boundary:** `Scheduler` retry loop + stale timer against a mocked adapter and frozen clock.
- **test type:** pytest-asyncio + freezegun; **file:** `backend/tests/test_scheduler.py`.

## Inner loop — initial unit test list

- [ ] Backoff sequence per class: rate-limited (retry_after / default), upstream (exponential, capped).
- [ ] `retry_after` honored before the next attempt; absent → config default backoff.
- [ ] `AuthError`/`ParseError` surface `error` with no auto-retry; last good snapshot retained.
- [ ] Stale timer scheduled at `source_ts + stale_after_s`; fires → `stale` + event when no newer data.
- [ ] A new successful fetch cancels/reschedules the timer; attempt counters reset on success.

## Out of scope (deferred)

- Region-switch and enable/disable (slice 04); status mapping itself (slice 02).
- SSE wire format (api-core/01).

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner units covered; `uv run pytest`, `uv run ruff` green; refactor on green.
- [ ] Evidence: pytest transcript (frozen-clock timing assertions). CI green; PR via `safe-pr`.

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: scheduler/02.
