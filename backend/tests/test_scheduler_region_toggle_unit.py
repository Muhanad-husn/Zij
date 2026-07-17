"""Unit tests for scheduler region-switch and enable/disable (issue #52),
covering design/specs/scheduler.md ("Region-switch sequence", step 3;
"Enable/disable (FR5)").

The acceptance test (test_scheduler_region_toggle.py) already proves,
end-to-end through `activate_region`/`set_enabled`: cancel-generation
ignore, registry-clear + `region_changed` emit, the AIR fallback
region-match gate, `active_region` persistence, and poll-layer disable.
These tests go one level narrower, isolating the three gaps the acceptance
test does not pin on its own:

  1. The **MARINE** fallback region-match gate (`_repopulate_fallback`) --
     the acceptance test only exercises this for `air`; marine is injected via
     the `stream` kwarg (not `adapters`), a structurally different path
     through `activate_region`'s repopulation branch (see the `domain in
     self._adapters or (self._stream is not None and self._stream.domain
     == domain)` guard in `backend/scheduler.py`), so it needs its own
     proof, both the mismatched-region-rejected and matched-region-used
     halves.
  2. The **land cache freshness gate** (`_repopulate_land`) -- storage.md
     "Refresh cadence": `now - fetched_at < land.cadence_s` (config
     `land.cadence_s`, "Older -> re-fetch"). A fresh row is served without a
     fetch; a stale row is left alone (next scheduled fetch handles it).
     This is a spec-defined threshold (storage.md, not an implementation
     detail), so it is pinned exactly, not loosely.
  3. **Stream enable/disable** (`set_enabled` marine branch) -- disabling
     calls `stream.stop()` and issues zero `stream.start()` calls (FR5,
     "zero stream while disabled"); enabling calls `stream.start()` and the
     scheduler's own `current_status` reads back `loading`.

Fakes are duplicated locally rather than imported from
`test_scheduler_region_toggle.py`, mirroring that file's own stated
rationale for not cross-importing test modules (each test file stays
independently evolving) and the `test_scheduler_unit.py` precedent (its
`_make_snapshot` docstring: "redefined locally rather than imported
cross-module").

`backend.scheduler` is imported inside test bodies (repo convention -- see
the note on avoiding module-scope imports of app-wiring modules at collection
time).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from backend.config import AppConfig, LayerCfg
from backend.events import EventBus
from backend.models import Domain, LayerSnapshot, LayerSnapshotMeta, LayerStatus
from backend.registry import Registry
from backend.sources.base import PollAdapter, Region, StreamAdapter
from backend.store import LandCacheRow

REGION_A = Region(id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5))
REGION_B = Region(id="malacca", label="Strait of Malacca", bbox=(98.0, 1.0, 104.0, 6.0))


def _make_snapshot(domain: Domain, region: Region) -> LayerSnapshot:
    """A minimal, valid LayerSnapshot for `domain`/`region` (redefined
    locally -- see module docstring)."""
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


def _make_land_row(region: Region, *, fetched_at: datetime) -> LandCacheRow:
    """A minimal, valid LandCacheRow with zero features (content is
    irrelevant to the freshness gate; only `fetched_at` matters)."""
    return LandCacheRow(
        region_id=region.id,
        bbox=region.bbox,
        geojson={"type": "FeatureCollection", "features": []},
        feature_count=0,
        osm_base=fetched_at,
        fetched_at=fetched_at,
    )


class FakeStreamAdapter(StreamAdapter):
    """A StreamAdapter double recording every `start`/`stop`/`set_region`
    call (redefined locally -- see module docstring)."""

    domain = Domain.MARINE
    source = "fake-stream"

    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.set_region_calls: list[Region] = []
        self._connected = True

    async def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1

    async def set_region(self, region: Region) -> None:
        self.set_region_calls.append(region)

    def snapshot(self) -> LayerSnapshot:
        return _make_snapshot(Domain.MARINE, REGION_A)

    @property
    def connected(self) -> bool:
        return self._connected


class FakeStore:
    """A hand-written Store double (no I/O needed to prove the behavior under
    test). Records every `get_fallback`/`get_land_cache` call."""

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
        self.put_config_override_calls: list[tuple[str, dict[str, Any]]] = []

    async def get_fallback(self, layer: str) -> LayerSnapshot | None:
        self.get_fallback_calls.append(layer)
        return self._fallback_by_layer.get(layer)

    async def get_land_cache(self, region_id: str) -> LandCacheRow | None:
        self.get_land_cache_calls.append(region_id)
        return self._land_row

    async def put_fallback(self, snap: LayerSnapshot) -> None:
        pass

    async def put_config_override(self, name: str, payload: dict[str, Any]) -> None:
        self.put_config_override_calls.append((name, payload))


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


def _air_layer(**overrides: Any) -> LayerCfg:
    defaults: dict[str, Any] = dict(
        enabled=False, cadence_s=1, cadence_floor_s=0, custom_bbox_cap_sq_deg=100
    )
    defaults.update(overrides)
    return LayerCfg(**defaults)


def _land_layer(**overrides: Any) -> LayerCfg:
    defaults: dict[str, Any] = dict(
        enabled=False, cadence_s=86400, cadence_floor_s=3600, custom_bbox_cap_sq_deg=100
    )
    defaults.update(overrides)
    return LayerCfg(**defaults)


class _NoOpAirAdapter(PollAdapter):
    """A PollAdapter placeholder never actually driven in these tests --
    only its presence in `adapters` matters (marks `air`/`land` as a layer
    the scheduler owns, per the constructor loop)."""

    source = "noop"

    async def fetch(self, region: Region) -> LayerSnapshot:
        raise AssertionError("fetch should not be called in these unit tests")


# ---------------------------------------------------------------------------
# 1. MARINE fallback region-match gate (_repopulate_fallback, marine branch)
# ---------------------------------------------------------------------------


async def test_activate_region_marine_fallback_mismatched_region_not_used():
    """A marine fallback row tagged region A must NOT repopulate the
    registry under a switch to region B (region-matched only, storage.md
    NOTE / scheduler.md step 3)."""
    from backend.scheduler import Scheduler

    stream = FakeStreamAdapter()
    registry = Registry()
    marine_fallback_a = _make_snapshot(Domain.MARINE, REGION_A)
    store = FakeStore(fallback_by_layer={"marine": marine_fallback_a})
    cfg = _make_cfg()

    scheduler = Scheduler(
        cfg, {}, REGION_A, registry=registry, store=store, stream=stream
    )

    await scheduler.activate_region(REGION_B)

    assert "marine" in store.get_fallback_calls
    assert Domain.MARINE not in registry


async def test_activate_region_marine_fallback_matched_region_used():
    """A marine fallback row tagged region B DOES repopulate the registry
    under a switch to region B."""
    from backend.scheduler import Scheduler

    stream = FakeStreamAdapter()
    registry = Registry()
    marine_fallback_b = _make_snapshot(Domain.MARINE, REGION_B)
    store = FakeStore(fallback_by_layer={"marine": marine_fallback_b})
    events = EventBus()
    subscriber = events.subscribe()
    cfg = _make_cfg()

    scheduler = Scheduler(
        cfg,
        {},
        REGION_A,
        registry=registry,
        store=store,
        stream=stream,
        events=events,
    )

    await scheduler.activate_region(REGION_B)

    assert "marine" in store.get_fallback_calls
    assert Domain.MARINE in registry
    assert registry[Domain.MARINE].meta.region_id == REGION_B.id

    # Drain the `region_changed` event published first, then the marine
    # snapshot publish -- proving the repopulated row was genuinely
    # broadcast, not just written into the registry.
    region_event = await subscriber.get()
    assert region_event["event"] == "region_changed"
    snapshot_event = await subscriber.get()
    assert snapshot_event["event"] == "snapshot"
    assert snapshot_event["data"]["meta"]["region_id"] == REGION_B.id
    assert snapshot_event["data"]["meta"]["layer"] == Domain.MARINE.value


# ---------------------------------------------------------------------------
# 2. Land cache freshness gate (_repopulate_land)
# ---------------------------------------------------------------------------


async def test_activate_region_fresh_land_cache_repopulates_without_fetch():
    """storage.md "Refresh cadence": `now - fetched_at < land.cadence_s` ->
    serve from cache. A fresh row (fetched seconds ago, cadence_s=86400)
    lands in the registry for the NEW region without any fetch."""
    from backend.scheduler import Scheduler

    now = datetime.now(timezone.utc)
    fresh_row = _make_land_row(REGION_B, fetched_at=now - timedelta(seconds=5))
    registry = Registry()
    store = FakeStore(land_row=fresh_row)
    cfg = _make_cfg(land=_land_layer(cadence_s=86400, cadence_floor_s=3600))

    scheduler = Scheduler(
        cfg,
        {Domain.LAND: _NoOpAirAdapter()},
        REGION_A,
        registry=registry,
        store=store,
    )

    await scheduler.activate_region(REGION_B)

    assert REGION_B.id in store.get_land_cache_calls
    assert Domain.LAND in registry
    assert registry[Domain.LAND].meta.region_id == REGION_B.id
    assert scheduler.current_status(Domain.LAND) in (
        LayerStatus.LIVE,
        LayerStatus.CACHED_FALLBACK,
    )


async def test_activate_region_stale_land_cache_not_repopulated():
    """A row older than `land.cadence_s` (here: 2 days, cadence 24h) is left
    alone -- the next scheduled fetch handles it, not the region switch."""
    from backend.scheduler import Scheduler

    now = datetime.now(timezone.utc)
    stale_row = _make_land_row(REGION_B, fetched_at=now - timedelta(days=2))
    registry = Registry()
    store = FakeStore(land_row=stale_row)
    cfg = _make_cfg(land=_land_layer(cadence_s=86400, cadence_floor_s=3600))

    scheduler = Scheduler(
        cfg,
        {Domain.LAND: _NoOpAirAdapter()},
        REGION_A,
        registry=registry,
        store=store,
    )

    await scheduler.activate_region(REGION_B)

    assert REGION_B.id in store.get_land_cache_calls
    assert Domain.LAND not in registry


# ---------------------------------------------------------------------------
# 3. Stream enable/disable (set_enabled, marine branch)
# ---------------------------------------------------------------------------


async def test_set_enabled_marine_false_stops_stream_and_issues_no_restart():
    """FR5: disabling marine stops the stream (zero upstream spend) and
    issues no `start()` call."""
    from backend.scheduler import Scheduler

    stream = FakeStreamAdapter()
    cfg = _make_cfg()
    scheduler = Scheduler(cfg, {}, REGION_A, stream=stream)

    await scheduler.set_enabled(Domain.MARINE, False)

    assert stream.stop_calls == 1
    assert stream.start_calls == 0


async def test_set_enabled_marine_true_starts_stream_and_reports_loading():
    """FR5: enabling marine starts the stream and the scheduler's own
    status reader reflects `loading` (transient, "Enable/disable (FR5)")."""
    from backend.scheduler import Scheduler

    stream = FakeStreamAdapter()
    cfg = _make_cfg()
    scheduler = Scheduler(cfg, {}, REGION_A, stream=stream)

    await scheduler.set_enabled(Domain.MARINE, True)

    assert stream.start_calls == 1
    assert scheduler.current_status(Domain.MARINE) == LayerStatus.LOADING


# ---------------------------------------------------------------------------
# 4. Region-switch status reset on no-repopulation (scheduler.md "Region-
#    switch sequence" step 3, "else, loading"; "Status ownership": the
#    scheduler is the sole writer). Regression coverage for the "second
#    region switch shows stale status" bug: a layer that was previously
#    live/cached-fallback must not keep reporting that status after a switch
#    to a region for which no fresh cache/fallback repopulates it.
# ---------------------------------------------------------------------------


async def test_activate_region_marine_no_repopulation_resets_stale_status_to_loading():
    """A marine fallback row tagged region A does not repopulate a switch to
    region B (mismatched-region gate, section 1 above) -- and per step 3
    ("else, loading") the scheduler must also overwrite whatever status it
    was reporting before the switch, not leave the prior live/cached-fallback
    value stuck on screen."""
    from backend.scheduler import Scheduler

    stream = FakeStreamAdapter()
    registry = Registry()
    marine_fallback_a = _make_snapshot(Domain.MARINE, REGION_A)
    store = FakeStore(fallback_by_layer={"marine": marine_fallback_a})
    cfg = _make_cfg()

    scheduler = Scheduler(
        cfg, {}, REGION_A, registry=registry, store=store, stream=stream
    )
    # Arrange: seed a prior `live` status directly on the scheduler's own
    # state -- standing in for a first successful fetch/repopulation before
    # this second switch (see module docstring: writing `_status` directly
    # is the documented arrange step when pre-seeding through the public
    # surface would require a full fetch cycle).
    scheduler._status[Domain.MARINE] = LayerStatus.LIVE

    # The fallback row is tagged REGION_A -- mismatched against this switch.
    await scheduler.activate_region(REGION_B)

    assert scheduler.current_status(Domain.MARINE) == LayerStatus.LOADING


async def test_activate_region_marine_no_fallback_row_resets_stale_status_to_loading():
    """Same bug, `None` case: no fallback row at all (not just a mismatched
    one) must also clear a prior `cached-fallback` status to `loading`."""
    from backend.scheduler import Scheduler

    stream = FakeStreamAdapter()
    registry = Registry()
    store = FakeStore(fallback_by_layer={})
    cfg = _make_cfg()

    scheduler = Scheduler(
        cfg, {}, REGION_A, registry=registry, store=store, stream=stream
    )
    scheduler._status[Domain.MARINE] = LayerStatus.CACHED_FALLBACK

    await scheduler.activate_region(REGION_B)

    assert scheduler.current_status(Domain.MARINE) == LayerStatus.LOADING


async def test_activate_region_land_no_repopulation_resets_stale_status_to_loading():
    """Land equivalent: `get_land_cache` returning `None` for the new region
    must clear a prior non-loading land status to `loading`, not leave it
    stuck at whatever it reported for the old region."""
    from backend.scheduler import Scheduler

    registry = Registry()
    store = FakeStore(land_row=None)
    cfg = _make_cfg(land=_land_layer(cadence_s=86400, cadence_floor_s=3600))

    scheduler = Scheduler(
        cfg,
        {Domain.LAND: _NoOpAirAdapter()},
        REGION_A,
        registry=registry,
        store=store,
    )
    scheduler._status[Domain.LAND] = LayerStatus.CACHED_FALLBACK

    await scheduler.activate_region(REGION_B)

    assert scheduler.current_status(Domain.LAND) == LayerStatus.LOADING


async def test_activate_region_land_stale_cache_resets_stale_status_to_loading():
    """Land equivalent, stale-row case: a cached row older than
    `land.cadence_s` is left alone by the repopulation gate (section 2
    above) -- but the prior status must still be reset to `loading`, since
    the layer is genuinely awaiting its next scheduled fetch under the new
    region, not still showing the old region's data."""
    from backend.scheduler import Scheduler

    now = datetime.now(timezone.utc)
    stale_row = _make_land_row(REGION_B, fetched_at=now - timedelta(days=2))
    registry = Registry()
    store = FakeStore(land_row=stale_row)
    cfg = _make_cfg(land=_land_layer(cadence_s=86400, cadence_floor_s=3600))

    scheduler = Scheduler(
        cfg,
        {Domain.LAND: _NoOpAirAdapter()},
        REGION_A,
        registry=registry,
        store=store,
    )
    scheduler._status[Domain.LAND] = LayerStatus.LIVE

    await scheduler.activate_region(REGION_B)

    assert scheduler.current_status(Domain.LAND) == LayerStatus.LOADING


# ---------------------------------------------------------------------------
# 5. Marine-enable event carries the scheduler's authoritative status, not
#    the adapter's hardcoded one (scheduler.md "Status ownership": the
#    scheduler is the ONLY writer of LayerStatus). `FakeStreamAdapter.
#    snapshot()` (via `_make_snapshot`) hardcodes `status=LIVE` -- the
#    adapter has no notion of the scheduler's enable/disable state -- so the
#    published `layer_status` event must carry `loading`, stamped by the
#    scheduler, not the adapter's raw snapshot value. `current_status` alone
#    does not prove this: it is the on-the-wire event that must be correct.
# ---------------------------------------------------------------------------


async def test_set_enabled_marine_true_publishes_authoritative_loading_status():
    """Subscribes a real `EventBus` queue, enables marine, and asserts the
    emitted `layer_status` event's `data["status"]` is `loading`, not the
    adapter's hardcoded `live`."""
    from backend.scheduler import Scheduler

    stream = FakeStreamAdapter()
    cfg = _make_cfg()
    events = EventBus()
    subscriber = events.subscribe()
    scheduler = Scheduler(cfg, {}, REGION_A, stream=stream, events=events)

    await scheduler.set_enabled(Domain.MARINE, True)

    event = await subscriber.get()
    assert event["event"] == "layer_status"
    assert event["data"]["status"] == LayerStatus.LOADING.value
