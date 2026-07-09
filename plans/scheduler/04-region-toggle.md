# Slice 04: Region switch + enable/disable

- **Feature:** scheduler
- **Slice slug:** region-toggle
- **Issue:** #52
- **Branch:** feat/scheduler/04-region-toggle
- **Project directory:** `backend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

`activate_region(region)` runs the ARCHITECTURE §4.2 sequence: set `_region`, bump
`_cancel_gen[domain]` so in-flight old-region fetches are discarded (a completing old-gen fetch
is ignored by checking the generation on return); **clear the registry** for all layers and emit
`region_changed`; repopulate cheaply where possible — land from `store.get_land_cache(new.id)`
if fresh, air/marine from `store.get_fallback` **only if its `region_id == new.id`** (mismatched
region fallback must not be shown); set `_wake` for poll layers; `await stream.set_region(new)`;
and persist the choice via `store.put_config_override("active_region", {"region_id": new.id})`.
`set_enabled(domain, False)` parks the poll loop / stops the stream adapter (zero upstream spend,
FR5); `set_enabled(True)` restarts, sets `_wake`, and emits `loading`.

## INVEST check

- **Independent:** builds on slice 02's status/write path; store + stream adapter injected (mockable).
- **Valuable:** FR1/FR5 region and layer control, and the "no old-region ghosts" correctness guarantee.
- **Small:** the switch sequence, the cancel-generation gate, the region-matched fallback check.
- **Testable:** pytest-asyncio with mocked store/stream asserting emit order and the fallback gate.

## Acceptance criterion (outer loop — the failing test)

```gherkin
Given a Scheduler on region A with an in-flight air fetch and a marine stream adapter
When  activate_region(B) is called
Then  the in-flight A fetch is cancelled/ignored, the registry is cleared, a `region_changed`
      event is emitted, the marine stream re-subscribes to B, and B is persisted as active_region
And   a fallback row whose region_id is A is NOT used to repopulate under B (region-matched only)
When  set_enabled("air", False) is called
Then  the air poll loop issues no further upstream fetches until re-enabled
```

- **Boundary:** `Scheduler.activate_region` / `set_enabled` against mocked store + stream adapter.
- **test type:** pytest-asyncio integration; **file:** `backend/tests/test_scheduler.py`.

## Inner loop — initial unit test list

- [ ] Cancel-generation bump: a completing old-gen fetch is ignored (generation checked on return).
- [ ] Registry cleared for all layers and `region_changed` emitted on switch.
- [ ] Repopulation gate: land cache used if fresh; air/marine fallback used only when `region_id` matches.
- [ ] `active_region` persisted via `put_config_override` on switch.
- [ ] Disable → zero upstream spend (poll parked / stream stopped); enable → `_wake` + `loading` emitted.

## Out of scope (deferred)

- The HTTP endpoints that call these (`/api/regions/activate`, `/api/layers/{domain}/toggle`) — api-core/02, api-core/03.
- Custom-bbox validation/estimate (api-core/02); stream adapter internals (sources-marine/02).

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner units covered; `uv run pytest`, `uv run ruff` green; refactor on green.
- [ ] Evidence: pytest transcript (emit-order + fallback-gate assertions). CI green; PR via `safe-pr`.

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: scheduler/02, store/03, sources-marine/02.
- 2026-07-09 built via `/sprint-start`. Outer test red `2ca0f99` → implementer greened → inner units + marker removal `f4c4bfb`. Two-stage review: Stage 1 PASS; Stage 2 found two status-tracking spec deviations (no-repopulation status not reset to `loading`; marine-enable event forwarded adapter's hardcoded `live`) — both fixed in-slice `1017a66` with regression-proven unit tests. 206 passed, ruff clean. Evidence `9b1469d`. **PR #85** into `main` (prepared; awaiting founder approval).
