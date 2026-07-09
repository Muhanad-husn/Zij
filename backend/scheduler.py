"""Scheduler core runtime (spec: design/specs/scheduler.md; plans:
plans/scheduler/01-core-runtime.md (issue #45),
plans/scheduler/02-status-write-path.md (issue #49),
plans/scheduler/04-region-toggle.md (issue #52)).

Slice 01 laid the concurrency spine: one asyncio task per poll layer,
per-layer cadence independence (FR6), single-flight coalescing of manual
`refresh()` against an in-flight scheduled fetch (FR6), and enable/disable
parking a layer purely on `_wake` for zero upstream spend while disabled
(FR5).

Slice 02 adds status ownership (FR7) and the write path (FR8/FR9/FR10): the
scheduler becomes the sole writer of `LayerStatus`, and every successful
fetch runs `integrity.apply -> registry[domain] = snap ->
events.publish_snapshot(snap) -> (air/marine only) await
store.put_fallback(snap)`, in that fixed order.

Slice 04 (this file, grown) adds the region-switch sequence
(`activate_region`, ARCHITECTURE §4.2) and extends `set_enabled` to also
supervise an optional marine `StreamAdapter` (FR5). Per-layer cancellation
uses a generation counter (`_cancel_gen`), not literal task cancellation: a
completing old-region fetch is discarded on return by comparing the
generation captured at fetch-start against the current one.

Slice 03 (this file, grown) adds backoff per error class (scheduler.md
"Backoff per error class") -- the poll loop honors `retry_after` for
`RateLimitedError`, exponential `min(base*2**n, max)` capped at `max_attempts`
for `UpstreamError`, and surfaces `AuthError`/`ParseError` with no auto-retry --
plus the event-driven stale *timer* (`_stale_timer`): after each successful
write, a one-shot `loop.call_at(timestamp_source + stale_after_s)` flips
`live->stale` and emits a `layer_status` event with no new fetch; a newer
successful fetch cancels/reschedules it.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
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
from backend.sources.base import (
    AuthError,
    ParseError,
    PollAdapter,
    RateLimitedError,
    Region,
    StreamAdapter,
    UpstreamError,
)
from backend.store import LandCacheRow, Store

logger = logging.getLogger(__name__)

# Per-error-class backoff defaults (scheduler.md "Backoff per error class"),
# used when the domain's config section omits a knob. Land reads `[overpass]`
# (`backoff_base_s`/`backoff_max_s`/`max_attempts`); air reads `[opensky]`,
# whose spec default retry schedule is `min(60*2**n, 300)` -- expressed here as
# base=60, max=300 so the same `min(base*2**n, max)` formula covers both.
# `(base_s, max_s, max_attempts)`.
_BACKOFF_DEFAULTS: dict[Domain, tuple[float, float, int]] = {
    Domain.LAND: (5.0, 300.0, 4),
    Domain.AIR: (60.0, 300.0, 4),
}


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
        self._stale_timer: dict[Domain, asyncio.TimerHandle | None] = {}

        for domain, layer_cfg in ((d, cfg.layers[d.value]) for d in adapters):
            self._enabled[domain] = layer_cfg.enabled
            self._cadence_s[domain] = effective_cadence_s(layer_cfg)
            self._inflight[domain] = None
            self._wake[domain] = asyncio.Event()
            self._status[domain] = LayerStatus.LOADING
            self._cancel_gen[domain] = 0
            self._stale_timer[domain] = None

        if stream is not None and stream.domain not in self._cancel_gen:
            # Marine supervised purely via the stream adapter (no poll loop
            # task, no `fetch`/cadence/enabled bookkeeping) -- still needs a
            # generation slot (`activate_region` bumps every layer's) and a
            # status/wake slot (`set_enabled`'s marine branch below).
            self._wake[stream.domain] = asyncio.Event()
            self._status[stream.domain] = LayerStatus.LOADING
            self._cancel_gen[stream.domain] = 0
            self._stale_timer[stream.domain] = None

    def current_status(self, domain: Domain) -> LayerStatus:
        """FR7 public reader (spec "Public interface"). The scheduler is the
        sole writer of `LayerStatus`; this only reads the last value it
        recorded for `domain`."""
        return self._status[domain]

    async def run(self) -> None:
        """Owns the `TaskGroup`; lifetime = app lifetime (spec "Task
        model"). One `_poll_loop(domain)` task per adapter this scheduler
        was constructed with."""
        try:
            async with asyncio.TaskGroup() as tg:
                for domain in self._adapters:
                    tg.create_task(self._poll_loop(domain))
        finally:
            # Shutdown (ARCHITECTURE §4.4): cancel any armed one-shot stale
            # timer so a stray `call_at` callback can't mutate status / publish
            # after the scheduler has torn down.
            for domain in list(self._stale_timer):
                self._cancel_stale_timer(domain)

    async def _poll_loop(self, domain: Domain) -> None:
        """Cadence timing per spec: `asyncio.wait_for(_wake.wait(),
        timeout=cadence_s)` -- timeout is a scheduled tick, the event being
        set is a manual refresh/enable kick. A disabled layer parks purely
        on `_wake` (no timeout) for zero upstream spend (FR5); re-enabling
        sets `_wake` for an immediate first fetch.

        Backoff per error class (scheduler.md "Backoff per error class") is a
        property of THIS loop, not `_do_fetch` (which `refresh()` also calls,
        one-shot): the wait before the *next* attempt is derived from the
        *outcome* of this one. `RateLimitedError` defers ~`retry_after` (not
        the shorter cadence); `UpstreamError` backs off exponentially, capped
        at `max_attempts`, then resumes normal cadence; `AuthError`/`ParseError`
        surface with no auto-retry (next scheduled tick may retry). A success,
        a manual refresh, or an enable kick resets the backoff. Backoff never
        blocks another layer -- each loop is independent (FR10)."""
        wake = self._wake[domain]
        attempts = 0  # consecutive UpstreamError count; reset on any success
        next_delay_s: float | None = None  # None -> use the layer's cadence
        while True:
            if self._enabled[domain]:
                timeout = (
                    next_delay_s
                    if next_delay_s is not None
                    else self._cadence_s[domain]
                )
                try:
                    await asyncio.wait_for(wake.wait(), timeout=timeout)
                except TimeoutError:
                    pass
                else:
                    # A manual refresh / enable kick overrides any pending
                    # backoff and fetches immediately.
                    next_delay_s = None
                    attempts = 0
            else:
                await wake.wait()
                next_delay_s = None
                attempts = 0
            wake.clear()
            if not self._enabled[domain]:
                continue
            # FR10: per-layer failure isolation -- a crashing adapter must not
            # kill the scheduler or a sibling layer's task. Cancellation still
            # propagates for clean shutdown.
            try:
                await self._do_fetch(domain)
            except asyncio.CancelledError:
                raise
            except RateLimitedError as exc:
                attempts = 0
                next_delay_s = (
                    exc.retry_after
                    if exc.retry_after is not None
                    else self._backoff_params(domain)[0]
                )
            except UpstreamError:
                base_s, max_s, max_attempts = self._backoff_params(domain)
                attempts += 1
                if attempts >= max_attempts:
                    attempts = 0
                    next_delay_s = None  # cap reached -> resume normal cadence
                else:
                    # Backoff exists to retry SOONER than the normal cadence
                    # after a failure (in every real config base << cadence),
                    # never to make a failing layer poll LESS often than a
                    # healthy one -- so the exponential delay is bounded above
                    # by the layer's own cadence (the cadence tick would fire a
                    # retry by then regardless). A no-op in production; only the
                    # exponential growth below the cadence is observable.
                    next_delay_s = min(
                        base_s * 2 ** (attempts - 1),
                        max_s,
                        float(self._cadence_s[domain]),
                    )
            except (AuthError, ParseError):
                # Surface, no auto-retry (scheduler.md): the next scheduled
                # cadence tick may retry after an operator fix.
                attempts = 0
                next_delay_s = None
            except Exception:
                logger.exception(
                    "layer %s: fetch failed, will retry next cadence tick",
                    domain,
                )
                attempts = 0
                next_delay_s = None
            else:
                attempts = 0
                next_delay_s = None

    def _backoff_params(self, domain: Domain) -> tuple[float, float, int]:
        """`(base_s, max_s, max_attempts)` for a layer, reading its config
        section (`[overpass]` for land, `[opensky]` for air) over the
        per-domain defaults."""
        base_s, max_s, max_attempts = _BACKOFF_DEFAULTS.get(domain, (5.0, 300.0, 4))
        section: dict[str, Any] = {
            Domain.LAND: self._cfg.overpass,
            Domain.AIR: self._cfg.opensky,
        }.get(domain, {})
        return (
            float(section.get("backoff_base_s", base_s)),
            float(section.get("backoff_max_s", max_s)),
            int(section.get("max_attempts", max_attempts)),
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
            # A pending old-region stale timer must not fire against the new
            # region's state (the bumped generation already guards its effect,
            # but cancel the handle so no stray callback lingers).
            self._cancel_stale_timer(domain)

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
            await self._handle_fetch_failure(domain, exc)
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

        # Write path step 7: (re)arm the event-driven stale timer against this
        # snapshot's own `source_ts + stale_after_s`. A newer successful fetch
        # reaching here cancels the prior handle first.
        self._arm_stale_timer(domain, snap)

    async def _handle_fetch_failure(self, domain: Domain, exc: BaseException) -> None:
        """Map a failed fetch to `LayerStatus` per the error class
        (scheduler.md "Status transitions" / "Backoff per error class").

        `RateLimitedError` -> `rate-limited`, carrying `retry_after_s`/`detail`
        on a published `layer_status` event (the poll loop separately defers
        the retry by `retry_after`). Every other error uses the "cached-fallback
        beats error" gate: on a warm, region-matched fallback row show
        `cached-fallback`, else `error`. That gate is a no-op (status untouched)
        when `store` was not supplied -- preserving the slice-02 contract."""
        if isinstance(exc, RateLimitedError):
            self._status[domain] = LayerStatus.RATE_LIMITED
            self._publish_status_event(
                domain,
                LayerStatus.RATE_LIMITED,
                retry_after_s=exc.retry_after,
                detail=str(exc) or None,
            )
            return

        if self._store is None:
            return

        cached = await self._store.get_fallback(domain.value)
        if cached is not None and cached.meta.region_id == self._region.id:
            self._status[domain] = LayerStatus.CACHED_FALLBACK
        else:
            self._status[domain] = LayerStatus.ERROR

    def _publish_status_event(
        self,
        domain: Domain,
        status: LayerStatus,
        *,
        retry_after_s: float | None = None,
        detail: str | None = None,
    ) -> None:
        """Publish a `layer_status`-only event (no feature delta) for a status
        change without a new snapshot (scheduler.md "Write path": e.g.
        `live->rate-limited`, the stale flip). Reuses the last registry
        snapshot's `meta` when present so `region_id`/timestamps stay accurate;
        otherwise builds a minimal meta from config."""
        if self._events is None:
            return
        prev = self._registry.get(domain) if self._registry is not None else None
        if prev is not None:
            meta = prev.meta.model_copy(
                update={
                    "status": status,
                    "retry_after_s": retry_after_s,
                    "detail": detail,
                }
            )
        else:
            layer_cfg = self._cfg.layers.get(domain.value)
            stale_after = _configured_stale_after_s(layer_cfg) if layer_cfg else 0
            meta = LayerSnapshotMeta(
                layer=domain,
                region_id=self._region.id,
                status=status,
                timestamp_fetched=None,
                timestamp_source=None,
                cadence_s=self._cadence_s.get(domain, 0),
                stale_after_s=stale_after,
                feature_count=0,
                retry_after_s=retry_after_s,
                detail=detail,
            )
        self._events.publish_layer_status(meta)

    def _arm_stale_timer(self, domain: Domain, snap: LayerSnapshot) -> None:
        """Schedule the one-shot `live->stale` flip at `source_ts +
        stale_after_s` (scheduler.md "Status transitions" stale-timer rule).
        Cancels any prior handle first. Skipped when the snapshot is already
        `stale` (nothing to flip) or has no source timestamp."""
        self._cancel_stale_timer(domain)
        if snap.meta.status != LayerStatus.LIVE:
            return
        if snap.meta.timestamp_source is None:
            return
        loop = asyncio.get_running_loop()
        now = datetime.now(timezone.utc)
        deadline = snap.meta.timestamp_source + timedelta(
            seconds=snap.meta.stale_after_s
        )
        seconds_until = max((deadline - now).total_seconds(), 0.0)
        gen = self._cancel_gen.get(domain, 0)
        self._stale_timer[domain] = loop.call_at(
            loop.time() + seconds_until, self._on_stale_timer, domain, gen
        )

    def _cancel_stale_timer(self, domain: Domain) -> None:
        handle = self._stale_timer.get(domain)
        if handle is not None:
            handle.cancel()
        self._stale_timer[domain] = None

    def _on_stale_timer(self, domain: Domain, gen: int) -> None:
        """One-shot stale-timer callback (sync -- `loop.call_at` contract). No
        fetch: if no newer data has arrived (status still `live`, same
        generation), flip `live->stale` and emit a `layer_status` event."""
        self._stale_timer[domain] = None
        if self._cancel_gen.get(domain, 0) != gen:
            return  # a region switch (or a newer arm) superseded this handle
        if self._status.get(domain) != LayerStatus.LIVE:
            return  # newer data / a different status already landed
        self._status[domain] = LayerStatus.STALE
        if self._registry is None:
            return
        snap = self._registry.get(domain)
        if snap is None:
            return
        snap.meta.status = LayerStatus.STALE
        if self._events is not None:
            self._events.publish_layer_status(snap.meta)
