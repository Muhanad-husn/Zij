"""Acceptance test for the scheduler concurrency spine (issue #45):
per-layer poll loop, single-flight coalescing, independent cadences, and
enable/disable.

Given a Scheduler running two mocked poll adapters (air, land) on
      independent cadences
When  a scheduled fetch for air is in flight and refresh("air") is called
      before it resolves
Then  exactly one adapter.fetch is issued for air and both callers receive
      the same snapshot
And   changing land's cadence does not alter air's tick timing (cadences
      independent, FR6)
And   a disabled layer's poll loop issues zero adapter.fetch calls until
      re-enabled (FR5)

Derived from design/specs/scheduler.md ("Task model", "_poll_loop",
"Coalescing (FR6)", "Enable/disable (FR5)"). This covers ONLY the
concurrency spine: status transitions, the write path (integrity -> registry
-> SSE -> fallback), backoff, the stale timer, region-switch, and marine
stream supervision are out of scope for later scheduler work, and are neither
referenced nor asserted here.

**Public surface this test locks (the minimal constructor this step can
honestly support)**:

    class Scheduler:
        def __init__(self, cfg: AppConfig,
                     adapters: dict[Domain, PollAdapter],
                     region: Region) -> None: ...
        async def run(self) -> None: ...                        # owns the TaskGroup
        async def set_enabled(self, domain: Domain, enabled: bool) -> None: ...
        async def refresh(self, domain: Domain) -> None: ...    # FR6; matches the
                                                                  # full spec's
                                                                  # `-> None` signature
        async def _do_fetch(self, domain: Domain) -> LayerSnapshot: ...  # spec-named
                                                                          # (scheduler.md
                                                                          # "Coalescing")
                                                                          # single-flight
                                                                          # primitive

The full-spec constructor (`registry`, `integrity`, `store`, `events`) has no
honest referent here yet (no write path exists), so this test constructs
`Scheduler(cfg, adapters, region)` only. `region` is an addition at this stage
(not in the full spec's constructor, since the full spec sets it later via
`activate_region()`, itself out of scope here) -- later work can grow the
constructor by adding new *optional* keyword-only collaborators without
breaking this call shape, extending it without a rewrite.

`refresh()`'s return type is kept at the full spec's `-> None` (no
deviation): rather than relying on the return value to prove "both callers
received the same snapshot", this test wraps the spec-named `_do_fetch`
(scheduler.md: "`_do_fetch(domain)` implements one shared awaitable per
layer") -- called internally by both the scheduled `_poll_loop` and by
`refresh()` -- to record each invocation's result and asserts they are the
identical object. Structural proof (`adapter.fetch` called exactly once)
plus that identity check is not satisfiable by a stub that merely fakes
concurrency (e.g. issuing two independent fetches that happen to look
alike): two distinct calls would fail the `is` check and the call-count
assertion both.

The cadence-independence clause is proven by comparing air's tick count
across two full scheduler runs that differ ONLY in land's configured
cadence: if land's cadence leaked into air's timing (e.g. a shared cadence
knob or a shared wake/timer bug), air's tick count would shift between the
two runs. A same-run "change cadence live" reading of the Gherkin is not
possible: neither this step's public surface nor the full spec's exposes a
runtime cadence setter (cadence is a `[layers.*]` config value, config.md) --
this is the closest honest, instrumentable reading of "changing land's
cadence does not alter air's tick timing" against the spec's actual API.

`cadence_s`/`cadence_floor_s` are `int` (backend/config.py `LayerCfg`), so
this test cannot use sub-second cadences; it uses the smallest meaningful
integer cadences (1s / 10s) with generous real-time windows and tolerances
instead. Real (unfrozen) sleeps are used deliberately -- asyncio's internal
scheduling clock (`loop.time()`, tracking `time.monotonic()`) is not
something `freezegun` intercepts, so a frozen wall clock would not actually
control `asyncio.wait_for` cadence ticks here.

It was committed red before any implementation existed (xfail):
`backend.scheduler` did not exist yet, so this errored on import and xfailed
cleanly. The implementation has since made it
genuinely pass; the xfail marker has been removed to finalize the contract.
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
from backend.sources.base import PollAdapter, Region

HORMUZ_REGION = Region(
    id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
)


def _make_snapshot(domain: Domain, region: Region) -> LayerSnapshot:
    """A minimal, valid LayerSnapshot for `domain`/`region` -- the exact
    content is irrelevant here (no write path, no status mapping);
    only object identity (is the SAME object handed to every joiner) and the
    upstream call count matter here."""
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
    """A PollAdapter double that counts `fetch` calls and can optionally hold
    a fetch in flight behind a caller-controlled `asyncio.Event` gate, so
    tests can deterministically arrange "a scheduled fetch is in flight"
    without racing real upstream I/O."""

    source = "fake"

    def __init__(self, domain: Domain, gate: asyncio.Event | None = None) -> None:
        self.domain = domain
        self.gate = gate
        self.call_count = 0
        # Set the instant a fetch call begins (before it may block on
        # `gate`) so tests can await "a fetch is now in flight" precisely.
        self.fetch_started = asyncio.Event()

    async def fetch(self, region: Region) -> LayerSnapshot:
        self.call_count += 1
        self.fetch_started.set()
        if self.gate is not None:
            await self.gate.wait()
        return _make_snapshot(self.domain, region)


def _make_cfg(
    *,
    air_cadence_s: int,
    air_enabled: bool = True,
    land_cadence_s: int,
    land_enabled: bool = True,
) -> AppConfig:
    """A minimal AppConfig carrying only the two poll layers this test
    exercises."""
    return AppConfig(
        regions=[],
        layers={
            "air": LayerCfg(
                enabled=air_enabled,
                cadence_s=air_cadence_s,
                cadence_floor_s=0,
                custom_bbox_cap_sq_deg=100,
            ),
            "land": LayerCfg(
                enabled=land_enabled,
                cadence_s=land_cadence_s,
                cadence_floor_s=0,
                custom_bbox_cap_sq_deg=40,
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
    `with` block, then cancel it and swallow the resulting cancellation --
    `run()` owns an infinite `asyncio.TaskGroup` (spec: "lifetime = app
    lifetime"), so tests must externally bound its lifetime."""
    task = asyncio.ensure_future(scheduler.run())
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, BaseExceptionGroup):
            await task


async def test_scheduler_core_runtime_coalescing_cadence_independence_and_disable():
    from backend.scheduler import Scheduler

    # =========================================================================
    # Given: a Scheduler running two mocked poll adapters (air, land) on
    # independent, tiny (1s) cadences.
    # =========================================================================
    air_gate = asyncio.Event()  # held closed: the first air fetch blocks on it
    air_adapter = FakeAdapter(Domain.AIR, gate=air_gate)
    land_adapter = FakeAdapter(Domain.LAND)

    cfg = _make_cfg(air_cadence_s=1, land_cadence_s=1)
    scheduler = Scheduler(
        cfg, {Domain.AIR: air_adapter, Domain.LAND: land_adapter}, HORMUZ_REGION
    )

    # Wrap the spec-named single-flight primitive (`_do_fetch`,
    # design/specs/scheduler.md "Coalescing (FR6)") to record every result it
    # hands back -- both the scheduled `_poll_loop`'s internal call and
    # `refresh()`'s call go through this same method, so recording it is the
    # only way (short of a registry, out of scope here) to observe
    # "both callers received the same snapshot".
    # Scoped to Domain.AIR only: land runs its own independent scheduled
    # poll loop and will call `_do_fetch(Domain.LAND)` on its own cadence
    # during this window too -- recording every domain indiscriminately
    # would pollute the air-only call-count assertion below with land's
    # unrelated ticks.
    do_fetch_results: list[LayerSnapshot] = []
    original_do_fetch = scheduler._do_fetch

    async def _recording_do_fetch(domain: Domain) -> LayerSnapshot:
        result = await original_do_fetch(domain)
        if domain is Domain.AIR:
            do_fetch_results.append(result)
        return result

    scheduler._do_fetch = _recording_do_fetch

    async with _running_scheduler(scheduler):
        # ---------------------------------------------------------------
        # When: a scheduled fetch for air is in flight (blocked on
        # air_gate) and refresh("air") is called before it resolves.
        # ---------------------------------------------------------------
        await asyncio.wait_for(air_adapter.fetch_started.wait(), timeout=3.0)

        refresh_task = asyncio.ensure_future(scheduler.refresh(Domain.AIR))
        # Yield to the event loop so `refresh()`'s call into `_do_fetch`
        # actually reaches "join the in-flight Future" before we release the
        # gate -- otherwise the manual call could race in only after the
        # first fetch has already resolved, which would not exercise
        # coalescing at all.
        await asyncio.sleep(0.05)

        air_gate.set()  # release the single held-open upstream fetch
        await asyncio.wait_for(refresh_task, timeout=3.0)

        # ---------------------------------------------------------------
        # Then: exactly one adapter.fetch is issued for air, and both the
        # scheduled path and the manual refresh() caller received the same
        # snapshot object (no second, independent fetch/result).
        # ---------------------------------------------------------------
        assert air_adapter.call_count == 1
        assert len(do_fetch_results) == 2
        assert do_fetch_results[0] is do_fetch_results[1]

        # ---------------------------------------------------------------
        # And: a disabled layer's poll loop issues zero adapter.fetch calls
        # until re-enabled (FR5). Land starts enabled above; disable it,
        # then prove a multi-cadence window produces no new fetches.
        # ---------------------------------------------------------------
        await scheduler.set_enabled(Domain.LAND, False)
        land_count_at_disable = land_adapter.call_count
        await asyncio.sleep(2.2)  # >> land's 1s cadence: ticks would have
        # fired here (at least once, likely twice) were the layer not
        # actually parked on `_wake`.
        assert land_adapter.call_count == land_count_at_disable

        # Re-enabling immediately kicks an upstream fetch (spec: "set _wake
        # for an immediate first fetch").
        land_adapter.fetch_started.clear()
        await scheduler.set_enabled(Domain.LAND, True)
        await asyncio.wait_for(land_adapter.fetch_started.wait(), timeout=3.0)
        assert land_adapter.call_count > land_count_at_disable

    # =========================================================================
    # And: changing land's cadence does not alter air's tick timing
    # (cadences independent, FR6). Compared across two fresh scheduler runs
    # differing ONLY in land's configured cadence -- neither this test's nor
    # the full spec's public surface exposes a live cadence setter (cadence
    # is a `[layers.*]` config value), so this is the closest honest,
    # instrumentable reading of the Gherkin against the actual API.
    # =========================================================================
    async def _run_and_count(land_cadence_s: int, window_s: float) -> dict[Domain, int]:
        air = FakeAdapter(Domain.AIR)
        land = FakeAdapter(Domain.LAND)
        run_cfg = _make_cfg(air_cadence_s=1, land_cadence_s=land_cadence_s)
        run_scheduler = Scheduler(
            run_cfg, {Domain.AIR: air, Domain.LAND: land}, HORMUZ_REGION
        )
        async with _running_scheduler(run_scheduler):
            await asyncio.sleep(window_s)
        return {Domain.AIR: air.call_count, Domain.LAND: land.call_count}

    counts_land_fast = await _run_and_count(land_cadence_s=1, window_s=2.5)
    counts_land_slow = await _run_and_count(land_cadence_s=10, window_s=2.5)

    # Air's own tick count is essentially unaffected by land's cadence
    # change (small tolerance for real-clock scheduling jitter only --
    # measured jitter in CI is 0; abs=1 still allows a single tick of slop
    # without masking a genuine cross-talk regression).
    assert counts_land_fast[Domain.AIR] == pytest.approx(
        counts_land_slow[Domain.AIR], abs=1
    )
    # Sanity: the cadence change we made DID take effect on land itself --
    # otherwise the assertion above would pass vacuously against a scheduler
    # that ignores cadence configuration entirely.
    assert counts_land_fast[Domain.LAND] > counts_land_slow[Domain.LAND]
