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
implementation existed (strict xfail, ): `backend/sources/base.py` and
`backend/sources/opensky.py` do not exist yet, so the `backend.sources.*`
imports below (placed inside the test body per test_config_acceptance.py
convention) raise `ImportError`, which strict-xfail records as `xfailed`
rather than a collection error.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

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


@pytest.mark.xfail(reason="opensky token manager not yet implemented", strict=True)
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
