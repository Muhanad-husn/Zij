"""Locked outer acceptance test for opensky-adapter step (issue #13): OAuth2
token manager.

Given an OpenSkyAdapter started with client credentials, the token endpoint
      mocked to return a token valid ~1800 s
When  three fetch-driven token acquisitions are awaited concurrently
Then  exactly one HTTP request is made to the token endpoint and all three
      see the same cached token
And   after advancing the clock to within token_refresh_margin_s of expiry,
      the next acquisition triggers exactly one refresh request
And   a non-2xx token response raises AuthError (no auto-retry)

This is the behavioral contract (), transcribed from
plans/opensky-adapter/01-token-manager.md ("Acceptance criterion") and
design/specs/opensky.md ("Token manager (OAuth2 client-credentials)"), honoring
the error taxonomy in design/contracts/adapter-interface.md (`AuthError`).

To exercise a genuine cold-cache single-flight race (matching the plan's inner
unit test list item "N concurrent acquisitions on a cold cache trigger exactly
one token request"), the three concurrent "fetch-driven token acquisitions"
are driven as three concurrent `OpenSkyAdapter.start()` calls on a freshly
constructed, never-started adapter -- `start()` is documented
(adapter-interface.md: "Must be idempotent") and (opensky.md "Public
interface": "open AsyncClient, prefetch token") as calling into the same
internal acquire-or-reuse path a concurrent `fetch()` would use. Racing it
directly keeps this test on the adapter's genuinely public surface
(`start()`/`stop()`) plus the attribute names the spec itself fixes
(`_access_token`, `_TokenManager`) as the sole observable proof of "the same
cached token" -- no invented token-returning accessor method is required. The
mocked token endpoint's `side_effect` list deliberately has exactly 2 entries
(one for the cold-cache concurrent acquisition, one for the post-expiry
refresh): a broken (non-single-flight) implementation would issue 3 requests
during the concurrent `gather` alone and exhaust the list with a hard error,
not merely a wrong call count -- so this is not satisfiable by a stub.

Names this test requires the developer to provide (spec/plan-fixed unless
noted "author's plumbing choice"):
  - backend.sources.base.AuthError (design/contracts/adapter-interface.md).
  - backend.sources.opensky.OpenSkyAdapter(cfg, secrets, credits) with async
    start()/stop() (design/specs/opensky.md "Public interface").
  - OpenSkyAdapter._token_manager: an instance of the spec-named
    `_TokenManager` (opensky.md "Internal design"), exposing
    `_access_token: str | None` (spec-fixed name) -- the attribute NAME
    `_token_manager` on the adapter is this author's plumbing choice
    (not spec-fixed), needed only to observe the cached value from outside.
  - backend.sources.opensky.OpenSkyCfg, constructible from the merged
    `[opensky]` + `[layers.air]` config tables per opensky.md ("`OpenSkyCfg`
    = the `[opensky]` table + `[layers.air]`"); this test merges
    `cfg.opensky` and `cfg.layers["air"].model_dump()` as kwargs, so
    `OpenSkyCfg` must accept that combined key set (and expose
    `daily_credit_budget`/`token_refresh_margin_s`, already in `[opensky]`).
  - backend.sources.opensky.CreditLedger(budget=...) -- a trivially
    constructible ledger; no credit-spend behavior is exercised in this
    slice (deferred to step per the plan's "Out of scope").

It was authored and committed red by the author before any
implementation existed (strict xfail, ). the developer has since made
it genuinely pass; the xfail marker has been removed to finalize the
contract.

Below the outer test are inner unit tests () covering gaps the outer
test deliberately does not exercise: warm-cache *sequential* reuse (the outer
test only proves the cold-cache *concurrent* race is single-flight), a
connection-level failure on the token endpoint (the outer test only proves a
non-2xx HTTP response raises `AuthError`), and `backend/sources/base.py`'s
structural exposure of the adapter interface contract.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx
from freezegun import freeze_time
from httpx import Response

TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)
STATES_URL = "https://opensky-network.org/api/states/all"

TOKEN_RESPONSE_1 = {
    "access_token": "test-jwt-access-token-first-9f3c",
    "expires_in": 1800,
    "token_type": "bearer",
}
TOKEN_RESPONSE_2 = {
    "access_token": "test-jwt-access-token-refreshed-7e21",
    "expires_in": 1800,
    "token_type": "bearer",
}

FIXTURES_DIR = Path(__file__).parent / "fixtures"
OPENSKY_FIXTURE = FIXTURES_DIR / "opensky_states_all_hormuz.json"


async def test_token_manager_single_flight(monkeypatch):
    # --- Given: client credentials in env (NFR5: env only) ---
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "test-opensky-client-id")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "test-opensky-client-secret")
    # Marine is enabled in the bundled config.toml (slice config-02, #42); a
    # non-empty value keeps its secret gate from firing for an unrelated
    # reason in this air-adapter-focused test.
    monkeypatch.setenv("AISSTREAM_API_KEY", "test-aisstream-api-key")
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)

    from backend.config import load_config
    from backend.sources.base import AuthError
    from backend.sources.opensky import CreditLedger, OpenSkyAdapter, OpenSkyCfg

    cfg, secrets = load_config()
    opensky_cfg = OpenSkyCfg(**cfg.opensky, **cfg.layers["air"].model_dump())
    token_refresh_margin_s = cfg.opensky["token_refresh_margin_s"]
    credits = CreditLedger(budget=opensky_cfg.daily_credit_budget)

    with freeze_time("2026-07-05T00:00:00+00:00") as frozen_time:
        async with respx.mock() as respx_mock:
            # Exactly 2 responses: one for the cold-cache concurrent
            # acquisition below, one for the post-expiry refresh. A
            # non-single-flight implementation would issue 3 requests during
            # the concurrent gather alone and exhaust this list with an
            # error, not merely a miscount.
            token_route = respx_mock.post(TOKEN_URL).mock(
                side_effect=[
                    Response(200, json=TOKEN_RESPONSE_1),
                    Response(200, json=TOKEN_RESPONSE_2),
                ]
            )

            adapter = OpenSkyAdapter(opensky_cfg, secrets, credits)

            # --- When: three fetch-driven token acquisitions awaited
            # concurrently, on a cold (never-started) token cache ---
            await asyncio.gather(adapter.start(), adapter.start(), adapter.start())

            # --- Then: exactly one HTTP request made to the token endpoint,
            # and the single cached token is the one the mock returned (all
            # three racing callers converge on it) ---
            assert token_route.call_count == 1
            assert (
                adapter._token_manager._access_token
                == (TOKEN_RESPONSE_1["access_token"])
            )

            # --- And: advance the clock to within token_refresh_margin_s of
            # the ~1800 s expiry; the next acquisition triggers exactly one
            # refresh request ---
            frozen_time.tick(
                delta=timedelta(
                    seconds=TOKEN_RESPONSE_1["expires_in"] - token_refresh_margin_s + 1
                )
            )
            await adapter.start()
            assert token_route.call_count == 2
            assert (
                adapter._token_manager._access_token
                == (TOKEN_RESPONSE_2["access_token"])
            )

            await adapter.stop()

    # --- And: a non-2xx token response raises AuthError, with no auto-retry
    # (adapter-interface.md: AuthError "surfaces, no auto-retry") ---
    async with respx.mock() as respx_mock_fail:
        failing_route = respx_mock_fail.post(TOKEN_URL).mock(
            return_value=Response(401, json={"error": "invalid_client"})
        )
        failing_adapter = OpenSkyAdapter(opensky_cfg, secrets, credits)
        with pytest.raises(AuthError):
            await failing_adapter.start()
        assert failing_route.call_count == 1


def _make_opensky_cfg(**overrides):
    """Minimal `OpenSkyCfg` for inner unit tests that only exercise the token
    manager, not the layer-rendering fields (author's plumbing choice --
    `OpenSkyCfg`'s required field set is spec-fixed, but the values here are
    arbitrary placeholders)."""
    from backend.sources.opensky import OpenSkyCfg

    defaults = dict(
        token_url=TOKEN_URL,
        states_url="https://opensky-network.org/api/states/all",
        token_refresh_margin_s=60,
        daily_credit_budget=4000,
        credit_warn_ratio=0.8,
        cadence_s=15,
        cadence_floor_s=5,
        custom_bbox_cap_sq_deg=100.0,
    )
    defaults.update(overrides)
    return OpenSkyCfg(**defaults)


async def test_token_manager_warm_cache_sequential_reuse():
    """Inner unit (plan item 1): a first acquisition fetches + caches a
    token; a second acquisition *sequentially after* (not racing) within the
    token's lifetime reuses the cached value with zero new token requests.
    Distinct from the outer test's cold-cache *concurrent* race: this pins
    that a warm cache short-circuits before ever touching the lock's fetch
    path, not merely that concurrent fetches collapse into one."""
    from backend.config import Secrets
    from backend.sources.opensky import _TokenManager

    secrets = Secrets(
        opensky_client_id="seq-client-id", opensky_client_secret="seq-secret"
    )
    cfg = _make_opensky_cfg()

    with freeze_time("2026-07-05T00:00:00+00:00"):
        async with respx.mock() as respx_mock:
            token_route = respx_mock.post(TOKEN_URL).mock(
                return_value=Response(200, json=TOKEN_RESPONSE_1)
            )
            async with httpx.AsyncClient() as client:
                manager = _TokenManager(cfg, secrets, client)

                first = await manager.get_token()
                assert token_route.call_count == 1
                assert first == TOKEN_RESPONSE_1["access_token"]

                # Sequential reuse, well within the ~1800 s lifetime: no new
                # request should be made.
                second = await manager.get_token()
                assert token_route.call_count == 1
                assert second == first


async def test_token_manager_connection_error_raises_autherror():
    """Inner unit (plan item 4, connection-error half): a transport-level
    failure talking to the token endpoint (not merely a non-2xx HTTP
    response, which the outer test already covers) raises AuthError with no
    auto-retry (adapter-interface.md: AuthError "surfaces, no auto-retry")."""
    from backend.config import Secrets
    from backend.sources.base import AuthError
    from backend.sources.opensky import _TokenManager

    secrets = Secrets(
        opensky_client_id="conn-client-id", opensky_client_secret="conn-secret"
    )
    cfg = _make_opensky_cfg()

    async with respx.mock() as respx_mock:
        failing_route = respx_mock.post(TOKEN_URL).mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        async with httpx.AsyncClient() as client:
            manager = _TokenManager(cfg, secrets, client)
            with pytest.raises(AuthError):
                await manager.get_token()
            assert failing_route.call_count == 1


def test_base_module_exposes_adapter_interface_contract():
    """Inner unit (plan item 5): backend.sources.base exposes SourceAdapter,
    PollAdapter, Region, and the full AdapterError taxonomy with the shapes
    the contract fixes (design/contracts/adapter-interface.md), e.g.
    RateLimitedError(retry_after=...) carries a `.retry_after` attribute."""
    from backend.sources.base import (
        AdapterError,
        AuthError,
        ParseError,
        PollAdapter,
        RateLimitedError,
        Region,
        SourceAdapter,
        UpstreamError,
    )

    # --- Region: a plain data shape with the contract-fixed fields ---
    region = Region(
        id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
    )
    assert region.id == "hormuz"
    assert region.bbox == (55.0, 25.0, 57.5, 27.5)

    # --- Error taxonomy: all four subclass AdapterError ---
    for error_cls in (RateLimitedError, AuthError, UpstreamError, ParseError):
        assert issubclass(error_cls, AdapterError)

    # --- RateLimitedError carries retry_after (contract-fixed shape) ---
    rate_limited = RateLimitedError(retry_after=30.5, message="too many requests")
    assert rate_limited.retry_after == 30.5
    assert str(rate_limited) == "too many requests"
    assert RateLimitedError().retry_after is None

    # --- PollAdapter is abstract (fetch is @abstractmethod): cannot be
    # instantiated directly, unlike the base SourceAdapter it extends ---
    assert issubclass(PollAdapter, SourceAdapter)
    with pytest.raises(TypeError):
        PollAdapter()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# opensky-adapter/02 (issue #14): fetch() parses /states/all into a
# LayerSnapshot(AIR).
# ---------------------------------------------------------------------------

# Two minimal synthetic 17-element state vectors, appended in-memory to the
# committed fixture's `states` list for this test only (the committed file on
# disk is left untouched -- other tests, e.g. test_fixtures_shape.py, keep
# asserting against the real recording). The real Hormuz capture happens to
# contain zero states with null lat/lon and zero with null time_position, so
# neither edge case the spec calls out (opensky.md "Response parsing": "Null
# lat/lon -> drop the state"; "null -> timestamp_source=None") is exercisable
# against the recording alone. design/docs/TESTING.md prefers real recorded
# fixtures and reserves synthetic data for edge cases the recording lacks --
# this is exactly that case, kept to the minimum two rows needed.
_NULL_POSITION_STATE = [
    "abc001",  # icao24
    "TESTAB  ",  # callsign
    "Testland",  # origin_country
    1783272400,  # time_position
    1783272400,  # last_contact
    None,  # longitude -- null position: this state must be DROPPED
    None,  # latitude
    1000.0,  # baro_altitude
    False,  # on_ground
    100.0,  # velocity
    90.0,  # true_track
    0.0,  # vertical_rate
    None,  # sensors
    1000.0,  # geo_altitude
    "1200",  # squawk
    False,  # spi
    1,  # position_source -> "ASTERIX"
]
_NULL_TIME_POSITION_STATE = [
    "abc002",  # icao24
    "TESTCD  ",  # callsign
    "Testland",  # origin_country
    None,  # time_position -- null: timestamp_source/position_age_s must be None, feature KEPT
    1783272410,  # last_contact
    55.35,  # longitude (inside the Hormuz bbox)
    25.30,  # latitude
    2000.0,  # baro_altitude
    False,  # on_ground
    120.0,  # velocity
    180.0,  # true_track
    0.0,  # vertical_rate
    None,  # sensors
    2000.0,  # geo_altitude
    "1201",  # squawk
    False,  # spi
    2,  # position_source -> "MLAT"
]


async def test_fetch_hormuz_states(monkeypatch):
    """Locked outer acceptance test for opensky-adapter step (issue #14).

    Given the committed fixture opensky_states_all_hormuz.json (plus two
          synthetic state vectors appended in-memory to cover the null-lat/lon
          and null-time_position cases absent from the real recording),
          httpx mocked (respx) for both the token endpoint and /states/all
    When  OpenSkyAdapter.fetch(hormuz_region) is awaited
    Then  it returns a LayerSnapshot with meta.layer == AIR and
          meta.feature_count == the number of states with non-null lat/lon
    And   a known state vector (icao24 "80160a") maps correctly: source_id,
          label (stripped callsign), lon/lat, attrs.velocity_ms/
          true_track_deg/altitude_m, and position_source int->label
    And   the null-lat/lon state is absent; the null-time_position state is
          kept with timestamp_source=None/position_age_s=None
    And   estimate_credits(hormuz_bbox) == 1 and the ledger's remaining
          decreased by exactly 1 after the fetch
    And   model_dump() of the snapshot contains no raw_payload

    Transcribed from plans/opensky-adapter/02-fetch-states.md ("Acceptance
    criterion") and design/specs/opensky.md ("Response parsing" index table +
    "position_source int->label": 0->ADS-B, 1->ASTERIX, 2->MLAT, 3->FLARM --
    the spec table is authoritative over the plan's prose ordering).

    It was authored and committed red by the author before `fetch()`
    existed (strict xfail, ): at that point `fetch()` unconditionally
    raised `NotImplementedError`, so this test failed for that reason and
    xfailed cleanly under the tests-green gate. Not satisfiable by a stub
    that merely returns an empty LayerSnapshot: the feature_count, the
    known-vector field mapping, the drop/null-timestamp handling, and the
    credit decrement are all asserted against concrete values pinned to this
    fixture. the developer has since made it genuinely pass; the xfail
    marker has been removed to finalize the contract.
    """
    # --- Given: client credentials in env (NFR5: env only) ---
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "test-opensky-client-id")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "test-opensky-client-secret")
    # Marine is enabled in the bundled config.toml (slice config-02, #42); a
    # non-empty value keeps its secret gate from firing for an unrelated
    # reason in this air-adapter-focused test.
    monkeypatch.setenv("AISSTREAM_API_KEY", "test-aisstream-api-key")
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)

    from backend.config import load_config
    from backend.models import Domain
    from backend.sources.base import Region
    from backend.sources.opensky import CreditLedger, OpenSkyAdapter, OpenSkyCfg

    cfg, secrets = load_config()
    opensky_cfg = OpenSkyCfg(**cfg.opensky, **cfg.layers["air"].model_dump())
    credits = CreditLedger(budget=opensky_cfg.daily_credit_budget)

    fixture_body = json.loads(OPENSKY_FIXTURE.read_text(encoding="utf-8"))
    real_state_count = len(fixture_body["states"])
    fixture_body = {
        **fixture_body,
        "states": [
            *fixture_body["states"],
            _NULL_POSITION_STATE,
            _NULL_TIME_POSITION_STATE,
        ],
    }
    assert all(len(vector) == 17 for vector in fixture_body["states"])

    hormuz_bbox = (55.0, 25.0, 57.5, 27.5)
    hormuz_region = Region(id="hormuz", label="Strait of Hormuz", bbox=hormuz_bbox)

    # Freeze "now" at the fixture's own top-level capture time, so the known
    # vector's position_age_s is an exact, deterministic value derived from
    # the recording itself (idx 3 time_position 1783272380, fixture "time"
    # 1783272484 -> 104.0 s), not an invented number.
    frozen_now = datetime.fromtimestamp(fixture_body["time"], tz=timezone.utc)

    with freeze_time(frozen_now):
        async with respx.mock() as respx_mock:
            respx_mock.post(TOKEN_URL).mock(
                return_value=Response(200, json=TOKEN_RESPONSE_1)
            )
            respx_mock.get(STATES_URL).mock(
                return_value=Response(200, json=fixture_body)
            )

            adapter = OpenSkyAdapter(opensky_cfg, secrets, credits)
            await adapter.start()

            remaining_before = credits.remaining

            # --- When ---
            snapshot = await adapter.fetch(hormuz_region)

            await adapter.stop()

    # --- Then: LayerSnapshot(meta.layer == AIR), feature_count == states
    # with non-null lat/lon (all 20 real states + the 1 kept synthetic state
    # with null time_position; the 1 synthetic null-position state is
    # dropped) ---
    expected_feature_count = real_state_count + 1
    assert snapshot.meta.layer == Domain.AIR
    assert snapshot.meta.region_id == "hormuz"
    assert snapshot.meta.feature_count == expected_feature_count
    assert len(snapshot.features) == expected_feature_count

    # --- And: a known state vector maps correctly (icao24 "80160a",
    # fixture row 0) ---
    known = next(f for f in snapshot.features if f.source_id == "80160a")
    assert known.label == "IGO63H"  # callsign "IGO63H  " stripped
    assert known.lon == 55.4025
    assert known.lat == 25.2317
    assert known.attrs["velocity_ms"] == 74.55
    assert known.attrs["true_track_deg"] == 301.17
    assert known.attrs["altitude_m"] == 10050.78
    assert known.attrs["position_source"] == "ADS-B"  # spec map: 0 -> "ADS-B"
    assert known.timestamp_source == datetime.fromtimestamp(1783272380, tz=timezone.utc)
    assert known.position_age_s == pytest.approx(104.0)

    # --- And: the null-lat/lon state is dropped entirely ---
    assert all(f.source_id != "abc001" for f in snapshot.features)

    # --- And: the null-time_position state is kept, with
    # timestamp_source=None/position_age_s=None ---
    null_time_feature = next(f for f in snapshot.features if f.source_id == "abc002")
    assert null_time_feature.timestamp_source is None
    assert null_time_feature.position_age_s is None
    assert null_time_feature.lon == 55.35
    assert null_time_feature.lat == 25.30
    assert null_time_feature.attrs["position_source"] == "MLAT"  # spec map: 2

    # --- And: credit accounting -- 1 credit for the Hormuz bbox (area 6.25
    # sq deg), decremented on the successful fetch ---
    assert adapter.estimate_credits(hormuz_bbox) == 1
    assert credits.remaining == remaining_before - 1

    # --- And: model_dump() of the snapshot carries no raw_payload anywhere
    # (Feature.raw_payload is in-memory only, exclude=True) ---
    dumped = snapshot.model_dump()
    for feature_dump in dumped["features"]:
        assert "raw_payload" not in feature_dump


# ---------------------------------------------------------------------------
# opensky-adapter/02 (issue #14) inner units (), authored against the
# now-built `fetch()`/`_parse_states()`/`CreditLedger` from the plan's
# ("Inner loop — initial unit test list", plans/opensky-adapter/02-fetch-
# states.md): each covers a gap the outer test above deliberately leaves
# unexercised (full field coverage, the unknown position_source code, the
# STALE/LIVE threshold, credit warn/rollover/server-truth override, and the
# full error taxonomy) rather than duplicating the outer test's happy path.
# ---------------------------------------------------------------------------


def _make_full_opensky_cfg(**overrides):
    """`OpenSkyCfg` with `deemphasize_after_s` set (unlike the token-manager
    tests' `_make_opensky_cfg`, which leaves layer-rendering fields at their
    token-only defaults) -- these parsing/fetch inner units need it to
    exercise the STALE/LIVE threshold."""
    return _make_opensky_cfg(deemphasize_after_s=60, **overrides)


def _make_state_vector(
    *,
    icao24="abc999",
    callsign="  TEST1 ",
    origin_country="France",
    time_position=None,
    last_contact=None,
    lon=10.5,
    lat=20.5,
    baro_altitude=1500.0,
    on_ground=True,
    velocity=50.0,
    true_track=180.0,
    vertical_rate=-1.5,
    sensors=None,
    geo_altitude=1600.0,
    squawk="7500",
    spi=True,
    position_source=3,
):
    """A fully-populated 17-element state vector (opensky.md index table),
    with every field distinct and non-default so a field-mapping bug
    (transposed indices, wrong attrs key, etc.) cannot hide behind a
    coincidental match."""
    return [
        icao24,
        callsign,
        origin_country,
        time_position,
        last_contact,
        lon,
        lat,
        baro_altitude,
        on_ground,
        velocity,
        true_track,
        vertical_rate,
        sensors,
        geo_altitude,
        squawk,
        spi,
        position_source,
    ]


def _make_bare_adapter(cfg):
    """An `OpenSkyAdapter` for inner units that only exercise the pure
    `_parse_states` parsing path (no I/O, no token) -- credentials are
    placeholders never actually used against a live endpoint."""
    from backend.config import Secrets
    from backend.sources.opensky import CreditLedger, OpenSkyAdapter

    secrets = Secrets(
        opensky_client_id="parse-only-id", opensky_client_secret="parse-only-secret"
    )
    credits = CreditLedger(budget=cfg.daily_credit_budget)
    return OpenSkyAdapter(cfg, secrets, credits)


def test_parse_states_full_index_map_and_raw_payload_wrapping():
    """Inner unit (plan item 1): every one of the 17 indices maps to the
    documented field (opensky.md "Response parsing" table), including fields
    the outer test's known-vector assertion doesn't touch (origin_country,
    on_ground, vertical_rate_ms, geo_altitude_m, squawk), plus
    geometry_type/geometry and the raw_payload wrapping (idx 12 `sensors`
    and idx 15 `spi` are documented "ignored" and must NOT leak into attrs)."""
    from backend.models import Domain, FeatureStatus, GeometryType

    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    time_position_epoch = int((now - timedelta(seconds=10)).timestamp())
    vector = _make_state_vector(time_position=time_position_epoch, last_contact=999)

    cfg = _make_full_opensky_cfg()
    adapter = _make_bare_adapter(cfg)

    features, newest_ts = adapter._parse_states({"states": [vector]}, now)

    assert len(features) == 1
    feature = features[0]
    assert feature.domain == Domain.AIR
    assert feature.source == "opensky"
    assert feature.source_id == "abc999"
    assert feature.label == "TEST1"  # callsign "  TEST1 " stripped
    assert feature.lon == 10.5
    assert feature.lat == 20.5
    assert feature.geometry_type == GeometryType.POINT
    assert feature.geometry is None
    assert feature.timestamp_source == now - timedelta(seconds=10)
    assert feature.position_age_s == pytest.approx(10.0)
    assert feature.status == FeatureStatus.LIVE  # 10s < deemphasize_after_s (60s)
    assert feature.attrs["origin_country"] == "France"
    assert feature.attrs["altitude_m"] == 1500.0
    assert feature.attrs["on_ground"] is True
    assert feature.attrs["velocity_ms"] == 50.0
    assert feature.attrs["true_track_deg"] == 180.0
    assert feature.attrs["vertical_rate_ms"] == -1.5
    assert feature.attrs["geo_altitude_m"] == 1600.0
    assert feature.attrs["squawk"] == "7500"
    assert feature.attrs["position_source"] == "FLARM"  # spec map: 3
    # idx 12 (sensors) and idx 15 (spi) are documented "ignored": neither
    # value (None / True) leaks into attrs under any key.
    assert "sensors" not in feature.attrs
    assert "spi" not in feature.attrs
    assert feature.raw_payload == {"state_vector": vector}
    assert newest_ts == now - timedelta(seconds=10)


def test_parse_states_blank_and_none_callsign_yield_none_label():
    """Inner unit: a blank (whitespace-only) or wholly absent callsign both
    yield `label=None` (opensky.md: "strip; None if blank"), not an empty
    string."""
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    cfg = _make_full_opensky_cfg()
    adapter = _make_bare_adapter(cfg)

    blank_vector = _make_state_vector(icao24="blank01", callsign="        ")
    none_vector = _make_state_vector(icao24="none01", callsign=None)

    features, _ = adapter._parse_states({"states": [blank_vector, none_vector]}, now)

    by_id = {f.source_id: f for f in features}
    assert by_id["blank01"].label is None
    assert by_id["none01"].label is None


def test_parse_states_unknown_position_source_code_stringified():
    """Inner unit (plan item 2): an undocumented `position_source` code
    (opensky.md only documents 0-3) falls back to `str(int(code))`, not a
    KeyError or a swallowed None."""
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    cfg = _make_full_opensky_cfg()
    adapter = _make_bare_adapter(cfg)

    vector = _make_state_vector(position_source=7)
    features, _ = adapter._parse_states({"states": [vector]}, now)

    assert features[0].attrs["position_source"] == "7"


@pytest.mark.parametrize(
    ("age_s", "expected_status"),
    [
        (59.0, "live"),
        (60.0, "live"),
        (61.0, "stale"),
    ],
)
def test_parse_states_stale_status_threshold(age_s, expected_status):
    """Inner unit (plan item 4): `FeatureStatus.STALE` is stamped only when
    `position_age_s > deemphasize_after_s` (60s, config); at or below the
    threshold the feature stays LIVE. Pinning both sides of the boundary,
    plus the exact threshold value itself (60.0s == deemphasize_after_s),
    catches an off-by-one (>= vs >): the spec's rule is strict `>`, so
    age == threshold must NOT be stale."""
    from backend.models import FeatureStatus

    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    cfg = _make_full_opensky_cfg()  # deemphasize_after_s=60
    adapter = _make_bare_adapter(cfg)

    time_position_epoch = int((now - timedelta(seconds=age_s)).timestamp())
    vector = _make_state_vector(time_position=time_position_epoch)
    features, _ = adapter._parse_states({"states": [vector]}, now)

    assert features[0].status == FeatureStatus(expected_status)


@pytest.mark.parametrize("order", ["ascending", "chronological_mixed", "descending"])
def test_parse_states_newest_timestamp_source_across_multiple_vectors(order):
    """Inner unit: `_parse_states`'s second return value (`newest_source_ts`,
    the snapshot's `meta.timestamp_source`) is the MAXIMUM of every feature's
    non-null `time_position` across the WHOLE batch, not merely the first
    vector seen. The existing outer/inner tests only ever pass a single
    vector, so a 'keep first' (or 'keep last-seen unconditionally') bug in
    place of an actual max-reduction would slip through uncaught. Parametrized
    over three input orderings of the same three timestamps (already
    ascending, out-of-order, and fully descending) to pin that the result is
    order-independent -- a real max, not an accidental artifact of iteration
    order."""
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    cfg = _make_full_opensky_cfg()
    adapter = _make_bare_adapter(cfg)

    # Three distinct, non-null time_position epochs; the middle one (oldest,
    # newest, middle) is deliberately not sorted in source order.
    oldest_epoch = int((now - timedelta(seconds=300)).timestamp())
    middle_epoch = int((now - timedelta(seconds=150)).timestamp())
    newest_epoch = int((now - timedelta(seconds=5)).timestamp())
    newest_ts = datetime.fromtimestamp(newest_epoch, tz=timezone.utc)

    vector_oldest = _make_state_vector(icao24="old0001", time_position=oldest_epoch)
    vector_middle = _make_state_vector(icao24="mid0002", time_position=middle_epoch)
    vector_newest = _make_state_vector(icao24="new0003", time_position=newest_epoch)

    orderings = {
        "ascending": [vector_oldest, vector_middle, vector_newest],
        "chronological_mixed": [vector_middle, vector_newest, vector_oldest],
        "descending": [vector_newest, vector_middle, vector_oldest],
    }
    vectors = orderings[order]

    features, batch_newest_ts = adapter._parse_states({"states": vectors}, now)

    assert len(features) == 3
    assert batch_newest_ts == newest_ts


def test_credit_ledger_spend_decrements_and_warn_ratio():
    """Inner unit (plan item 5): a successful spend decrements `remaining`;
    `warn` flips true once `spent/budget` exceeds `warn_ratio` (0.5 default,
    opensky.md "Credit accounting"), and stays false at/just-under it."""
    from backend.sources.opensky import CreditLedger

    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    ledger = CreditLedger(budget=100)  # warn_ratio default 0.5

    ledger.spend(10, now=now)
    assert ledger.remaining == 90
    assert ledger.spent == 10
    assert ledger.warn is False

    ledger.spend(40, now=now)  # spent=50, 50/100 == 0.5, not > 0.5
    assert ledger.spent == 50
    assert ledger.warn is False

    ledger.spend(1, now=now)  # spent=51, 51/100 > 0.5
    assert ledger.spent == 51
    assert ledger.warn is True


def test_credit_ledger_rolls_over_at_utc_midnight():
    """Inner unit (plan item 5, rollover half): spend on day 1 persists
    until a `spend`/`override_remaining` call observes UTC midnight has
    passed, at which point `remaining` resets to the full `budget` before
    the new amount is applied (opensky.md: "roll over at UTC midnight")."""
    from backend.sources.opensky import CreditLedger

    day_one = datetime(2026, 7, 5, 23, 0, 0, tzinfo=timezone.utc)
    day_two = datetime(2026, 7, 6, 1, 0, 0, tzinfo=timezone.utc)
    ledger = CreditLedger(budget=100)

    ledger.spend(30, now=day_one)
    assert ledger.remaining == 70

    ledger.spend(10, now=day_two)
    assert ledger.remaining == 90  # rolled over to 100, then -10


def test_credit_ledger_override_remaining_is_server_truth():
    """Inner unit (plan item 5, server-truth half): `override_remaining`
    (an upstream `X-Rate-Limit-Remaining` header) supersedes the local
    estimate outright, regardless of prior spend."""
    from backend.sources.opensky import CreditLedger

    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    ledger = CreditLedger(budget=100)
    ledger.spend(10, now=now)
    assert ledger.remaining == 90

    ledger.override_remaining(3987, now=now)
    assert ledger.remaining == 3987


async def test_fetch_429_with_retry_after_header():
    """Inner unit (plan item 6): a 429 with a `Retry-After` header raises
    `RateLimitedError` carrying it as a float (opensky.md failure table)."""
    from backend.config import Secrets
    from backend.sources.base import RateLimitedError, Region
    from backend.sources.opensky import CreditLedger, OpenSkyAdapter

    cfg = _make_full_opensky_cfg()
    secrets = Secrets(opensky_client_id="x", opensky_client_secret="y")
    credits = CreditLedger(budget=cfg.daily_credit_budget)
    region = Region(
        id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
    )

    async with respx.mock() as respx_mock:
        respx_mock.post(TOKEN_URL).mock(
            return_value=Response(200, json=TOKEN_RESPONSE_1)
        )
        respx_mock.get(STATES_URL).mock(
            return_value=Response(429, headers={"Retry-After": "12.5"})
        )
        adapter = OpenSkyAdapter(cfg, secrets, credits)
        with pytest.raises(RateLimitedError) as exc_info:
            await adapter.fetch(region)
        assert exc_info.value.retry_after == 12.5


async def test_fetch_429_without_retry_after_header_leaves_retry_after_none():
    """Inner unit (plan item 6): absent `Retry-After`, `retry_after=None`
    (scheduler falls back to config backoff, opensky.md failure table)."""
    from backend.config import Secrets
    from backend.sources.base import RateLimitedError, Region
    from backend.sources.opensky import CreditLedger, OpenSkyAdapter

    cfg = _make_full_opensky_cfg()
    secrets = Secrets(opensky_client_id="x", opensky_client_secret="y")
    credits = CreditLedger(budget=cfg.daily_credit_budget)
    region = Region(
        id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
    )

    async with respx.mock() as respx_mock:
        respx_mock.post(TOKEN_URL).mock(
            return_value=Response(200, json=TOKEN_RESPONSE_1)
        )
        respx_mock.get(STATES_URL).mock(return_value=Response(429))
        adapter = OpenSkyAdapter(cfg, secrets, credits)
        with pytest.raises(RateLimitedError) as exc_info:
            await adapter.fetch(region)
        assert exc_info.value.retry_after is None


async def test_fetch_429_with_malformed_retry_after_header_yields_typed_error():
    """Regression (review must-fix, commit 005e11c): a 429 whose `Retry-After`
    header is present but not a bare-float form (RFC 7231 also allows an
    HTTP-date, which `float()` cannot parse) must still raise the typed
    `RateLimitedError` with `retry_after=None` -- not let a bare `ValueError`
    from the failed `float()` parse escape uncaught. Distinct from the
    existing 'with header' (numeric) and 'without header' (absent) cases:
    this is the third, malformed case a naive `float(header)` with no
    try/except would blow up on."""
    from backend.config import Secrets
    from backend.sources.base import RateLimitedError, Region
    from backend.sources.opensky import CreditLedger, OpenSkyAdapter

    cfg = _make_full_opensky_cfg()
    secrets = Secrets(opensky_client_id="x", opensky_client_secret="y")
    credits = CreditLedger(budget=cfg.daily_credit_budget)
    region = Region(
        id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
    )

    async with respx.mock() as respx_mock:
        respx_mock.post(TOKEN_URL).mock(
            return_value=Response(200, json=TOKEN_RESPONSE_1)
        )
        respx_mock.get(STATES_URL).mock(
            return_value=Response(
                429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}
            )
        )
        adapter = OpenSkyAdapter(cfg, secrets, credits)
        with pytest.raises(RateLimitedError) as exc_info:
            await adapter.fetch(region)
        assert exc_info.value.retry_after is None


@pytest.mark.parametrize("status", [500, 503])
async def test_fetch_5xx_raises_upstream_error(status):
    """Inner unit (plan item 6): any 5xx raises `UpstreamError`."""
    from backend.config import Secrets
    from backend.sources.base import Region, UpstreamError
    from backend.sources.opensky import CreditLedger, OpenSkyAdapter

    cfg = _make_full_opensky_cfg()
    secrets = Secrets(opensky_client_id="x", opensky_client_secret="y")
    credits = CreditLedger(budget=cfg.daily_credit_budget)
    region = Region(
        id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
    )

    async with respx.mock() as respx_mock:
        respx_mock.post(TOKEN_URL).mock(
            return_value=Response(200, json=TOKEN_RESPONSE_1)
        )
        respx_mock.get(STATES_URL).mock(return_value=Response(status))
        adapter = OpenSkyAdapter(cfg, secrets, credits)
        with pytest.raises(UpstreamError):
            await adapter.fetch(region)


async def test_fetch_timeout_raises_upstream_error():
    """Inner unit (plan item 6): a request timeout raises `UpstreamError`,
    not left as a raw `httpx.TimeoutException`."""
    from backend.config import Secrets
    from backend.sources.base import Region, UpstreamError
    from backend.sources.opensky import CreditLedger, OpenSkyAdapter

    cfg = _make_full_opensky_cfg()
    secrets = Secrets(opensky_client_id="x", opensky_client_secret="y")
    credits = CreditLedger(budget=cfg.daily_credit_budget)
    region = Region(
        id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
    )

    async with respx.mock() as respx_mock:
        respx_mock.post(TOKEN_URL).mock(
            return_value=Response(200, json=TOKEN_RESPONSE_1)
        )
        respx_mock.get(STATES_URL).mock(side_effect=httpx.TimeoutException("timed out"))
        adapter = OpenSkyAdapter(cfg, secrets, credits)
        with pytest.raises(UpstreamError):
            await adapter.fetch(region)


async def test_fetch_transport_error_raises_upstream_error():
    """Inner unit (plan item 6): a connection-level transport failure (not
    merely a timeout) also raises `UpstreamError`."""
    from backend.config import Secrets
    from backend.sources.base import Region, UpstreamError
    from backend.sources.opensky import CreditLedger, OpenSkyAdapter

    cfg = _make_full_opensky_cfg()
    secrets = Secrets(opensky_client_id="x", opensky_client_secret="y")
    credits = CreditLedger(budget=cfg.daily_credit_budget)
    region = Region(
        id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
    )

    async with respx.mock() as respx_mock:
        respx_mock.post(TOKEN_URL).mock(
            return_value=Response(200, json=TOKEN_RESPONSE_1)
        )
        respx_mock.get(STATES_URL).mock(side_effect=httpx.ConnectError("refused"))
        adapter = OpenSkyAdapter(cfg, secrets, credits)
        with pytest.raises(UpstreamError):
            await adapter.fetch(region)


async def test_fetch_malformed_json_raises_parse_error():
    """Inner unit (plan item 6): a 2xx response whose body isn't valid JSON
    raises `ParseError` (opensky.md failure table: "2xx but JSON/schema
    invalid")."""
    from backend.config import Secrets
    from backend.sources.base import ParseError, Region
    from backend.sources.opensky import CreditLedger, OpenSkyAdapter

    cfg = _make_full_opensky_cfg()
    secrets = Secrets(opensky_client_id="x", opensky_client_secret="y")
    credits = CreditLedger(budget=cfg.daily_credit_budget)
    region = Region(
        id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
    )

    async with respx.mock() as respx_mock:
        respx_mock.post(TOKEN_URL).mock(
            return_value=Response(200, json=TOKEN_RESPONSE_1)
        )
        respx_mock.get(STATES_URL).mock(
            return_value=Response(200, text="not valid json{")
        )
        adapter = OpenSkyAdapter(cfg, secrets, credits)
        with pytest.raises(ParseError):
            await adapter.fetch(region)


async def test_fetch_missing_states_key_raises_parse_error():
    """Inner unit (plan item 6): valid JSON that lacks the documented
    `states` array is a schema-invalid 2xx body -> `ParseError`, not a
    silent empty snapshot or a raw KeyError."""
    from backend.config import Secrets
    from backend.sources.base import ParseError, Region
    from backend.sources.opensky import CreditLedger, OpenSkyAdapter

    cfg = _make_full_opensky_cfg()
    secrets = Secrets(opensky_client_id="x", opensky_client_secret="y")
    credits = CreditLedger(budget=cfg.daily_credit_budget)
    region = Region(
        id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
    )

    async with respx.mock() as respx_mock:
        respx_mock.post(TOKEN_URL).mock(
            return_value=Response(200, json=TOKEN_RESPONSE_1)
        )
        respx_mock.get(STATES_URL).mock(return_value=Response(200, json={"nope": True}))
        adapter = OpenSkyAdapter(cfg, secrets, credits)
        with pytest.raises(ParseError):
            await adapter.fetch(region)


@pytest.mark.parametrize("status", [401, 403])
async def test_fetch_401_403_raises_autherror_and_invalidates_token(status):
    """Inner unit (plan item 6, auth half): a 401/403 on `/states/all`
    (token rejected) raises `AuthError` and invalidates the cached token so
    the next attempt re-fetches (opensky.md failure table)."""
    from backend.config import Secrets
    from backend.sources.base import AuthError, Region
    from backend.sources.opensky import CreditLedger, OpenSkyAdapter

    cfg = _make_full_opensky_cfg()
    secrets = Secrets(opensky_client_id="x", opensky_client_secret="y")
    credits = CreditLedger(budget=cfg.daily_credit_budget)
    region = Region(
        id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
    )

    async with respx.mock() as respx_mock:
        respx_mock.post(TOKEN_URL).mock(
            return_value=Response(200, json=TOKEN_RESPONSE_1)
        )
        respx_mock.get(STATES_URL).mock(return_value=Response(status))
        adapter = OpenSkyAdapter(cfg, secrets, credits)
        with pytest.raises(AuthError):
            await adapter.fetch(region)
        assert adapter._token_manager._access_token is None


async def test_fetch_rate_limit_remaining_header_overrides_ledger_estimate():
    """Inner unit (plan item 5, out-of-scope note lifted in): when the
    states response carries `X-Rate-Limit-Remaining`, it is authoritative
    over the local decrement (opensky.md: "server truth > estimate"),
    overwriting whatever the estimate-based `spend()` computed."""
    from backend.config import Secrets
    from backend.sources.base import Region
    from backend.sources.opensky import CreditLedger, OpenSkyAdapter

    cfg = _make_full_opensky_cfg()
    secrets = Secrets(opensky_client_id="x", opensky_client_secret="y")
    credits = CreditLedger(budget=cfg.daily_credit_budget)
    region = Region(
        id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
    )

    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    with freeze_time(now):
        async with respx.mock() as respx_mock:
            respx_mock.post(TOKEN_URL).mock(
                return_value=Response(200, json=TOKEN_RESPONSE_1)
            )
            respx_mock.get(STATES_URL).mock(
                return_value=Response(
                    200,
                    json={"time": int(now.timestamp()), "states": []},
                    headers={"X-Rate-Limit-Remaining": "3123"},
                )
            )
            adapter = OpenSkyAdapter(cfg, secrets, credits)
            await adapter.fetch(region)

    # Not `budget - estimate` (would be 3999): server truth wins outright.
    assert credits.remaining == 3123


async def test_fetch_credentials_never_appear_in_raw_payload_or_model_dump():
    """Inner unit (plan item 7, NFR5): the client secret used to obtain the
    bearer token never surfaces anywhere in a fetched snapshot's
    `raw_payload` or its `model_dump()` wire body."""
    import json as json_module

    from backend.config import Secrets
    from backend.sources.base import Region
    from backend.sources.opensky import CreditLedger, OpenSkyAdapter

    secret_marker = "unmistakable-super-secret-marker-4f8c"
    cfg = _make_full_opensky_cfg()
    secrets = Secrets(
        opensky_client_id="nfr5-client-id", opensky_client_secret=secret_marker
    )
    credits = CreditLedger(budget=cfg.daily_credit_budget)
    region = Region(
        id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)
    )

    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    vector = _make_state_vector(time_position=int(now.timestamp()))
    with freeze_time(now):
        async with respx.mock() as respx_mock:
            respx_mock.post(TOKEN_URL).mock(
                return_value=Response(200, json=TOKEN_RESPONSE_1)
            )
            respx_mock.get(STATES_URL).mock(
                return_value=Response(
                    200, json={"time": int(now.timestamp()), "states": [vector]}
                )
            )
            adapter = OpenSkyAdapter(cfg, secrets, credits)
            snapshot = await adapter.fetch(region)

    dumped_json = json_module.dumps(snapshot.model_dump(mode="json"))
    assert secret_marker not in dumped_json
    for feature in snapshot.features:
        assert secret_marker not in json_module.dumps(feature.raw_payload)
