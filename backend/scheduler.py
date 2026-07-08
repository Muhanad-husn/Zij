"""Scheduler core runtime (spec: design/specs/scheduler.md; plan:
plans/scheduler/01-core-runtime.md; issue #45).

step walking skeleton: the concurrency spine only -- one asyncio task
per poll layer, per-layer cadence independence (FR6), single-flight
coalescing of manual `refresh()` against an in-flight scheduled fetch
(FR6), and enable/disable parking a layer purely on `_wake` for zero
upstream spend while disabled (FR5).

Out of scope for this slice (later scheduler slices 02-04, per the plan and
spec's "Acceptance criteria" sections not exercised here): `LayerStatus`
ownership/transitions, the write path (integrity -> registry -> SSE ->
fallback), backoff, the event-driven stale timer, region-switch
(`activate_region`), and marine stream supervision.
"""

from __future__ import annotations

import asyncio
import logging

from backend.config import AppConfig, effective_cadence_s
from backend.models import Domain, LayerSnapshot
from backend.sources.base import PollAdapter, Region

logger = logging.getLogger(__name__)


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
    ) -> None:
        self._cfg = cfg
        self._adapters = adapters
        self._region = region

        self._enabled: dict[Domain, bool] = {}
        self._cadence_s: dict[Domain, int] = {}
        self._inflight: dict[Domain, asyncio.Future[LayerSnapshot] | None] = {}
        self._wake: dict[Domain, asyncio.Event] = {}

        for domain, layer_cfg in ((d, cfg.layers[d.value]) for d in adapters):
            self._enabled[domain] = layer_cfg.enabled
            self._cadence_s[domain] = effective_cadence_s(layer_cfg)
            self._inflight[domain] = None
            self._wake[domain] = asyncio.Event()

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
                    await asyncio.wait_for(
                        wake.wait(), timeout=self._cadence_s[domain]
                    )
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
        except BaseException as exc:  # noqa: BLE001 - propagate to caller
            if not fut.done():
                fut.set_exception(exc)
            raise
        else:
            fut.set_result(result)
            return result
        finally:
            self._inflight[domain] = None
