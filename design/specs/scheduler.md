# Spec — `scheduler.py` (per-layer scheduler)

**Purpose.** The runtime heart (PRD §10, ARCHITECTURE §5): one asyncio task per enabled poll layer + supervision of the marine stream task; per-layer cadence, manual-refresh coalescing (FR6), the **sole** ownership of `LayerStatus`, and the write path adapter→integrity→registry→SSE→fallback. Failure isolation (FR10) is structural: each layer's work runs in its own `try/except`.

## Public interface
```python
class Scheduler:
    def __init__(self, cfg: AppConfig, adapters: dict[Domain, SourceAdapter],
                 registry: Registry, integrity: Integrity, store: Store,
                 events: EventBus): ...

    async def run(self) -> None                          # owns the asyncio.TaskGroup; lifetime = app lifetime
    async def activate_region(self, region: Region) -> None
    async def set_enabled(self, domain: Domain, enabled: bool) -> None   # FR5
    async def refresh(self, domain: Domain) -> None      # FR6 one layer
    async def refresh_all(self) -> None                  # FR6 all enabled
    def current_status(self, domain: Domain) -> LayerStatus
```
`Registry` = in-memory `dict[Domain, LayerSnapshot]` (the snapshot registry; §Snapshot registry). `EventBus` publishes SSE `snapshot`/`layer_status`/`region_changed` ([api.md](../contracts/api.md#sse)). `Integrity` and `Store` per their specs.

## Internal design

### Task model ([ADR-8](../docs/DECISIONS.md#adr-8--concurrency-pure-asyncio))
- `run()` opens one `asyncio.TaskGroup`. Under it:
  - **One `_poll_loop(domain)` task per enabled poll layer** (air, land).
  - **One `_stream_supervisor()` task** if the marine source is a `StreamAdapter`: it owns `adapter.start()`, samples `snapshot()` on the marine cadence, and watches `connected`.
- Per-layer control primitives:
  ```python
  _enabled: dict[Domain, bool]
  _cadence_s: dict[Domain, int]          # effective (config + floor)
  _inflight: dict[Domain, asyncio.Future[LayerSnapshot] | None]  # coalescing token
  _wake: dict[Domain, asyncio.Event]     # manual refresh / enable kick
  _cancel_gen: dict[Domain, int]         # region-switch cancellation generation
  _stale_timer: dict[Domain, asyncio.TimerHandle | None]
  _status: dict[Domain, LayerStatus]
  _region: Region | None
  ```

### `_poll_loop(domain)`
```
while True:
    wait for min(cadence deadline, _wake[domain]); if disabled: park on _wake
    snap = await _do_fetch(domain)     # coalesced; may raise -> handled in _do_fetch
```
- Cadence timing: `asyncio.wait_for(_wake.wait(), timeout=cadence_s)`; timeout → scheduled tick, event set → manual refresh (FR6). Clear the event after each wake.
- Disabled layer parks purely on `_wake` (no timeout) → **zero API spend while disabled (FR5)**; enabling sets `_wake` for an immediate first fetch.

### Coalescing (FR6) — single-flight per layer
`_do_fetch(domain)` implements one shared awaitable per layer:
```python
fut = self._inflight[domain]
if fut is not None:
    return await fut            # join in-flight fetch — no second upstream call, no double credit spend
fut = loop.create_future(); self._inflight[domain] = fut
try:
    result = await adapter.fetch(region)   # the ONLY upstream call
    fut.set_result(result)
finally:
    self._inflight[domain] = None
```
A manual `refresh(domain)` during a scheduled fetch calls `_do_fetch`, sees `_inflight[domain] is not None`, and awaits the same Future — satisfying FR6's "coalesces rather than double-spending credits". The primitive is a **shared `asyncio.Future` per layer** (not a lock — callers need the *result*, not just mutual exclusion). Marine (stream) has no in-flight fetch; `refresh` just forces an immediate `snapshot()` sample.

### Write path (adapter result → SSE), per successful poll or stream sample
1. `snap = adapter.fetch(region)` **or** `adapter.snapshot()`.
2. `snap.features = integrity.apply(snap.features, prev_positions)` (integrity.md; pure, in-loop). Runs **post-adapter, pre-registry**. `prev_positions` per domain: **marine** — the aisstream adapter's `_prev_pos` table (per-report granularity, aisstream.md); **air** — derived by the scheduler from the *outgoing* registry snapshot before step 4 replaces it: `{f.source_id: (f.lat, f.lon, f.timestamp_source) for f in registry[AIR].features}` (empty on first fetch or after region switch — air kinematics then yields no flags, which is correct: no prior report to compare against). **Land** — empty map (kinematics not applicable). No new scheduler state; the registry already holds the previous snapshot at this point (FR9).
3. Compute authoritative `meta`: set `meta.status` (below), `meta.cadence_s`, `meta.stale_after_s = cadence_s * stale_multiplier`, `meta.timestamp_fetched`, `meta.timestamp_source`, `meta.feature_count`, `meta.retry_after_s`/`detail` as applicable.
4. `registry[domain] = snap` (authoritative source of truth, ARCHITECTURE §3).
5. `events.publish_snapshot(snap)` (SSE `snapshot`, raw_payload excluded).
6. **Air/marine only:** `await store.put_fallback(snap)` (FR8; land is in `land_cache`, not here — storage.md).
7. Arm the stale timer (below).

`layer_status`-only events (no feature delta) are published when status/timestamp changes without a new snapshot (e.g. `live→rate-limited`, stale flip, `reconnecting`).

### Status ownership — the scheduler is the ONLY writer of `LayerStatus`
Adapters return/raise; scheduler maps outcome → `LayerStatus` per ARCHITECTURE §5 state machine + adapter-interface.md taxonomy. Full transition table:

| From | Trigger | To |
|---|---|---|
| `*` (init) | task start | `loading` |
| `loading`/`live`/`stale` | fetch ok, `source_age ≤ stale_after_s` | `live` |
| `loading`/`live` | fetch ok, `source_age > stale_after_s` | `stale` |
| `loading` | first fetch pending, warm fallback exists | `cached-fallback` |
| `loading` | fetch failed, **no** warm cache | `error` |
| `live`/`stale`/`cached-fallback` | scheduled tick / manual refresh begins | `loading` (transient; only emitted if fetch is non-trivial — land fetch, not a fast cache hit) |
| `live`/`stale` | `source_age` crosses `stale_after_s`, no new data | `stale` (stale-timer, below) |
| `live`/`cached-fallback` | `RateLimitedError` | `rate-limited` (carry `retry_after_s`) |
| `rate-limited` | retry after `retry_after` succeeds | `live` |
| `rate-limited` | still failing, warm cache | `cached-fallback` |
| `live`/`rate-limited` | `UpstreamError`/`AuthError`/`ParseError`, **warm cache** | `cached-fallback` |
| `live` | `UpstreamError`/`AuthError`/`ParseError`, **no cache** | `error` |
| `error` | retry begins | `loading` |
| `cached-fallback` | live fetch succeeds | `live` (or `stale`) |
| `live` (marine) | `connected == False` | `reconnecting` |
| `reconnecting` (marine) | `connected == True` + snapshot | `live` |
| `reconnecting` (marine) | still down, warm cache | `cached-fallback` |

Rules:
- **`stale` is time-derived, recomputed even without new data.** Implementation: **event-driven stale timer**, not polling. After each successful write, `loop.call_at(timestamp_source + stale_after_s)` schedules a one-shot check; if no newer data arrived by then, flip `live→stale` and emit a `layer_status` event. A new successful fetch cancels/reschedules the timer. Chosen over a periodic sweep (cheaper, exact, no idle wakeups — matters for the 24 h land layer whose stale flip is at 48 h).
- **`cached-fallback` beats `error`:** on any failure the scheduler checks `store.get_fallback(domain)` (air/marine) / `store.get_land_cache` (land). If a warm row exists (and its `region_id` matches the active region), serve it labeled `cached-fallback` with true age `now - fetched_at` (FR8/FR10). `error` only when no cache.
- `retry_after_s` from `RateLimitedError` is honored before the next attempt (FR2); if the error carried none, use config backoff.

### Backoff per error class (adapter-interface.md taxonomy)
| Error | Action | Backoff |
|---|---|---|
| `RateLimitedError` | retry | `retry_after` if present, else `overpass.backoff_base_s`/opensky default `min(60*2**n, 300)` |
| `UpstreamError` | retry | exponential `min(base*2**n, backoff_max_s, cadence_s)` [†], capped at layer `max_attempts` then resume normal cadence |
| `AuthError` | **surface, no auto-retry** | badge `error`, `detail` = credential message (NFR5); next scheduled tick may retry after operator fix |
| `ParseError` | **surface, no retry** | keep last good snapshot; `error` (or retain prior `live`/`cached-fallback`); log for operator |

[†] The `UpstreamError` backoff delay is additionally bounded by the layer's effective cadence, so a failing layer never polls *less* often than a healthy one would. `RateLimitedError` is **exempt** from the cadence bound: a 429 `Retry-After` longer than the cadence is still honored in full (FR2).

Attempt counters reset on any success. Backoff never blocks other layers (each loop independent — FR10).

### Region-switch sequence (`activate_region`, ARCHITECTURE §4.2)
1. `_region = new`; bump `_cancel_gen[domain]` for all layers → in-flight `fetch`es for the old region are cancelled (their Future is discarded; a completing old-gen fetch is ignored on return by checking the generation).
2. **Clear the registry** for all layers and publish `region_changed` (frontend clears; api.md). Decision: **clear, not keep-until-replaced** — keeping old-region features on the map during a switch is a correctness/UX hazard (features outside the new bbox linger, integrity flags mislead). Cost is a brief empty layer, immediately refilled from cache/fallback.
3. **Immediate repopulation where cheap:** for land, `store.get_land_cache(new.id)` — if fresh, publish it (`live`/`cached-fallback`) without a fetch. For air/marine, `store.get_fallback(domain)` **only if its `region_id == new.id`** (fallback is keyed by layer, not region — a mismatched region's fallback must not be shown); else `loading`.
4. Poll layers: set `_wake` → next tick fetches the new bbox.
5. Stream adapter: `await adapter.set_region(new)` → aisstream re-subscribes + clears its table (aisstream.md).
6. Persist the new region as the `active_region` `config_override` row (`store.put_config_override("active_region", {"region_id": new.id})`, storage.md) so startup restores it ([ARCHITECTURE §4.1](../docs/ARCHITECTURE.md#41-startup--warm-cache-path-15-s-to-interactive-nfr4), config.md §Precedence).

> NOTE: `fallback_snapshots` is keyed by `layer` only (storage.md), so on a region switch the persisted air/marine fallback may belong to a different region. The scheduler must gate cold-load/repopulation on `snapshot_json`'s `meta.region_id` matching the active region. See Contract issue in the return summary.

### Snapshot registry
- In-memory `dict[Domain, LayerSnapshot]`, holding full `Feature`s **with** `raw_payload` (feature-schema.md). The single source of truth (ARCHITECTURE §3); SSE full-state-on-connect ([ADR-12](../docs/DECISIONS.md#adr-12--sse-reconnection)) and `GET /api/layers/{domain}/snapshot` read from it.
- Write path ordering (above) is fixed: **integrity pass → registry set → SSE publish → fallback persist**. Registry is updated before SSE so a concurrent connect always sees consistent state.

### Enable/disable (FR5)
`set_enabled(domain, False)`: park the poll loop on `_wake` (no ticks → zero spend); for marine, `await adapter.stop()` (close websocket → zero stream). `set_enabled(domain, True)`: restart the adapter (`start()` for stream) and set `_wake` for an immediate fetch; emit `loading`.

### Shutdown (ARCHITECTURE §4.4)
TaskGroup cancellation propagates into in-flight `fetch`es (adapters close clients in `finally`); `StreamAdapter.stop()` closes the websocket; fallback rows already persisted per refresh (no flush needed).

## Failure modes
Every fetch/sample is awaited inside a per-layer `try/except` (FR10) — one layer's exception never touches another's task or badge. Unexpected (non-`AdapterError`) exceptions are caught, logged, mapped to `error`/`cached-fallback`, and the loop continues (a crashing adapter must not kill the scheduler).

## Configuration consumed
`[layers.*]` (`enabled`, `cadence_s`, `cadence_floor_s`, `stale_multiplier`); `[overpass]`/`[opensky]` backoff knobs (for its retry loop). Effective cadence = `max(cadence_s, cadence_floor_s)`.

## Acceptance criteria
- [ ] **FR6** — a manual refresh during an in-flight scheduled fetch joins the same `Future`; exactly one upstream call / one credit charge (single-flight verified).
- [ ] **FR6** — per-layer cadences are independent; changing one layer's cadence/override affects no other layer.
- [ ] **FR5** — a disabled layer issues zero upstream requests (poll loop parked; stream socket closed).
- [ ] **FR7** — scheduler is the only writer of `LayerStatus`; `stale` flips exactly at `source_ts + 2×cadence` via the event-driven timer, even with no new data.
- [ ] **FR7** — the seven-state machine (incl. marine-only `reconnecting`) is implemented per the transition table.
- [ ] **FR8/FR10** — on any failure with a warm, region-matched cache the layer shows `cached-fallback` (not `error`); `error` only with no cache; other layers keep running.
- [ ] **FR2** — `rate-limited` honors `retry_after` before retrying.
- [ ] **ARCHITECTURE §4.2** — region switch cancels in-flight fetches, clears the registry, emits `region_changed`, re-subscribes the stream, and repopulates from region-matched cache/fallback only.
- [ ] Write path order is integrity → registry → SSE → fallback for every successful update.
