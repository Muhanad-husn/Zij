"""Unit tests for two small scheduler enhancements (issues #87, #88).

Authored test-first: the red contract (all three gap tests below
`xfail(strict=True)`, the rest of this file already green) landed at
`a84f6b9`, before either behavior was implemented. Both were then greened in
`backend/scheduler.py`; this follow-up removes the now-satisfied `xfail`
markers, closing the contract (never loosening it).

Issue #87 (design/specs/scheduler.md "Status transitions" table, row
`rate-limited | still failing, warm cache | cached-fallback`):
`_handle_fetch_failure` used to map EVERY `RateLimitedError` to
`rate-limited` and return immediately -- the `store.get_fallback`
cached-fallback gate below it was only ever reached by non-`RateLimitedError`
exceptions, so this spec row was unreachable. It now falls through to that
same gate on a REPEATED rate-limited failure. These tests pin:
  1. The FIRST rate-limited failure stays `rate-limited` even with a warm
     cache already sitting in the store (unchanged behavior -- spec row
     `live`/`cached-fallback` -> `RateLimitedError` -> `rate-limited`).
  2. A REPEATED rate-limited failure (layer already `rate-limited`) with a
     warm, REGION-MATCHED fallback degrades to `cached-fallback` (#87).
  3. A repeated rate-limited failure with NO warm cache stays
     `rate-limited` (no false degrade).
  4. A repeated rate-limited failure with a warm but MISMATCHED-region
     fallback also stays `rate-limited` (the "warm cache" in the spec row
     means region-matched, same gate the non-rate-limited branch already
     enforces -- storage.md NOTE / scheduler.md "cached-fallback beats
     error").

Issue #88 (scheduler.md "Region-switch sequence" step 3 + "Status
transitions" stale-timer rule): `_repopulate_land`/`_repopulate_fallback`
used to write a LIVE snapshot into the registry/SSE on a region switch
without calling `_arm_stale_timer` -- a repopulated layer never flipped
live->stale on its own schedule (up to 24h for land) until the next real
fetch happened to land. Both now call `_arm_stale_timer` at the end of their
write, exactly like `_handle_fetch_success`. These tests directly drive
`_repopulate_land`/`_repopulate_fallback` with a deliberately backdated
`timestamp_source` (same technique as `test_scheduler_backoff_stale_unit.py`'s
`_backdated_snapshot`/`epsilon`) and assert the one-shot stale flip fires on
schedule with NO new fetch, for the land cache-repopulate path and the air
fallback-repopulate path.

Direct calls to `_handle_fetch_failure`/`_repopulate_land`/
`_repopulate_fallback`, and pre-seeding `scheduler._status[...]` directly as
an arrange step, are the same idioms already used by
`test_scheduler_backoff_stale_unit.py` and `test_scheduler_region_toggle_unit.py`
-- reused here rather than invented fresh. Fakes/helpers are duplicated
locally rather than imported cross-module, mirroring both sibling files'
stated convention.

`backend.scheduler` is imported inside test bodies (repo convention -- avoids
module-scope imports of app-wiring modules at collection time).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.config import AppConfig, LayerCfg
from backend.events import EventBus
from backend.models import Domain, LayerSnapshot, LayerSnapshotMeta, LayerStatus
from backend.registry import Registry
from backend.sources.base import PollAdapter, RateLimitedError, Region
from backend.store import LandCacheRow

REGION_A = Region(id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5))
REGION_B = Region(id="malacca", label="Strait of Malacca", bbox=(98.0, 1.0, 104.0, 6.0))


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


def _make_land_row(
    region: Region, *, fetched_at: datetime, osm_base: datetime
) -> LandCacheRow:
    """A minimal, valid LandCacheRow -- `osm_base` (source timestamp) and
    `fetched_at` (fetch timestamp) are independently controllable so a test
    can keep the row FRESH by the `_repopulate_land` freshness gate
    (`now - fetched_at < cadence_s`) while separately backdating `osm_base`
    to control the stale-timer deadline (`osm_base + stale_after_s`)."""
    return LandCacheRow(
        region_id=region.id,
        bbox=region.bbox,
        geojson={"type": "FeatureCollection", "features": []},
        feature_count=0,
        osm_base=osm_base,
        fetched_at=fetched_at,
    )


class _NoOpAdapter(PollAdapter):
    """A PollAdapter placeholder never actually driven in these tests -- only
    its presence in `adapters` matters (marks a domain as one the scheduler
    owns, so its `_stale_timer`/`_cancel_gen`/etc. slots are initialized by
    the constructor loop)."""

    source = "noop"

    def __init__(self, domain: Domain) -> None:
        self.domain = domain

    async def fetch(self, region: Region) -> LayerSnapshot:
        raise AssertionError("fetch should not be called in these unit tests")


class _FakeStore:
    """A hand-written Store double (no I/O needed) recording every
    `get_fallback`/`get_land_cache` call -- mirrors
    `test_scheduler_region_toggle_unit.py`'s `FakeStore`."""

    def __init__(
        self,
        *,
        fallback_by_layer: dict[str, LayerSnapshot | None] | None = None,
        land_row: LandCacheRow | None = None,
    ) -> None:
        self._fallback_by_layer = fallback_by_layer or {}
        self._land_row = land_row
        self.get_fallback_calls: list[str] = []
        self.get_land_cache_calls: list[str] = []

    async def get_fallback(self, layer: str) -> LayerSnapshot | None:
        self.get_fallback_calls.append(layer)
        return self._fallback_by_layer.get(layer)

    async def get_land_cache(self, region_id: str) -> LandCacheRow | None:
        self.get_land_cache_calls.append(region_id)
        return self._land_row

    async def put_fallback(self, snap: LayerSnapshot) -> None:
        pass

    async def put_config_override(self, name: str, payload: dict[str, Any]) -> None:
        pass


def _make_cfg(**layers: LayerCfg) -> AppConfig:
    return AppConfig(
        regions=[],
        layers=layers,
        overpass={},
        opensky={},
        aisstream={},
        integrity={},
        server={},
    )


def _land_layer(**overrides: Any) -> LayerCfg:
    defaults: dict[str, Any] = dict(
        enabled=False,
        cadence_s=100,
        cadence_floor_s=0,
        stale_multiplier=1,
        custom_bbox_cap_sq_deg=40,
    )
    defaults.update(overrides)
    return LayerCfg(**defaults)


def _air_layer(**overrides: Any) -> LayerCfg:
    defaults: dict[str, Any] = dict(
        enabled=False,
        cadence_s=60,
        cadence_floor_s=0,
        stale_multiplier=2,
        custom_bbox_cap_sq_deg=100,
    )
    defaults.update(overrides)
    return LayerCfg(**defaults)


async def _first_matching_event(
    subscriber: "asyncio.Queue", event_name: str, *, timeout: float
) -> dict:
    """Drain `subscriber` until an event named `event_name` arrives, or
    `timeout` elapses (matches `test_scheduler_backoff_stale_unit.py`)."""

    async def _scan() -> dict:
        while True:
            item = await subscriber.get()
            if item["event"] == event_name:
                return item

    return await asyncio.wait_for(_scan(), timeout=timeout)


# =============================================================================
# #87 -- repeated 429 with a warm cache degrades rate-limited -> cached-fallback
# =============================================================================


async def test_handle_fetch_failure_first_rate_limited_stays_rate_limited_even_with_warm_cache():
    """spec row: `live`/`cached-fallback` -> `RateLimitedError` -> `rate-
    limited` (NOT `cached-fallback`) -- a warm cache existing must not, by
    itself, change the FIRST rate-limited failure's status. Already-correct
    today (current `_handle_fetch_failure` returns on `RateLimitedError`
    unconditionally); pinned green (no xfail) as a regression guard for the
    #87 change made below it -- a fix that consulted the cache on every
    `RateLimitedError` regardless of prior status would wrongly degrade this
    FIRST failure too."""
    from backend.scheduler import Scheduler

    adapter = _NoOpAdapter(Domain.LAND)
    warm_row = _make_snapshot(Domain.LAND, REGION_A)
    store = AsyncMock()
    store.get_fallback = AsyncMock(return_value=warm_row)
    events = EventBus()
    subscriber = events.subscribe()
    cfg = _make_cfg(land=_land_layer())
    scheduler = Scheduler(
        cfg, {Domain.LAND: adapter}, REGION_A, store=store, events=events
    )
    assert scheduler.current_status(Domain.LAND) != LayerStatus.RATE_LIMITED

    await scheduler._handle_fetch_failure(
        Domain.LAND, RateLimitedError(retry_after=9.0, message="429 simulated")
    )

    assert scheduler.current_status(Domain.LAND) == LayerStatus.RATE_LIMITED
    event = await _first_matching_event(subscriber, "layer_status", timeout=1.0)
    assert event["data"]["status"] == "rate-limited"
    assert event["data"]["retry_after_s"] == pytest.approx(9.0)


async def test_handle_fetch_failure_repeated_rate_limited_with_warm_matched_cache_degrades_to_cached_fallback():
    """scheduler.md Status transitions row: `rate-limited | still failing,
    warm cache | cached-fallback`. A layer already `rate-limited` that fails
    again with `RateLimitedError` while a warm, region-matched fallback row
    exists must degrade to `cached-fallback` -- serving the cache rather
    than parking indefinitely at `rate-limited`.

    feature-schema.md: `retry_after_s: float | None = None  # set when
    status == rate-limited` -- once the status is no longer `rate-limited`
    (here, degraded to `cached-fallback`), the published event's
    `retry_after_s` must be `None`, not a leftover leak of the
    `RateLimitedError`'s own `retry_after` value. The sibling non-rate-
    limited failure gate (`test_scheduler_backoff_stale_unit.py`'s
    `ParseError`/`cached-fallback` tests) already behaves this way; this
    branch must match it."""
    from backend.scheduler import Scheduler

    adapter = _NoOpAdapter(Domain.LAND)
    warm_row = _make_snapshot(Domain.LAND, REGION_A)
    store = AsyncMock()
    store.get_fallback = AsyncMock(return_value=warm_row)
    events = EventBus()
    subscriber = events.subscribe()
    cfg = _make_cfg(land=_land_layer())
    scheduler = Scheduler(
        cfg, {Domain.LAND: adapter}, REGION_A, store=store, events=events
    )
    scheduler._status[Domain.LAND] = LayerStatus.RATE_LIMITED  # already failing

    await scheduler._handle_fetch_failure(
        Domain.LAND,
        RateLimitedError(retry_after=9.0, message="429 simulated again"),
    )

    assert scheduler.current_status(Domain.LAND) == LayerStatus.CACHED_FALLBACK
    event = await _first_matching_event(subscriber, "layer_status", timeout=1.0)
    assert event["data"]["status"] == "cached-fallback"
    assert event["data"]["retry_after_s"] is None


async def test_handle_fetch_failure_repeated_rate_limited_without_warm_cache_stays_rate_limited():
    """No false degrade: a layer already `rate-limited` that fails again
    with NO warm cache available at all must stay `rate-limited`, never
    fall through to `cached-fallback` or `error`."""
    from backend.scheduler import Scheduler

    adapter = _NoOpAdapter(Domain.LAND)
    store = AsyncMock()
    store.get_fallback = AsyncMock(return_value=None)
    events = EventBus()
    subscriber = events.subscribe()
    cfg = _make_cfg(land=_land_layer())
    scheduler = Scheduler(
        cfg, {Domain.LAND: adapter}, REGION_A, store=store, events=events
    )
    scheduler._status[Domain.LAND] = LayerStatus.RATE_LIMITED

    await scheduler._handle_fetch_failure(
        Domain.LAND,
        RateLimitedError(retry_after=9.0, message="429 simulated again"),
    )

    assert scheduler.current_status(Domain.LAND) == LayerStatus.RATE_LIMITED
    event = await _first_matching_event(subscriber, "layer_status", timeout=1.0)
    assert event["data"]["status"] == "rate-limited"
    # Still `rate-limited` -> the event must carry the real retry_after_s
    # (feature-schema.md: "set when status == rate-limited"), not None.
    assert event["data"]["retry_after_s"] == pytest.approx(9.0)


async def test_handle_fetch_failure_repeated_rate_limited_with_mismatched_region_cache_stays_rate_limited():
    """The "warm cache" in the spec row means region-matched, the same gate
    the non-rate-limited branch already enforces (storage.md NOTE:
    `fallback_snapshots` is keyed by layer only, so a mismatched-region row
    must never be shown). A fallback row that exists but belongs to a
    DIFFERENT region must not trigger the degrade -- the layer stays
    `rate-limited`."""
    from backend.scheduler import Scheduler

    adapter = _NoOpAdapter(Domain.LAND)
    mismatched_row = _make_snapshot(Domain.LAND, REGION_B)  # wrong region
    store = AsyncMock()
    store.get_fallback = AsyncMock(return_value=mismatched_row)
    events = EventBus()
    subscriber = events.subscribe()
    cfg = _make_cfg(land=_land_layer())
    scheduler = Scheduler(
        cfg, {Domain.LAND: adapter}, REGION_A, store=store, events=events
    )
    scheduler._status[Domain.LAND] = LayerStatus.RATE_LIMITED

    await scheduler._handle_fetch_failure(
        Domain.LAND,
        RateLimitedError(retry_after=9.0, message="429 simulated again"),
    )

    assert scheduler.current_status(Domain.LAND) == LayerStatus.RATE_LIMITED
    event = await _first_matching_event(subscriber, "layer_status", timeout=1.0)
    assert event["data"]["status"] == "rate-limited"
    # Still `rate-limited` -> the event must carry the real retry_after_s
    # (feature-schema.md: "set when status == rate-limited"), not None.
    assert event["data"]["retry_after_s"] == pytest.approx(9.0)


# =============================================================================
# #88 -- region-switch cache repopulation arms the event-driven stale timer
# =============================================================================


async def test_repopulate_land_arms_the_stale_timer_so_it_flips_to_stale_on_schedule():
    from backend.scheduler import Scheduler

    stale_after_s = 100  # cadence_s(100) * stale_multiplier(1)
    epsilon = 0.25
    now = datetime.now(timezone.utc)
    fresh_row = _make_land_row(
        REGION_B,
        fetched_at=now - timedelta(seconds=5),  # well under cadence_s -> fresh
        osm_base=now - timedelta(seconds=stale_after_s - epsilon),
    )
    registry = Registry()
    events = EventBus()
    subscriber = events.subscribe()
    store = _FakeStore(land_row=fresh_row)
    cfg = _make_cfg(land=_land_layer(cadence_s=stale_after_s, stale_multiplier=1))
    scheduler = Scheduler(
        cfg,
        {Domain.LAND: _NoOpAdapter(Domain.LAND)},
        REGION_A,
        registry=registry,
        store=store,
        events=events,
    )

    await scheduler._repopulate_land(REGION_B)

    # Sanity: the cache genuinely repopulated live before we assert the timer.
    assert Domain.LAND in registry
    assert registry[Domain.LAND].meta.status == LayerStatus.LIVE

    event = await _first_matching_event(subscriber, "layer_status", timeout=2.0)

    assert event["data"]["status"] == "stale"
    assert scheduler.current_status(Domain.LAND) == LayerStatus.STALE
    assert registry[Domain.LAND].meta.status == LayerStatus.STALE


async def test_repopulate_fallback_air_arms_the_stale_timer_so_it_flips_to_stale_on_schedule():
    from backend.scheduler import Scheduler

    stale_after_s = 50
    epsilon = 0.25
    now = datetime.now(timezone.utc)
    fallback = _make_snapshot(
        Domain.AIR,
        REGION_B,
        status=LayerStatus.LIVE,
        timestamp_source=now - timedelta(seconds=stale_after_s - epsilon),
        cadence_s=25,
        stale_after_s=stale_after_s,
    )
    registry = Registry()
    events = EventBus()
    subscriber = events.subscribe()
    store = _FakeStore(fallback_by_layer={"air": fallback})
    cfg = _make_cfg(air=_air_layer())
    scheduler = Scheduler(
        cfg,
        {Domain.AIR: _NoOpAdapter(Domain.AIR)},
        REGION_A,
        registry=registry,
        store=store,
        events=events,
    )

    await scheduler._repopulate_fallback(Domain.AIR, REGION_B)

    # Sanity: the fallback genuinely repopulated live before we assert the
    # timer.
    assert Domain.AIR in registry
    assert registry[Domain.AIR].meta.status == LayerStatus.LIVE

    event = await _first_matching_event(subscriber, "layer_status", timeout=2.0)

    assert event["data"]["status"] == "stale"
    assert scheduler.current_status(Domain.AIR) == LayerStatus.STALE
    assert registry[Domain.AIR].meta.status == LayerStatus.STALE
