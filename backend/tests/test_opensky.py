"""Locked outer acceptance test for opensky-adapter slice 01 (issue #13): OAuth2
token manager.

Given an OpenSkyAdapter started with client credentials, the token endpoint
      mocked to return a token valid ~1800 s
When  three fetch-driven token acquisitions are awaited concurrently
Then  exactly one HTTP request is made to the token endpoint and all three
      see the same cached token
And   after advancing the clock to within token_refresh_margin_s of expiry,
      the next acquisition triggers exactly one refresh request
And   a non-2xx token response raises AuthError (no auto-retry)

This is the behavioral contract (DEC-1), transcribed from
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

Names this test requires the implementer to provide (spec/plan-fixed unless
noted "test-author's plumbing choice"):
  - backend.sources.base.AuthError (design/contracts/adapter-interface.md).
  - backend.sources.opensky.OpenSkyAdapter(cfg, secrets, credits) with async
    start()/stop() (design/specs/opensky.md "Public interface").
  - OpenSkyAdapter._token_manager: an instance of the spec-named
    `_TokenManager` (opensky.md "Internal design"), exposing
    `_access_token: str | None` (spec-fixed name) -- the attribute NAME
    `_token_manager` on the adapter is this test-author's plumbing choice
    (not spec-fixed), needed only to observe the cached value from outside.
  - backend.sources.opensky.OpenSkyCfg, constructible from the merged
    `[opensky]` + `[layers.air]` config tables per opensky.md ("`OpenSkyCfg`
    = the `[opensky]` table + `[layers.air]`"); this test merges
    `cfg.opensky` and `cfg.layers["air"].model_dump()` as kwargs, so
    `OpenSkyCfg` must accept that combined key set (and expose
    `daily_credit_budget`/`token_refresh_margin_s`, already in `[opensky]`).
  - backend.sources.opensky.CreditLedger(budget=...) -- a trivially
    constructible ledger; no credit-spend behavior is exercised in this
    slice (deferred to slice 02 per the plan's "Out of scope").

It was authored and committed red by the test-author before any
implementation existed (strict xfail, DEC-33). The implementer has since made
it genuinely pass; the xfail marker has been removed to finalize the
contract.

Below the outer test are inner unit tests (DEC-34) covering gaps the outer
test deliberately does not exercise: warm-cache *sequential* reuse (the outer
test only proves the cold-cache *concurrent* race is single-flight), a
connection-level failure on the token endpoint (the outer test only proves a
non-2xx HTTP response raises `AuthError`), and `backend/sources/base.py`'s
structural exposure of the adapter interface contract.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import httpx
import pytest
import respx
from freezegun import freeze_time
from httpx import Response

TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)

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
    manager, not the layer-rendering fields (test-author's plumbing choice --
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
