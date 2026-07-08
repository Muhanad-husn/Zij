"""Locked outer acceptance test for sources-marine slice 01 (issue #47):
aisstream core -- subscribe, message table, snapshot().

Given the recorded aisstream messages (backend/tests/fixtures/
      aisstream_messages.jsonl) fed through a mocked websocket
When  the read loop processes a PositionReport then a ShipStaticData for the
      same MMSI (plus a >30-min-silent and a >2h-silent vessel, in the same
      recording)
Then  snapshot() returns one MARINE feature (that MMSI) carrying position,
      enriched name, SOG and COG
And   _prev_pos holds that MMSI's prior fix (lat, lon, timestamp_source) for
      FR9
And   a vessel silent > 30 min renders FeatureStatus.STALE and one silent
      > 2 h is excluded
And   snapshot() performs no I/O and never raises

This is the behavioral contract (DEC-1), transcribed from
plans/sources-marine/01-aisstream-core.md ("Acceptance criterion") and
design/specs/aisstream.md ("Message handling" + "snapshot()"), honoring the
`StreamAdapter` surface in design/contracts/adapter-interface.md.

The recorded fixture is hand-authored (no live aisstream capture exists yet)
but mirrors the real aisstream.io wire shape verbatim: top-level
`MessageType`, `MetaData.{MMSI,ShipName,time_utc}`, and
`Message.PositionReport.*` / `Message.ShipStaticData.*`. `time_utc` uses
aisstream's actual (non-ISO) wire format -- Go's `time.Time.String()`,
`"YYYY-MM-DD HH:MM:SS.ffffff +0000 UTC"` -- so a naive `datetime.fromisoformat`
implementation genuinely fails against it; this is not satisfiable by a stub
that ignores `MetaData.time_utc` or invents its own clock.

"Now" for the aging computation (spec: `snapshot()`'s `now =
datetime.now(UTC)`) is controlled via `freezegun.freeze_time`, matching the
project's established pattern for deterministic clock control
(test_opensky.py) rather than real wall-clock sleeps -- the fixture's
`time_utc` values are all authored as fixed offsets *before* the frozen "now"
(10/2/1 min for the live vessel's two fixes + static enrichment, 40 min for
the >30-min-stale vessel, 150 min for the >2h-dropped vessel), so aging is a
pure function of the recorded data, never of real elapsed time.

The mocked websocket is a `_FakeConnect`/`_FakeAisStreamConnection` pair
patched in for `backend.sources.aisstream.websockets.connect` (the module's
own `import websockets`, following aisstream.md "Websocket lifecycle": "via
the `websockets` library"). `_FakeConnect` mimics the real `websockets`
library's dual awaitable/async-context-manager `Connect` return value so this
test does not prescribe which of the two equally-idiomatic calling
conventions (`ws = await websockets.connect(uri)` vs. `async with
websockets.connect(uri) as ws:`) the implementer picks. The fixture lines are
yielded verbatim (raw JSON text, undecoded) via `async for raw in ws:`,
exercising the adapter's own `json.loads` + dispatch-by-`MessageType`, not a
pre-parsed stub.

Names this test requires the implementer to provide (spec/plan-fixed unless
noted "test-author's plumbing choice"):
  - backend.sources.aisstream.AisStreamAdapter(cfg, secrets) with async
    start()/stop()/set_region(region), sync snapshot(), and a `connected`
    property (design/specs/aisstream.md "Public interface").
  - backend.sources.aisstream.AisStreamCfg, constructible from the merged
    `[aisstream]` + `[layers.marine]` config tables
    (`AisStreamCfg(**cfg.aisstream, **cfg.layers["marine"].model_dump())`),
    mirroring `OpenSkyCfg`'s established shape (test_opensky.py) -- including
    accepting the full `LayerCfg.model_dump()` key set (so
    `simplify_tolerance_deg`/`max_rendered_features`, unused by marine, must
    have defaults) -- this merge convention is this test-author's plumbing
    choice, transplanted from the sibling adapter, not spec-prose-fixed.
  - `AisStreamAdapter._read_task: asyncio.Task` (spec-fixed name,
    design/specs/aisstream.md "Internal design": "`_ws / _read_task:
    asyncio.Task`") -- awaited directly here (instead of a sleep-based poll
    loop) to deterministically drain the finite recorded fixture before
    calling `snapshot()`.
  - `AisStreamAdapter._prev_pos: dict[str, tuple[float, float, datetime |
    None]]` keyed by MMSI (test-author's plumbing choice for the *shape* of
    `_PrevPos`, since the spec only fixes the field CONTENT as "(lat, lon,
    timestamp_source)" -- design/specs/aisstream.md "Message handling" -- not
    a concrete Python type; a plain 3-tuple in that literal order is the
    simplest reading of the spec's own parenthetical and this test unpacks it
    positionally).
  - `Feature.attrs` keys `sog_kn`/`cog_deg`/`heading_deg`/`nav_status`
    (design/specs/aisstream.md "Message handling": "attrs: sog_kn (Sog),
    cog_deg (Cog), heading_deg (TrueHeading, drop sentinel 511->None),
    nav_status (NavigationalStatus)").
  - `Feature.label`/enrichment sourced from either `MetaData.ShipName` or
    `Message.ShipStaticData.Name` (spec: "`_Entry.name` (`ShipName`/`Name`)"
    lists both without picking one) -- the fixture sets both to the identical
    value "MERIDIAN STAR" so this test does not need to pin which the
    implementer reads.

It was authored and committed red by the test-author before any
implementation existed (strict xfail, DEC-33): at this point
`backend.sources.aisstream` does not exist at all, so the module-scope
import inside the test body raises `ModuleNotFoundError`, which xfails
cleanly under the tests-green gate. Not satisfiable by a stub that returns an
empty snapshot: the exact feature count (2, not 0/1/3), the live vessel's
overwritten position/enriched name/SOG/COG/511-sentinel-heading, the prior
fix in `_prev_pos`, and the STALE/dropped partition across three distinct
vessels are all asserted against concrete values pinned to the recorded
fixture.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest
from freezegun import freeze_time

FIXTURES_DIR = Path(__file__).parent / "fixtures"
AISSTREAM_FIXTURE = FIXTURES_DIR / "aisstream_messages.jsonl"

# "Now" for the aging computation -- frozen, so position_age_s is a pure
# function of the recorded `time_utc` values, never of real wall-clock time.
FROZEN_NOW = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)

MMSI_LIVE = "366111222"  # PositionReport x2 + ShipStaticData -- the happy path
MMSI_STALE = "366222333"  # last heard 40 min before FROZEN_NOW -- > 30 min
MMSI_DROPPED = "366333444"  # last heard 150 min before FROZEN_NOW -- > 2 h


class _FakeAisStreamConnection:
    """Stand-in for a `websockets` client connection: async-iterates the
    recorded fixture lines as raw text frames -- mirroring `async for raw in
    ws:` (design/specs/aisstream.md "Read loop") -- and records `send()`
    calls (the subscribe payload). `close()` is a no-op."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.sent: list[str] = []
        self.closed = False

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self._iter_lines()

    async def _iter_lines(self):
        for line in self._lines:
            yield line


class _FakeConnect:
    """Stand-in for `websockets.connect(uri)`. The real `websockets` library
    returns a `Connect` object that is BOTH directly awaitable (`ws = await
    websockets.connect(uri)`) AND usable as `async with websockets.connect(
    uri) as ws:`. Supporting both here means this test does not prescribe
    which calling convention the implementer picks."""

    def __init__(self, connection: _FakeAisStreamConnection) -> None:
        self._connection = connection

    def __await__(self):
        async def _get() -> _FakeAisStreamConnection:
            return self._connection

        return _get().__await__()

    async def __aenter__(self) -> _FakeAisStreamConnection:
        return self._connection

    async def __aexit__(self, *exc_info: object) -> None:
        await self._connection.close()


def _load_fixture_lines() -> list[str]:
    lines = [
        line
        for line in AISSTREAM_FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 5, "fixture shape this test depends on has changed"
    return lines


@pytest.mark.xfail(
    reason="aisstream adapter (backend.sources.aisstream) not yet implemented",
    strict=True,
)
async def test_aisstream_processes_position_and_static_then_snapshot(monkeypatch):
    # --- Given: client credentials in env (NFR5: env only); the recorded
    # aisstream messages fed through a mocked websocket ---
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "test-opensky-client-id")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "test-opensky-client-secret")
    monkeypatch.setenv("AISSTREAM_API_KEY", "test-aisstream-api-key")
    monkeypatch.delenv("AISHUB_USERNAME", raising=False)
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)

    from backend.config import load_config
    from backend.models import Domain, FeatureStatus
    from backend.sources.aisstream import AisStreamAdapter, AisStreamCfg
    from backend.sources.base import Region

    cfg, secrets = load_config()
    aisstream_cfg = AisStreamCfg(**cfg.aisstream, **cfg.layers["marine"].model_dump())
    # Pin the two aging thresholds this test exercises are the real bundled
    # config values (config.toml [layers.marine]), not test-invented numbers.
    assert aisstream_cfg.deemphasize_after_s == 1800
    assert aisstream_cfg.drop_after_s == 7200

    region = Region(
        id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
    )
    lines = _load_fixture_lines()
    connection = _FakeAisStreamConnection(lines)
    monkeypatch.setattr(
        "backend.sources.aisstream.websockets.connect",
        lambda uri, **kwargs: _FakeConnect(connection),
    )

    with freeze_time(FROZEN_NOW):
        adapter = AisStreamAdapter(aisstream_cfg, secrets)

        # Region set before the socket opens -- aisstream.md's own
        # `set_region` docstring: "...if open, else it applies on next
        # connect" -- so this is the documented pre-connect bootstrap path,
        # not the full mid-stream re-subscribe/clear-table behavior deferred
        # to slice 02 (plan "Out of scope").
        await adapter.set_region(region)

        # --- When: start() connects the mocked socket, subscribes, and
        # launches the read loop; awaiting `_read_task` deterministically
        # drains the whole (finite) recorded fixture before `snapshot()` is
        # sampled -- no sleep-based polling ---
        await adapter.start()
        assert adapter.connected is True
        await asyncio.wait_for(adapter._read_task, timeout=5.0)

        # --- Then: snapshot() returns the live + stale vessels, excluding
        # the one silent > 2 h; sync call, no await, so a coroutine-returning
        # (i.e. accidentally async) snapshot() would fail every assertion
        # below rather than silently pass ---
        snapshot = adapter.snapshot()

    assert snapshot.meta.layer == Domain.MARINE
    assert len(snapshot.features) == 2
    by_mmsi = {feature.source_id: feature for feature in snapshot.features}
    assert set(by_mmsi) == {MMSI_LIVE, MMSI_STALE}

    # --- And: the MMSI that received a PositionReport then a
    # ShipStaticData carries position from the SECOND (overwriting)
    # PositionReport, the enriched name, and SOG/COG ---
    live = by_mmsi[MMSI_LIVE]
    assert live.status == FeatureStatus.LIVE
    assert live.lat == pytest.approx(26.15)
    assert live.lon == pytest.approx(56.25)
    assert live.label == "MERIDIAN STAR"
    assert live.attrs["sog_kn"] == pytest.approx(13.1)
    assert live.attrs["cog_deg"] == pytest.approx(91.0)
    # 511 sentinel (the live vessel's second PositionReport) -> None
    # (aisstream.md: "TrueHeading, drop sentinel 511->None").
    assert live.attrs["heading_deg"] is None
    assert live.attrs["nav_status"] == 0
    assert live.timestamp_source == datetime(2026, 7, 9, 11, 58, 0, tzinfo=timezone.utc)
    assert live.position_age_s == pytest.approx(120.0)  # FROZEN_NOW - 11:58

    # --- And: _prev_pos holds the PRIOR fix (from the FIRST PositionReport,
    # overwritten by the second) -- FR9 kinematics input (aisstream.md:
    # "Before overwriting, copy the outgoing entry's (lat,lon,
    # timestamp_source) into _prev_pos[MMSI]") ---
    prev_lat, prev_lon, prev_ts = adapter._prev_pos[MMSI_LIVE]
    assert prev_lat == pytest.approx(26.1)
    assert prev_lon == pytest.approx(56.2)
    assert prev_ts == datetime(2026, 7, 9, 11, 50, 0, tzinfo=timezone.utc)

    # --- And: a vessel silent > 30 min renders FeatureStatus.STALE (still
    # present -- de-emphasis, not exclusion) ---
    stale = by_mmsi[MMSI_STALE]
    assert stale.status == FeatureStatus.STALE
    assert stale.position_age_s == pytest.approx(2400.0)  # 40 min

    # --- And: the vessel silent > 2 h is excluded from snapshot() entirely
    # (aisstream.md: "age > cfg.drop_after_s -> excluded from the
    # snapshot") ---
    assert MMSI_DROPPED not in by_mmsi
