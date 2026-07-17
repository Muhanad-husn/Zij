"""Scheduler core runtime (spec: design/specs/scheduler.md; issues #45, #49,
#52).

The concurrency spine: one asyncio task per poll layer, per-layer cadence
independence (FR6), single-flight coalescing of manual `refresh()` against an
in-flight scheduled fetch (FR6), and enable/disable parking a layer purely on
`_wake` for zero upstream spend while disabled (FR5).

Status ownership (FR7) and the write path (FR8/FR9/FR10): the scheduler
becomes the sole writer of `LayerStatus`, and every successful fetch runs
`integrity.apply -> registry[domain] = snap ->
events.publish_snapshot(snap) -> (air/marine only) await
store.put_fallback(snap)`, in that fixed order.

The region-switch sequence (`activate_region`, ARCHITECTURE §4.2) extends
`set_enabled` to also supervise an optional marine `StreamAdapter` (FR5).
Per-layer cancellation uses a generation counter (`_cancel_gen`), not literal
task cancellation: a completing old-region fetch is discarded on return by
comparing the generation captured at fetch-start against the current one.

Backoff per error class (scheduler.md
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
        # Shared "the marine socket has been started" flag. The supervisor is
        # the SOLE caller of `stream.start()` (set_enabled's enable path only
        # wakes it); this flag lets the supervisor skip re-starting an already-
        # started socket -- distinguishing a never-started stream (retry the
        # connect) from a started-but-transiently-dropped one (the adapter's
        # own read loop owns that reconnect). Reset to False when set_enabled
        # stops the socket, so a disable->enable cycle re-starts it exactly
        # once.
        self._stream_started = False

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
            # Marine supervised via `_stream_supervisor` (no poll loop task,
            # no `fetch`/single-flight bookkeeping) -- still needs a
            # generation slot (`activate_region` bumps every layer's), a
            # status/wake slot (`set_enabled`'s marine branch below), an
            # enabled flag (config-driven initial state, mirroring the poll
            # layers' `_enabled`), and an effective cadence for its own
            # sampling loop.
            stream_layer_cfg = cfg.layers.get(stream.domain.value)
            self._enabled[stream.domain] = (
                stream_layer_cfg.enabled if stream_layer_cfg is not None else True
            )
            self._cadence_s[stream.domain] = (
                effective_cadence_s(stream_layer_cfg)
                if stream_layer_cfg is not None
                else 1
            )
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
        was constructed with, plus one `_stream_supervisor()` task if a
        marine `StreamAdapter` was injected."""
        try:
            async with asyncio.TaskGroup() as tg:
                for domain in self._adapters:
                    tg.create_task(self._poll_loop(domain))
                if self._stream is not None:
                    tg.create_task(self._stream_supervisor())
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

    async def _stream_supervisor(self) -> None:
        """One task if the marine source is a `StreamAdapter` (spec "Task
        model"): owns `adapter.start()`, samples `snapshot()` on the marine
        cadence, and watches `connected`. Mirrors `_poll_loop`'s cadence
        timing (`asyncio.wait_for(_wake.wait(), timeout=cadence_s)`,
        enable/disable parking on `_wake`) but samples the adapter's
        in-memory table instead of awaiting a `fetch`. FR10 isolation: a
        crashing sample must not kill the scheduler or a sibling layer."""
        stream = self._stream
        assert stream is not None
        domain = stream.domain
        wake = self._wake[domain]

        if self._enabled.get(domain, True):
            self._stream_started = await self._bootstrap_stream(domain)

        while True:
            cadence_s = self._cadence_s.get(domain, 1)
            if self._enabled.get(domain, True):
                try:
                    await asyncio.wait_for(wake.wait(), timeout=cadence_s)
                except TimeoutError:
                    pass
            else:
                await wake.wait()
            wake.clear()
            if not self._enabled.get(domain, True):
                continue
            # Start the socket if it has never been started -- covers both a
            # boot-time connect failure retrying and a set_enabled(enable) that
            # only woke us. The supervisor is the SOLE start() caller, so this
            # never races/double-starts against set_enabled. Once started the
            # flag stays True and the adapter's own read loop owns mid-stream
            # reconnects (a transient `connected == False` must NOT re-start()).
            if not self._stream_started:
                self._stream_started = await self._bootstrap_stream(domain)
                if not self._stream_started:
                    continue
            try:
                await self._sample_stream(domain)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "marine stream: sample failed, will retry next cadence tick"
                )

    async def _bootstrap_stream(self, domain: Domain) -> bool:
        """Push the active region onto the stream then `start()` it, isolating
        any connect failure (FR10). The region is set BEFORE start() so the
        first subscribe carries the bbox (aisstream.md "set_region" pre-connect
        bootstrap) -- without it the initial subscribe goes out with an empty
        `BoundingBoxes` list and the socket receives no vessels until a region
        switch. A failed initial connect (DNS, refused, TLS) must NOT propagate
        out of `_stream_supervisor`: that task runs inside `run()`'s
        `TaskGroup`, and an unhandled raise there would cancel the sibling air/
        land poll loops too (scheduler.md "Failure modes"). On failure this
        maps the layer to reconnecting/cached-fallback and returns False so the
        supervisor retries on the next cadence tick; returns True once
        started."""
        stream = self._stream
        assert stream is not None
        try:
            if self._region is not None:
                await stream.set_region(self._region)
            await stream.start()
            return True
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "marine stream: start failed, will retry next cadence tick"
            )
            await self._handle_stream_disconnected(domain)
            return False

    async def _sample_stream(self, domain: Domain) -> None:
        """One sample of the marine stream (spec "Write path": `snap =
        adapter.snapshot()`, then the same write path a successful poll
        fetch runs). `connected == False` maps to `reconnecting` (or
        `cached-fallback` if a warm, region-matched cache exists) per the
        "Status transitions" table, rather than running the write path
        against a possibly-stale table."""
        stream = self._stream
        assert stream is not None
        if not stream.connected:
            await self._handle_stream_disconnected(domain)
            return
        snap = stream.snapshot()
        await self._handle_fetch_success(domain, snap)

    async def _handle_stream_disconnected(self, domain: Domain) -> None:
        """Marine-only `reconnecting` state (spec "Status transitions": `live
        (marine) | connected == False -> reconnecting`; `reconnecting |
        still down, warm cache -> cached-fallback`) -- reuses the same
        "cached-fallback beats error" gate the poll write path uses on
        failure, substituting `reconnecting` for `error` as the no-cache
        fallback (a stream drop is a transient reconnect, not a hard
        failure)."""
        if self._store is not None:
            cached = await self._store.get_fallback(domain.value)
            if cached is not None and cached.meta.region_id == self._region.id:
                if self._status.get(domain) != LayerStatus.CACHED_FALLBACK:
                    self._status[domain] = LayerStatus.CACHED_FALLBACK
                    self._publish_status_event(
                        domain,
                        LayerStatus.CACHED_FALLBACK,
                        detail="marine stream disconnected",
                    )
                return
        if self._status.get(domain) != LayerStatus.RECONNECTING:
            self._status[domain] = LayerStatus.RECONNECTING
            self._publish_status_event(
                domain,
                LayerStatus.RECONNECTING,
                detail="marine stream disconnected",
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
            self._enabled[domain] = enabled
            if enabled:
                # Pre-connect bootstrap (aisstream.md "set_region"): push the
                # active region before start() so the re-enable subscribe
                # carries the bbox -- without it a marine layer that booted
                # disabled and is enabled via the API before any region switch
                # would subscribe with an empty BoundingBoxes list (#113).
                if self._region is not None:
                    await self._stream.set_region(self._region)
                await self._stream.start()
                # Mark the socket started so the supervisor -- woken just below
                # -- does NOT also call start() (a second start() would orphan
                # the prior _ws/_read_task). `_stream_started` is the single
                # shared source of truth between this enable path and the
                # supervisor's bootstrap retry.
                self._stream_started = True
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
                # The socket is down -- let the supervisor re-start it exactly
                # once on the next enable (see _stream_started).
                self._stream_started = False
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

        # Event-driven stale timer (#88): a cache-repopulated layer must
        # still flip live->stale on its own schedule with no new fetch,
        # exactly like a fresh `_handle_fetch_success` write.
        self._arm_stale_timer(Domain.LAND, snap)

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

        # Event-driven stale timer (#88): a cache-repopulated layer must
        # still flip live->stale on its own schedule with no new fetch,
        # exactly like a fresh `_handle_fetch_success` write.
        self._arm_stale_timer(domain, fallback)

    async def refresh(self, domain: Domain) -> None:
        """FR6 manual kick: join the same single-flight fetch a scheduled
        tick may already have in flight for this layer."""
        await self._do_fetch(domain)

    async def refresh_all(self) -> list[Domain]:
        """FR6 "refresh all enabled layers" trigger (api.md "POST
        /api/refresh"; plan api-core/03 "Absorbs #38"). Queues an immediate
        refresh for every currently-enabled POLL layer (`_adapters`) and
        returns exactly the list it queued, so the caller echoes the
        scheduler's own enabled set rather than a hardcoded domain list --
        a disabled layer is genuinely excluded. Per-layer isolation (FR10):
        one layer's fetch failure (already recorded + published by
        `_handle_fetch_failure`, #38) must never stop a sibling layer's
        refresh."""
        queued = [
            domain for domain in self._adapters if self._enabled.get(domain, False)
        ]
        for domain in queued:
            try:
                await self.refresh(domain)
            except Exception:
                logger.warning(
                    "refresh_all: layer %s refresh failed", domain, exc_info=True
                )
        return queued

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
        were not supplied (callers without them keep working unmodified)."""
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
        the retry by `retry_after`) -- UNLESS the layer is already
        `rate-limited` (a repeated 429), in which case it falls through to
        the same "cached-fallback beats error" gate below (#87 spec row
        `rate-limited | still failing, warm cache | cached-fallback`), so a
        layer parked at `rate-limited` still degrades to the warm cache
        rather than staying stuck. Every other error (and a repeated
        rate-limited with no/mismatched cache) uses that gate: on a warm,
        region-matched fallback row show `cached-fallback`, else `error`;
        either way (#38) a `layer_status` event carrying a non-empty `detail`
        is published, so a manual refresh's failure is never a silent
        success. That gate is a no-op (status untouched, nothing published)
        when `store` was not supplied -- preserving the step contract."""
        detail = str(exc) or f"{type(exc).__name__} while fetching {domain.value}"

        if isinstance(exc, RateLimitedError):
            if self._status.get(domain) != LayerStatus.RATE_LIMITED:
                self._status[domain] = LayerStatus.RATE_LIMITED
                self._publish_status_event(
                    domain,
                    LayerStatus.RATE_LIMITED,
                    retry_after_s=exc.retry_after,
                    detail=detail,
                )
                return

            if self._store is None:
                return

            cached = await self._store.get_fallback(domain.value)
            if cached is not None and cached.meta.region_id == self._region.id:
                status = LayerStatus.CACHED_FALLBACK
            else:
                status = LayerStatus.RATE_LIMITED
            self._status[domain] = status
            self._publish_status_event(
                domain,
                status,
                retry_after_s=(
                    exc.retry_after if status == LayerStatus.RATE_LIMITED else None
                ),
                detail=detail,
            )
            return

        if self._store is None:
            return

        cached = await self._store.get_fallback(domain.value)
        if cached is not None and cached.meta.region_id == self._region.id:
            status = LayerStatus.CACHED_FALLBACK
        else:
            status = LayerStatus.ERROR
        self._status[domain] = status
        self._publish_status_event(domain, status, detail=detail)

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
