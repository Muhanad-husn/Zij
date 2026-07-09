"""Scheduler core runtime (spec: design/specs/scheduler.md; plans:
plans/scheduler/01-core-runtime.md (issue #45),
plans/scheduler/02-status-write-path.md (issue #49),
plans/scheduler/04-region-toggle.md (issue #52)).

step laid the concurrency spine: one asyncio task per poll layer,
per-layer cadence independence (FR6), single-flight coalescing of manual
`refresh()` against an in-flight scheduled fetch (FR6), and enable/disable
parking a layer purely on `_wake` for zero upstream spend while disabled
(FR5).

step adds status ownership (FR7) and the write path (FR8/FR9/FR10): the
scheduler becomes the sole writer of `LayerStatus`, and every successful
fetch runs `integrity.apply -> registry[domain] = snap ->
events.publish_snapshot(snap) -> (air/marine only) await
store.put_fallback(snap)`, in that fixed order.

step (this file, grown) adds the region-switch sequence
(`activate_region`, ARCHITECTURE §4.2) and extends `set_enabled` to also
supervise an optional marine `StreamAdapter` (FR5). Per-layer cancellation
uses a generation counter (`_cancel_gen`), not literal task cancellation: a
completing old-region fetch is discarded on return by comparing the
generation captured at fetch-start against the current one.

Still out of scope (later scheduler step): backoff per error class, the
event-driven stale *timer* (stale is only computed at write time here).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from backend.config import AppConfig, effective_cadence_s
from backend.config import stale_after_s as _configured_stale_after_s
from backend.events import EventBus
from backend.integrity import Integrity, PrevPos
from backend.models import (
    Domain,
    Feature,
    GeometryType,
    LayerSnapshot,
    LayerSnapshotMeta,
    LayerStatus,
)
from backend.registry import Registry
from backend.sources.base import PollAdapter, Region, StreamAdapter
from backend.store import LandCacheRow, Store

logger = logging.getLogger(__name__)


def _geojson_feature_to_feature(gj_feature: dict[str, Any]) -> Feature:
    """Inverse of the `land_cache.geojson` encoding (storage.md). Mirrors
    `backend.main._geojson_to_feature`; kept local so `scheduler.py` does not
    depend on `main.py` (wrong dependency direction -- `main.py` wires the
    scheduler, not the other way around)."""
    properties = dict(gj_feature["properties"])
    if properties.get("geometry_type") == GeometryType.POINT.value:
        properties["geometry"] = None
    else:
        properties["geometry"] = gj_feature.get("geometry")
    return Feature.model_validate(properties)


def _land_snapshot_from_cache_row(
    row: LandCacheRow, *, cadence_s: int, stale_after_s: int
) -> LayerSnapshot:
    """Mirrors `backend.main._land_snapshot_from_cache_row` (same rationale
    as `_geojson_feature_to_feature` above)."""
    features = [
        _geojson_feature_to_feature(gj) for gj in row.geojson.get("features", [])
    ]
    meta = LayerSnapshotMeta(
        layer=Domain.LAND,
        region_id=row.region_id,
        status=LayerStatus.LIVE,
        timestamp_fetched=row.fetched_at,
        timestamp_source=row.osm_base,
        cadence_s=cadence_s,
        stale_after_s=stale_after_s,
        feature_count=row.feature_count,
    )
    return LayerSnapshot(meta=meta, features=features)


class Scheduler:
    """Owns one `_poll_loop(domain)` task per poll layer under a single
    `asyncio.TaskGroup` (spec "Task model"). Only the step subset of the
    full spec's control primitives is kept: `_enabled`, `_cadence_s`,
    `_inflight` (the single-flight coalescing token per layer), and `_wake`
    (manual refresh / enable kick).
    """

    def __init__(
        self,
        cfg: AppConfig,
        adapters: dict[Domain, PollAdapter],
        region: Region,
        *,
        registry: Registry | None = None,
        integrity: Integrity | None = None,
        store: Store | None = None,
        events: EventBus | None = None,
        stream: StreamAdapter | None = None,
    ) -> None:
        self._cfg = cfg
        self._adapters = adapters
        self._region = region
        self._registry = registry
        self._integrity = integrity
        self._store = store
        self._events = events
        self._stream = stream

        self._enabled: dict[Domain, bool] = {}
        self._cadence_s: dict[Domain, int] = {}
        self._inflight: dict[Domain, asyncio.Future[LayerSnapshot] | None] = {}
        self._wake: dict[Domain, asyncio.Event] = {}
        self._status: dict[Domain, LayerStatus] = {}
        self._cancel_gen: dict[Domain, int] = {}

        for domain, layer_cfg in ((d, cfg.layers[d.value]) for d in adapters):
            self._enabled[domain] = layer_cfg.enabled
            self._cadence_s[domain] = effective_cadence_s(layer_cfg)
            self._inflight[domain] = None
            self._wake[domain] = asyncio.Event()
            self._status[domain] = LayerStatus.LOADING
            self._cancel_gen[domain] = 0

        if stream is not None and stream.domain not in self._cancel_gen:
            # Marine supervised purely via the stream adapter (no poll loop
            # task, no `fetch`/cadence/enabled bookkeeping) -- still needs a
            # generation slot (`activate_region` bumps every layer's) and a
            # status/wake slot (`set_enabled`'s marine branch below).
            self._wake[stream.domain] = asyncio.Event()
            self._status[stream.domain] = LayerStatus.LOADING
            self._cancel_gen[stream.domain] = 0

    def current_status(self, domain: Domain) -> LayerStatus:
        """FR7 public reader (spec "Public interface"). The scheduler is the
        sole writer of `LayerStatus`; this only reads the last value it
        recorded for `domain`."""
        return self._status[domain]

    async def run(self) -> None:
        """Owns the `TaskGroup`; lifetime = app lifetime (spec "Task
        model"). One `_poll_loop(domain)` task per adapter this scheduler
        was constructed with."""
        async with asyncio.TaskGroup() as tg:
            for domain in self._adapters:
                tg.create_task(self._poll_loop(domain))

    async def _poll_loop(self, domain: Domain) -> None:
        """Cadence timing per spec: `asyncio.wait_for(_wake.wait(),
        timeout=cadence_s)` -- timeout is a scheduled tick, the event being
        set is a manual refresh/enable kick. A disabled layer parks purely
        on `_wake` (no timeout) for zero upstream spend (FR5); re-enabling
        sets `_wake` for an immediate first fetch."""
        wake = self._wake[domain]
        while True:
            if self._enabled[domain]:
                try:
                    await asyncio.wait_for(wake.wait(), timeout=self._cadence_s[domain])
                except TimeoutError:
                    pass
            else:
                await wake.wait()
            wake.clear()
            if self._enabled[domain]:
                # FR10: per-layer failure isolation -- a crashing adapter
                # must not kill the scheduler or a sibling layer's task.
                # Cancellation still propagates for clean shutdown.
                try:
                    await self._do_fetch(domain)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "layer %s: fetch failed, will retry next cadence tick",
                        domain,
                    )

    async def set_enabled(self, domain: Domain, enabled: bool) -> None:
        """FR5. Disabling parks the loop on `_wake` (checked on its next
        wake); enabling sets `_wake` for an immediate fetch.

        Marine variant (scheduler.md "Enable/disable (FR5)"): when `domain`
        is the injected stream's domain and it has no poll-loop task of its
        own (not in `_adapters`), disable/enable instead supervise the
        `StreamAdapter` directly -- `stop()` (close the websocket -> zero
        stream) / `start()` + `_wake` + an emitted `loading` status.
        """
        if (
            self._stream is not None
            and domain == self._stream.domain
            and domain not in self._adapters
        ):
            if enabled:
                await self._stream.start()
                if domain in self._wake:
                    self._wake[domain].set()
                self._status[domain] = LayerStatus.LOADING
                if self._events is not None:
                    snap = self._stream.snapshot()
                    # The adapter's snapshot() hardcodes status=LIVE (it has
                    # no notion of the scheduler's enable/disable state) --
                    # the scheduler is the sole writer of LayerStatus
                    # (spec "Status ownership"), so stamp the authoritative
                    # value onto the published meta before it goes out.
                    # snapshot() returns a freshly constructed LayerSnapshot
                    # on every call, so mutating this meta in place carries
                    # no aliasing risk against the adapter's internal table.
                    snap.meta.status = LayerStatus.LOADING
                    self._events.publish_layer_status(snap.meta)
            else:
                await self._stream.stop()
            return

        self._enabled[domain] = enabled
        if enabled:
            self._wake[domain].set()

    async def activate_region(self, region: Region) -> None:
        """Region-switch sequence (scheduler.md "Region-switch sequence",
        ARCHITECTURE §4.2), steps 1-6 in order:

        1. Set `_region`; bump `_cancel_gen[domain]` for every layer so an
           in-flight old-region fetch's result is discarded on return
           (`_do_fetch` checks the generation).
        2. Clear the registry for all layers and publish `region_changed`.
        3. Repopulate cheaply: land from `store.get_land_cache` if fresh;
           air/marine from `store.get_fallback` only when the row's
           `region_id` matches the new region (a mismatched-region fallback
           must never be shown -- `fallback_snapshots` is keyed by layer
           only, storage.md).
        4. Set `_wake` for poll layers (next tick fetches the new bbox).
        5. `await stream.set_region(new)` if a marine stream is injected.
        6. Persist the new region as the `active_region` config override.

        Every collaborator (`registry`/`store`/`events`/`stream`) is
        optional and guarded exactly like the write path in
        `_handle_fetch_success`/`_handle_fetch_failure` -- a caller that
        didn't supply one keeps working with that step skipped.
        """
        for domain in self._cancel_gen:
            self._cancel_gen[domain] += 1

        self._region = region

        if self._registry is not None:
            self._registry.clear()

        if self._events is not None:
            self._events.publish_region_changed(region.id, region.bbox)

        if self._store is not None:
            if Domain.LAND in self._adapters:
                await self._repopulate_land(region)
            for domain in (Domain.AIR, Domain.MARINE):
                if domain in self._adapters or (
                    self._stream is not None and self._stream.domain == domain
                ):
                    await self._repopulate_fallback(domain, region)

        for domain in self._adapters:
            self._wake[domain].set()

        if self._stream is not None:
            await self._stream.set_region(region)

        if self._store is not None:
            await self._store.put_config_override(
                "active_region", {"region_id": region.id}
            )

    async def _repopulate_land(self, region: Region) -> None:
        """Region-switch step 3, land branch: serve the cached land layer
        without a fetch if it's still fresh (storage.md "Refresh cadence":
        `now - fetched_at < land cadence`, mirroring the same freshness rule
        used for the normal Overpass refresh)."""
        assert self._store is not None
        row = await self._store.get_land_cache(region.id)
        if row is None:
            self._status[Domain.LAND] = LayerStatus.LOADING
            return

        cadence_s = self._cadence_s.get(Domain.LAND, 0)
        now = datetime.now(timezone.utc)
        age_s = (now - row.fetched_at).total_seconds()
        if cadence_s and age_s >= cadence_s:
            self._status[Domain.LAND] = LayerStatus.LOADING
            return  # stale -- leave it to the next scheduled fetch

        layer_cfg = self._cfg.layers.get(Domain.LAND.value)
        stale_after = _configured_stale_after_s(layer_cfg) if layer_cfg else cadence_s
        snap = _land_snapshot_from_cache_row(
            row, cadence_s=cadence_s, stale_after_s=stale_after
        )
        if self._registry is not None:
            self._registry[Domain.LAND] = snap
        if self._events is not None:
            self._events.publish_snapshot(snap)
        self._status[Domain.LAND] = snap.meta.status

    async def _repopulate_fallback(self, domain: Domain, region: Region) -> None:
        """Region-switch step 3, air/marine branch: the region-matched
        fallback gate. `store.get_fallback` is always consulted (so a
        caller can prove it was checked); the row is only used to
        repopulate when its `region_id` matches the new region."""
        assert self._store is not None
        fallback = await self._store.get_fallback(domain.value)
        if fallback is None or fallback.meta.region_id != region.id:
            self._status[domain] = LayerStatus.LOADING
            return
        if self._registry is not None:
            self._registry[domain] = fallback
        if self._events is not None:
            self._events.publish_snapshot(fallback)
        self._status[domain] = fallback.meta.status

    async def refresh(self, domain: Domain) -> None:
        """FR6 manual kick: join the same single-flight fetch a scheduled
        tick may already have in flight for this layer."""
        await self._do_fetch(domain)

    async def _do_fetch(self, domain: Domain) -> LayerSnapshot:
        """Single-flight per layer (spec "Coalescing (FR6)"): a shared
        `asyncio.Future`, not a lock -- joining callers need the *result*,
        not just mutual exclusion."""
        fut = self._inflight[domain]
        if fut is not None:
            return await fut

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._inflight[domain] = fut
        gen = self._cancel_gen.get(domain, 0)
        try:
            result = await self._adapters[domain].fetch(self._region)
        except asyncio.CancelledError as exc:
            # Cancellation (app shutdown, or a sibling layer's TaskGroup
            # tearing down) must short-circuit to a clean re-raise *before*
            # any failure write-path work -- it is not a fetch failure, so
            # it must never run `_handle_fetch_failure` (no superfluous
            # `store.get_fallback` call, no `_status[domain]` mutation, and
            # no risk of a store-closing error replacing/masking the
            # original `CancelledError`). The future still needs its
            # exception set/retrieved for the same "never retrieved"
            # log-on-GC reason as the genuine-error branch below, so a
            # joiner's `await fut` still observes cancellation correctly.
            if not fut.done():
                fut.set_exception(exc)
                fut.exception()
            raise
        except BaseException as exc:  # noqa: BLE001 - propagate to caller
            if not fut.done():
                fut.set_exception(exc)
                # The owner call re-raises `exc` directly below rather than
                # via `await fut` -- only *joiners* (a concurrent refresh())
                # consume the future's exception. With no joiner, nothing
                # ever retrieves it, and asyncio logs "Future exception was
                # never retrieved" at GC time. Calling `.exception()` here
                # marks it retrieved (clears the log-on-GC flag) without
                # disturbing what a joiner's `await fut` observes -- the
                # stored exception is still raised for every awaiter.
                fut.exception()
            await self._handle_fetch_failure(domain)
            raise
        else:
            # Region-switch cancellation (scheduler.md "Region-switch
            # sequence" step 1): `activate_region` does not literally cancel
            # an in-flight fetch (adapters aren't required to tolerate that
            # mid-request) -- it bumps `_cancel_gen[domain]` instead. A fetch
            # that started under the old generation still completes (this
            # `await` above already ran), but its result is stale: skip the
            # write path so it never lands in the registry/SSE/fallback for
            # the new region. The future is still resolved with the (unused)
            # result so any joiner's `await fut` completes cleanly.
            if self._cancel_gen.get(domain, 0) == gen:
                await self._handle_fetch_success(domain, result)
            fut.set_result(result)
            return result
        finally:
            self._inflight[domain] = None

    async def _handle_fetch_success(self, domain: Domain, snap: LayerSnapshot) -> None:
        """Write path (scheduler.md "Write path", steps 2-6) + status mapping
        (FR7) for a successful fetch. No-op if the write-path collaborators
        were not supplied (step callers keep working unmodified)."""
        if self._registry is None:
            return

        prev: dict[str, PrevPos] = {}
        if domain is Domain.AIR:
            prev_snap = self._registry.get(Domain.AIR)
            if prev_snap is not None:
                prev = {
                    f.source_id: PrevPos(
                        lat=f.lat, lon=f.lon, timestamp_source=f.timestamp_source
                    )
                    for f in prev_snap.features
                }

        if self._integrity is not None:
            snap.features = self._integrity.apply(snap.features, prev)

        layer_cfg = self._cfg.layers[domain.value]
        cadence_s = self._cadence_s[domain]
        stale_after = _configured_stale_after_s(layer_cfg)
        now = datetime.now(timezone.utc)
        source_age = (
            (now - snap.meta.timestamp_source).total_seconds()
            if snap.meta.timestamp_source is not None
            else 0.0
        )
        status = LayerStatus.LIVE if source_age <= stale_after else LayerStatus.STALE

        snap.meta.status = status
        snap.meta.cadence_s = cadence_s
        snap.meta.stale_after_s = stale_after
        snap.meta.timestamp_fetched = now
        snap.meta.feature_count = len(snap.features)

        self._registry[domain] = snap

        if self._events is not None:
            self._events.publish_snapshot(snap)

        if self._store is not None and domain in (Domain.AIR, Domain.MARINE):
            await self._store.put_fallback(snap)

        self._status[domain] = status

    async def _handle_fetch_failure(self, domain: Domain) -> None:
        """`cached-fallback` beats `error` (scheduler.md): on any failure,
        check for a warm, region-matched fallback row before giving up. A
        no-op (status untouched) if `store` was not supplied."""
        if self._store is None:
            return

        cached = await self._store.get_fallback(domain.value)
        if cached is not None and cached.meta.region_id == self._region.id:
            self._status[domain] = LayerStatus.CACHED_FALLBACK
        else:
            self._status[domain] = LayerStatus.ERROR
