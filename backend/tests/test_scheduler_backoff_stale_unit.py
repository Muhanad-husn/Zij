"""Inner unit tests for scheduler step (issue #50), transcribed from the
plan's "Inner loop -- initial unit test list" (plans/scheduler/
03-backoff-stale.md) and design/specs/scheduler.md ("Backoff per error
class", "Status transitions" table's stale-timer rule).

The outer acceptance test (test_scheduler_backoff_stale.py) already proves,
end-to-end through the natural `_poll_loop` tick + `refresh()`: `retry_after`
honored over the layer's own cadence, exponential backoff capped at
`max_attempts` then resuming cadence, and the event-driven stale timer firing
`live -> stale` with no new fetch. These tests go one level narrower,
isolating gaps the single flowing outer scenario does not pin on its own:

  1. `_backoff_params` -- the config-knob-vs-default resolution itself
     (`[overpass]`/`[opensky]` sections vs the per-domain fallback), never
     exercised in isolation by the outer test.
  2. `_handle_fetch_failure` -- the RateLimitedError branch's status +
     published event, and the `AuthError`/`ParseError` no-auto-retry /
     last-good-snapshot-retained behavior, called directly (no real-time
     poll-loop wait needed for the pure status-mapping half).
  3. `retry_after` ABSENT -> config default backoff (the outer test only
     covers `retry_after` PRESENT).
  4. The attempt counter genuinely RESETS on success (not just "eventually
     resumes cadence after the cap", which the outer test's phase 2 already
     shows) -- proven by a failure AFTER an intervening success using the
     short, first-attempt delay again, not a continued, larger exponent.
  5. the developer's own documented decision (backend/scheduler.py
     `_poll_loop`'s `UpstreamError` branch) that the exponential backoff
     delay is additionally capped at the layer's own cadence, so a failing
     layer never polls LESS often than a healthy one -- NOT itself stated in
     design/specs/scheduler.md's "Backoff per error class" table (which
     reads only `min(base*2**n, max)`, capped at `max_attempts`). Pinned
     here so a future change to this behavior surfaces as a failing test,
     not silently; if this turns out not to match spec intent, that is a
     `spec discrepancy` question for the reviewer/maintainer, not a reason to loosen
     this test now.
  6. `AuthError` causes no auto-retry (i.e. NOT exponential backoff like
     `UpstreamError`) -- only the outer test's own error classes
     (RateLimited/Upstream) are exercised end-to-end there.
  7. `_arm_stale_timer`/`_cancel_stale_timer` in isolation: armed only for a
     LIVE snapshot, cancels a prior handle when rearmed, and (critically) a
     SECOND, later successful fetch genuinely cancels the FIRST timer so its
     now-stale deadline never fires a stray event -- the outer test's phase
     3 only ever arms one timer, so a bug that left an old handle alive
     after a rearm would not be caught there.

Fakes are duplicated locally (adapters, `_wait_until`/`_first_matching_event`
helpers) rather than imported from `test_scheduler_backoff_stale.py`,
mirroring that file's own convention and step/04's precedent for
independently-evolving test files.

`backend.scheduler` is imported inside test bodies (repo convention -- avoids
module-scope imports of app-wiring modules at collection time; here it also
just matches the sibling outer file's own style).

Written by the author (); the developer is separated
out of `backend/tests/` and may not edit this file.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from unittest.mock import AsyncMock

import pytest

from backend.config import AppConfig, LayerCfg
from backend.events import EventBus
from backend.models import Domain, LayerSnapshot, LayerSnapshotMeta, LayerStatus
from backend.registry import Registry
from backend.sources.base import (
    AuthError,
    ParseError,
    PollAdapter,
    RateLimitedError,
    Region,
    UpstreamError,
)

HORMUZ_REGION = Region(
    id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
)


def _make_cfg(
    *,
    land_cadence_s: int = 10,
    land_backoff_base_s: float | None = None,
    land_backoff_max_s: float | None = None,
    land_max_attempts: int | None = None,
    air_cadence_s: int = 100,
    air_stale_multiplier: int = 2,
    air_opensky: dict[str, Any] | None = None,
) -> AppConfig:
    """A minimal AppConfig carrying both `land`/`air`, whose `[overpass]`/
    `[opensky]` backoff knobs (plain `dict[str, Any]`) this test overrides
    selectively -- omitted knobs exercise the per-domain defaults."""
    overpass: dict[str, Any] = {}
    if land_backoff_base_s is not None:
        overpass["backoff_base_s"] = land_backoff_base_s
    if land_backoff_max_s is not None:
        overpass["backoff_max_s"] = land_backoff_max_s
    if land_max_attempts is not None:
        overpass["max_attempts"] = land_max_attempts
    return AppConfig(
        regions=[],
        layers={
            "land": LayerCfg(
                enabled=True,
                cadence_s=land_cadence_s,
                cadence_floor_s=0,
                stale_multiplier=2,
                custom_bbox_cap_sq_deg=40,
            ),
            "air": LayerCfg(
                enabled=True,
                cadence_s=air_cadence_s,
                cadence_floor_s=0,
                stale_multiplier=air_stale_multiplier,
                custom_bbox_cap_sq_deg=100,
            ),
        },
        overpass=overpass,
        opensky=air_opensky or {},
        aisstream={},
        integrity={},
        server={},
    )


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
    `timeout` elapses."""

    async def _scan() -> dict:
        while True:
            item = await subscriber.get()
            if item["event"] == event_name:
                return item

    return await asyncio.wait_for(_scan(), timeout=timeout)


def _make_snapshot(
    domain: Domain,
    region: Region,
    *,
    status: LayerStatus = LayerStatus.LIVE,
    timestamp_source: datetime | None = None,
    cadence_s: int = 1,
    stale_after_s: int = 2,
) -> LayerSnapshot:
    now = datetime.now(timezone.utc)
    return LayerSnapshot(
        meta=LayerSnapshotMeta(
            layer=domain,
            region_id=region.id,
            status=status,
            timestamp_fetched=now,
            timestamp_source=timestamp_source if timestamp_source is not None else now,
            cadence_s=cadence_s,
            stale_after_s=stale_after_s,
            feature_count=0,
        ),
        features=[],
    )


def _backdated_snapshot(
    domain: Domain, region: Region, *, stale_after_s: int, epsilon: float
) -> LayerSnapshot:
    """A LIVE snapshot whose `timestamp_source` is deliberately backdated so
    `source_ts + stale_after_s` lands only `epsilon` REAL seconds in the
    future -- same legitimate technique as the outer test's
    `AlreadyAgedThenIdleAdapter`."""
    now = datetime.now(timezone.utc)
    source_ts = now - timedelta(seconds=stale_after_s - epsilon)
    return _make_snapshot(
        domain,
        region,
        status=LayerStatus.LIVE,
        timestamp_source=source_ts,
        cadence_s=stale_after_s,
        stale_after_s=stale_after_s,
    )


SUCCESS = object()  # sentinel: "next fetch() call succeeds with a fresh snapshot"


class _ScriptedAdapter(PollAdapter):
    """Returns a fresh success snapshot or raises, per the ordered `script`
    (each item either a `BaseException` instance or the `SUCCESS` sentinel);
    the LAST item repeats forever once the script is exhausted. Records the
    monotonic time of each call (`call_times`) so tests can measure the
    real-time gap between consecutive attempts."""

    source = "fake"

    def __init__(self, domain: Domain, script: list) -> None:
        self.domain = domain
        self._script = list(script)
        self.call_count = 0
        self.call_times: list[float] = []

    async def fetch(self, region: Region) -> LayerSnapshot:
        self.call_count += 1
        self.call_times.append(asyncio.get_running_loop().time())
        item = self._script[min(self.call_count - 1, len(self._script) - 1)]
        if item is SUCCESS:
            return _make_snapshot(self.domain, region)
        assert isinstance(item, BaseException)
        raise item


class _NeverCalledAdapter(PollAdapter):
    """A PollAdapter double whose `fetch` fails the test if ever called --
    used to prove the stale-timer flip does NOT issue a new fetch."""

    source = "fake"

    def __init__(self, domain: Domain) -> None:
        self.domain = domain
        self.call_count = 0

    async def fetch(self, region: Region) -> LayerSnapshot:
        self.call_count += 1
        raise AssertionError("adapter.fetch must not be called by the stale timer")


@contextlib.asynccontextmanager
async def _running_poll_loop(scheduler, domain: Domain):
    task = asyncio.ensure_future(scheduler._poll_loop(domain))
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# =============================================================================
# 1. `_backoff_params` -- config knobs vs per-domain defaults.
# =============================================================================


async def test_backoff_params_land_reads_overpass_config_over_defaults():
    from backend.scheduler import Scheduler

    adapter = _ScriptedAdapter(Domain.LAND, [SUCCESS])
    cfg = _make_cfg(
        land_cadence_s=10,
        land_backoff_base_s=7.0,
        land_backoff_max_s=42.0,
        land_max_attempts=6,
    )
    scheduler = Scheduler(cfg, {Domain.LAND: adapter}, HORMUZ_REGION)

    assert scheduler._backoff_params(Domain.LAND) == (7.0, 42.0, 6)


async def test_backoff_params_air_default_matches_opensky_spec_when_config_omits_knobs():
    from backend.scheduler import Scheduler

    adapter = _ScriptedAdapter(Domain.AIR, [SUCCESS])
    # `air_opensky` deliberately omitted (empty {}) -- no backoff_base_s /
    # backoff_max_s of its own.
    cfg = _make_cfg(air_cadence_s=100, air_stale_multiplier=2)
    scheduler = Scheduler(cfg, {Domain.AIR: adapter}, HORMUZ_REGION)

    base_s, max_s, max_attempts = scheduler._backoff_params(Domain.AIR)

    # scheduler.md "Backoff per error class": "opensky default retry
    # schedule is min(60*2**n, 300)" -- i.e. base=60, max=300 -- when config
    # supplies no knobs of its own.
    assert base_s == 60.0
    assert max_s == 300.0
    assert isinstance(max_attempts, int) and max_attempts > 0


# =============================================================================
# 2. `_handle_fetch_failure` -- RateLimitedError status + published event.
# =============================================================================


async def test_handle_fetch_failure_rate_limited_sets_status_and_publishes_retry_after_event():
    from backend.scheduler import Scheduler

    adapter = _ScriptedAdapter(Domain.LAND, [SUCCESS])
    events = EventBus()
    subscriber = events.subscribe()
    cfg = _make_cfg()
    scheduler = Scheduler(cfg, {Domain.LAND: adapter}, HORMUZ_REGION, events=events)

    await scheduler._handle_fetch_failure(
        Domain.LAND, RateLimitedError(retry_after=17.0, message="429 simulated")
    )

    assert scheduler.current_status(Domain.LAND) == LayerStatus.RATE_LIMITED
    event = await _first_matching_event(subscriber, "layer_status", timeout=1.0)
    assert event["data"]["status"] == "rate-limited"
    assert event["data"]["retry_after_s"] == pytest.approx(17.0)


async def test_handle_fetch_failure_rate_limited_with_no_retry_after_publishes_none():
    from backend.scheduler import Scheduler

    adapter = _ScriptedAdapter(Domain.LAND, [SUCCESS])
    events = EventBus()
    subscriber = events.subscribe()
    cfg = _make_cfg()
    scheduler = Scheduler(cfg, {Domain.LAND: adapter}, HORMUZ_REGION, events=events)

    await scheduler._handle_fetch_failure(
        Domain.LAND, RateLimitedError(retry_after=None, message="429 simulated")
    )

    assert scheduler.current_status(Domain.LAND) == LayerStatus.RATE_LIMITED
    event = await _first_matching_event(subscriber, "layer_status", timeout=1.0)
    assert event["data"]["retry_after_s"] is None


# =============================================================================
# 3. `retry_after` ABSENT -> config default backoff (poll-loop timing; the
#    outer test only covers `retry_after` PRESENT).
# =============================================================================


async def test_poll_loop_rate_limited_without_retry_after_defers_by_config_backoff_default():
    backoff_base_s = 0.3
    cadence_s = 5  # far longer than this test's window
    adapter = _ScriptedAdapter(
        Domain.LAND,
        [RateLimitedError(retry_after=None, message="429 simulated"), SUCCESS],
    )
    cfg = _make_cfg(
        land_cadence_s=cadence_s,
        land_backoff_base_s=backoff_base_s,
        land_backoff_max_s=10.0,
        land_max_attempts=5,
    )
    from backend.scheduler import Scheduler

    scheduler = Scheduler(cfg, {Domain.LAND: adapter}, HORMUZ_REGION)

    async with _running_poll_loop(scheduler, Domain.LAND):
        scheduler._wake[Domain.LAND].set()  # immediate first (failing) attempt
        await _wait_until(lambda: adapter.call_count >= 1, timeout=2.0)

        # Not sooner than the configured default backoff.
        await asyncio.sleep(backoff_base_s * 0.5)
        assert adapter.call_count == 1

        # The retry lands around the configured default (~0.3s), well under
        # the layer's own 5s cadence -- proving the DEFAULT backoff drove it,
        # not a wait for the full cadence.
        await _wait_until(lambda: adapter.call_count >= 2, timeout=2.0)
        assert adapter.call_count == 2


# =============================================================================
# 4/5. UpstreamError exponential shape, attempt-counter reset on success, and
#      the cadence cap (developer's documented decision).
# =============================================================================


async def test_poll_loop_upstream_error_backoff_delays_grow_exponentially():
    from backend.scheduler import Scheduler

    base_s = 0.15
    cadence_s = 10  # far longer than this test's window
    adapter = _ScriptedAdapter(
        Domain.LAND,
        [UpstreamError("x"), UpstreamError("x"), UpstreamError("x"), SUCCESS],
    )
    cfg = _make_cfg(
        land_cadence_s=cadence_s,
        land_backoff_base_s=base_s,
        land_backoff_max_s=100.0,
        land_max_attempts=10,  # never reached in this window
    )
    scheduler = Scheduler(cfg, {Domain.LAND: adapter}, HORMUZ_REGION)

    async with _running_poll_loop(scheduler, Domain.LAND):
        scheduler._wake[Domain.LAND].set()
        await _wait_until(lambda: adapter.call_count >= 4, timeout=3.0)

    t = adapter.call_times
    delta1 = t[1] - t[0]  # expected ~ base_s * 2**0 = 0.15
    delta2 = t[2] - t[1]  # expected ~ base_s * 2**1 = 0.30
    delta3 = t[3] - t[2]  # expected ~ base_s * 2**2 = 0.60

    # Each successive gap is meaningfully larger than the last (exponential
    # growth, not a flat/linear backoff) -- generous ratio bounds tolerate
    # real-clock scheduling jitter while still ruling out "same delay every
    # time" or "linear +base_s every time".
    assert delta2 > delta1 * 1.5
    assert delta3 > delta2 * 1.5


async def test_upstream_backoff_attempt_counter_resets_after_a_success():
    """A success mid-sequence resets the attempt counter: the failure
    immediately AFTER a success must back off by the SHORT, first-attempt
    delay again -- not a larger delay that continued counting from before
    the success. A bug that failed to reset `attempts` on success would
    compute the third failure's delay as `base*2**2`, comfortably missing
    the tight window asserted below."""
    from backend.scheduler import Scheduler

    base_s = 0.12
    cadence_s = 1.0
    adapter = _ScriptedAdapter(
        Domain.LAND,
        [
            UpstreamError("x"),  # attempt 1 -> delay ~ base_s (0.12s)
            UpstreamError("x"),  # attempt 2 -> delay ~ base_s*2 (0.24s)
            SUCCESS,  # resets attempts to 0; next wait is normal cadence
            UpstreamError("x"),  # attempt 1 AGAIN (if reset) -> delay ~ base_s
            SUCCESS,
        ],
    )
    cfg = _make_cfg(
        land_cadence_s=cadence_s,
        land_backoff_base_s=base_s,
        land_backoff_max_s=10.0,
        land_max_attempts=10,
    )
    scheduler = Scheduler(cfg, {Domain.LAND: adapter}, HORMUZ_REGION)

    async with _running_poll_loop(scheduler, Domain.LAND):
        scheduler._wake[Domain.LAND].set()
        # Calls 1-3 (fail, fail, succeed) happen quickly via backoff, then
        # call 4 arrives after the post-success normal-cadence wait (~1s).
        await _wait_until(lambda: adapter.call_count >= 4, timeout=3.0)

        # If attempts were reset by the intervening success, call 5 (another
        # failure -> success) lands within a SHORT window comparable to
        # `base_s`, not the much larger `base_s * 2**2` a non-reset bug
        # would produce.
        await _wait_until(lambda: adapter.call_count >= 5, timeout=base_s * 4)
        assert adapter.call_count == 5


async def test_upstream_backoff_capped_at_the_layers_own_cadence_not_exceeding_it():
    """developer's documented decision (backend/scheduler.py `_poll_loop`
    UpstreamError branch): the exponential delay is additionally bounded
    above by the layer's own cadence, so a failing layer never polls LESS
    often than a healthy one. `base_s` is deliberately set larger than
    `cadence_s`, so the RAW exponential value (`base_s * 2**0`) would exceed
    cadence if uncapped -- only a cap-aware implementation retries within
    the tight window below."""
    from backend.scheduler import Scheduler

    base_s = 2.0  # > cadence_s: the raw exponential value would exceed cadence
    cadence_s = 1
    adapter = _ScriptedAdapter(Domain.LAND, [UpstreamError("x"), SUCCESS])
    cfg = _make_cfg(
        land_cadence_s=cadence_s,
        land_backoff_base_s=base_s,
        land_backoff_max_s=100.0,
        land_max_attempts=5,
    )
    scheduler = Scheduler(cfg, {Domain.LAND: adapter}, HORMUZ_REGION)

    async with _running_poll_loop(scheduler, Domain.LAND):
        scheduler._wake[Domain.LAND].set()
        await _wait_until(lambda: adapter.call_count >= 1, timeout=2.0)

        # The retry lands around cadence_s (~1s, the cap), comfortably
        # before the uncapped 2s exponential value.
        await _wait_until(lambda: adapter.call_count >= 2, timeout=1.6)
        assert adapter.call_count == 2


# =============================================================================
# 6. `AuthError`/`ParseError`: status mapping, no accelerated auto-retry,
#    last-good-snapshot retained.
# =============================================================================


async def test_handle_fetch_failure_auth_error_with_no_cache_yields_error():
    from backend.scheduler import Scheduler

    adapter = _ScriptedAdapter(Domain.LAND, [SUCCESS])
    store = AsyncMock()
    store.get_fallback = AsyncMock(return_value=None)
    cfg = _make_cfg()
    scheduler = Scheduler(cfg, {Domain.LAND: adapter}, HORMUZ_REGION, store=store)

    await scheduler._handle_fetch_failure(Domain.LAND, AuthError("bad credentials"))

    assert scheduler.current_status(Domain.LAND) == LayerStatus.ERROR


async def test_handle_fetch_failure_parse_error_with_warm_region_matched_cache_yields_cached_fallback():
    from backend.scheduler import Scheduler

    warm_row = _make_snapshot(Domain.LAND, HORMUZ_REGION)
    adapter = _ScriptedAdapter(Domain.LAND, [SUCCESS])
    store = AsyncMock()
    store.get_fallback = AsyncMock(return_value=warm_row)
    cfg = _make_cfg()
    scheduler = Scheduler(cfg, {Domain.LAND: adapter}, HORMUZ_REGION, store=store)

    await scheduler._handle_fetch_failure(Domain.LAND, ParseError("bad schema"))

    assert scheduler.current_status(Domain.LAND) == LayerStatus.CACHED_FALLBACK


async def test_poll_loop_auth_error_causes_no_accelerated_retry_just_normal_cadence():
    """`AuthError` must NOT be routed through the exponential-backoff path
    (that is `UpstreamError`'s alone, scheduler.md "Backoff per error
    class") -- the next attempt only comes at the layer's normal cadence.
    `backoff_base_s` is deliberately tiny: if `AuthError` were mistakenly
    treated like `UpstreamError`, the retry would land almost immediately,
    well before the assertion below."""
    from backend.scheduler import Scheduler

    cadence_s = 1
    adapter = _ScriptedAdapter(Domain.LAND, [AuthError("bad credentials"), SUCCESS])
    store = AsyncMock()
    store.get_fallback = AsyncMock(return_value=None)
    cfg = _make_cfg(
        land_cadence_s=cadence_s,
        land_backoff_base_s=0.05,
        land_backoff_max_s=0.1,
        land_max_attempts=5,
    )
    scheduler = Scheduler(cfg, {Domain.LAND: adapter}, HORMUZ_REGION, store=store)

    async with _running_poll_loop(scheduler, Domain.LAND):
        scheduler._wake[Domain.LAND].set()
        await _wait_until(lambda: adapter.call_count >= 1, timeout=2.0)
        assert scheduler.current_status(Domain.LAND) == LayerStatus.ERROR

        # Comfortably beyond the tiny backoff knobs (0.05s/0.1s) but still
        # short of the 1s cadence -- a bug routing AuthError through the
        # UpstreamError backoff branch would already have retried by here.
        await asyncio.sleep(0.3)
        assert adapter.call_count == 1

        # The retry eventually lands at the layer's own normal cadence.
        await _wait_until(lambda: adapter.call_count >= 2, timeout=1.5)
        assert adapter.call_count == 2


async def test_handle_fetch_failure_retains_last_good_snapshot_in_registry():
    from backend.scheduler import Scheduler

    registry = Registry()
    good_snap = _make_snapshot(Domain.LAND, HORMUZ_REGION)
    registry[Domain.LAND] = good_snap
    adapter = _ScriptedAdapter(Domain.LAND, [SUCCESS])
    cfg = _make_cfg()
    scheduler = Scheduler(cfg, {Domain.LAND: adapter}, HORMUZ_REGION, registry=registry)

    await scheduler._handle_fetch_failure(Domain.LAND, ParseError("bad schema"))

    # The registry's last good snapshot is untouched by a failure -- the
    # SAME object, not replaced or mutated.
    assert registry[Domain.LAND] is good_snap


# =============================================================================
# 7. `_arm_stale_timer`/`_cancel_stale_timer` in isolation.
# =============================================================================


async def test_arm_stale_timer_fires_and_flips_live_to_stale_with_event_and_no_fetch():
    from backend.scheduler import Scheduler

    registry = Registry()
    events = EventBus()
    subscriber = events.subscribe()
    adapter = _NeverCalledAdapter(Domain.AIR)
    cfg = _make_cfg(air_cadence_s=100, air_stale_multiplier=2)
    scheduler = Scheduler(
        cfg, {Domain.AIR: adapter}, HORMUZ_REGION, registry=registry, events=events
    )

    epsilon = 0.15
    stale_after_s = 200
    snap = _backdated_snapshot(
        Domain.AIR, HORMUZ_REGION, stale_after_s=stale_after_s, epsilon=epsilon
    )
    registry[Domain.AIR] = snap
    scheduler._status[Domain.AIR] = LayerStatus.LIVE

    scheduler._arm_stale_timer(Domain.AIR, snap)
    assert scheduler._stale_timer[Domain.AIR] is not None

    event = await _first_matching_event(subscriber, "layer_status", timeout=2.0)

    assert event["data"]["status"] == "stale"
    assert scheduler.current_status(Domain.AIR) == LayerStatus.STALE
    assert registry[Domain.AIR].meta.status == LayerStatus.STALE
    assert adapter.call_count == 0  # no new fetch -- purely time-derived


async def test_arm_stale_timer_is_a_no_op_for_a_non_live_snapshot():
    from backend.scheduler import Scheduler

    adapter = _ScriptedAdapter(Domain.AIR, [SUCCESS])
    cfg = _make_cfg(air_cadence_s=100, air_stale_multiplier=2)
    scheduler = Scheduler(cfg, {Domain.AIR: adapter}, HORMUZ_REGION)

    already_stale_snap = _make_snapshot(
        Domain.AIR, HORMUZ_REGION, status=LayerStatus.STALE
    )

    scheduler._arm_stale_timer(Domain.AIR, already_stale_snap)

    # Nothing to flip from `stale` -- no timer armed.
    assert scheduler._stale_timer[Domain.AIR] is None


async def test_arm_stale_timer_cancels_the_prior_handle_when_rearmed():
    from backend.scheduler import Scheduler

    adapter = _ScriptedAdapter(Domain.AIR, [SUCCESS])
    cfg = _make_cfg(air_cadence_s=100, air_stale_multiplier=2)
    scheduler = Scheduler(cfg, {Domain.AIR: adapter}, HORMUZ_REGION)

    far_future_snap_1 = _make_snapshot(
        Domain.AIR,
        HORMUZ_REGION,
        status=LayerStatus.LIVE,
        cadence_s=10_000,
        stale_after_s=10_000,
    )
    scheduler._arm_stale_timer(Domain.AIR, far_future_snap_1)
    first_handle = scheduler._stale_timer[Domain.AIR]
    assert first_handle is not None
    assert first_handle.cancelled() is False

    far_future_snap_2 = _make_snapshot(
        Domain.AIR,
        HORMUZ_REGION,
        status=LayerStatus.LIVE,
        cadence_s=10_000,
        stale_after_s=10_000,
    )
    scheduler._arm_stale_timer(Domain.AIR, far_future_snap_2)
    second_handle = scheduler._stale_timer[Domain.AIR]

    assert second_handle is not None
    assert second_handle is not first_handle
    assert first_handle.cancelled() is True  # the prior handle was cancelled


async def test_a_newer_successful_fetch_reschedules_the_stale_timer_so_the_old_deadline_never_fires():
    """Two successive fetches through `refresh()`: the FIRST snapshot's
    stale deadline lands shortly after the SECOND, fresh snapshot has
    already replaced it in the registry. Proves the old timer handle is
    genuinely CANCELLED on rearm (not merely superseded in intent) -- a bug
    that left the first handle alive would still flip the layer to `stale`
    (and emit a stray event) at the old, now-irrelevant deadline even though
    fresher data already arrived.

    `_handle_fetch_success` recomputes `meta.stale_after_s` authoritatively
    from config (`cadence_s * stale_multiplier`, scheduler.md "Compute
    authoritative meta") on EVERY write, so both fetches share the same
    6s `stale_after_s` -- only `timestamp_source` differs between them:
    the first is deliberately backdated so its deadline lands ~epsilon
    seconds away; the second is fresh (deadline ~6s away, far outside this
    test's window)."""
    from backend.scheduler import Scheduler

    cadence_s = 3
    stale_multiplier = 2  # config-derived stale_after_s = 6s for BOTH fetches
    epsilon_1 = 0.3  # first snapshot's deadline, ~0.3s after it is armed

    now = datetime.now(timezone.utc)
    snap_1 = _make_snapshot(
        Domain.AIR,
        HORMUZ_REGION,
        status=LayerStatus.LIVE,
        timestamp_source=now
        - timedelta(seconds=(cadence_s * stale_multiplier) - epsilon_1),
    )
    snap_2 = _make_snapshot(
        Domain.AIR, HORMUZ_REGION, status=LayerStatus.LIVE, timestamp_source=now
    )
    adapter = _ScriptedAdapter(Domain.AIR, [SUCCESS])
    # Override fetch() to serve the two scripted snapshots directly (rather
    # than the generic _make_snapshot the SUCCESS sentinel would build) so
    # each carries the exact backdated/fresh timestamp this test needs.
    results = [snap_1, snap_2]

    async def _fetch(region: Region) -> LayerSnapshot:
        adapter.call_count += 1
        return results.pop(0)

    adapter.fetch = _fetch  # type: ignore[method-assign]

    registry = Registry()
    events = EventBus()
    subscriber = events.subscribe()
    cfg = _make_cfg(air_cadence_s=cadence_s, air_stale_multiplier=stale_multiplier)
    scheduler = Scheduler(
        cfg, {Domain.AIR: adapter}, HORMUZ_REGION, registry=registry, events=events
    )

    # First fetch arms a timer at the SHORT deadline (~epsilon_1 away).
    await scheduler.refresh(Domain.AIR)
    assert scheduler.current_status(Domain.AIR) == LayerStatus.LIVE

    # Second fetch, immediately after, replaces the snapshot and must cancel
    # the first (short-deadline) timer, rearming a far-future one instead.
    await scheduler.refresh(Domain.AIR)
    assert scheduler.current_status(Domain.AIR) == LayerStatus.LIVE

    # Wait past the FIRST snapshot's now-irrelevant deadline. If the old
    # timer were still alive, it would have fired here, flipping status to
    # `stale` and publishing a stray `layer_status` event.
    await asyncio.sleep(epsilon_1 + 0.3)

    assert scheduler.current_status(Domain.AIR) == LayerStatus.LIVE
    with pytest.raises(asyncio.TimeoutError):
        await _first_matching_event(subscriber, "layer_status", timeout=0.1)
