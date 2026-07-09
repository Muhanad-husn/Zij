# Slice 01: SSE endpoint — GET /api/events with full-state-on-connect

- **Feature:** api-core
- **Slice slug:** sse-endpoint
- **Issue:** #53
- **Branch:** feat/api-core/01-sse-endpoint
- **Project directory:** `backend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** yes ⭐

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

`GET /api/events` serves a single `text/event-stream` via sse-starlette (ADR-2). An `EventBus`
sits between the scheduler and connected clients; the scheduler's `publish_snapshot` /
`publish_layer_status` / `publish_region_changed` fan out to every subscriber. **Full-state-on-
connect (ADR-12):** on each (re)connect the server first emits a `snapshot` event for each
**enabled** layer from the registry, then streams incrementals. Events carry `event:`, JSON
`data:`, and a monotonic `id:`; `raw_payload` is excluded from every `snapshot`. A `ping`
keep-alive fires on `[server].sse_ping_s`. The app lifespan starts the scheduler + registry so
the stream has something to publish (ARCHITECTURE §4.1).

## INVEST check

- **Independent:** the scheduler/registry are injected (a fake registry seeded with a fixture snapshot suffices).
- **Valuable:** the push channel every frontend slice consumes; unblocks the whole UI (frontend/01).
- **Small:** one route, the EventBus fan-out, the on-connect replay loop, lifespan wiring.
- **Testable:** an httpx streaming client reads the event frames; assert full-state-first then incrementals.

## Acceptance criterion (outer loop — the failing test)

```gherkin
Given the app with a registry holding an enabled air snapshot
When  a client connects to GET /api/events
Then  it first receives a `snapshot` event for each enabled layer (raw_payload excluded)
When  the scheduler subsequently publishes a layer_status change
Then  the client receives a `layer_status` event with a monotonic id, without reconnecting
And   each event frame carries event:, data: (valid JSON), and id:
```

- **Boundary:** `GET /api/events` read by a streaming httpx client; scheduler publish via the EventBus.
- **test type:** pytest-asyncio integration; **file:** `backend/tests/test_api.py`.

## Inner loop — initial unit test list

- [ ] On connect, one `snapshot` per **enabled** layer is emitted before any incremental event.
- [ ] `snapshot` data excludes `raw_payload`; shape matches `LayerSnapshot` (feature-schema.md).
- [ ] `layer_status` carries `LayerSnapshotMeta` only; `region_changed` carries `{region_id, bbox}`.
- [ ] Event `id:` is monotonic across a connection.
- [ ] EventBus fan-out reaches multiple concurrent subscribers; a slow/closed client doesn't block others.
- [ ] Disabled layers are not replayed on connect.

## Out of scope (deferred)

- Region endpoints (slice 02); toggle/refresh (03); caveats/raw/presets (04).
- Client-side EventSource handling (frontend/01).

## Definition of done

- [x] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [x] Inner units covered; `uv run pytest`, `uv run ruff` green; refactor on green.
- [x] Evidence: pytest transcript of the streamed frames (full-state-then-incremental). CI green; PR via `safe-pr`.

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: scheduler/02, store/02.
- 2026-07-09 built (#53). Blockers #49 (scheduler/02) + #40 (store/02) merged.
  Outer test committed red via strict-xfail (`16a637d`), greened (`89d3e43`):
  `GET /api/events` (sse-starlette) full-state-on-connect + `EventBus` fan-out
  + `create_app`/lifespan wiring. Outer test drives a real ephemeral-port
  uvicorn server (httpx `ASGITransport` can't stream an infinite SSE response).
  Inner units in `test_events_unit.py` (fan-out, slow-client isolation,
  region_changed shape, subscriber lifecycle) + an enabled-only-replay and a
  disconnect-cleanup integration assertion. 187 tests green. Two-stage review
  PASS (done-with-concerns findings addressed pre-PR). Scheduler lifespan
  wiring deferred (this slice drives EventBus/Registry directly, per the outer
  test's disclosed scope).
