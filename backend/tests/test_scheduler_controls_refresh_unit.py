"""Inner unit test for api-core step (issue #55), transcribed from the
plan's "Inner loop -- initial unit test list"
(plans/api-core/03-controls-refresh.md):

  - "Only enabled layers appear in the refresh_all queued list."

The outer acceptance test (backend/tests/test_api.py::
test_layer_toggle_and_refresh_controls_delegate_and_surface_failures_via_sse)
drives `POST /api/refresh` against an `AsyncMock` scheduler whose
`refresh_all` is pre-configured with a fixed return value (`[air, land]`) --
that proves the ROUTE echoes back whatever the scheduler reports, but never
exercises the real `Scheduler.refresh_all` filtering logic itself (the
mock's return value is scripted by the test, not computed by
`backend/scheduler.py`). This test closes that gap directly against the real
`Scheduler`: with air enabled and land disabled, `refresh_all()` must queue
(and actually fetch) only air, leaving land's adapter completely untouched --
a stub that hardcoded "every adapter present" would pass the outer test's
mocked Part A but fail this one.

`backend.scheduler` is imported inside the test body (repo convention -- see
the durable memory note on avoiding module-scope imports of app-wiring
modules at collection time).

Written by the author (); the developer is separated
out of `backend/tests/` and may not edit this file.
"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.config import AppConfig, LayerCfg
from backend.models import Domain, LayerSnapshot, LayerSnapshotMeta, LayerStatus
from backend.sources.base import PollAdapter, Region

HORMUZ_REGION = Region(
    id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
)


def _make_snapshot(domain: Domain, region: Region) -> LayerSnapshot:
    """A minimal, valid LayerSnapshot -- content is irrelevant here; only
    which adapters get called (and how many times) matters."""
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
    """Minimal PollAdapter double: counts `fetch` calls (redefined locally --
    mirrors test_scheduler_unit.py's own precedent for not cross-importing
    test modules)."""

    source = "fake"

    def __init__(self, domain: Domain) -> None:
        self.domain = domain
        self.call_count = 0

    async def fetch(self, region: Region) -> LayerSnapshot:
        self.call_count += 1
        return _make_snapshot(self.domain, region)


def _make_cfg(*, air_enabled: bool, land_enabled: bool) -> AppConfig:
    return AppConfig(
        regions=[],
        layers={
            "air": LayerCfg(
                enabled=air_enabled,
                cadence_s=1,
                cadence_floor_s=0,
                custom_bbox_cap_sq_deg=100,
            ),
            "land": LayerCfg(
                enabled=land_enabled,
                cadence_s=1,
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


async def test_refresh_all_queues_and_fetches_only_enabled_poll_layers():
    from backend.scheduler import Scheduler

    air_adapter = _CountingAdapter(Domain.AIR)
    land_adapter = _CountingAdapter(Domain.LAND)
    cfg = _make_cfg(air_enabled=True, land_enabled=False)
    scheduler = Scheduler(
        cfg, {Domain.AIR: air_adapter, Domain.LAND: land_adapter}, HORMUZ_REGION
    )

    # ---------------------------------------------------------------
    # When: refresh_all() runs with air enabled and land disabled.
    # ---------------------------------------------------------------
    queued = await scheduler.refresh_all()

    # ---------------------------------------------------------------
    # Then: only air is reported queued -- the real filtering logic, not a
    # scripted mock return value.
    # ---------------------------------------------------------------
    assert queued == [Domain.AIR]

    # And: land's adapter was never actually called -- a disabled layer is
    # genuinely excluded from the upstream fetch, not merely omitted from
    # the returned list while still being fetched underneath.
    assert air_adapter.call_count == 1
    assert land_adapter.call_count == 0


async def test_refresh_all_returns_empty_list_when_no_poll_layers_enabled():
    from backend.scheduler import Scheduler

    air_adapter = _CountingAdapter(Domain.AIR)
    land_adapter = _CountingAdapter(Domain.LAND)
    cfg = _make_cfg(air_enabled=False, land_enabled=False)
    scheduler = Scheduler(
        cfg, {Domain.AIR: air_adapter, Domain.LAND: land_adapter}, HORMUZ_REGION
    )

    queued = await scheduler.refresh_all()

    assert queued == []
    assert air_adapter.call_count == 0
    assert land_adapter.call_count == 0
