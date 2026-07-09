"""Locked outer acceptance test for scheduler slice 04 (issue #52):
region-switch (`activate_region`) + stream-aware enable/disable.

Given a Scheduler on region A with an in-flight air fetch and a marine
      stream adapter
When  activate_region(B) is called
Then  the in-flight A fetch is cancelled/ignored, the registry is cleared,
      a `region_changed` event is emitted, the marine stream re-subscribes
      to B, and B is persisted as active_region
And   a fallback row whose region_id is A is NOT used to repopulate under B
      (region-matched only)
When  set_enabled("air", False) is called
Then  the air poll loop issues no further upstream fetches until re-enabled

Transcribed from plans/scheduler/04-region-toggle.md ("Acceptance
criterion") and design/specs/scheduler.md ("Region-switch sequence
(activate_region, ARCHITECTURE §4.2)", "Enable/disable (FR5)"), including
the NOTE that `fallback_snapshots` is keyed by layer only, so a region
switch must gate repopulation on the fallback row's `meta.region_id`
matching the new region.

**Why a NEW file, not `backend/tests/test_scheduler.py`.** The plan names
`test_scheduler.py` as the file, but that module is slice 01's LOCKED outer
contract (its own docstring: "It was authored and committed red ... the
xfail marker has been removed to finalize the contract" -- not to be
reopened or appended to by a later slice). Adding a second, unrelated
locked contract into the same module would blur ownership of two
independently-evolving acceptance tests and risk an editor of slice 04
accidentally touching slice 01's frozen assertions. A new file preserves
both contracts' independence; this is the honest reading of the plan's
intent, not a deviation from it.

**Public surface this test locks (test-author's chosen minimal slice 04
constructor grown from slice 01/02, per "extend without a rewrite")**:

    class Scheduler:
        def __init__(self, cfg, adapters, region, *,
                     registry=None, integrity=None, store=None,
                     events=None, stream: StreamAdapter | None = None) -> None: ...
        async def activate_region(self, region: Region) -> None: ...
        async def set_enabled(self, domain: Domain, enabled: bool) -> None: ...

`stream` is a NEW optional keyword-only collaborator (mirrors the
already-optional `registry`/`integrity`/`store`/`events` kwargs slice 02
added) -- every existing slice-01/02 call shape (`Scheduler(cfg, adapters,
region)` and `Scheduler(cfg, adapters, region, registry=..., ...)`) keeps
working unmodified. Marine is deliberately NOT put in the `adapters` dict
(that dict is `dict[Domain, PollAdapter]`, per the full spec's constructor
signature) -- the marine `StreamAdapter` is a structurally different
collaborator (`start`/`stop`/`set_region`/`snapshot`/`connected`, no
`fetch`), so it is injected through its own `stream` kwarg rather than
forced into the poll-adapter mapping. `set_enabled` itself is unchanged
(already public since slice 01); this test only re-locks its poll-loop
parking behavior for the `air` domain in the context of a region switch,
per the Gherkin's explicit `set_enabled("air", False)` clause.

**Mocked collaborators.** `FakeStreamAdapter` records every `set_region`
call. `FakeStore` is a hand-written double (not the real SQLite `Store` --
no I/O needed to prove the region-matched gate) whose `get_fallback("air")`
returns a snapshot fixture tagged `meta.region_id == REGION_A.id`, and which
records every `get_fallback`/`put_config_override` call. A REAL `EventBus`
is used (not a recording fake) with a subscribed queue read via
`asyncio.wait_for` -- proving `region_changed` was genuinely published
through the real pub/sub fan-out, not just that some internal method was
invoked. `Registry` is the real (trivial) `dict` subclass, pre-seeded with
a stale region-A snapshot so "cleared" is a genuine before/after
transition, not a vacuous "was already empty" pass.

**Proving "in-flight A fetch cancelled/ignored" without literal
cancellation.** Per the spec, the fetch coroutine is NOT `.cancel()`-ed --
"their Future is discarded ... a completing old-gen fetch is ignored on
return by checking the generation." This test reuses slice 01's
gate-controlled `FakeAdapter` pattern: a `refresh(Domain.AIR)` is started
under region A and held in flight on a caller-controlled `asyncio.Event`
gate; `activate_region(B)` is called while it is still gated (proving the
switch does not wait for/depend on the in-flight fetch); the gate is then
released and the fetch is awaited to completion. A stub that let this stale
result land in the registry (or in a subsequent `region_changed`-adjacent
write) would fail the post-release "registry still has no AIR entry"
assertion below -- the only way to pass is to actually track a
per-domain generation and check it after the await, exactly as the spec
prescribes.

**Proving the fallback gate is a genuine check-then-reject, not a
no-op.** `store.get_fallback` call-tracking plus the empty-registry
assertion together rule out both failure modes a stub could take: (a)
never consulting the fallback at all (caught by asserting `"air"` appears
in `store.get_fallback_calls`), and (b) consulting it but using it anyway
because the region-match check was skipped (caught by asserting the
registry stays empty for AIR after the switch, even though a fallback row
existed).

**Proving the switch is genuinely usable afterward, not just broken.**
After the assertions above, `set_enabled(Domain.AIR, True)` is called and
the poll loop is allowed to tick once for the NEW region: the resulting
snapshot IS asserted to land in the registry, tagged with `region_id ==
REGION_B.id`. Without this, a scheduler that simply discarded ALL air
writes forever (not just the stale generation) would vacuously pass the
"stayed empty" assertions above; this closes that loophole. That same
enabled window is then used for the Gherkin's final clause: disabling
(`set_enabled(Domain.AIR, False)`) is asserted to stop further
`adapter.fetch` calls across a multi-cadence real-time window (reusing
slice 01's disable-proof pattern, scoped here to `air` per the Gherkin).

Real (unfrozen) sleeps are used for cadence-timing assertions, for the same
reason documented in slice 01's `test_scheduler.py`: asyncio's internal
scheduling clock is not something `freezegun` intercepts.

`backend.scheduler` is imported inside the test body (repo convention --
see slice 01's `test_scheduler.py` and the durable memory note on avoiding
module-scope imports of app-wiring modules at collection time; harmless
here in practice since this module imports no app-wiring code, but kept
for consistency).

Authored and committed red by the test-author before any implementation
existed (strict xfail, DEC-33): `Scheduler.activate_region` and the
`stream` constructor kwarg did not exist yet, so this failed on
`AttributeError`/`TypeError` and xfailed cleanly under the tests-green
gate. The implementer has since made it pass; the xfail marker is removed
to finalize the contract (DEC-1/DEC-34). See
`test_scheduler_region_toggle_unit.py` for the inner-unit pass added in the
same close-out commit (marine fallback region-match gate, land cache
freshness gate, stream enable/disable) -- the gaps this outer test itself
does not pin.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
from typing import Any

from backend.config import AppConfig, LayerCfg
from backend.events import EventBus
from backend.models import Domain, LayerSnapshot, LayerSnapshotMeta, LayerStatus
from backend.registry import Registry
from backend.sources.base import PollAdapter, Region, StreamAdapter

REGION_A = Region(id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5))
REGION_B = Region(id="malacca", label="Strait of Malacca", bbox=(98.0, 1.0, 104.0, 6.0))


def _make_snapshot(domain: Domain, region: Region) -> LayerSnapshot:
    """A minimal, valid LayerSnapshot for `domain`/`region` -- mirrors
    slice 01's helper of the same name (this is a separate test module, so
    it is redefined locally rather than imported cross-module)."""
    now = datetime.now(timezone.utc)
    return LayerSnapshot(
        meta=LayerSnapshotMeta(
            layer=domain,
            region_id=region.id,
            status=LayerStatus.LIVE,
            timestamp_fetched=now,
            timestamp_source=now,
            cadence_s=1,
            stale_after_s=2,
            feature_count=0,
        ),
        features=[],
    )


class FakeAdapter(PollAdapter):
    """A PollAdapter double that counts `fetch` calls, records the region
    each call was made with, and can optionally hold a fetch in flight
    behind a caller-controlled `asyncio.Event` gate (slice 01 pattern)."""

    source = "fake"

    def __init__(self, domain: Domain, gate: asyncio.Event | None = None) -> None:
        self.domain = domain
        self.gate = gate
        self.call_count = 0
        self.regions_seen: list[Region] = []
        self.fetch_started = asyncio.Event()

    async def fetch(self, region: Region) -> LayerSnapshot:
        self.call_count += 1
        self.regions_seen.append(region)
        self.fetch_started.set()
        if self.gate is not None:
            await self.gate.wait()
        return _make_snapshot(self.domain, region)


class FakeStreamAdapter(StreamAdapter):
    """A StreamAdapter double that only records `set_region` calls -- the
    stream adapter's own internals (websocket, table, jitter) are
    sources-marine/02's concern (out of scope, per the plan)."""

    domain = Domain.MARINE
    source = "fake-stream"

    def __init__(self) -> None:
        self.set_region_calls: list[Region] = []
        self._connected = True

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def set_region(self, region: Region) -> None:
        self.set_region_calls.append(region)

    def snapshot(self) -> LayerSnapshot:
        return _make_snapshot(Domain.MARINE, REGION_A)

    @property
    def connected(self) -> bool:
        return self._connected


class FakeStore:
    """A hand-written Store double (not the real SQLite-backed `Store` --
    no I/O is needed to prove the region-matched fallback gate). Records
    every `get_fallback`/`put_config_override` call for the
    check-then-reject assertions documented above."""

    def __init__(self, fallback_by_layer: dict[str, LayerSnapshot | None]) -> None:
        self._fallback_by_layer = fallback_by_layer
        self.get_fallback_calls: list[str] = []
        self.put_config_override_calls: list[tuple[str, dict[str, Any]]] = []

    async def get_fallback(self, layer: str) -> LayerSnapshot | None:
        self.get_fallback_calls.append(layer)
        return self._fallback_by_layer.get(layer)

    async def get_land_cache(self, region_id: str):
        return None

    async def put_fallback(self, snap: LayerSnapshot) -> None:
        pass

    async def put_config_override(self, name: str, payload: dict[str, Any]) -> None:
        self.put_config_override_calls.append((name, payload))


def _make_cfg(*, air_cadence_s: int, air_enabled: bool) -> AppConfig:
    """A minimal AppConfig carrying only the `air` layer this test
    exercises (marine is injected via the `stream` kwarg, not `cfg.layers`,
    per the constructor surface documented above)."""
    return AppConfig(
        regions=[],
        layers={
            "air": LayerCfg(
                enabled=air_enabled,
                cadence_s=air_cadence_s,
                cadence_floor_s=0,
                custom_bbox_cap_sq_deg=100,
            ),
        },
        overpass={},
        opensky={},
        aisstream={},
        integrity={},
        server={},
    )


@contextlib.asynccontextmanager
async def _running_scheduler(scheduler):
    """Run `scheduler.run()` as a background task for the duration of the
    `with` block (slice 01 pattern -- `run()` owns an infinite
    `asyncio.TaskGroup`)."""
    task = asyncio.ensure_future(scheduler.run())
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, BaseExceptionGroup):
            await task


async def test_activate_region_cancels_stale_fetch_clears_registry_gates_fallback_and_disable_stops_polling():
    from backend.scheduler import Scheduler

    # =========================================================================
    # Given: a Scheduler on region A with a marine stream adapter, air
    # initially disabled (fetches driven explicitly via refresh() for
    # deterministic control over "an in-flight air fetch"), and:
    #  - a registry pre-seeded with a stale region-A AIR snapshot (so
    #    "cleared" is a genuine before/after transition), and
    #  - a store whose "air" fallback row is tagged region A (so the
    #    region-matched gate has something real to reject under region B).
    # =========================================================================
    air_gate = asyncio.Event()  # held closed: the first air fetch blocks on it
    air_adapter = FakeAdapter(Domain.AIR, gate=air_gate)
    stream = FakeStreamAdapter()

    registry = Registry()
    registry[Domain.AIR] = _make_snapshot(Domain.AIR, REGION_A)

    region_a_fallback = _make_snapshot(Domain.AIR, REGION_A)
    store = FakeStore(fallback_by_layer={"air": region_a_fallback})

    events = EventBus()
    subscriber = events.subscribe()

    cfg = _make_cfg(air_cadence_s=1, air_enabled=False)
    scheduler = Scheduler(
        cfg,
        {Domain.AIR: air_adapter},
        REGION_A,
        registry=registry,
        store=store,
        events=events,
        stream=stream,
    )

    async with _running_scheduler(scheduler):
        # ---------------------------------------------------------------
        # ...with an in-flight air fetch: a manual refresh() is started
        # under region A and held gated (fetch entered, not yet returned).
        # ---------------------------------------------------------------
        refresh_task = asyncio.ensure_future(scheduler.refresh(Domain.AIR))
        await asyncio.wait_for(air_adapter.fetch_started.wait(), timeout=3.0)
        assert air_adapter.regions_seen[-1].id == REGION_A.id

        # ---------------------------------------------------------------
        # When: activate_region(B) is called (while the A fetch is still
        # gated -- the switch must not wait on it).
        # ---------------------------------------------------------------
        await asyncio.wait_for(scheduler.activate_region(REGION_B), timeout=3.0)

        # ---------------------------------------------------------------
        # Then: the registry is cleared (the stale region-A AIR entry that
        # was pre-seeded is gone)...
        # ---------------------------------------------------------------
        assert len(registry) == 0

        # ...a `region_changed` event was genuinely published through the
        # real EventBus fan-out...
        event = await asyncio.wait_for(subscriber.get(), timeout=1.0)
        assert event["event"] == "region_changed"
        assert event["data"]["region_id"] == REGION_B.id

        # ...the marine stream re-subscribed to B...
        assert len(stream.set_region_calls) == 1
        assert stream.set_region_calls[0].id == REGION_B.id

        # ...and B was persisted as the active_region config override.
        assert ("active_region", {"region_id": REGION_B.id}) in (
            store.put_config_override_calls
        )

        # ---------------------------------------------------------------
        # And: the region-A-tagged air fallback was consulted (the gate
        # actually checked it) but NOT used to repopulate under B (the
        # registry stays empty for AIR) -- region-matched only.
        # ---------------------------------------------------------------
        assert "air" in store.get_fallback_calls
        assert Domain.AIR not in registry

        # ---------------------------------------------------------------
        # Releasing the gated region-A fetch now lets it complete: its
        # stale-generation result must be ignored, not written to the
        # registry (which is now under region B).
        # ---------------------------------------------------------------
        air_gate.set()
        await asyncio.wait_for(refresh_task, timeout=3.0)
        await asyncio.sleep(0.1)  # let any (incorrect) write-path settle
        assert Domain.AIR not in registry

        # ---------------------------------------------------------------
        # Sanity: the switch left the scheduler genuinely usable for the
        # NEW region, not merely broken -- enabling air now lets a fresh,
        # current-generation fetch land in the registry under region B.
        # ---------------------------------------------------------------
        air_adapter.fetch_started.clear()
        await scheduler.set_enabled(Domain.AIR, True)
        await asyncio.wait_for(air_adapter.fetch_started.wait(), timeout=3.0)
        await asyncio.sleep(0.1)
        assert Domain.AIR in registry
        assert registry[Domain.AIR].meta.region_id == REGION_B.id
        fetch_count_before_disable = air_adapter.call_count

        # ---------------------------------------------------------------
        # When: set_enabled("air", False) is called.
        # Then: the air poll loop issues no further upstream fetches until
        # re-enabled -- proven across a multi-cadence real-time window.
        # ---------------------------------------------------------------
        await scheduler.set_enabled(Domain.AIR, False)
        await asyncio.sleep(2.2)  # >> air's 1s cadence
        assert air_adapter.call_count == fetch_count_before_disable
