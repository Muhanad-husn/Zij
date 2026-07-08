"""Inner unit tests for scheduler slice 01 (issue #45), transcribed from the
plan's "Inner loop — initial unit test list"
(plans/scheduler/01-core-runtime.md):

  - Effective cadence = max(cadence_s, cadence_floor_s).
  - `_wake` set -> immediate wake; cleared after each wake; timeout ->
    scheduled tick.
  - `_do_fetch` shares one Future per layer; a second concurrent caller
    awaits it (no 2nd `fetch`).
  - Disabled layer parks on `_wake` only (no cadence timeout, no fetch);
    enabling sets `_wake`.
  - `TaskGroup` starts one task per enabled poll layer; shutdown cancels
    cleanly.

The outer acceptance test (test_scheduler.py) already proves single-flight
coalescing and cadence independence end-to-end through the public surface
(`run`/`refresh`/`set_enabled`). These tests go one level down, exercising
`Scheduler`'s real internals directly (`_cadence_s`, `_wake`, `_do_fetch`,
`_poll_loop`) so each item in the plan's unit list has its own narrow,
deterministic proof, isolated from the others -- e.g. the wake/timeout tests
here never touch `_do_fetch` coalescing, and the coalescing test here never
goes through `_poll_loop` at all.

Out of scope, same as the outer test (later scheduler slices 02-04):
`LayerStatus` ownership/transitions, the write path, backoff, the stale
timer, region-switch, marine stream supervision.

Written by the test-author (DEC-1/DEC-34); the implementer is path-guarded
out of `backend/tests/` and may not edit this file.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone

import pytest

from backend.config import AppConfig, LayerCfg
from backend.models import (
    Domain,
    LayerSnapshot,
    LayerSnapshotMeta,
    LayerStatus,
)
from backend.scheduler import Scheduler
from backend.sources.base import PollAdapter, Region, UpstreamError

HORMUZ_REGION = Region(
    id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
)


def _make_snapshot(domain: Domain, region: Region) -> LayerSnapshot:
    """A minimal, valid LayerSnapshot -- content is irrelevant to this slice
    (no write path, no status mapping); only object identity and the
    upstream call count matter here (mirrors test_scheduler.py)."""
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


class _CountingAdapter(PollAdapter):
    """Minimal PollAdapter double: counts `fetch` calls and exposes an event
    set the instant a fetch begins, optionally held open behind a
    caller-controlled `asyncio.Event` gate so a fetch can be deterministically
    kept in flight."""

    source = "fake"

    def __init__(self, domain: Domain, gate: asyncio.Event | None = None) -> None:
        self.domain = domain
        self.gate = gate
        self.call_count = 0
        self.fetch_started = asyncio.Event()

    async def fetch(self, region: Region) -> LayerSnapshot:
        self.call_count += 1
        self.fetch_started.set()
        if self.gate is not None:
            await self.gate.wait()
        return _make_snapshot(self.domain, region)


def _make_cfg(
    *,
    air_cadence_s: int = 1,
    air_cadence_floor_s: int = 0,
    air_enabled: bool = True,
    land_cadence_s: int = 1,
    land_cadence_floor_s: int = 0,
    land_enabled: bool = True,
) -> AppConfig:
    """A minimal AppConfig carrying the two poll layers this slice knows
    about. `Scheduler.__init__` only iterates over the domains present in
    the `adapters` dict it is constructed with, so tests that only pass an
    `air` adapter never touch the `land` entry here."""
    return AppConfig(
        regions=[],
        layers={
            "air": LayerCfg(
                enabled=air_enabled,
                cadence_s=air_cadence_s,
                cadence_floor_s=air_cadence_floor_s,
                custom_bbox_cap_sq_deg=100,
            ),
            "land": LayerCfg(
                enabled=land_enabled,
                cadence_s=land_cadence_s,
                cadence_floor_s=land_cadence_floor_s,
                custom_bbox_cap_sq_deg=40,
            ),
        },
        overpass={},
        opensky={},
        aisstream={},
        integrity={},
        server={},
    )


# --- Effective cadence = max(cadence_s, cadence_floor_s) --------------------


async def test_effective_cadence_uses_the_floor_when_floor_dominates():
    adapter = _CountingAdapter(Domain.AIR)
    cfg = _make_cfg(air_cadence_s=10, air_cadence_floor_s=100)
    scheduler = Scheduler(cfg, {Domain.AIR: adapter}, HORMUZ_REGION)

    assert scheduler._cadence_s[Domain.AIR] == 100


async def test_effective_cadence_uses_cadence_when_cadence_dominates():
    adapter = _CountingAdapter(Domain.AIR)
    cfg = _make_cfg(air_cadence_s=600, air_cadence_floor_s=60)
    scheduler = Scheduler(cfg, {Domain.AIR: adapter}, HORMUZ_REGION)

    assert scheduler._cadence_s[Domain.AIR] == 600


# --- `_wake` set -> immediate wake; cleared after each wake; timeout -------
# --- -> scheduled tick ------------------------------------------------------


async def test_wake_set_triggers_immediate_fetch_then_wake_is_cleared():
    adapter = _CountingAdapter(Domain.AIR)
    # Cadence far longer than this test's window: any fetch observed can only
    # be attributable to the manual `_wake.set()` below, never a timeout tick.
    cfg = _make_cfg(air_cadence_s=3600, air_cadence_floor_s=0)
    scheduler = Scheduler(cfg, {Domain.AIR: adapter}, HORMUZ_REGION)

    loop_task = asyncio.ensure_future(scheduler._poll_loop(Domain.AIR))
    try:
        await asyncio.sleep(0.1)
        assert adapter.call_count == 0  # no wake yet, cadence nowhere near due

        scheduler._wake[Domain.AIR].set()
        await asyncio.wait_for(adapter.fetch_started.wait(), timeout=2.0)

        assert adapter.call_count == 1
        # `_wake.clear()` runs as soon as `wait_for(wake.wait())` returns --
        # before the fetch itself -- so it is already cleared here (spec:
        # "cleared after each wake").
        assert scheduler._wake[Domain.AIR].is_set() is False
    finally:
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task


async def test_poll_loop_ticks_on_cadence_timeout_when_wake_never_set():
    adapter = _CountingAdapter(Domain.AIR)
    cfg = _make_cfg(air_cadence_s=1, air_cadence_floor_s=0)
    scheduler = Scheduler(cfg, {Domain.AIR: adapter}, HORMUZ_REGION)

    loop_task = asyncio.ensure_future(scheduler._poll_loop(Domain.AIR))
    try:
        # `_wake` is never touched: any fetch observed here can only come
        # from the cadence-timeout branch of `_poll_loop`.
        await asyncio.wait_for(adapter.fetch_started.wait(), timeout=3.0)
        assert adapter.call_count == 1
        assert scheduler._wake[Domain.AIR].is_set() is False
    finally:
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task


# --- `_do_fetch` single-flight per layer -------------------------------------


async def test_do_fetch_shares_one_future_for_a_second_concurrent_caller():
    gate = asyncio.Event()  # held closed: the first fetch blocks on it
    adapter = _CountingAdapter(Domain.AIR, gate=gate)
    cfg = _make_cfg(air_cadence_s=1000, air_cadence_floor_s=0)
    scheduler = Scheduler(cfg, {Domain.AIR: adapter}, HORMUZ_REGION)

    first = asyncio.ensure_future(scheduler._do_fetch(Domain.AIR))
    await asyncio.wait_for(adapter.fetch_started.wait(), timeout=2.0)

    # A second, concurrent caller arrives while the first `_do_fetch` is
    # still in flight (blocked on `gate`) -- it must join the same in-flight
    # Future rather than issuing a second upstream `fetch`.
    second = asyncio.ensure_future(scheduler._do_fetch(Domain.AIR))
    await asyncio.sleep(0.05)  # let `second` actually reach the join point

    gate.set()  # release the single held-open upstream fetch
    result_first, result_second = await asyncio.wait_for(
        asyncio.gather(first, second), timeout=2.0
    )

    assert adapter.call_count == 1
    assert result_first is result_second


class _RaisingOnceAdapter(PollAdapter):
    """A PollAdapter double whose `fetch` blocks on a caller-controlled gate,
    then raises the FIRST time it is released -- every subsequent call
    succeeds immediately. Used to pin `_do_fetch`'s exception path
    (scheduler.py: `fut.set_exception(exc)` then re-raise, `_inflight`
    cleared in `finally`): joining callers must see the SAME exception, and
    `_inflight` must reset so the next call issues a genuinely fresh fetch."""

    source = "fake"

    def __init__(self, domain: Domain, gate: asyncio.Event) -> None:
        self.domain = domain
        self.gate = gate
        self.call_count = 0
        self.fetch_started = asyncio.Event()

    async def fetch(self, region: Region) -> LayerSnapshot:
        self.call_count += 1
        self.fetch_started.set()
        if self.call_count == 1:
            await self.gate.wait()
            raise UpstreamError("simulated adapter failure")
        return _make_snapshot(self.domain, region)


async def test_do_fetch_exception_is_shared_with_joiner_then_inflight_resets():
    """Pins behavior already present in current `_do_fetch` code -- GREEN,
    no xfail marker. A first caller's fetch is held in flight and will raise;
    a second, concurrent caller joins the same Future and must receive the
    IDENTICAL exception object (not an independent copy). Afterward
    `_inflight[domain]` must be reset so a subsequent `_do_fetch` issues a
    fresh upstream fetch rather than replaying the exhausted Future."""
    gate = asyncio.Event()  # held closed: the first (raising) fetch blocks on it
    adapter = _RaisingOnceAdapter(Domain.AIR, gate=gate)
    cfg = _make_cfg(air_cadence_s=1000, air_cadence_floor_s=0)
    scheduler = Scheduler(cfg, {Domain.AIR: adapter}, HORMUZ_REGION)

    first = asyncio.ensure_future(scheduler._do_fetch(Domain.AIR))
    await asyncio.wait_for(adapter.fetch_started.wait(), timeout=2.0)

    # A second, concurrent caller arrives while the first `_do_fetch` is
    # still in flight (blocked on `gate`) -- it must join the same in-flight
    # Future rather than issuing a second upstream `fetch`.
    second = asyncio.ensure_future(scheduler._do_fetch(Domain.AIR))
    await asyncio.sleep(0.05)  # let `second` actually reach the join point

    gate.set()  # release the single held-open upstream fetch -- it raises

    with pytest.raises(UpstreamError) as first_exc_info:
        await asyncio.wait_for(first, timeout=2.0)
    with pytest.raises(UpstreamError) as second_exc_info:
        await asyncio.wait_for(second, timeout=2.0)

    # Both joining callers see the SAME exception object -- proof of a
    # shared Future, not two independent upstream calls that happen to both
    # fail.
    assert first_exc_info.value is second_exc_info.value
    assert adapter.call_count == 1  # exactly one upstream call for both joiners

    # `_inflight[domain]` is reset in `_do_fetch`'s `finally` clause.
    assert scheduler._inflight[Domain.AIR] is None

    # A subsequent `_do_fetch` call issues a genuinely fresh upstream fetch
    # (not a replay of the exhausted, exception-carrying Future) and this
    # time succeeds.
    result = await scheduler._do_fetch(Domain.AIR)
    assert adapter.call_count == 2
    assert isinstance(result, LayerSnapshot)


# --- Disabled layer parks on `_wake` only; enabling sets `_wake` ------------


async def test_disabled_layer_parks_on_wake_only_with_no_timeout_and_no_fetch():
    adapter = _CountingAdapter(Domain.AIR)
    cfg = _make_cfg(air_cadence_s=1, air_cadence_floor_s=0, air_enabled=False)
    scheduler = Scheduler(cfg, {Domain.AIR: adapter}, HORMUZ_REGION)

    loop_task = asyncio.ensure_future(scheduler._poll_loop(Domain.AIR))
    try:
        # >> the 1s configured cadence: were the disabled loop still subject
        # to a cadence timeout (rather than parked on a bare `wake.wait()`
        # with no timeout at all), a tick would have fired here at least once.
        await asyncio.sleep(2.2)
        assert adapter.call_count == 0

        await scheduler.set_enabled(Domain.AIR, True)
        # `set_enabled` sets `_wake` synchronously (no internal await), so
        # this holds true before `_poll_loop` gets a chance to run again.
        assert scheduler._wake[Domain.AIR].is_set() is True

        await asyncio.wait_for(adapter.fetch_started.wait(), timeout=2.0)
        assert adapter.call_count == 1
    finally:
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task


# --- `TaskGroup` starts one task per poll layer; shutdown cancels cleanly ---


async def test_run_starts_one_poll_loop_task_per_adapter_and_shuts_down_cleanly():
    air_adapter = _CountingAdapter(Domain.AIR)
    land_adapter = _CountingAdapter(Domain.LAND)
    cfg = _make_cfg(air_cadence_s=1, land_cadence_s=1)
    scheduler = Scheduler(
        cfg, {Domain.AIR: air_adapter, Domain.LAND: land_adapter}, HORMUZ_REGION
    )

    started: list[Domain] = []
    park = asyncio.Event()

    async def _fake_poll_loop(domain: Domain) -> None:
        started.append(domain)
        await park.wait()  # block until the TaskGroup is torn down below

    scheduler._poll_loop = _fake_poll_loop  # type: ignore[method-assign]

    run_task = asyncio.ensure_future(scheduler.run())
    try:
        # `TaskGroup.create_task` schedules but does not immediately run its
        # tasks; a short yield lets both be scheduled once (each awaits the
        # shared `park` gate rather than doing any real I/O).
        await asyncio.sleep(0.1)
        assert sorted(started, key=lambda d: d.value) == [Domain.AIR, Domain.LAND]

        run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, BaseExceptionGroup):
            await asyncio.wait_for(run_task, timeout=2.0)
        assert run_task.done()
    finally:
        park.set()
        if not run_task.done():
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, BaseExceptionGroup):
                await run_task


# --- FR10: per-layer failure isolation ---------------------------------------


class _FailOnceThenSucceedAdapter(PollAdapter):
    """A PollAdapter double whose `fetch` raises on the given (1-indexed)
    call numbers and otherwise behaves like `_CountingAdapter` -- used to
    prove per-layer failure isolation (FR10, design/specs/scheduler.md
    "Purpose": "each layer's work runs in its own try/except"; "Failure
    modes": "a crashing adapter must not kill the scheduler ... the loop
    continues")."""

    source = "fake"

    def __init__(self, domain: Domain, fail_on_calls: set[int]) -> None:
        self.domain = domain
        self.fail_on_calls = fail_on_calls
        self.call_count = 0
        self.fetch_started = asyncio.Event()

    async def fetch(self, region: Region) -> LayerSnapshot:
        self.call_count += 1
        self.fetch_started.set()
        if self.call_count in self.fail_on_calls:
            raise UpstreamError("simulated adapter failure")
        return _make_snapshot(self.domain, region)


async def test_one_layers_raising_adapter_does_not_crash_run_or_the_other_layer():
    """FR10: with two poll layers (air, land) running under one `run()`, air's
    adapter raising on its first tick must NOT crash the `TaskGroup`/`run()`,
    must NOT stop land's independent cadence, and air itself must recover --
    a later tick issues a fresh fetch. Slice 01 implements no
    status/LayerStatus/backoff, so this asserts survival + continuation only,
    never any status mapping.

    `_poll_loop` now wraps `_do_fetch` in its own try/except (scheduler.py),
    so air's raised exception is caught and logged in place -- it never
    propagates out of air's task, `asyncio.TaskGroup`/`run()` stays alive, and
    land's independent cadence is unaffected (DEC-33: was xfail, now green)."""
    air_adapter = _FailOnceThenSucceedAdapter(Domain.AIR, fail_on_calls={1})
    land_adapter = _CountingAdapter(Domain.LAND)
    cfg = _make_cfg(air_cadence_s=1, land_cadence_s=1)
    scheduler = Scheduler(
        cfg, {Domain.AIR: air_adapter, Domain.LAND: land_adapter}, HORMUZ_REGION
    )

    run_task = asyncio.ensure_future(scheduler.run())
    try:
        # Air's very first tick raises. Give the exception time to propagate
        # (or, with correct isolation, to be caught and swallowed) before
        # asserting anything about survival.
        await asyncio.wait_for(air_adapter.fetch_started.wait(), timeout=3.0)
        await asyncio.sleep(0.2)

        # (a) `run()` must still be alive -- not crashed by air's exception.
        assert not run_task.done()

        # (b) land keeps fetching on its own cadence, unaffected by air's
        # failure -- its call count keeps climbing over a multi-cadence
        # window.
        land_count_after_air_failure = land_adapter.call_count
        await asyncio.sleep(2.2)  # >> land's 1s cadence
        assert land_adapter.call_count > land_count_after_air_failure

        # (c) air recovers: a later scheduled tick issues a fresh fetch (call
        # count advances past the failing first call).
        assert air_adapter.call_count > 1
    finally:
        run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, BaseExceptionGroup):
            await run_task
