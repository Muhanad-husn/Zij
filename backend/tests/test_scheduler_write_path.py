"""Locked outer acceptance test for scheduler slice 02 (issue #49): status
ownership + the write path.

Given a Scheduler with mocked integrity, registry, event bus and store
When  a poll fetch returns a snapshot whose source timestamp is fresh
Then  the layer status is `live`, integrity ran before the registry was set,
      SSE published after the registry was set, and an air fallback row was
      persisted (raw_payload excluded)
When  a fetch returns a snapshot whose source age exceeds 2x cadence
Then  the layer status is `stale`
When  a fetch fails and a warm region-matched cache exists
Then  the layer status is `cached-fallback` (not `error`); with no cache it
      is `error`

Transcribed from plans/scheduler/02-status-write-path.md ("Acceptance
criterion") and design/specs/scheduler.md ("Write path", "Status
ownership... transition table", "cached-fallback beats error"). Slice 01's
concurrency spine (backend/tests/test_scheduler.py) is untouched; this file
only exercises the NEW write-path/status-ownership surface, driven through
`refresh(domain)` for a deterministic single write (no cadence timing races
-- unlike slice 01, nothing here depends on real-clock scheduling).

**Public surface this test locks (constructor extension, "extend without a
rewrite")**: the full spec constructor is
`Scheduler(cfg, adapters, registry, integrity, store, events)`, but slice 01
locked the positional `Scheduler(cfg, adapters, region)` call shape, which
must stay green. This test locks the constructor as

    Scheduler(cfg, adapters, region,
              *, registry=None, integrity=None, store=None, events=None)

i.e. `registry`/`integrity`/`store`/`events` become optional keyword-only
parameters, so slice 01's positional 3-arg call keeps working unmodified
while this slice's tests pass all four collaborators by keyword. This test
also locks the public `current_status(domain) -> LayerStatus` reader named
in the spec's "Public interface".

**Collaborator injection surface (test-author's choice, since `Registry`/
`EventBus` do not exist as modules yet)**:

- `registry`: a plain `dict` subclass (`RecordingRegistry`) that also
  appends to a shared `call_order` list on `__setitem__` -- this keeps exact
  `dict[Domain, LayerSnapshot]` semantics (spec: "Registry = in-memory
  dict[Domain, LayerSnapshot]"), including `KeyError`-on-missing/`.get`
  behaviour the air-`prev`-derivation test below depends on, while still
  making the write-path ORDER observable.
- `integrity`: a `Mock` whose `.apply` is a passthrough recording every
  `(features, prev)` call -- mirrors the real, already-implemented
  `Integrity.apply(features, prev) -> list[Feature]` (sync, no I/O).
- `events`: a `Mock` whose `.publish_snapshot` records call order. The
  frozen spec's write-path list is textually explicit about which steps are
  awaited and which are not: step 6 reads "**await** store.put_fallback(snap)"
  while step 5 reads only "events.publish_snapshot(snap)" (no await) --
  mirrored here as a plain synchronous callable, not an `AsyncMock`.
- `store`: an `AsyncMock` matching the real, already-implemented
  `Store.put_fallback`/`Store.get_fallback` (both genuinely `async def`).

**Order locked**: `integrity.apply` -> `registry[domain] = snap` ->
`events.publish_snapshot(snap)` -> `store.put_fallback(snap)`, exactly the
numbered sequence in scheduler.md's "Write path" (steps 2/4/5/6). A single
shared `call_order` list, appended to by every collaborator double,
captures true global order (not just per-mock call counts).

**Exception propagation from `refresh()` on a failed fetch is deliberately
NOT locked here.** The spec does not pin whether `refresh()` swallows the
adapter's exception once `LayerStatus` has been recorded, or re-raises it
after recording -- both are defensible designs the plan does not
distinguish between. `_refresh_tolerating_adapter_errors` calls `refresh()`
and discards any raised exception so this test locks only what the plan
actually specifies (the resulting `current_status`), not an unspecified
propagation detail; if the implementation fails to record status at all,
the subsequent `current_status` assertion still fails the test honestly.

**Deferred to the inner unit list** (not locked in this outer test, to
avoid over-constraining underspecified branches):
- The exact registry/events/store call sequence when a failure is served
  from a warm cache (`cached-fallback`) -- the spec numbers only the
  SUCCESSFUL write path 1-7; whether/how the cached snapshot is
  re-published is left to the implementer and the inner unit list.
- A cache row whose `region_id` does NOT match the active region (must
  still map to `error`, per "cached-fallback beats error": "and its
  region_id matches the active region") -- only the matching-region and
  no-cache-at-all cases are asserted in this outer test, per the plan's
  explicit acceptance criterion. Now covered by an inner unit test added at
  marker-removal time (below,
  `test_fetch_failure_with_region_mismatched_cache_yields_error_not_cached_fallback`),
  once the implementer's region-match gate existed to exercise.
- Backoff per error class and the event-driven stale timer (slice 03,
  explicitly out of scope per the plan).

It was authored and committed RED before any implementation of this surface
existed (strict xfail, DEC-33): `backend.scheduler.Scheduler` did not yet
accept `registry`/`integrity`/`store`/`events`, nor expose `current_status`,
so every test below failed against the then-current constructor/surface and
xfailed cleanly under the tests-green gate. The implementer has since made
it genuinely pass; the xfail marker has been removed to finalize the
contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

from backend.config import AppConfig, LayerCfg
from backend.integrity import PrevPos
from backend.models import (
    Domain,
    Feature,
    GeometryType,
    LayerSnapshot,
    LayerSnapshotMeta,
    LayerStatus,
)
from backend.sources.base import PollAdapter, Region, UpstreamError

HORMUZ_REGION = Region(
    id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
)


class RecordingRegistry(dict):
    """A real `dict[Domain, LayerSnapshot]` (Registry's exact spec shape)
    that also appends to a shared `call_order` list on every write, so the
    write-path ORDER is observable without giving up genuine dict semantics
    (`KeyError`/`.get` on a missing domain -- needed by the air-`prev`
    derivation test, which reads the registry's prior state before it is
    replaced)."""

    def __init__(self, call_order: list[str]) -> None:
        super().__init__()
        self._call_order = call_order

    def __setitem__(self, key: Domain, value: LayerSnapshot) -> None:
        self._call_order.append("registry.set")
        super().__setitem__(key, value)


class ScriptedAdapter(PollAdapter):
    """A PollAdapter double that returns (or raises) each item of `results`
    in order, one per `fetch()` call -- lets a test script exactly what
    successive polls of the same layer see (needed for the air-`prev`
    derivation test's two-fetch sequence)."""

    source = "fake"

    def __init__(
        self, domain: Domain, results: list[LayerSnapshot | BaseException]
    ) -> None:
        self.domain = domain
        self._results = list(results)
        self.call_count = 0

    async def fetch(self, region: Region) -> LayerSnapshot:
        self.call_count += 1
        result = self._results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _make_cfg(*, cadence_s: int = 10) -> AppConfig:
    """A minimal AppConfig carrying only the air layer this file exercises."""
    return AppConfig(
        regions=[],
        layers={
            "air": LayerCfg(
                enabled=True,
                cadence_s=cadence_s,
                cadence_floor_s=0,
                custom_bbox_cap_sq_deg=100,
            ),
        },
        overpass={},
        opensky={},
        aisstream={},
        integrity={},
        server={},
    )


def _adapter_meta(
    *, timestamp_source: datetime, feature_count: int, cadence_s: int
) -> LayerSnapshotMeta:
    """A valid meta as a PollAdapter would return it: `status` always LIVE
    (adapter-interface.md: "leaves LayerSnapshot.meta.status as LIVE -- the
    scheduler overwrites meta.status authoritatively"). `cadence_s`/
    `stale_after_s` here are placeholders the scheduler is expected to
    recompute authoritatively (scheduler.md "Compute authoritative meta");
    this test only asserts on the scheduler's resulting `current_status`,
    never on these adapter-supplied placeholder fields."""
    now = datetime.now(timezone.utc)
    return LayerSnapshotMeta(
        layer=Domain.AIR,
        region_id=HORMUZ_REGION.id,
        status=LayerStatus.LIVE,
        timestamp_fetched=now,
        timestamp_source=timestamp_source,
        cadence_s=cadence_s,
        stale_after_s=cadence_s * 2,
        feature_count=feature_count,
    )


def _feature(
    source_id: str,
    lat: float,
    lon: float,
    timestamp_source: datetime,
    *,
    raw_payload: dict | None = None,
) -> Feature:
    now = datetime.now(timezone.utc)
    return Feature(
        domain=Domain.AIR,
        source="opensky",
        source_id=source_id,
        lat=lat,
        lon=lon,
        geometry_type=GeometryType.POINT,
        timestamp_source=timestamp_source,
        timestamp_fetched=now,
        position_age_s=(now - timestamp_source).total_seconds(),
        raw_payload=raw_payload,
    )


def _build_collaborators(*, get_fallback_return: LayerSnapshot | None = None):
    """Builds the four mocked write-path collaborators plus the shared
    `call_order` list and the `integrity.apply` per-call `prev` recorder."""
    call_order: list[str] = []
    registry = RecordingRegistry(call_order)

    integrity_prev_calls: list[dict[str, PrevPos]] = []

    def _apply(features: list[Feature], prev: dict[str, PrevPos]) -> list[Feature]:
        call_order.append("integrity.apply")
        integrity_prev_calls.append(dict(prev))
        return features

    integrity = Mock()
    integrity.apply = Mock(side_effect=_apply)

    def _publish(snap: LayerSnapshot) -> None:
        call_order.append("events.publish_snapshot")

    events = Mock()
    events.publish_snapshot = Mock(side_effect=_publish)

    async def _put_fallback(snap: LayerSnapshot) -> None:
        call_order.append("store.put_fallback")

    store = AsyncMock()
    store.put_fallback = AsyncMock(side_effect=_put_fallback)
    store.get_fallback = AsyncMock(return_value=get_fallback_return)

    return call_order, registry, integrity, integrity_prev_calls, events, store


async def _refresh_tolerating_adapter_errors(scheduler, domain: Domain) -> None:
    """See module docstring: the spec does not pin whether `refresh()`
    swallows or re-raises the adapter's exception once `LayerStatus` has
    been recorded. Tolerating either keeps this test locked to what the
    plan actually specifies -- the resulting `current_status` -- without
    overspecifying an exception-propagation detail the plan never
    mentions."""
    try:
        await scheduler.refresh(domain)
    except Exception:  # noqa: BLE001 - deliberately broad, see docstring
        pass


async def test_fresh_fetch_yields_live_ordered_write_path_and_persisted_air_fallback_without_raw_payload():
    from backend.scheduler import Scheduler

    now = datetime.now(timezone.utc)
    feature_with_raw = _feature(
        "A1", 10.0, 20.0, now, raw_payload={"icao24": "a1a1a1", "secret": "do-not-ship"}
    )
    snap = LayerSnapshot(
        meta=_adapter_meta(timestamp_source=now, feature_count=1, cadence_s=10),
        features=[feature_with_raw],
    )
    adapter = ScriptedAdapter(Domain.AIR, [snap])
    call_order, registry, integrity, integrity_prev_calls, events, store = (
        _build_collaborators()
    )
    cfg = _make_cfg(cadence_s=10)
    scheduler = Scheduler(
        cfg,
        {Domain.AIR: adapter},
        HORMUZ_REGION,
        registry=registry,
        integrity=integrity,
        store=store,
        events=events,
    )

    # ---------------------------------------------------------------
    # When: a poll fetch returns a snapshot whose source timestamp is fresh
    # (age ~0s, well under stale_after_s = cadence_s * 2 = 20s).
    # ---------------------------------------------------------------
    await scheduler.refresh(Domain.AIR)

    # ---------------------------------------------------------------
    # Then: the layer status is `live`.
    # ---------------------------------------------------------------
    assert scheduler.current_status(Domain.AIR) == LayerStatus.LIVE

    # And: integrity's `prev` was empty on this, the very first air fetch
    # (no prior registry snapshot exists to derive it from).
    assert integrity_prev_calls == [{}]

    # And: integrity ran before the registry was set, SSE published after
    # the registry was set, and the air fallback persist came last --
    # scheduler.md "Write path" steps 2 (integrity) / 4 (registry) /
    # 5 (SSE) / 6 (fallback), in that exact order.
    assert call_order == [
        "integrity.apply",
        "registry.set",
        "events.publish_snapshot",
        "store.put_fallback",
    ]

    # And: the registry now holds the written snapshot for air.
    assert registry[Domain.AIR].meta.status == LayerStatus.LIVE

    # And: an air fallback row was persisted.
    store.put_fallback.assert_awaited_once()
    persisted_snap = store.put_fallback.await_args.args[0]
    assert persisted_snap.meta.layer == Domain.AIR

    # And: raw_payload never rides the published or persisted snapshot --
    # proven by seeding a feature WITH a raw_payload above and checking it
    # is absent from both serialized forms.
    published_snap = events.publish_snapshot.call_args.args[0]
    assert "raw_payload" not in published_snap.model_dump_json()
    assert "raw_payload" not in persisted_snap.model_dump_json()


async def test_aged_source_timestamp_yields_stale_status():
    from backend.scheduler import Scheduler

    # cadence_s=10 -> stale_after_s = 20s; 100s is well past that threshold.
    old = datetime.now(timezone.utc) - timedelta(seconds=100)
    snap = LayerSnapshot(
        meta=_adapter_meta(timestamp_source=old, feature_count=0, cadence_s=10),
        features=[],
    )
    adapter = ScriptedAdapter(Domain.AIR, [snap])
    call_order, registry, integrity, integrity_prev_calls, events, store = (
        _build_collaborators()
    )
    cfg = _make_cfg(cadence_s=10)
    scheduler = Scheduler(
        cfg,
        {Domain.AIR: adapter},
        HORMUZ_REGION,
        registry=registry,
        integrity=integrity,
        store=store,
        events=events,
    )

    # ---------------------------------------------------------------
    # When: a fetch returns a snapshot whose source age exceeds 2x cadence.
    # ---------------------------------------------------------------
    await scheduler.refresh(Domain.AIR)

    # ---------------------------------------------------------------
    # Then: the layer status is `stale`.
    # ---------------------------------------------------------------
    assert scheduler.current_status(Domain.AIR) == LayerStatus.STALE


async def test_fetch_failure_with_warm_region_matched_cache_yields_cached_fallback_not_error():
    from backend.scheduler import Scheduler

    warm_row = LayerSnapshot(
        meta=_adapter_meta(
            timestamp_source=datetime.now(timezone.utc), feature_count=0, cadence_s=10
        ),
        features=[],
    )
    adapter = ScriptedAdapter(Domain.AIR, [UpstreamError("upstream 503")])
    call_order, registry, integrity, integrity_prev_calls, events, store = (
        _build_collaborators(get_fallback_return=warm_row)
    )
    cfg = _make_cfg(cadence_s=10)
    scheduler = Scheduler(
        cfg,
        {Domain.AIR: adapter},
        HORMUZ_REGION,
        registry=registry,
        integrity=integrity,
        store=store,
        events=events,
    )

    # ---------------------------------------------------------------
    # When: a fetch fails and a warm, region-matched cache exists
    # (warm_row.meta.region_id == HORMUZ_REGION.id, the active region).
    # ---------------------------------------------------------------
    await _refresh_tolerating_adapter_errors(scheduler, Domain.AIR)

    # ---------------------------------------------------------------
    # Then: the layer status is `cached-fallback` (NOT `error`) --
    # scheduler.md "cached-fallback beats error".
    # ---------------------------------------------------------------
    assert scheduler.current_status(Domain.AIR) == LayerStatus.CACHED_FALLBACK

    # And: the cache was actually consulted (not a hardcoded status).
    store.get_fallback.assert_awaited()

    # And: a failed fetch never runs the successful-update-only fallback
    # persist step (scheduler.md "Write path" step 6 is part of the
    # SUCCESSFUL write path only).
    store.put_fallback.assert_not_called()


async def test_fetch_failure_with_region_mismatched_cache_yields_error_not_cached_fallback():
    """Inner unit test (deferred from the outer test's docstring, added at
    marker-removal time): scheduler.md "cached-fallback beats error" reads
    "...and its region_id matches the active region" -- a warm cache row
    exists (`store.get_fallback` returns non-None), but its
    `meta.region_id` is a DIFFERENT region than the one this scheduler is
    active for. This must still map to `error`, not `cached-fallback`; a
    stub that maps "any non-None cache row" to `cached-fallback` (ignoring
    region_id entirely) would pass the sibling matching-region test above
    but wrongly pass this row through too -- this test is what actually
    proves the region-match gate exists and is consulted, not just that
    `get_fallback` returned something."""
    from backend.scheduler import Scheduler

    stale_other_region_row = LayerSnapshot(
        meta=_adapter_meta(
            timestamp_source=datetime.now(timezone.utc), feature_count=0, cadence_s=10
        ),
        features=[],
    )
    stale_other_region_row.meta.region_id = "some-other-region"
    adapter = ScriptedAdapter(Domain.AIR, [UpstreamError("upstream 503")])
    call_order, registry, integrity, integrity_prev_calls, events, store = (
        _build_collaborators(get_fallback_return=stale_other_region_row)
    )
    cfg = _make_cfg(cadence_s=10)
    scheduler = Scheduler(
        cfg,
        {Domain.AIR: adapter},
        HORMUZ_REGION,
        registry=registry,
        integrity=integrity,
        store=store,
        events=events,
    )

    # ---------------------------------------------------------------
    # When: a fetch fails and a warm cache row exists, but its region_id
    # ("some-other-region") does NOT match the scheduler's active region
    # (HORMUZ_REGION.id == "hormuz").
    # ---------------------------------------------------------------
    await _refresh_tolerating_adapter_errors(scheduler, Domain.AIR)

    # ---------------------------------------------------------------
    # Then: the layer status is `error` (NOT `cached-fallback`) -- a
    # region-mismatched cache row does not count as a warm fallback.
    # ---------------------------------------------------------------
    assert scheduler.current_status(Domain.AIR) == LayerStatus.ERROR

    # And: the cache was actually consulted (the mismatch, not a missing
    # lookup, is what drove the `error` outcome).
    store.get_fallback.assert_awaited()

    # And: still no successful-write-path steps ran on this failed fetch.
    store.put_fallback.assert_not_called()


async def test_fetch_failure_with_no_cache_yields_error():
    from backend.scheduler import Scheduler

    adapter = ScriptedAdapter(Domain.AIR, [UpstreamError("upstream 503")])
    call_order, registry, integrity, integrity_prev_calls, events, store = (
        _build_collaborators(get_fallback_return=None)
    )
    cfg = _make_cfg(cadence_s=10)
    scheduler = Scheduler(
        cfg,
        {Domain.AIR: adapter},
        HORMUZ_REGION,
        registry=registry,
        integrity=integrity,
        store=store,
        events=events,
    )

    # ---------------------------------------------------------------
    # When: a fetch fails and no cache exists.
    # ---------------------------------------------------------------
    await _refresh_tolerating_adapter_errors(scheduler, Domain.AIR)

    # ---------------------------------------------------------------
    # Then: the layer status is `error`.
    # ---------------------------------------------------------------
    assert scheduler.current_status(Domain.AIR) == LayerStatus.ERROR

    # And: the cache was actually consulted (not a hardcoded status), and
    # nothing in the successful write path ran -- there was no snapshot to
    # run it on.
    store.get_fallback.assert_awaited()
    integrity.apply.assert_not_called()
    assert Domain.AIR not in registry
    events.publish_snapshot.assert_not_called()
    store.put_fallback.assert_not_called()


async def test_air_prev_derived_from_outgoing_registry_snapshot_before_replacement():
    from backend.scheduler import Scheduler

    t1 = datetime.now(timezone.utc) - timedelta(seconds=5)
    t2 = datetime.now(timezone.utc)
    feature_1 = _feature("A1", 10.0, 20.0, t1)
    feature_2 = _feature("A1", 10.5, 20.5, t2)
    snap_1 = LayerSnapshot(
        meta=_adapter_meta(timestamp_source=t1, feature_count=1, cadence_s=10),
        features=[feature_1],
    )
    snap_2 = LayerSnapshot(
        meta=_adapter_meta(timestamp_source=t2, feature_count=1, cadence_s=10),
        features=[feature_2],
    )
    adapter = ScriptedAdapter(Domain.AIR, [snap_1, snap_2])
    call_order, registry, integrity, integrity_prev_calls, events, store = (
        _build_collaborators()
    )
    cfg = _make_cfg(cadence_s=10)
    scheduler = Scheduler(
        cfg,
        {Domain.AIR: adapter},
        HORMUZ_REGION,
        registry=registry,
        integrity=integrity,
        store=store,
        events=events,
    )

    # First air fetch ever: no prior registry snapshot to derive `prev` from.
    await scheduler.refresh(Domain.AIR)
    assert integrity_prev_calls[0] == {}

    # Second air fetch: `prev` is derived from the OUTGOING registry
    # snapshot (snap_1, as written after the first fetch) before it is
    # replaced by snap_2 -- scheduler.md "Write path" step 2: "derived by
    # the scheduler from the outgoing registry snapshot before step 4
    # replaces it: {f.source_id: (f.lat, f.lon, f.timestamp_source) for f
    # in registry[AIR].features}". The real (non-mocked) Integrity.apply
    # consumes `prev` via attribute access (`prev_pos.lat`, `.lon`,
    # `.timestamp_source`; backend/integrity.py), so the scheduler must
    # build `PrevPos` instances here, not raw tuples.
    await scheduler.refresh(Domain.AIR)
    assert integrity_prev_calls[1] == {
        "A1": PrevPos(lat=10.0, lon=20.0, timestamp_source=t1)
    }
