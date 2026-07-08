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

from backend.config import AppConfig, LayerCfg
from backend.models import (
    Domain,
    LayerSnapshot,
    LayerSnapshotMeta,
    LayerStatus,
)
from backend.scheduler import Scheduler
from backend.sources.base import PollAdapter, Region

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
