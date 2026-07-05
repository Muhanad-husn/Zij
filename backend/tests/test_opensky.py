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
    monkeypatch.delenv("AISSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("AISHUB_USERNAME", raising=False)
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
            assert adapter._token_manager._access_token == (
                TOKEN_RESPONSE_1["access_token"]
            )

            # --- And: advance the clock to within token_refresh_margin_s of
            # the ~1800 s expiry; the next acquisition triggers exactly one
            # refresh request ---
            frozen_time.tick(
                delta=timedelta(
                    seconds=TOKEN_RESPONSE_1["expires_in"]
                    - token_refresh_margin_s
                    + 1
                )
            )
            await adapter.start()
            assert token_route.call_count == 2
            assert adapter._token_manager._access_token == (
                TOKEN_RESPONSE_2["access_token"]
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


@pytest.mark.xfail(
    reason="fetch() not yet implemented (opensky-adapter/02)", strict=True
)
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

    Authored and committed red by the author before fetch() existed
    (strict xfail, ): today fetch() unconditionally raises
    NotImplementedError, so this test fails for that reason and xfails
    cleanly under the tests-green gate. Not satisfiable by a stub that merely
    returns an empty LayerSnapshot: the feature_count, the known-vector field
    mapping, the drop/null-timestamp handling, and the credit decrement are
    all asserted against concrete values pinned to this fixture.
    """
    # --- Given: client credentials in env (NFR5: env only) ---
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "test-opensky-client-id")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "test-opensky-client-secret")
    monkeypatch.delenv("AISSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("AISHUB_USERNAME", raising=False)
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
    assert known.timestamp_source == datetime.fromtimestamp(
        1783272380, tz=timezone.utc
    )
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
