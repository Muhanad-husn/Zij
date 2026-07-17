"""Acceptance test for issue #113: the scheduler and a marine adapter are
wired into the REAL app lifespan.

Given the real `create_app` factory, with a fake marine `StreamAdapter`
      injected via a NEW `marine_adapter` keyword-only parameter and a fast
      marine cadence in the injected config (air/land disabled so the run is
      hermetic and unambiguous)
When  the app is served under its genuine ASGI lifespan (a real running
      uvicorn server -- lifespan startup/shutdown actually execute, unlike a
      bare `create_app(...)` construction)
Then  the scheduler's background loop(s) actually start: WITHOUT any manual
      refresh call, `GET /api/layers/marine/snapshot` becomes 200 carrying
      the injected fake's data
And   an SSE `snapshot` event for the marine layer is observable on
      `GET /api/events`, again with no manual refresh
And   the fake stream adapter's `start()` was called during startup and its
      `stop()` during shutdown (adapter-interface.md "Async lifecycle":
      startup calls `start()` on every enabled adapter; shutdown calls
      `stop()` on all adapters)
And   shutting the server down (lifespan exit) completes cleanly within a
      bounded timeout -- no hang, no exception propagating out of shutdown.

Spec basis (an implementation gap, NOT an inconsistency in the spec -- see
issue #113): design/specs/scheduler.md "Task model" ("`run()` opens one
`asyncio.TaskGroup`" / "lifetime = app lifetime" / "One `_stream_supervisor()`
task if the marine source is a `StreamAdapter`"); design/docs/ARCHITECTURE.md
§4.1 ("scheduler starts adapter tasks at startup"); design/contracts/
adapter-interface.md "Async lifecycle & region propagation" (startup calls
`start()`, shutdown calls `stop()`, on every adapter). Today `backend/
main.py:create_app` builds a `Scheduler` with only
`{Domain.AIR: air_adapter, Domain.LAND: land_adapter}`, never imports
`backend.sources.aisstream`, has no `marine_adapter` parameter, and its
lifespan only does `await store.init()` / `await store.close()` -- it never
calls `scheduler.run()` at all, so the real app never starts a single
background task and `GET /api/layers/marine/snapshot` 404s forever.

Design seam this test locks in (backend/main.py):

    def create_app(*, static_dir, config, secrets,
                    air_adapter=None, land_adapter=None,
                    marine_adapter: StreamAdapter | None = None,
                    store=None, registry=None, events=None,
                    scheduler=None) -> FastAPI: ...

`marine_adapter` is a NEW optional keyword-only collaborator mirroring the
already-optional `air_adapter`/`land_adapter` (same "extend without a
rewrite" shape, api-core precedent): when omitted, `create_app` builds the
default `AisStreamAdapter` from `config`/`secrets` (mirroring how
`air_adapter` defaults to `OpenSkyAdapter`); when supplied, as here with a
test double, it is used verbatim and wired into `Scheduler(..., stream=
marine_adapter)`. The lifespan must start `scheduler.run()` as a background
task at startup and cancel/await it cleanly at shutdown -- every existing
`create_app(...)` call site in `test_api.py` keeps working unmodified
because every new parameter is optional.

Committed red before any implementation existed (xfail): at that
point `create_app(..., marine_adapter=...)` raised `TypeError` on the
unknown keyword, so the tests failed immediately and xfailed cleanly.
The implementation has since made both genuinely pass;
the xfail markers have been removed to finalize the contract.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import httpx
import uvicorn

# Fast, hermetic marine cadence (config.md "[layers.*]": `cadence_s`/
# `cadence_floor_s`; `effective_cadence_s = max(cadence_s, cadence_floor_s)`)
# so the scheduler's marine sampling loop -- once it exists -- has time to
# fire well within this test's bounded waits.
_MARINE_CADENCE_S = 1
_ACTIVE_REGION_ID = "hormuz"  # config.toml's regions[0].id (load_config default)
_FAKE_MMSI = "999000111"


def _make_fake_marine_stream():
    """A minimal `StreamAdapter` double (mirrors
    `test_scheduler_region_toggle.py::FakeStreamAdapter`): records
    start/stop/set_region calls and serves a fixed, non-empty
    `LayerSnapshot` from `snapshot()` -- no real websocket, no network.
    Deferred imports (never at module top) so this file never triggers the
    `backend.sources.*`/`backend.main` secret gate at collection time."""
    from datetime import datetime, timezone

    from backend.models import (
        Domain,
        Feature,
        FeatureStatus,
        GeometryType,
        LayerSnapshot,
        LayerSnapshotMeta,
        LayerStatus,
    )
    from backend.sources.base import Region, StreamAdapter

    class _FakeMarineStream(StreamAdapter):
        domain = Domain.MARINE
        source = "fake-aisstream"

        def __init__(self) -> None:
            self.start_calls = 0
            self.stop_calls = 0
            self.set_region_calls: list[Region] = []
            self._connected = False

        async def start(self) -> None:
            self.start_calls += 1
            self._connected = True

        async def stop(self) -> None:
            self.stop_calls += 1
            self._connected = False

        async def set_region(self, region: Region) -> None:
            self.set_region_calls.append(region)

        @property
        def connected(self) -> bool:
            return self._connected

        def snapshot(self) -> LayerSnapshot:
            now = datetime.now(timezone.utc)
            feature = Feature(
                domain=Domain.MARINE,
                source=self.source,
                source_id=_FAKE_MMSI,
                label="MV OUTER TEST",
                lat=26.5,
                lon=56.2,
                geometry_type=GeometryType.POINT,
                geometry=None,
                timestamp_source=now,
                timestamp_fetched=now,
                position_age_s=0.0,
                status=FeatureStatus.LIVE,
                attrs={"sog_kn": 12.3},
                raw_payload={"MessageType": "PositionReport"},
            )
            meta = LayerSnapshotMeta(
                layer=Domain.MARINE,
                region_id=_ACTIVE_REGION_ID,
                status=LayerStatus.LIVE,
                timestamp_fetched=now,
                timestamp_source=now,
                cadence_s=_MARINE_CADENCE_S,
                stale_after_s=2 * _MARINE_CADENCE_S,
                feature_count=1,
            )
            return LayerSnapshot(meta=meta, features=[feature])

    return _FakeMarineStream()


@contextlib.asynccontextmanager
async def _serving(app):
    """Serve `app` on a real ephemeral-port uvicorn server IN-PROCESS so its
    lifespan startup/shutdown genuinely run (`uvicorn.Server.serve()` drives
    the ASGI lifespan protocol) -- unlike a bare `create_app(...)`
    construction, or `httpx.ASGITransport` used directly, which accumulates
    an entire response before yielding it and so can't stream an infinite
    SSE response (see `test_api.py::_connect_sse`, same rationale). Yields
    the server's `base_url`; on exit, requests a graceful stop and awaits the
    serve task under a bounded timeout, so a lifespan-shutdown hang or
    exception fails THIS test rather than hanging the suite (and blocking
    the pre-commit test run)."""
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    )
    serve_task = asyncio.create_task(server.serve())
    try:

        async def _await_started() -> None:
            while not server.started:  # noqa: ASYNC110 (bounded by wait_for below)
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_await_started(), timeout=10.0)
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        # A hang or a raised exception here is exactly "shutdown is not
        # clean" -- deliberately NOT suppressed, so it fails this test.
        await asyncio.wait_for(serve_task, timeout=10.0)


async def _iter_sse_frames(response: httpx.Response):
    """Parse a `text/event-stream` body into `{"event", "data", "id"}`-shaped
    frame dicts, skipping sse-starlette's `:`-prefixed ping/comment heartbeat
    lines (api.md "event: ping"). Mirrors `test_api.py::_iter_sse_frames`."""
    current: dict[str, str] = {}
    async for raw_line in response.aiter_lines():
        line = raw_line.rstrip("\n")
        if line == "":
            if current:
                yield current
                current = {}
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "data" and "data" in current:
            current["data"] += "\n" + value
        else:
            current[field] = value


async def _find_marine_snapshot_frame(response: httpx.Response, *, timeout_s: float):
    """Read frames off `response` until a `snapshot` event for the marine
    layer is observed, or `timeout_s` elapses (whichever first) -- proving
    the SSE event was genuinely PUSHED by the running app, not fabricated by
    the test."""
    frames = _iter_sse_frames(response)
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    while True:
        remaining = deadline - loop.time()
        assert remaining > 0, "no marine `snapshot` SSE frame observed in time"
        frame = await asyncio.wait_for(frames.__anext__(), timeout=remaining)
        if frame.get("event") != "snapshot":
            continue
        data = json.loads(frame["data"])
        if data.get("meta", {}).get("layer") == "marine":
            return data


async def test_marine_snapshot_and_sse_populate_via_real_app_lifespan_without_manual_refresh(
    tmp_path,
):
    from backend.config import load_config
    from backend.main import create_app
    from backend.store import Store

    # --- Given: a hermetic config -- air/land disabled (no network, no
    # ambiguity about which layer produced an SSE frame), marine enabled with
    # a fast cadence so the (currently nonexistent) marine sampling loop has
    # every chance to fire within this test's bounded waits ---
    cfg, secrets = load_config(
        overrides={
            "layers": {
                "air": {"enabled": False},
                "land": {"enabled": False},
                "marine": {
                    "enabled": True,
                    "cadence_s": _MARINE_CADENCE_S,
                    "cadence_floor_s": _MARINE_CADENCE_S,
                },
            }
        }
    )
    assert cfg.layers["air"].enabled is False
    assert cfg.layers["land"].enabled is False
    assert cfg.layers["marine"].enabled is True
    assert cfg.active_region_id == _ACTIVE_REGION_ID

    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        "<!doctype html><html><body>Zij</body></html>", encoding="utf-8"
    )

    fake_marine = _make_fake_marine_stream()
    store = Store(db_path=tmp_path / "lifespan.db")

    app = create_app(
        static_dir=static_dir,
        config=cfg,
        secrets=secrets,
        marine_adapter=fake_marine,
        store=store,
    )

    async with _serving(app) as base_url:
        async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
            # --- Then: GET /api/layers/marine/snapshot becomes 200 with the
            # fake's data, with NO manual refresh call anywhere in this test
            # (POST /api/layers/marine/refresh is never invoked) ---
            loop = asyncio.get_event_loop()
            deadline = loop.time() + 8.0
            snapshot_body = None
            while True:
                resp = await client.get("/api/layers/marine/snapshot")
                if resp.status_code == 200:
                    snapshot_body = resp.json()
                    break
                assert loop.time() < deadline, (
                    "GET /api/layers/marine/snapshot never became 200 "
                    f"(last status {resp.status_code}, body {resp.text!r})"
                )
                await asyncio.sleep(0.1)

            assert snapshot_body["meta"]["layer"] == "marine"
            assert snapshot_body["meta"]["region_id"] == _ACTIVE_REGION_ID
            assert snapshot_body["meta"]["feature_count"] == 1
            assert len(snapshot_body["features"]) == 1
            assert snapshot_body["features"][0]["source_id"] == _FAKE_MMSI

            # --- And: an SSE `snapshot` event for marine is observable ---
            async with client.stream("GET", "/api/events") as sse_resp:
                assert sse_resp.status_code == 200
                marine_data = await _find_marine_snapshot_frame(sse_resp, timeout_s=8.0)
                assert marine_data["meta"]["region_id"] == _ACTIVE_REGION_ID
                assert marine_data["meta"]["feature_count"] == 1
                assert marine_data["features"][0]["source_id"] == _FAKE_MMSI

            # --- And: adapter-interface.md's async lifecycle was honored --
            # start() at startup ---
            assert fake_marine.start_calls >= 1

    # --- And: shutdown was clean (the `_serving` context manager above
    # already asserts the serve task exits within its bounded timeout without
    # raising) AND stop() was called on the marine adapter during it ---
    assert fake_marine.stop_calls >= 1


# ===========================================================================
# Unit test: the default marine adapter -- built from config/secrets when
# `marine_adapter` is omitted -- must actually be an `AisStreamAdapter`
# wired into the scheduler, mirroring how `air_adapter` already defaults to
# an `OpenSkyAdapter`.
#
# `create_app(...)` alone never performs any I/O (only `AisStreamAdapter.
# start()`, invoked by `scheduler.run()`, opens the websocket) -- this test
# therefore never enters a lifespan context and needs no network mocking; it
# inspects the constructed object graph directly.
#
# Introspection seam this test expects to be exposed:
# `app.state.scheduler` (a `backend.scheduler.Scheduler` instance) -- a
# standard FastAPI `app.state` attribute.
# ===========================================================================


def test_default_app_wires_a_marine_stream_adapter_from_config_and_secrets(
    tmp_path,
):
    from backend.config import load_config
    from backend.main import create_app
    from backend.models import Domain, LayerStatus
    from backend.scheduler import Scheduler
    from backend.sources.aisstream import AisStreamAdapter

    # --- Given: the bundled config's marine layer enabled, with
    # AISSTREAM_API_KEY present (backend/tests/conftest.py's session-wide
    # hermetic baseline already supplies a non-empty value) ---
    cfg, secrets = load_config()
    assert cfg.layers["marine"].enabled is True
    assert secrets.aisstream_api_key

    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html></html>", encoding="utf-8")

    # --- When: create_app is built WITHOUT an injected marine_adapter ---
    app = create_app(static_dir=static_dir, config=cfg, secrets=secrets)

    # --- Then: the scheduler is exposed and carries a real AisStreamAdapter
    # wired as its marine `stream` collaborator ---
    assert isinstance(app.state.scheduler, Scheduler)
    assert isinstance(app.state.scheduler._stream, AisStreamAdapter)
    # Behavioral corroboration: current_status(MARINE) only returns a value
    # (rather than raising KeyError) once a stream has genuinely been
    # registered with the scheduler (scheduler.py's constructor only adds a
    # MARINE status/wake/generation slot when `stream is not None`).
    assert app.state.scheduler.current_status(Domain.MARINE) == LayerStatus.LOADING
