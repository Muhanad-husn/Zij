# Slice 02: aisstream resilience — reconnect, eviction, region switch

- **Feature:** sources-marine
- **Slice slug:** aisstream-resilience
- **Issue:** #51
- **Branch:** feat/sources-marine/02-aisstream-resilience
- **Project directory:** `backend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

The adapter survives websocket drops and region switches. On `ConnectionClosed`/read error it
sets `_connected=False` and reconnects with exponential backoff + **full jitter**
(`random.uniform(0, min(reconnect_max_s, reconnect_base_s * 2**attempt))`, base 2 s / max 60 s),
resetting `attempt` on a successful subscribe, and **retains** `_table`/`_prev_pos` across the
blip so the map ages naturally rather than blanking. A lightweight eviction sweep (every
`cadence_s`) removes `_table`/`_prev_pos` entries older than `drop_after_s`. `set_region(region)`
tears down and re-subscribes (a fresh subscribe on the open socket) and **clears** `_table` and
`_prev_pos` — the new region is a different vessel population (ARCHITECTURE §4.2).

## INVEST check

- **Independent:** extends slice 01's adapter; ws drop and region switch are driven in-test.
- **Valuable:** FR3 reconnect + the "no old-region ghosts" correctness guarantee on switch.
- **Small:** the reconnect loop, one sweep coroutine, `set_region`.
- **Testable:** a mocked socket that raises `ConnectionClosed`; frozen/controlled clock for backoff bounds.

## Acceptance criterion (outer loop — the failing test)

```gherkin
Given a started aisstream adapter serving a populated table
When  the websocket drops
Then  connected becomes False and the adapter reconnects with exponential backoff plus jitter
And   snapshot() keeps serving the aging table throughout (never blanks on a transient drop)
When  set_region is called with a new bbox
Then  a fresh subscribe for the new bbox is sent and _table and _prev_pos are cleared
And   no vessel from the previous region appears in the next snapshot
```

- **Boundary:** `AisStreamAdapter` (`connected`, `snapshot`, `set_region`) over a fault-injecting mocked socket.
- **test type:** pytest-asyncio integration; **file:** `backend/tests/test_aisstream.py`.

## Inner loop — initial unit test list

- [ ] Backoff delay stays within `[0, min(reconnect_max_s, reconnect_base_s*2**attempt)]`; `attempt` resets on subscribe.
- [ ] `_table`/`_prev_pos` retained across a reconnect (data ages via `last_heard`, not wiped).
- [ ] Sweep evicts entries with `age > drop_after_s` from both `_table` and `_prev_pos`.
- [ ] `set_region` sends a new subscribe payload and clears `_table` + `_prev_pos`.

## Out of scope (deferred)

- Core connect/subscribe/message/snapshot (slice 01).
- Scheduler `reconnecting` status mapping (scheduler feature — the adapter only exposes `connected`).

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner units covered; `uv run pytest`, `uv run ruff` green; refactor on green.
- [ ] Evidence: pytest transcript (fault-injected drop + region switch). CI green; PR via `safe-pr`.

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: sources-marine/01.
