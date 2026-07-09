"""Locked outer acceptance test for scheduler slice 03 (issue #50): backoff
per error class + the event-driven stale timer.

Given a layer whose adapter raises RateLimitedError(retry_after=3)
When  the scheduler handles it
Then  the layer shows `rate-limited` (carrying `retry_after_s`) and the next
      attempt is deferred ~retry_after (not sooner -- not at the layer's own,
      shorter cadence)
When  the adapter raises UpstreamError repeatedly
Then  retries back off exponentially and cap at max_attempts before
      resuming the layer's normal cadence
Given a layer that fetched live data with no subsequent update
When  the clock reaches source_ts + 2xcadence
Then  the layer flips to `stale` via the timer and emits a `layer_status`
      event (no new fetch)

Transcribed from plans/scheduler/03-backoff-stale.md ("Acceptance
criterion") and design/specs/scheduler.md ("Backoff per error class
(adapter-interface.md taxonomy)", "Status transitions" table's stale-timer
rule: "event-driven stale timer ... loop.call_at(timestamp_source +
stale_after_s) ... if no newer data arrived by then, flip live->stale and
emit a layer_status event").

**Why a NEW file, not `backend/tests/test_scheduler.py`.** The plan names
`test_scheduler.py` as the file, but that module is slice 01's LOCKED outer
contract (its own docstring: "not to be reopened or appended to by a later
slice"). Slice 04's test-author already established the precedent of a new,
independently-owned file per slice
(`test_scheduler_region_toggle.py`) for exactly this reason; this file
follows that same convention (`test_scheduler_backoff_stale.py`), the
honest reading of the plan's intent against the actual repo state.

**Public surface this test locks.** Only already-public methods from the
full spec's constructor/surface (scheduler.md "Public interface"), already
exercised by slice 01/02/04's outer tests:

    class Scheduler:
        def __init__(self, cfg, adapters, region, *,
                     registry=None, integrity=None, store=None,
                     events=None, stream=None) -> None: ...
        async def run(self) -> None: ...
        async def refresh(self, domain: Domain) -> None: ...
        def current_status(self, domain: Domain) -> LayerStatus: ...

No new constructor surface is introduced by this slice per the plan (only
internal backoff/timer bookkeeping, e.g. some `_stale_timer`-shaped table
per scheduler.md's private state list) -- this test therefore asserts
exclusively through `current_status()`, real `EventBus` events, adapter call
counts, and elapsed real time, never through private attributes (per the
dispatch brief: "not private attributes where a public signal exists").

**Domain choice.** Phase 1/2 (backoff) use `Domain.LAND`, whose backoff
knobs (`backoff_base_s`/`backoff_max_s`/`max_attempts`) are already present
in `[overpass]` (backend/config.toml) and are read here as a plain
`dict[str, Any]` (`AppConfig.overpass`), so this test can pass small
fractional seconds (e.g. `0.15`) for a fast, deterministic real-time proof
without needing frozen time. Phase 3 (stale timer) uses `Domain.AIR` purely
to diversify domain coverage; it needs no backoff config.

**Why real (unfrozen) time, not freezegun, despite the plan's suggestion.**
Per slice 01's `test_scheduler.py` (still-binding durable lesson): asyncio's
internal scheduling clock (`loop.time()`, tracking `time.monotonic()`) is
NOT something `freezegun` intercepts. The spec's own stale-timer design
(`loop.call_at`) is bound to that same real monotonic clock, so freezing
`datetime.now()` cannot accelerate when the timer actually fires. Instead,
phase 3 exploits a legitimate, honest technique: the mocked adapter reports
a `timestamp_source` that is deliberately backdated (as real upstream data
legitimately can be), so `source_ts + stale_after_s` lands only a small
`epsilon` of *real* seconds in the future -- proving the exact
`source_ts + stale_after_s` firing rule (FR7: "time-derived, recomputed even
without new data") without waiting out the full configured
`stale_after_s` (200s here) in wall-clock time. Phases 1/2 use small,
sub-cadence-scale real sleeps for the same reason (matches the established
"smallest meaningful integer cadences + generous tolerances" pattern from
slice 01/04, since `cadence_s` is an `int`, `LayerCfg`).

**Why the FIRST fetch in phases 1/2 comes from the natural `_poll_loop`
tick, not a manual `refresh()`.** The backoff-driven RETRY must be an
automatic property of the scheduler's own retry loop, not something this
test re-triggers by hand -- using `refresh()` for the very first attempt
would leave it ambiguous whether a later "second" call was the loop's own
backoff-driven retry or an artifact of this test's own control flow. Letting
`_poll_loop`'s normal cadence tick perform the FIRST fetch, then observing
if/when a SECOND, automatic fetch happens, is the only way to genuinely pin
"the scheduler's own retry timing changes based on the error class", not
just "a caller can retry".

**Timing design (the actual distinguishing power against the current,
pre-slice-03 code).**
- Phase 1: `cadence_s=1` (land's own, shorter, cadence) vs
  `retry_after_s=3`. The CURRENT scheduler (no backoff yet) retries at the
  layer's own cadence on any failure -- i.e. ~1s after the RateLimitedError,
  well before the mandated `retry_after`. This test asserts the adapter is
  NOT called a second time until well past the naive 1s mark (1.7s
  elapsed), which the current code already violates (it retries at ~1s);
  only an implementation that actually honors `retry_after` over cadence
  passes.
- Phase 2: `cadence_s=2`, `backoff_base_s=0.15`, `backoff_max_s=0.5`,
  `max_attempts=3`. A correct implementation reaches 3 consecutive failures
  in well under a second (exponential, capped at `backoff_max_s`) -- the
  current code (cadence-only retries) would need ~4s to reach the same
  count, so a tight timeout after the first failure cleanly separates
  "backoff implemented" from "not implemented". A second window then proves
  retries genuinely PAUSE after `max_attempts` (ruling out "keep retrying at
  the capped interval forever", a plausible half-implementation), and a
  third window proves the 4th attempt resumes at the layer's OWN cadence
  (not sooner, not never).
- Phase 3: the current code never arms any stale timer at all (per
  `backend/scheduler.py`'s own top-of-file docstring: "Still out of scope
  (later scheduler slice 03): ... the event-driven stale *timer*"), so the
  `layer_status`/`stale` event this test waits for currently never arrives,
  and the wait cleanly times out.

Each phase, if the corresponding piece of slice 03 is missing, fails fast
(seconds, not minutes) via a bounded `asyncio.wait_for` -- never hangs the
suite/commit-hook.

It is authored and committed red by the test-author before any
implementation exists (strict xfail, DEC-33): none of `_do_fetch`'s error
handling honors `retry_after`/exponential backoff, and no stale timer is
armed anywhere in `backend/scheduler.py` yet, so this genuinely fails
against the current code and xfails cleanly under the tests-green gate.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
from typing import Callable

import pytest

from backend.config import AppConfig, LayerCfg
from backend.events import EventBus
from backend.models import Domain, LayerSnapshot, LayerSnapshotMeta, LayerStatus
from backend.registry import Registry
from backend.sources.base import PollAdapter, RateLimitedError, Region, UpstreamError

HORMUZ_REGION = Region(
    id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
)


def _make_land_cfg(
    *, cadence_s: int, backoff_base_s: float, backoff_max_s: float, max_attempts: int
) -> AppConfig:
    """A minimal AppConfig carrying only `land`, whose `[overpass]` backoff
    knobs (a plain `dict[str, Any]`, config.py `AppConfig.overpass`) this
    test overrides with small fractional seconds for a fast, deterministic
    real-time proof."""
    return AppConfig(
        regions=[],
        layers={
            "land": LayerCfg(
                enabled=True,
                cadence_s=cadence_s,
                cadence_floor_s=0,
                stale_multiplier=2,
                custom_bbox_cap_sq_deg=40,
            ),
        },
        overpass={
            "backoff_base_s": backoff_base_s,
            "backoff_max_s": backoff_max_s,
            "max_attempts": max_attempts,
        },
        opensky={},
        aisstream={},
        integrity={},
        server={},
    )


def _make_air_cfg(*, cadence_s: int, stale_multiplier: int) -> AppConfig:
    """A minimal AppConfig carrying only `air`; no backoff config needed for
    the stale-timer phase."""
    return AppConfig(
        regions=[],
        layers={
            "air": LayerCfg(
                enabled=True,
                cadence_s=cadence_s,
                cadence_floor_s=0,
                stale_multiplier=stale_multiplier,
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
    `with` block, then cancel it (slice 01/04 pattern -- `run()` owns an
    infinite `asyncio.TaskGroup`)."""
    task = asyncio.ensure_future(scheduler.run())
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, BaseExceptionGroup):
            await task


async def _wait_until(
    predicate: Callable[[], bool], *, timeout: float, interval: float = 0.02
) -> None:
    """Poll `predicate` until true or `timeout` elapses (bounded -- never
    hangs the suite/commit-hook on a missing behavior)."""

    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(interval)

    await asyncio.wait_for(_poll(), timeout=timeout)


async def _first_matching_event(
    subscriber: "asyncio.Queue", event_name: str, *, timeout: float
) -> dict:
    """Drain `subscriber` until an event named `event_name` arrives, or
    `timeout` elapses. Bounded regardless of how many non-matching events
    (e.g. an initial `snapshot`) arrive first."""

    async def _scan() -> dict:
        while True:
            item = await subscriber.get()
            if item["event"] == event_name:
                return item

    return await asyncio.wait_for(_scan(), timeout=timeout)


def _make_success_snapshot(domain: Domain, region: Region) -> LayerSnapshot:
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


class RateLimitedOnceAdapter(PollAdapter):
    """Raises `RateLimitedError(retry_after=...)` on the FIRST call only;
    every subsequent call succeeds -- pins the "next attempt deferred ~
    retry_after" clause without leaving the layer permanently broken."""

    source = "fake-overpass"

    def __init__(self, domain: Domain, retry_after: float) -> None:
        self.domain = domain
        self.retry_after = retry_after
        self.call_count = 0

    async def fetch(self, region: Region) -> LayerSnapshot:
        self.call_count += 1
        if self.call_count == 1:
            raise RateLimitedError(
                retry_after=self.retry_after, message="429 simulated"
            )
        return _make_success_snapshot(self.domain, region)


class UpstreamFailNTimesAdapter(PollAdapter):
    """Raises `UpstreamError` on the first `fail_calls` calls, then
    succeeds -- pins "exponential backoff, capped at max_attempts, then
    resume normal cadence"."""

    source = "fake-overpass"

    def __init__(self, domain: Domain, fail_calls: int) -> None:
        self.domain = domain
        self.fail_calls = fail_calls
        self.call_count = 0

    async def fetch(self, region: Region) -> LayerSnapshot:
        self.call_count += 1
        if self.call_count <= self.fail_calls:
            raise UpstreamError("simulated upstream failure")
        return _make_success_snapshot(self.domain, region)


class AlreadyAgedThenIdleAdapter(PollAdapter):
    """Succeeds exactly once (subsequent calls would be a bug for this test
    -- the poll loop's cadence is set far beyond the test window, so none
    are expected) with a `timestamp_source` deliberately backdated so that
    `source_ts + stale_after_s` -- the exact deadline the event-driven timer
    must fire at (scheduler.md) -- lands only `epsilon` REAL seconds in the
    future. This is not a shortcut around the spec's timing rule; it is the
    same rule, exercised with a data point that is legitimately already
    almost-stale the moment it is fetched (adapters report a source
    timestamp derived from the actual upstream data, which can be old on
    arrival)."""

    source = "fake-opensky"

    def __init__(self, domain: Domain, stale_after_s: int, epsilon: float) -> None:
        self.domain = domain
        self.stale_after_s = stale_after_s
        self.epsilon = epsilon
        self.call_count = 0

    async def fetch(self, region: Region) -> LayerSnapshot:
        self.call_count += 1
        now = datetime.now(timezone.utc)
        source_ts = now - timedelta(seconds=self.stale_after_s - self.epsilon)
        return LayerSnapshot(
            meta=LayerSnapshotMeta(
                layer=self.domain,
                region_id=region.id,
                status=LayerStatus.LIVE,
                timestamp_fetched=now,
                timestamp_source=source_ts,
                cadence_s=100,
                stale_after_s=self.stale_after_s,
                feature_count=0,
            ),
            features=[],
        )


@pytest.mark.xfail(
    reason="scheduler backoff + event-driven stale timer not yet implemented (#50)",
    strict=True,
)
async def test_scheduler_backoff_per_error_class_and_event_driven_stale_timer():
    from backend.scheduler import Scheduler

    # =========================================================================
    # Phase 1 -- Given a layer whose adapter raises RateLimitedError(retry_after=3)
    # When the scheduler handles it (via its own natural cadence tick, cadence_s=1)
    # Then the layer shows `rate-limited` (carrying retry_after_s) and the
    #      next attempt is deferred ~3s -- NOT at the layer's own, shorter
    #      1s cadence.
    # =========================================================================
    retry_after_s = 3.0
    land_adapter_1 = RateLimitedOnceAdapter(Domain.LAND, retry_after=retry_after_s)
    registry_1 = Registry()
    events_1 = EventBus()
    subscriber_1 = events_1.subscribe()
    cfg_1 = _make_land_cfg(
        cadence_s=1, backoff_base_s=5, backoff_max_s=300, max_attempts=4
    )
    scheduler_1 = Scheduler(
        cfg_1,
        {Domain.LAND: land_adapter_1},
        HORMUZ_REGION,
        registry=registry_1,
        events=events_1,
    )

    async with _running_scheduler(scheduler_1):
        # The layer's own 1s cadence drives the first (failing) attempt.
        await _wait_until(lambda: land_adapter_1.call_count >= 1, timeout=3.0)

        status_event = await _first_matching_event(
            subscriber_1, "layer_status", timeout=2.0
        )
        assert status_event["data"]["status"] == "rate-limited"
        assert status_event["data"]["retry_after_s"] == pytest.approx(retry_after_s)
        assert scheduler_1.current_status(Domain.LAND) == LayerStatus.RATE_LIMITED

        # Not sooner: comfortably past the layer's OWN 1s cadence (a naive
        # cadence-only retry would already have fired again by ~1s after the
        # failure) but still short of retry_after_s (3s).
        await asyncio.sleep(1.7)
        assert land_adapter_1.call_count == 1

        # The deferred retry lands around retry_after_s, not the 1s cadence.
        await _wait_until(lambda: land_adapter_1.call_count >= 2, timeout=3.0)
        assert land_adapter_1.call_count == 2

    # =========================================================================
    # Phase 2 -- When the adapter raises UpstreamError repeatedly
    # Then retries back off exponentially and cap at max_attempts before
    #      resuming the layer's normal cadence.
    # =========================================================================
    cadence_s_2 = 2
    backoff_base_s_2 = 0.15
    backoff_max_s_2 = 0.5
    max_attempts_2 = 3
    land_adapter_2 = UpstreamFailNTimesAdapter(Domain.LAND, fail_calls=max_attempts_2)
    registry_2 = Registry()
    events_2 = EventBus()
    cfg_2 = _make_land_cfg(
        cadence_s=cadence_s_2,
        backoff_base_s=backoff_base_s_2,
        backoff_max_s=backoff_max_s_2,
        max_attempts=max_attempts_2,
    )
    scheduler_2 = Scheduler(
        cfg_2,
        {Domain.LAND: land_adapter_2},
        HORMUZ_REGION,
        registry=registry_2,
        events=events_2,
    )

    async with _running_scheduler(scheduler_2):
        # The layer's own cadence drives the FIRST (failing) attempt.
        await _wait_until(lambda: land_adapter_2.call_count >= 1, timeout=4.0)

        # Exponential backoff (base=0.15s, max=0.5s) drives the remaining
        # two failures (reaching max_attempts=3) far faster than the 2s
        # cadence would allow on its own -- a tight 1.5s window here is
        # already impossible for a naive cadence-only retry loop (which
        # would need ~4s to reach count 3), cleanly separating "backoff
        # implemented" from "not implemented".
        await _wait_until(lambda: land_adapter_2.call_count >= 3, timeout=1.5)
        assert land_adapter_2.call_count == 3

        # After max_attempts is reached, retries PAUSE: comfortably beyond
        # backoff_max_s_2 (rules out "keep retrying at the capped interval
        # forever") but still short of the layer's cadence_s_2.
        await asyncio.sleep(backoff_max_s_2 + 0.4)
        assert land_adapter_2.call_count == 3

        # The 4th attempt resumes at the layer's OWN normal cadence.
        await _wait_until(lambda: land_adapter_2.call_count >= 4, timeout=3.0)
        assert land_adapter_2.call_count == 4

    # =========================================================================
    # Phase 3 -- Given a layer that fetched live data with no subsequent update
    # When the clock reaches source_ts + 2xcadence (stale_after_s)
    # Then the layer flips to `stale` via the timer and emits a
    #      `layer_status` event, with NO new fetch.
    # =========================================================================
    stale_after_s_3 = 200  # cadence_s=100 * stale_multiplier=2
    epsilon_3 = 0.4
    air_adapter_3 = AlreadyAgedThenIdleAdapter(
        Domain.AIR, stale_after_s=stale_after_s_3, epsilon=epsilon_3
    )
    registry_3 = Registry()
    events_3 = EventBus()
    subscriber_3 = events_3.subscribe()
    cfg_3 = _make_air_cfg(cadence_s=100, stale_multiplier=2)
    scheduler_3 = Scheduler(
        cfg_3,
        {Domain.AIR: air_adapter_3},
        HORMUZ_REGION,
        registry=registry_3,
        events=events_3,
    )

    async with _running_scheduler(scheduler_3):
        # A manual refresh() drives the one successful fetch deterministically
        # (the layer's 100s cadence is far outside this test's window, so the
        # natural poll loop never ticks here) -- the stale-timer arming lives
        # in the WRITE PATH (_handle_fetch_success), which refresh() exercises
        # identically to a scheduled tick.
        await scheduler_3.refresh(Domain.AIR)
        assert air_adapter_3.call_count == 1
        assert scheduler_3.current_status(Domain.AIR) == LayerStatus.LIVE
        assert registry_3[Domain.AIR].meta.status == LayerStatus.LIVE

        # The event-driven timer fires ~epsilon_3 REAL seconds later (because
        # source_ts + stale_after_s was deliberately arranged to be only that
        # far in the future), flipping live -> stale with NO new fetch.
        stale_event = await _first_matching_event(
            subscriber_3, "layer_status", timeout=3.0
        )
        assert stale_event["data"]["status"] == "stale"
        assert scheduler_3.current_status(Domain.AIR) == LayerStatus.STALE
        assert air_adapter_3.call_count == 1
