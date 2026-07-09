"""Scheduler core runtime (spec: design/specs/scheduler.md; plans:
plans/scheduler/01-core-runtime.md (issue #45),
plans/scheduler/02-status-write-path.md (issue #49)).

Slice 01 laid the concurrency spine: one asyncio task per poll layer,
per-layer cadence independence (FR6), single-flight coalescing of manual
`refresh()` against an in-flight scheduled fetch (FR6), and enable/disable
parking a layer purely on `_wake` for zero upstream spend while disabled
(FR5).

Slice 02 (this file, grown) adds status ownership (FR7) and the write path
(FR8/FR9/FR10): the scheduler becomes the sole writer of `LayerStatus`, and
every successful fetch runs `integrity.apply -> registry[domain] = snap ->
events.publish_snapshot(snap) -> (air/marine only) await
store.put_fallback(snap)`, in that fixed order.

Still out of scope (later scheduler slices 03-04): backoff per error class,
the event-driven stale *timer* (stale is only computed at write time here),
region-switch (`activate_region`), enable/disable of marine stream
supervision, and the real SSE endpoint (api-core/01).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from backend.config import AppConfig, effective_cadence_s
from backend.config import stale_after_s as _configured_stale_after_s
from backend.events import EventBus
from backend.integrity import Integrity, PrevPos
from backend.models import Domain, LayerSnapshot, LayerStatus
from backend.registry import Registry
from backend.sources.base import PollAdapter, Region
from backend.store import Store

logger = logging.getLogger(__name__)


class Scheduler:
    """Owns one `_poll_loop(domain)` task per poll layer under a single
    `asyncio.TaskGroup` (spec "Task model"). Only the slice-01 subset of the
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
    ) -> None:
        self._cfg = cfg
        self._adapters = adapters
        self._region = region
        self._registry = registry
        self._integrity = integrity
        self._store = store
        self._events = events

        self._enabled: dict[Domain, bool] = {}
        self._cadence_s: dict[Domain, int] = {}
        self._inflight: dict[Domain, asyncio.Future[LayerSnapshot] | None] = {}
        self._wake: dict[Domain, asyncio.Event] = {}
        self._status: dict[Domain, LayerStatus] = {}

        for domain, layer_cfg in ((d, cfg.layers[d.value]) for d in adapters):
            self._enabled[domain] = layer_cfg.enabled
            self._cadence_s[domain] = effective_cadence_s(layer_cfg)
            self._inflight[domain] = None
            self._wake[domain] = asyncio.Event()
            self._status[domain] = LayerStatus.LOADING

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
        wake); enabling sets `_wake` for an immediate fetch."""
        self._enabled[domain] = enabled
        if enabled:
            self._wake[domain].set()

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
            await self._handle_fetch_success(domain, result)
            fut.set_result(result)
            return result
        finally:
            self._inflight[domain] = None

    async def _handle_fetch_success(self, domain: Domain, snap: LayerSnapshot) -> None:
        """Write path (scheduler.md "Write path", steps 2-6) + status mapping
        (FR7) for a successful fetch. No-op if the write-path collaborators
        were not supplied (slice 01 callers keep working unmodified)."""
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
