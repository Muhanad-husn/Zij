"""Locked outer acceptance test for sources-marine step (issue #47):
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

This is the behavioral contract (), transcribed from
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
websockets.connect(uri) as ws:`) the developer picks. The fixture lines are
yielded verbatim (raw JSON text, undecoded) via `async for raw in ws:`,
exercising the adapter's own `json.loads` + dispatch-by-`MessageType`, not a
pre-parsed stub.

Names this test requires the developer to provide (spec/plan-fixed unless
noted "author's plumbing choice"):
  - backend.sources.aisstream.AisStreamAdapter(cfg, secrets) with async
    start()/stop()/set_region(region), sync snapshot(), and a `connected`
    property (design/specs/aisstream.md "Public interface").
  - backend.sources.aisstream.AisStreamCfg, constructible from the merged
    `[aisstream]` + `[layers.marine]` config tables
    (`AisStreamCfg(**cfg.aisstream, **cfg.layers["marine"].model_dump())`),
    mirroring `OpenSkyCfg`'s established shape (test_opensky.py) -- including
    accepting the full `LayerCfg.model_dump()` key set (so
    `simplify_tolerance_deg`/`max_rendered_features`, unused by marine, must
    have defaults) -- this merge convention is this author's plumbing
    choice, transplanted from the sibling adapter, not spec-prose-fixed.
  - `AisStreamAdapter._read_task: asyncio.Task` (spec-fixed name,
    design/specs/aisstream.md "Internal design": "`_ws / _read_task:
    asyncio.Task`") -- awaited directly here (instead of a sleep-based poll
    loop) to deterministically drain the finite recorded fixture before
    calling `snapshot()`.
  - `AisStreamAdapter._prev_pos: dict[str, tuple[float, float, datetime |
    None]]` keyed by MMSI (author's plumbing choice for the *shape* of
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
    developer reads.

It was authored and committed red by the author before any
implementation existed (strict xfail, ): at this point
`backend.sources.aisstream` does not exist at all, so the module-scope
import inside the test body raises `ModuleNotFoundError`, which xfails
cleanly under the tests-green gate. Not satisfiable by a stub that returns an
empty snapshot: the exact feature count (2, not 0/1/3), the live vessel's
overwritten position/enriched name/SOG/COG/511-sentinel-heading, the prior
fix in `_prev_pos`, and the STALE/dropped partition across three distinct
vessels are all asserted against concrete values pinned to the recorded
fixture. the developer has since made it genuinely pass; the xfail marker
has been removed to finalize the contract.

Below the outer test are inner unit tests () covering plan items
("Inner loop -- initial unit test list",
plans/sources-marine/01-aisstream-core.md) the outer test deliberately does
not exercise, or exercises only incidentally:
  - the bbox `[w,s,e,n]` -> aisstream `[[s,w],[n,e]]` corner transform in the
    subscribe payload -- the outer test's `_FakeAisStreamConnection` records
    `.sent` but the outer test never inspects it, so the transform itself is
    unpinned there.
  - `PositionReport` -> `_Entry` mapping for a NORMAL (non-511) heading --
    the outer test's live vessel is only ever sampled after its second,
    overwriting `PositionReport` (heading=511->None), so a real numeric
    heading passing through `attrs["heading_deg"]` unchanged is never
    actually pinned by the outer test; paired here with the 511 sentinel
    case as the two-way branch of the same mapping.
  - `ShipStaticData` enrichment NOT moving position/`last_heard` -- the
    outer fixture's static message happens to carry the same lat/lon as the
    live vessel's preceding `PositionReport`, so the outer test cannot
    distinguish "position held" from "position coincidentally re-set to the
    same value"; also pins the "no entry yet -> no-op" branch (spec:
    "Does not create an entry on its own").
  - `snapshot()` fresh-copy / no-I/O behavior -- the outer test only ever
    calls `snapshot()` once, after a full mocked-websocket round trip, so it
    cannot show two calls return distinct `Feature` objects, or that
    `snapshot()` needs no live connection at all.

The `_prev_pos` overwrite copy and the STALE (>30 min) / dropped (>2 h)
aging partition are both already pinned by the outer test against concrete
fixture values across three distinct MMSIs, so they are not duplicated here.
"""

from __future__ import annotations

import asyncio
import json
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
    which calling convention the developer picks."""

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
        # to step (plan "Out of scope").
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


def _make_aisstream_cfg(**overrides):
    """Minimal `AisStreamCfg` for inner unit tests that only exercise
    message-handling / snapshot logic, not a live connection (author's
    plumbing choice -- the required field set is spec-fixed, the values here
    are arbitrary placeholders)."""
    from backend.sources.aisstream import AisStreamCfg

    defaults = dict(
        ws_url="wss://stream.aisstream.io/v0/stream",
        cadence_s=60,
        cadence_floor_s=60,
        custom_bbox_cap_sq_deg=40.0,
    )
    defaults.update(overrides)
    return AisStreamCfg(**defaults)


def _position_report_line(
    mmsi: int,
    lat: float,
    lon: float,
    time_utc: str,
    *,
    sog: float = 0.0,
    cog: float = 0.0,
    heading: int = 0,
    nav_status: int = 0,
    ship_name: str = "",
) -> str:
    """A raw (undecoded) PositionReport frame, mirroring the recorded
    fixture's wire shape."""
    return json.dumps(
        {
            "MessageType": "PositionReport",
            "MetaData": {
                "MMSI": mmsi,
                "ShipName": ship_name,
                "latitude": lat,
                "longitude": lon,
                "time_utc": time_utc,
            },
            "Message": {
                "PositionReport": {
                    "Latitude": lat,
                    "Longitude": lon,
                    "Cog": cog,
                    "Sog": sog,
                    "TrueHeading": heading,
                    "NavigationalStatus": nav_status,
                }
            },
        }
    )


def _ship_static_data_line(
    mmsi: int,
    *,
    lat: float = 0.0,
    lon: float = 0.0,
    name: str = "TEST VESSEL",
    call_sign: str = "T3ST1",
    ship_type: int = 70,
) -> str:
    """A raw (undecoded) ShipStaticData frame. `MetaData.latitude/longitude`
    is deliberately settable independently of any prior PositionReport, to
    prove enrichment never moves the entry's actual feature position."""
    return json.dumps(
        {
            "MessageType": "ShipStaticData",
            "MetaData": {
                "MMSI": mmsi,
                "ShipName": name,
                "latitude": lat,
                "longitude": lon,
                "time_utc": "2026-07-09 10:05:00.000000 +0000 UTC",
            },
            "Message": {
                "ShipStaticData": {
                    "Name": name,
                    "CallSign": call_sign,
                    "Type": ship_type,
                }
            },
        }
    )


async def test_subscribe_payload_bbox_corner_transform():
    """Inner unit (plan item 1): `region.bbox` `[w,s,e,n]` is transformed to
    aisstream's own `[[s,w],[n,e]]` corner order in the subscribe payload
    (aisstream.md "Websocket lifecycle"). Deliberately asymmetric bbox
    values (10,20,30,40) so a transposed axis or swapped south/north would
    be caught -- a naive passthrough of `[w,s,e,n]` would leave
    `BoundingBoxes` as `[[10,20],[30,40]]`, not `[[20,10],[40,30]]`. The
    outer test's fake connection records `.sent` but the outer test itself
    never inspects it, so this transform is otherwise unpinned anywhere."""
    from backend.config import Secrets
    from backend.sources.aisstream import AisStreamAdapter
    from backend.sources.base import Region

    cfg = _make_aisstream_cfg()
    secrets = Secrets(aisstream_api_key="unit-test-api-key")
    adapter = AisStreamAdapter(cfg, secrets)
    await adapter.set_region(
        Region(id="test", label="Test", bbox=(10.0, 20.0, 30.0, 40.0))
    )

    payload = adapter._build_subscribe_payload()

    assert payload["BoundingBoxes"] == [[[20.0, 10.0], [40.0, 30.0]]]
    assert payload["APIKey"] == "unit-test-api-key"
    assert payload["FilterMessageTypes"] == ["PositionReport", "ShipStaticData"]


def test_position_report_heading_511_sentinel_vs_normal_passthrough():
    """Inner unit (plan item 2): `TrueHeading`'s 511 "not available" sentinel
    maps to `heading_deg=None`; any other numeric heading passes through
    unchanged (aisstream.md "Message handling"). The outer test only ever
    samples the live vessel's SECOND `PositionReport` (heading=511), so a
    normal heading value surviving into `attrs` unchanged is not otherwise
    pinned anywhere."""
    from backend.config import Secrets
    from backend.sources.aisstream import AisStreamAdapter

    cfg = _make_aisstream_cfg()
    secrets = Secrets(aisstream_api_key="unit-test-api-key")

    normal = AisStreamAdapter(cfg, secrets)
    normal._handle_message(
        _position_report_line(
            111222333, 10.0, 20.0, "2026-07-09 10:00:00.000000 +0000 UTC", heading=87
        )
    )
    assert normal._table["111222333"].feature.attrs["heading_deg"] == 87

    sentinel = AisStreamAdapter(cfg, secrets)
    sentinel._handle_message(
        _position_report_line(
            111222333, 10.0, 20.0, "2026-07-09 10:00:00.000000 +0000 UTC", heading=511
        )
    )
    assert sentinel._table["111222333"].feature.attrs["heading_deg"] is None


def test_ship_static_data_enriches_without_moving_position_or_last_heard():
    """Inner unit (plan item 3): a `ShipStaticData` message enriches
    name/callsign/ship_type and refreshes `label`, but does NOT move the
    entry's `lat`/`lon` or `last_heard` (aisstream.md: static "does not
    create an entry on its own" and is not itself "a position fix") -- and,
    for an MMSI never seen in a `PositionReport`, is a pure no-op. The outer
    fixture's static message happens to carry the SAME lat/lon as the
    preceding `PositionReport`, so it cannot distinguish "position held"
    from "coincidentally re-set to the same value"; this test uses a
    deliberately DIFFERENT `MetaData` lat/lon on the static message to catch
    that."""
    from backend.config import Secrets
    from backend.sources.aisstream import AisStreamAdapter

    cfg = _make_aisstream_cfg()
    secrets = Secrets(aisstream_api_key="unit-test-api-key")
    adapter = AisStreamAdapter(cfg, secrets)

    with freeze_time("2026-07-09T10:00:00+00:00"):
        adapter._handle_message(
            _position_report_line(
                366111222, 10.0, 20.0, "2026-07-09 10:00:00.000000 +0000 UTC"
            )
        )
    entry_before = adapter._table["366111222"]
    last_heard_before = entry_before.last_heard
    lat_before, lon_before = entry_before.feature.lat, entry_before.feature.lon

    with freeze_time("2026-07-09T10:05:00+00:00"):
        adapter._handle_message(_ship_static_data_line(366111222, lat=99.0, lon=88.0))

    entry_after = adapter._table["366111222"]
    assert entry_after.feature.lat == pytest.approx(lat_before)
    assert entry_after.feature.lon == pytest.approx(lon_before)
    assert entry_after.last_heard == last_heard_before
    assert entry_after.name == "TEST VESSEL"
    assert entry_after.callsign == "T3ST1"
    assert entry_after.feature.attrs["ship_type"] == 70
    assert entry_after.feature.label == "TEST VESSEL"

    # --- And: a ShipStaticData for an MMSI never seen in a PositionReport
    # is a pure no-op -- does not create an entry ---
    adapter._handle_message(_ship_static_data_line(999888777, lat=1.0, lon=1.0))
    assert "999888777" not in adapter._table


def test_snapshot_returns_fresh_copies_without_a_live_connection():
    """Inner unit (plan item 6): `snapshot()` needs no live websocket at all
    (adapter never `start()`-ed) and returns a genuinely fresh `Feature`
    object on every call, not a cached/shared reference (aisstream.md
    "snapshot()": "features are new objects (point-in-time copy)"). The
    outer test only ever calls `snapshot()` once, after a full
    mocked-socket round trip, so neither "no connection needed" nor "fresh
    object identity across calls" is pinned there."""
    from backend.config import Secrets
    from backend.models import Domain
    from backend.sources.aisstream import AisStreamAdapter

    cfg = _make_aisstream_cfg()
    secrets = Secrets(aisstream_api_key="unit-test-api-key")
    adapter = AisStreamAdapter(cfg, secrets)

    # No start()/connect at all -- snapshot() on a brand-new adapter is a
    # pure read of an empty table: no I/O, no raise.
    empty = adapter.snapshot()
    assert empty.meta.layer == Domain.MARINE
    assert empty.features == []

    adapter._handle_message(
        _position_report_line(
            366111222, 10.0, 20.0, "2026-07-09 10:00:00.000000 +0000 UTC"
        )
    )

    with freeze_time("2026-07-09T10:01:00+00:00"):
        first = adapter.snapshot()
        second = adapter.snapshot()

    # Same MMSI, but each snapshot() call must hand back its own object.
    assert first.features[0] is not second.features[0]
    assert first.features[0] == second.features[0]


def test_parse_aisstream_time_utc_variable_length_fraction():
    """Regression (reviewer finding, review pass on #47): Go's
    `time.Time.String()` prints a *variable-length* fractional-seconds
    component (0-9 digits, trailing zeros trimmed), not always 6. Before the
    fix, `_parse_aisstream_time_utc` only handled the exact 6-digit form the
    original fixture happened to use; the 0-digit ("no fraction at all") and
    9-digit (nanosecond) forms raised `ValueError` at `strptime`. This pins
    the pad/truncate-to-6-digits normalization across the whole legal range:
    no fraction, a short (3-digit) fraction, and a full 9-digit nanosecond
    fraction that must be truncated, not rejected."""
    from backend.sources.aisstream import _parse_aisstream_time_utc

    # No "." at all -- the time landed exactly on the second.
    no_fraction = _parse_aisstream_time_utc("2026-07-09 11:58:00 +0000 UTC")
    assert no_fraction == datetime(2026, 7, 9, 11, 58, 0, 0, tzinfo=timezone.utc)
    assert no_fraction.tzinfo is not None
    assert no_fraction.utcoffset() == timezone.utc.utcoffset(None)

    # 3-digit fraction -- padded up to 6 digits (123 -> 123000 microseconds),
    # not left/right-justified any other way.
    mid = _parse_aisstream_time_utc("2026-07-09 11:58:00.123 +0000 UTC")
    assert mid.microsecond == 123000
    assert mid.tzinfo is not None

    # 9-digit nanosecond fraction -- truncated to microsecond precision
    # (123456789 -> 123456), not rejected by strptime's 1-6 digit `%f`.
    nano = _parse_aisstream_time_utc("2026-07-09 11:58:00.123456789 +0000 UTC")
    assert nano.microsecond == 123456
    assert nano.tzinfo is not None
    assert nano.utcoffset() == timezone.utc.utcoffset(None)


def test_snapshot_feature_attrs_is_a_distinct_dict_per_snapshot():
    """Regression (reviewer finding, review pass on #47): before the fix,
    `snapshot()`'s `model_copy(update={"attrs": ...})` still handed back the
    SAME `attrs` dict object the stored `_table` entry's `Feature` held (a
    shallow `model_copy` without an explicit fresh `attrs` copy shares
    mutable field values by reference), so a caller mutating a returned
    snapshot's `attrs` would corrupt the adapter's own internal state. This
    drives a real PositionReport through `_handle_message` (same helper the
    other inner unit tests use) to build genuine table state, then proves
    the snapshotted feature's `attrs` is a distinct object from -- and
    mutating it does not affect -- the stored entry's `attrs`."""
    from backend.config import Secrets
    from backend.sources.aisstream import AisStreamAdapter

    cfg = _make_aisstream_cfg()
    secrets = Secrets(aisstream_api_key="unit-test-api-key")
    adapter = AisStreamAdapter(cfg, secrets)

    adapter._handle_message(
        _position_report_line(
            366111222,
            10.0,
            20.0,
            "2026-07-09 10:00:00.000000 +0000 UTC",
            sog=5.0,
            cog=45.0,
        )
    )

    snapshot = adapter.snapshot()
    assert len(snapshot.features) == 1
    snap_feature = snapshot.features[0]
    entry = adapter._table["366111222"]

    assert snap_feature.attrs is not entry.feature.attrs
    assert snap_feature.attrs == entry.feature.attrs

    snap_feature.attrs["sog_kn"] = 999.0
    snap_feature.attrs["injected"] = "should not leak"

    assert entry.feature.attrs["sog_kn"] == pytest.approx(5.0)
    assert "injected" not in entry.feature.attrs
