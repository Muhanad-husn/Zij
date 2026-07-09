"""Locked outer acceptance test for backend-api step (issue #17): the
FastAPI app serving health, config, and the static frontend.

Given the FastAPI app built with loaded config and secrets
When  GET /api/health is requested
Then  it returns 200 with status "ok", a version string, and a numeric
      uptime_s
And   GET /api/config returns 200 with the 7 regions and the air/land layer
      settings
And   the /api/config body contains neither OPENSKY_CLIENT_ID nor
      OPENSKY_CLIENT_SECRET (NFR5) -- checked by asserting the literal secret
      VALUES never appear anywhere in the serialized response body, with the
      app wired to real, known secret values so the assertion is meaningful
And   a request to an unknown /api/ path returns the api.md error envelope
      ({"error":{"code":"not_found",...}}) with a matching 404 status
And   / serves the static frontend's index.html (200, HTML body), proving
      /api/* is matched before the static fallback (assertions 1-4 above all
      hit real /api/* routes and are not swallowed by the static mount)

This is the behavioral contract (), transcribed from
plans/backend-api/01-app-health-config.md and design/contracts/api.md ("GET
/api/health", "GET /api/config", "Error envelope") and
design/contracts/config.md / backend/config.py (`load_config()` ->
`(AppConfig, Secrets)`, `Secrets` never folded into `AppConfig`).

Design seam this test locks in for the developer (backend/main.py):

    def create_app(*, static_dir: Path | str, config: AppConfig,
                    secrets: Secrets) -> FastAPI: ...

`create_app` is an explicit factory so this test never depends on a real
frontend build -- it points `static_dir` at a `tmp_path` directory containing
a minimal `index.html` it writes itself, and injects a config/secrets pair it
controls (secrets carrying known, literal values via monkeypatched env before
`load_config()`, per config.py's env/.env-only secrets loading). The contract
additionally requires a module-level `backend.main:app` (the uvicorn
entrypoint referenced by api.md) but this test drives its assertions through
the factory instance, not the module-level singleton, so it stays hermetic
even though a real frontend build does not exist yet.

It was authored and committed red by the author before any
implementation existed, guarded by a strict xfail (): `backend.main`
had no `create_app`/`app`, so the import raised `ImportError` and the test
xfailed rather than errored. the developer has since built `backend/main.py`
to satisfy this exact seam -- the test now genuinely passes and the marker is
removed below to finalize the contract. This assertion itself is never
weakened.
"""

import json
from pathlib import Path

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_OPENSKY_FIXTURE = _FIXTURES_DIR / "opensky_states_all_hormuz.json"
_OVERPASS_FIXTURE = _FIXTURES_DIR / "overpass_hormuz.json"

# A valid-looking OAuth token response so the injected OpenSkyAdapter's token
# manager succeeds before it reaches the (respx-mocked) /states/all call.
_TOKEN_RESPONSE = {
    "access_token": "outer-test-opensky-access-token-18",
    "expires_in": 1800,
    "token_type": "bearer",
}


def test_health_and_config(tmp_path, monkeypatch):
    # --- Given: a real, known pair of OpenSky secret values wired through
    # env (config.py's Secrets is env/.env-only, NFR5) so the "never leaks"
    # assertion below is meaningful rather than vacuous ---
    client_id = "outer-test-opensky-client-id-4f2a"
    client_secret = "outer-test-opensky-client-secret-9b7d"
    monkeypatch.setenv("OPENSKY_CLIENT_ID", client_id)
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", client_secret)
    # Marine is enabled in the bundled config.toml (slice config-02, #42), so
    # its own secret gate needs a non-empty value too, or load_config() below
    # raises MissingSecretError for an unrelated reason.
    monkeypatch.setenv("AISSTREAM_API_KEY", "outer-test-aisstream-api-key-4f2a")
    monkeypatch.delenv("AISHUB_USERNAME", raising=False)
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)

    from backend.config import load_config
    from backend.main import create_app

    cfg, secrets = load_config()
    assert secrets.opensky_client_id == client_id
    assert secrets.opensky_client_secret == client_secret

    # --- Given: a hermetic static dir standing in for the not-yet-built
    # frontend, containing a minimal index.html ---
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    index_html = "<!doctype html><html><body>Zij</body></html>"
    (static_dir / "index.html").write_text(index_html, encoding="utf-8")

    app = create_app(static_dir=static_dir, config=cfg, secrets=secrets)
    client = TestClient(app)

    # --- When: GET /api/health ---
    health_resp = client.get("/api/health")

    # --- Then: 200 with status "ok", a version string, a numeric uptime_s ---
    assert health_resp.status_code == 200
    health_body = health_resp.json()
    assert health_body["status"] == "ok"
    assert isinstance(health_body["version"], str)
    assert health_body["version"]
    assert isinstance(health_body["uptime_s"], (int, float))
    assert not isinstance(health_body["uptime_s"], bool)
    assert health_body["uptime_s"] >= 0

    # uptime_s must actually track elapsed process time, not a constant --
    # a second call strictly after the first must not report a smaller value.
    later_resp = client.get("/api/health")
    assert later_resp.json()["uptime_s"] >= health_body["uptime_s"]

    # --- And: GET /api/config returns 200 with the 7 regions and the
    # air/land layer settings ---
    config_resp = client.get("/api/config")
    assert config_resp.status_code == 200
    config_body = config_resp.json()

    assert "regions" in config_body
    assert len(config_body["regions"]) == 7
    region_ids = {region["id"] for region in config_body["regions"]}
    assert region_ids == {
        "hormuz",
        "persian-gulf",
        "gulf-of-oman",
        "iraq-corridor",
        "syria-corridor",
        "eastern-med",
        "suez-canal",
    }

    assert "layers" in config_body
    assert "air" in config_body["layers"]
    assert "land" in config_body["layers"]

    air_layer = config_body["layers"]["air"]
    assert air_layer["enabled"] is True
    assert air_layer["cadence_s"] == 600
    assert air_layer["cadence_floor_s"] == 60
    assert air_layer["custom_bbox_cap_sq_deg"] == 100

    land_layer = config_body["layers"]["land"]
    assert land_layer["enabled"] is True
    assert land_layer["cadence_s"] == 86400
    assert land_layer["cadence_floor_s"] == 3600
    assert land_layer["custom_bbox_cap_sq_deg"] == 40
    assert land_layer["simplify_tolerance_deg"] == 0.0005
    assert land_layer["max_rendered_features"] == 5000

    # --- And: the /api/config body does NOT include active_region_id
    # (regression lock, config step / #46): AppConfig.active_region_id is
    # an internal resolved value (config-module.md "active_region_id") that
    # api.md's "GET /api/config" shape pins without it -- the active region
    # is meant to surface via a separate future endpoint, not folded into
    # this one. A review-driven fix (5a9907e) added `Field(exclude=True)` to
    # keep it out of serialization; this assertion is the regression test
    # that locks that fix so the drift can't silently return. Also confirm
    # the attribute is still readable internally, so the field wasn't
    # simply removed rather than excluded from serialization only.
    assert cfg.active_region_id
    assert "active_region_id" not in config_body

    # --- And: the /api/config body contains neither OPENSKY_CLIENT_ID nor
    # OPENSKY_CLIENT_SECRET -- checked as the literal secret VALUES never
    # appearing anywhere in the raw serialized response body (NFR5) ---
    config_raw_text = config_resp.text
    assert client_id not in config_raw_text
    assert client_secret not in config_raw_text
    # Also guard the field names themselves, structurally, so a future
    # refactor that folds Secrets into the response under a renamed key still
    # trips this assertion.
    assert "opensky_client_id" not in config_raw_text
    assert "opensky_client_secret" not in config_raw_text

    # --- And: a request to an unknown /api/ path returns the api.md error
    # envelope with a matching HTTP status ---
    missing_resp = client.get("/api/does-not-exist")
    assert missing_resp.status_code == 404
    missing_body = missing_resp.json()
    assert "error" in missing_body
    assert missing_body["error"]["code"] == "not_found"
    assert "message" in missing_body["error"]

    # --- And: / serves the static frontend's index.html, proving /api/* is
    # matched before the static fallback (the /api/* routes above all hit
    # real handlers rather than falling through to the static mount) ---
    root_resp = client.get("/")
    assert root_resp.status_code == 200
    assert "text/html" in root_resp.headers["content-type"]
    assert "Zij" in root_resp.text


# --- Inner unit tests () --------------------------------------------
#
# These target internal collaborators of backend/main.py that the outer test
# above does not isolate: the full status->code envelope mapping (api.md
# defines eight codes; the outer test only exercises 404), the routing
# scope of the /api/* catch-all against the static mount's own 404 handling,
# and the defensive module-level `app` construction used by the real uvicorn
# entrypoint.


def test_status_to_code_mapping_matches_error_envelope_contract():
    """api.md ("Error envelope") pins eight codes to eight HTTP statuses.
    The outer test only ever exercises the 404/not_found pair (via the
    /api/* catch-all); this locks in the full reverse-lookup table the
    exception handler uses for any HTTPException raised elsewhere in the
    app without an explicit envelope body, so a future route that raises
    e.g. `HTTPException(422)` or `HTTPException(429)` gets the *correct*
    `code`, not just a plausible one.
    """
    from backend.main import _STATUS_TO_CODE

    assert _STATUS_TO_CODE == {
        400: "bad_request",
        401: "auth_error",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        429: "rate_limited",
        500: "internal",
        502: "upstream_error",
    }


def test_error_envelope_helper_builds_api_md_shape():
    """`_error_envelope` is the single place the `{"error": {...}}` body is
    assembled; pin its shape directly (code/message plus arbitrary extras
    such as `retry_after_s`) rather than relying only on the one HTTPException
    path the outer test drives.
    """
    from backend.main import _error_envelope

    body = _error_envelope("rate_limited", "too many requests", retry_after_s=42)
    assert body == {
        "error": {
            "code": "rate_limited",
            "message": "too many requests",
            "retry_after_s": 42,
        }
    }


def test_unmatched_non_api_path_does_not_get_the_api_error_envelope(tmp_path):
    """Precedence pin, the other direction from the outer test's `/` check:
    an unmatched path *outside* `/api/*` must fall through to the static
    mount's own 404 handling, not be swallowed by the `/api/{rest:path}`
    catch-all or by the global HTTPException handler producing the api.md
    envelope. If routing were ever misconfigured so the catch-all (or the
    exception handler) applied globally, this would start returning the
    `{"error": {"code": "not_found", ...}}` envelope for a plain static 404
    too, and this test would catch that regression.
    """
    from backend.config import load_config
    from backend.main import create_app

    cfg, secrets = load_config()

    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        "<!doctype html><html><body>Zij</body></html>", encoding="utf-8"
    )

    app = create_app(static_dir=static_dir, config=cfg, secrets=secrets)
    client = TestClient(app)

    api_missing = client.get("/api/does-not-exist")
    assert api_missing.status_code == 404
    assert api_missing.json()["error"]["code"] == "not_found"

    static_missing = client.get("/this-page-does-not-exist")
    assert static_missing.status_code == 404
    # Distinctly NOT our envelope: no "error" key at all.
    assert "error" not in static_missing.json()


def test_module_level_app_imports_and_builds_without_a_frontend_build(monkeypatch):
    """The module-level `backend.main:app` (the real uvicorn entrypoint) is
    built at import time via `_build_default_app()`, which must succeed when
    the real `frontend/dist` directory does not exist yet (falling back to a
    directory that does exist) as long as the enabled air layer's required
    secrets are present. This is exactly the "bare `import backend.main`"
    scenario the module docstring calls out, and the outer test above never
    imports the module this way -- it only calls the `create_app` factory
    directly.

    Secrets are wired via known, non-empty env values (monkeypatched) rather
    than relying on whatever the ambient `.env`/environment happens to
    contain, so this test proves "builds without a frontend/dist" on its own
    terms, independent of a checked-in `.env`.
    """
    import importlib

    monkeypatch.setenv("OPENSKY_CLIENT_ID", "reload-test-opensky-client-id")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "reload-test-opensky-client-secret")

    import backend.main as main_module

    importlib.reload(main_module)

    from fastapi import FastAPI

    assert isinstance(main_module.app, FastAPI)
    # `frontend/dist` genuinely does not exist in this checkout, so
    # `_build_default_app` must have taken the fallback static-dir branch
    # (asserted directly rather than merely relying on the app having built).
    assert not main_module._FRONTEND_DIST.is_dir()


def test_module_level_app_fails_fast_when_required_secret_missing(monkeypatch):
    """config.md: "Startup fails fast with a named error if a secret
    required by an enabled layer is missing." The air layer is enabled by
    default (backend/config.py `_DEFAULTS["layers"]["air"]["enabled"]`), so
    neutralizing its required OpenSky secrets via real (falsy) env values --
    which override any `.env` entry in pydantic-settings -- must make the
    real uvicorn entrypoint's build raise `MissingSecretError`, not swallow
    it and fall back to a default/blank config.
    """
    import importlib

    import backend.main as main_module
    from backend.config import MissingSecretError

    monkeypatch.setenv("OPENSKY_CLIENT_ID", "")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "")

    try:
        with pytest.raises(MissingSecretError):
            importlib.reload(main_module)
    finally:
        # `importlib.reload` raising mid-module-body leaves `backend.main`
        # partially executed (no module-level `app`); restore it with good
        # secrets so later tests importing/using `backend.main` are
        # unaffected by this test's env manipulation or module state.
        monkeypatch.setenv("OPENSKY_CLIENT_ID", "restore-opensky-client-id")
        monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "restore-opensky-client-secret")
        importlib.reload(main_module)


# ===========================================================================
# backend-api step (issue #18): REST snapshot + manual refresh endpoints.
#
# Locked outer acceptance test (), transcribed from
# plans/backend-api/02-data-endpoints.md ("Acceptance criterion") and
# design/contracts/api.md ("GET /api/layers/{domain}/snapshot", "POST
# /api/refresh", "Error envelope") + design/contracts/storage.md
# ("land_cache" 24h freshness). Committed RED first (strict xfail, ).
# ===========================================================================


def test_snapshots_and_refresh(tmp_path, monkeypatch):
    """Given the app with Hormuz active and OpenSky/Overpass mocked (respx) to
    return the recorded Hormuz fixtures:

    - GET /api/layers/air/snapshot -> 200 LayerSnapshot(AIR); feature_count
      matches the parsed states; the body carries no `raw_payload`.
    - GET /api/layers/land/snapshot -> 200 LayerSnapshot(LAND); the first call
      fetches Overpass and writes the land_cache through, the second call is
      served from the (still-fresh, <24h) cache WITHOUT a second Overpass
      fetch.
    - POST /api/refresh -> 202 {"queued":["air","land"]} and forces a fresh
      fetch of both layers (a fresh Overpass fetch despite the warm cache, and
      a fresh /states/all fetch).
    - When OpenSky returns 429, GET /api/layers/air/snapshot surfaces the
      api.md `rate_limited` error envelope (429, code/message/retry_after_s)
      while GET /api/layers/land/snapshot still succeeds -- FR10 failure
      isolation: one layer failing never blocks the other.

    Design seam this test locks in for the developer (backend/main.py). The
    three new endpoints need three collaborators -- the OpenSky adapter, the
    Overpass adapter, and the Store -- injected into `create_app` by dependency
    injection. The locked signature EXTENDS step's factory with three new
    keyword-only params, each OPTIONAL with a config/secrets-derived default so
    every existing `create_app(static_dir=, config=, secrets=)` call keeps
    working unchanged:

        def create_app(
            *,
            static_dir: Path | str,
            config: AppConfig,
            secrets: Secrets,
            air_adapter: OpenSkyAdapter | None = None,
            land_adapter: OverpassAdapter | None = None,
            store: Store | None = None,
        ) -> FastAPI: ...

    This test injects its own real `OpenSkyAdapter` / `OverpassAdapter` (so
    their upstream httpx traffic is respx-mockable) and a real `Store` on a
    hermetic per-app tmp sqlite db (so the land_cache round-trip is real and
    isolated). The app is responsible for initializing its Store at startup
    (the app is driven through `with TestClient(app)` so that startup runs on
    the same event loop the async handlers use); the region is hardcoded to
    Hormuz for this slice (no activation endpoint yet), so the test never needs
    to construct a Region -- it only mocks the token/states/mirror URLs, which
    respx matches on URL (ignoring the region-derived query string).

    Why this is not satisfiable by a stub or a tautology:
      - The AIR `feature_count` is pinned to the number of non-null-position
        states in the recorded fixture (read at test time, not a hardcoded
        literal), and cross-checked against `len(features)` and `> 0`; a stub
        returning an empty snapshot fails.
      - The warm-cache lock compares the Overpass route's `call_count` across
        the two land reads: it must be > 0 after the first (a real fetch
        happened) and UNCHANGED after the second (served from cache, no second
        Overpass call). A "fetch every time" implementation fails the second
        assertion; a "never fetch" one fails the first.
      - `POST /api/refresh` must raise the Overpass and /states/all counts
        ABOVE their warm-cache values -- a fresh fetch of both despite the warm
        cache -- so an implementation that merely returns the queued list
        without forcing a refetch fails.
      - The FR10 429 branch asserts the air request 429s with the exact api.md
        `rate_limited` envelope AND that the land request still returns 200 in
        the same app -- failure isolation is not satisfiable by an
        all-or-nothing handler.

    Committed RED before implementation (strict xfail, ): the three
    endpoints did not exist and `create_app` did not yet accept the injection
    keywords, so the assertions/`create_app` call failed inside this test body
    and it xfailed cleanly under the tests-green gate. the developer has since
    built `backend/main.py` to satisfy this exact seam -- the test now genuinely
    passes and the marker has been removed to finalize the contract. The
    assertions themselves are never weakened.
    """
    # --- Given: known OpenSky secrets in env (NFR5: env only) ---
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "outer-test-opensky-client-id-18")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "outer-test-opensky-client-secret-18")
    # Marine is enabled in the bundled config.toml (slice config-02, #42); a
    # non-empty value keeps its secret gate from firing for an unrelated
    # reason in this air/land-focused test.
    monkeypatch.setenv("AISSTREAM_API_KEY", "outer-test-aisstream-api-key-18")
    monkeypatch.delenv("AISHUB_USERNAME", raising=False)
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)

    # Test-only speedup (allowed): drop the 0.5s inter-class Overpass sleep so
    # the six sequential class queries per land fetch don't slow the suite.
    import backend.sources.overpass as overpass_module

    monkeypatch.setattr(overpass_module, "_CLASS_DELAY_S", 0)

    from backend.config import load_config
    from backend.main import create_app
    from backend.sources.opensky import CreditLedger, OpenSkyAdapter, OpenSkyCfg
    from backend.sources.overpass import OverpassAdapter, OverpassCfg
    from backend.store import Store

    cfg, secrets = load_config()

    token_url = cfg.opensky["token_url"]
    states_url = cfg.opensky["states_url"]
    mirror_url = OverpassCfg(**cfg.overpass, **cfg.layers["land"].model_dump()).mirrors[
        0
    ]

    opensky_fixture = json.loads(_OPENSKY_FIXTURE.read_text(encoding="utf-8"))
    overpass_fixture = json.loads(_OVERPASS_FIXTURE.read_text(encoding="utf-8"))

    # Derived from the fixture content (not a hardcoded literal): the adapter
    # drops states with null lat/lon (vector[6]/vector[5]), so the expected AIR
    # feature_count is exactly the count of states with both present.
    expected_air_count = sum(
        1
        for state in opensky_fixture["states"]
        if state[5] is not None and state[6] is not None
    )
    assert expected_air_count > 0

    # A hermetic static dir standing in for the not-yet-built frontend.
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        "<!doctype html><html><body>Zij</body></html>", encoding="utf-8"
    )

    def build_app(db_name: str):
        """Build an app with freshly injected real adapters + a real Store on
        its own tmp sqlite db, so each scenario is independent."""
        opensky_cfg = OpenSkyCfg(**cfg.opensky, **cfg.layers["air"].model_dump())
        credits = CreditLedger(
            budget=opensky_cfg.daily_credit_budget,
            warn_ratio=opensky_cfg.credit_warn_ratio,
        )
        air_adapter = OpenSkyAdapter(opensky_cfg, secrets, credits)
        overpass_cfg = OverpassCfg(**cfg.overpass, **cfg.layers["land"].model_dump())
        land_adapter = OverpassAdapter(overpass_cfg)
        store = Store(db_path=tmp_path / db_name)
        return create_app(
            static_dir=static_dir,
            config=cfg,
            secrets=secrets,
            air_adapter=air_adapter,
            land_adapter=land_adapter,
            store=store,
        )

    # --- Happy path: air snapshot, land snapshot + warm cache, refresh ---
    app = build_app("happy.db")
    with respx.mock() as respx_mock:
        respx_mock.post(token_url).mock(
            return_value=Response(200, json=_TOKEN_RESPONSE)
        )
        states_route = respx_mock.get(states_url).mock(
            return_value=Response(200, json=opensky_fixture)
        )
        # Matched on URL only (any method/body): every one of the six
        # whitelisted Overpass class queries hits this same mocked mirror.
        overpass_route = respx_mock.route(url=mirror_url).mock(
            return_value=Response(200, json=overpass_fixture)
        )

        with TestClient(app) as client:
            # --- GET /api/layers/air/snapshot ---
            air_resp = client.get("/api/layers/air/snapshot")
            assert air_resp.status_code == 200
            air_body = air_resp.json()
            assert air_body["meta"]["layer"] == "air"
            assert air_body["meta"]["region_id"] == "hormuz"
            assert air_body["meta"]["feature_count"] == expected_air_count
            assert len(air_body["features"]) == expected_air_count
            # No raw_payload anywhere in the body (Feature.raw_payload is
            # exclude=True; api.md: "raw_payload excluded").
            assert "raw_payload" not in air_resp.text
            for feature in air_body["features"]:
                assert "raw_payload" not in feature

            # --- GET /api/layers/land/snapshot (1st: cold cache -> fetch) ---
            land_resp_1 = client.get("/api/layers/land/snapshot")
            assert land_resp_1.status_code == 200
            land_body_1 = land_resp_1.json()
            assert land_body_1["meta"]["layer"] == "land"
            assert land_body_1["meta"]["region_id"] == "hormuz"
            assert land_body_1["meta"]["feature_count"] == len(land_body_1["features"])
            assert land_body_1["meta"]["feature_count"] > 0
            overpass_after_first = overpass_route.call_count
            assert overpass_after_first > 0  # a real Overpass fetch happened

            # --- GET /api/layers/land/snapshot (2nd: warm cache -> no fetch) ---
            land_resp_2 = client.get("/api/layers/land/snapshot")
            assert land_resp_2.status_code == 200
            land_body_2 = land_resp_2.json()
            assert land_body_2["meta"]["layer"] == "land"
            assert land_body_2["meta"]["region_id"] == "hormuz"
            # Equivalent snapshot, served from the fresh (<24h) land_cache
            # WITHOUT a second Overpass call.
            assert (
                land_body_2["meta"]["feature_count"]
                == land_body_1["meta"]["feature_count"]
            )
            assert overpass_route.call_count == overpass_after_first

            # --- POST /api/refresh -> 202, forces a fresh fetch of both ---
            states_before_refresh = states_route.call_count
            refresh_resp = client.post("/api/refresh")
            assert refresh_resp.status_code == 202
            assert refresh_resp.json() == {"queued": ["air", "land"]}
            # A fresh Overpass fetch despite the warm cache, and a fresh
            # /states/all fetch: both counts rise above their warm values.
            assert overpass_route.call_count > overpass_after_first
            assert states_route.call_count > states_before_refresh

    # --- FR10: OpenSky 429 -> air rate_limited envelope; land still succeeds ---
    app_429 = build_app("fr10.db")
    with respx.mock() as respx_mock_429:
        respx_mock_429.post(token_url).mock(
            return_value=Response(200, json=_TOKEN_RESPONSE)
        )
        respx_mock_429.get(states_url).mock(
            return_value=Response(429, headers={"Retry-After": "42"})
        )
        respx_mock_429.route(url=mirror_url).mock(
            return_value=Response(200, json=overpass_fixture)
        )

        with TestClient(app_429) as client_429:
            air_429 = client_429.get("/api/layers/air/snapshot")
            assert air_429.status_code == 429
            air_429_body = air_429.json()
            assert air_429_body["error"]["code"] == "rate_limited"
            assert "message" in air_429_body["error"]
            assert air_429_body["error"]["retry_after_s"] == 42

            # FR10 failure isolation: the air 429 does not block land.
            land_ok = client_429.get("/api/layers/land/snapshot")
            assert land_ok.status_code == 200
            land_ok_body = land_ok.json()
            assert land_ok_body["meta"]["layer"] == "land"
            assert land_ok_body["meta"]["region_id"] == "hormuz"
            assert land_ok_body["meta"]["feature_count"] > 0


# --- Inner unit tests, step () -----------------------------------
#
# These target collaborators of backend/main.py that the outer
# `test_snapshots_and_refresh` above does NOT isolate:
#   1. the full AdapterError -> HTTP status/envelope table (the outer test
#      only drives the 429 branch end-to-end);
#   2. the lossless Feature <-> GeoJSON-Feature round-trip that backs the
#      land_cache serialization (the load-bearing new logic);
#   3. the stale-cache (>=24h) refetch + write-through branch the outer
#      test's warm-cache path never reaches;
#   4. `_land_snapshot_from_cache_row`'s meta assembly (cadence/stale from
#      config, osm_base as the source timestamp -- FR4).


def test_adapter_error_to_http_maps_the_full_taxonomy():
    """api.md ("Error envelope") + adapter-interface.md error taxonomy: every
    `AdapterError` subtype maps to a specific status + envelope `code`. The
    outer test only exercises the 429/`rate_limited` branch end-to-end; pin
    the whole table here so the 401/502/500 branches (and the 429 header) are
    each locked, not just the one the happy path happens to hit.
    """
    from backend.main import _adapter_error_to_http
    from backend.sources.base import (
        AdapterError,
        AuthError,
        ParseError,
        RateLimitedError,
        UpstreamError,
    )

    # 401 auth_error, no extra headers.
    auth = _adapter_error_to_http(AuthError("bad credentials"))
    assert auth.status_code == 401
    assert auth.detail == {
        "error": {"code": "auth_error", "message": "bad credentials"}
    }
    assert auth.headers is None

    # 502 upstream_error from a transient UpstreamError.
    upstream = _adapter_error_to_http(UpstreamError("overpass 5xx"))
    assert upstream.status_code == 502
    assert upstream.detail == {
        "error": {"code": "upstream_error", "message": "overpass 5xx"}
    }

    # 502 upstream_error from a ParseError too (same status + envelope code).
    parse = _adapter_error_to_http(ParseError("unparseable body"))
    assert parse.status_code == 502
    assert parse.detail["error"]["code"] == "upstream_error"
    assert parse.detail["error"]["message"] == "unparseable body"

    # 500 internal for a generic / unknown AdapterError subtype.
    generic = _adapter_error_to_http(AdapterError("something else"))
    assert generic.status_code == 500
    assert generic.detail == {
        "error": {"code": "internal", "message": "something else"}
    }

    # 429 rate_limited: retry_after_s in the body AND a Retry-After header.
    limited = _adapter_error_to_http(
        RateLimitedError(retry_after=42, message="slow down")
    )
    assert limited.status_code == 429
    assert limited.detail["error"]["code"] == "rate_limited"
    assert limited.detail["error"]["message"] == "slow down"
    assert limited.detail["error"]["retry_after_s"] == 42
    assert limited.headers == {"Retry-After": "42"}

    # 429 with no Retry-After available: retry_after_s null, no header emitted.
    limited_none = _adapter_error_to_http(RateLimitedError())
    assert limited_none.status_code == 429
    assert limited_none.detail["error"]["code"] == "rate_limited"
    assert limited_none.detail["error"]["retry_after_s"] is None
    assert limited_none.headers is None


def test_feature_geojson_round_trip_is_lossless():
    """`_feature_to_geojson` / `_geojson_to_feature` back the land_cache
    `geojson` column: a `LayerSnapshot(LAND)` is stored as a GeoJSON
    FeatureCollection and later rebuilt from it. The round-trip must be
    lossless for every geometry shape the Overpass adapter emits -- POINT
    (geometry None, synthesized Point on the wire), LINESTRING and POLYGON
    (real geometry dict), and a feature with no source timestamp
    (timestamp_source None). Real `Feature` instances are constructed here
    (mirroring the adapter's output) so this is not a tautology against a stub.
    """
    from datetime import datetime, timezone

    from backend.main import _feature_to_geojson, _geojson_to_feature
    from backend.models import Domain, Feature, FeatureStatus, GeometryType

    osm_base = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    fetched = datetime(2024, 6, 2, 0, 0, 0, tzinfo=timezone.utc)
    age = (fetched - osm_base).total_seconds()

    point = Feature(
        domain=Domain.LAND,
        source="overpass",
        source_id="node/1",
        label="Port of Hormuz",
        lat=26.9,
        lon=56.3,
        geometry_type=GeometryType.POINT,
        geometry=None,
        timestamp_source=osm_base,
        timestamp_fetched=fetched,
        position_age_s=age,
        status=FeatureStatus.LIVE,
        attrs={"harbour": "yes", "name": "Port of Hormuz"},
    )
    linestring = Feature(
        domain=Domain.LAND,
        source="overpass",
        source_id="way/100",
        label="E311",
        lat=25.2,
        lon=55.5,
        geometry_type=GeometryType.LINESTRING,
        geometry={"type": "LineString", "coordinates": [[55.5, 25.2], [55.6, 25.3]]},
        timestamp_source=osm_base,
        timestamp_fetched=fetched,
        position_age_s=age,
        attrs={"highway": "motorway", "ref": "E311"},
    )
    polygon = Feature(
        domain=Domain.LAND,
        source="overpass",
        source_id="way/200",
        label=None,
        lat=25.0,
        lon=55.0,
        geometry_type=GeometryType.POLYGON,
        geometry={
            "type": "Polygon",
            "coordinates": [[[55.0, 25.0], [55.1, 25.0], [55.1, 25.1], [55.0, 25.0]]],
        },
        timestamp_source=osm_base,
        timestamp_fetched=fetched,
        position_age_s=age,
        attrs={"landuse": "port"},
    )
    no_source_ts = Feature(
        domain=Domain.LAND,
        source="overpass",
        source_id="node/2",
        label=None,
        lat=26.0,
        lon=56.0,
        geometry_type=GeometryType.POINT,
        geometry=None,
        timestamp_source=None,
        timestamp_fetched=fetched,
        position_age_s=None,
    )

    # POINT features synthesize a Point geometry from lon/lat on the wire...
    point_gj = _feature_to_geojson(point)
    assert point_gj["type"] == "Feature"
    assert point_gj["geometry"] == {
        "type": "Point",
        "coordinates": [point.lon, point.lat],
    }
    # ...while line/polygon features carry their real geometry dict verbatim.
    line_gj = _feature_to_geojson(linestring)
    assert line_gj["geometry"] == linestring.geometry

    # Full lossless round-trip for every representative shape.
    for feature in (point, linestring, polygon, no_source_ts):
        rebuilt = _geojson_to_feature(_feature_to_geojson(feature))
        assert rebuilt == feature


def test_stale_land_cache_triggers_refetch_and_write_through(tmp_path, monkeypatch):
    """storage.md land_cache freshness gate: serve from cache only while
    `now - fetched_at < 24h`, else refetch and write the fresh result through.
    The outer test only ever exercises the WARM (<24h) branch; this drives the
    STALE (>=86400s) branch it never reaches. A stale row is seeded with a
    deliberately-wrong feature_count (1) so a served-from-stale response is
    distinguishable from a genuine refetch: after the GET the response must
    carry the freshly-fetched fixture's real count (>1), proving the >=24h
    boundary forced an Overpass call rather than serving the stale row.
    """
    import asyncio
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("OPENSKY_CLIENT_ID", "stale-test-opensky-client-id")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "stale-test-opensky-client-secret")
    # Marine is enabled in the bundled config.toml (slice config-02, #42); a
    # non-empty value keeps its secret gate from firing for an unrelated
    # reason in this land-cache-focused test.
    monkeypatch.setenv("AISSTREAM_API_KEY", "stale-test-aisstream-api-key")
    monkeypatch.delenv("AISHUB_USERNAME", raising=False)
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)

    import backend.sources.overpass as overpass_module

    monkeypatch.setattr(overpass_module, "_CLASS_DELAY_S", 0)

    from backend.config import load_config
    from backend.main import create_app
    from backend.sources.opensky import CreditLedger, OpenSkyAdapter, OpenSkyCfg
    from backend.sources.overpass import OverpassAdapter, OverpassCfg
    from backend.store import LandCacheRow, Store

    cfg, secrets = load_config()
    mirror_url = OverpassCfg(**cfg.overpass, **cfg.layers["land"].model_dump()).mirrors[
        0
    ]
    overpass_fixture = json.loads(_OVERPASS_FIXTURE.read_text(encoding="utf-8"))

    db_path = tmp_path / "stale.db"

    # A >24h-old row (25h) with feature_count deliberately == 1, so serving it
    # from cache would be visibly wrong versus a real Overpass refetch.
    stale_row = LandCacheRow(
        region_id="hormuz",
        bbox=(55.0, 25.0, 57.5, 27.5),
        geojson={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [56.0, 26.0]},
                    "properties": {
                        "domain": "land",
                        "source": "overpass",
                        "source_id": "node/stale",
                        "label": None,
                        "lat": 26.0,
                        "lon": 56.0,
                        "geometry_type": "point",
                        "timestamp_source": None,
                        "timestamp_fetched": "2000-01-01T00:00:00Z",
                        "position_age_s": None,
                        "status": "live",
                        "integrity_flags": [],
                        "attrs": {},
                    },
                }
            ],
        },
        feature_count=1,
        osm_base=datetime(2000, 1, 1, tzinfo=timezone.utc),
        fetched_at=datetime.now(timezone.utc) - timedelta(hours=25),
    )

    async def _seed() -> None:
        seeder = Store(db_path=db_path)
        await seeder.init()
        await seeder.put_land_cache(stale_row)
        await seeder.close()

    asyncio.run(_seed())

    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        "<!doctype html><html><body>Zij</body></html>", encoding="utf-8"
    )

    opensky_cfg = OpenSkyCfg(**cfg.opensky, **cfg.layers["air"].model_dump())
    credits = CreditLedger(
        budget=opensky_cfg.daily_credit_budget,
        warn_ratio=opensky_cfg.credit_warn_ratio,
    )
    air_adapter = OpenSkyAdapter(opensky_cfg, secrets, credits)
    land_adapter = OverpassAdapter(
        OverpassCfg(**cfg.overpass, **cfg.layers["land"].model_dump())
    )
    store = Store(db_path=db_path)
    app = create_app(
        static_dir=static_dir,
        config=cfg,
        secrets=secrets,
        air_adapter=air_adapter,
        land_adapter=land_adapter,
        store=store,
    )

    with respx.mock() as respx_mock:
        overpass_route = respx_mock.route(url=mirror_url).mock(
            return_value=Response(200, json=overpass_fixture)
        )
        with TestClient(app) as client:
            resp = client.get("/api/layers/land/snapshot")
            assert resp.status_code == 200
            body = resp.json()
            # The stale (>=24h) row forced a real Overpass refetch...
            assert overpass_route.call_count > 0
            # ...and the served snapshot is the freshly-fetched one, NOT the
            # seeded stale row (whose feature_count was 1).
            assert body["meta"]["feature_count"] > 1
            assert body["meta"]["feature_count"] == len(body["features"])
            refetch_count = overpass_route.call_count

            # The refetch wrote a fresh row through: a second read is now served
            # from the (<24h) cache with no further Overpass calls.
            resp2 = client.get("/api/layers/land/snapshot")
            assert resp2.status_code == 200
            assert (
                resp2.json()["meta"]["feature_count"] == body["meta"]["feature_count"]
            )
            assert overpass_route.call_count == refetch_count


def test_land_snapshot_from_cache_row_meta_uses_config_not_row(monkeypatch):
    """`_land_snapshot_from_cache_row` rebuilds a `LayerSnapshot(LAND)` meta
    from a cache row plus config-derived cadence. Per FR4/FR7 + config.md the
    land badge's cadence/stale come from `config.layers["land"]` (86400 / 2x),
    NOT from the row (which has no cadence field), and `timestamp_source` is
    the row's `osm_base` (FR4: the land badge shows osm_base), while
    `timestamp_fetched`/`feature_count` come from the row.
    """
    from datetime import datetime, timezone

    monkeypatch.setenv("OPENSKY_CLIENT_ID", "meta-test-opensky-client-id")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "meta-test-opensky-client-secret")
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)

    from backend.config import load_config
    from backend.main import _feature_to_geojson, _land_snapshot_from_cache_row
    from backend.models import Domain, Feature, GeometryType, LayerStatus
    from backend.store import LandCacheRow

    cfg, _ = load_config()
    land = cfg.layers["land"]
    cadence_s = land.cadence_s
    stale_after_s = land.cadence_s * land.stale_multiplier
    assert cadence_s == 86400
    assert stale_after_s == 172800

    osm_base = datetime(2024, 5, 1, 6, 0, 0, tzinfo=timezone.utc)
    fetched_at = datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
    features = [
        Feature(
            domain=Domain.LAND,
            source="overpass",
            source_id="node/9",
            label="Port",
            lat=26.5,
            lon=56.1,
            geometry_type=GeometryType.POINT,
            geometry=None,
            timestamp_source=osm_base,
            timestamp_fetched=fetched_at,
            position_age_s=7200.0,
            attrs={"harbour": "yes"},
        ),
        Feature(
            domain=Domain.LAND,
            source="overpass",
            source_id="way/9",
            label=None,
            lat=25.5,
            lon=55.5,
            geometry_type=GeometryType.LINESTRING,
            geometry={
                "type": "LineString",
                "coordinates": [[55.5, 25.5], [55.6, 25.6]],
            },
            timestamp_source=osm_base,
            timestamp_fetched=fetched_at,
            position_age_s=7200.0,
            attrs={"highway": "motorway"},
        ),
    ]
    row = LandCacheRow(
        region_id="hormuz",
        bbox=(55.0, 25.0, 57.5, 27.5),
        geojson={
            "type": "FeatureCollection",
            "features": [_feature_to_geojson(f) for f in features],
        },
        feature_count=len(features),
        osm_base=osm_base,
        fetched_at=fetched_at,
    )

    snapshot = _land_snapshot_from_cache_row(
        row, cadence_s=cadence_s, stale_after_s=stale_after_s
    )
    meta = snapshot.meta
    assert meta.layer == Domain.LAND
    assert meta.region_id == "hormuz"
    assert meta.status == LayerStatus.LIVE
    # cadence/stale come from config (land 86400 / 2x), independent of the row.
    assert meta.cadence_s == 86400
    assert meta.stale_after_s == 172800
    # FR4: the land badge's source timestamp is the row's osm_base.
    assert meta.timestamp_source == osm_base
    assert meta.timestamp_fetched == fetched_at
    assert meta.feature_count == len(features)
    assert len(snapshot.features) == len(features)
    # Round-trip fidelity: the rebuilt features equal the originals.
    assert snapshot.features == features


# --- Inner unit tests, step hardening (issue #18 two-stage review) ------
#
# Two non-blocking review findings the maintainer chose to fix before the PR. Both
# were committed RED under a strict xfail (): the assertion inside each
# body failed, pytest reported it `xfailed`, and the suite stayed green so the
# red commit could land before the developer greened it. the developer has
# since hardened `backend/main.py` to satisfy both -- the tests now genuinely
# pass and the markers have been removed to finalize the contract. Neither
# assertion was ever weakened.


def test_unexpected_handler_failure_still_returns_api_md_envelope(
    tmp_path, monkeypatch
):
    """Review finding #1: every non-2xx response must use the api.md error
    envelope, but the snapshot handlers catch only `AdapterError`. A NON-
    `AdapterError` raised by a collaborator (here a `RuntimeError` from the air
    adapter's `fetch`, standing in for any unexpected fault such as a `Store`/
    sqlite error) currently falls through to Starlette's default 500 -- a bare,
    non-envelope body -- violating "every non-2xx uses the envelope".

    Lock the hardened behavior: an unexpected exception inside a snapshot
    handler is surfaced as **500** with the api.md `internal` envelope
    (`{"error": {"code": "internal", "message": ...}}`), NOT a bare Starlette
    500. The distinguishing assertion is the presence of the top-level `error`
    key with `code == "internal"` -- a bare Starlette 500 has no such envelope
    (it is a plain "Internal Server Error"), mirroring how
    `test_unmatched_non_api_path...` distinguishes our envelope from a plain
    static 404.

    Deterministic trigger: a minimal fake air adapter whose `fetch` raises
    `RuntimeError("boom")`, injected via `create_app`, with a real `Store` on a
    tmp db and real `config`/`secrets`. `raise_server_exceptions=False` so the
    unhandled exception is materialized as an actual HTTP response we can
    inspect (rather than re-raised into the test), letting the *envelope*
    assertion -- not an incidental propagated exception -- be the thing that is
    absent today and present once hardened.
    """
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "boom-test-opensky-client-id")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "boom-test-opensky-client-secret")
    # Marine is enabled in the bundled config.toml (slice config-02, #42); a
    # non-empty value keeps its secret gate from firing for an unrelated
    # reason in this error-envelope-focused test.
    monkeypatch.setenv("AISSTREAM_API_KEY", "boom-test-aisstream-api-key")
    monkeypatch.delenv("AISHUB_USERNAME", raising=False)
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)

    from backend.config import load_config
    from backend.main import create_app
    from backend.store import Store

    cfg, secrets = load_config()

    class _BoomAirAdapter:
        """Minimal fake air adapter exposing only what the app touches: an
        `async fetch` that raises a NON-`AdapterError`, and a no-op `async stop`
        (the lifespan calls `stop()` on shutdown)."""

        async def fetch(self, region):
            del region
            raise RuntimeError("boom")

        async def stop(self):
            return None

    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        "<!doctype html><html><body>Zij</body></html>", encoding="utf-8"
    )

    store = Store(db_path=tmp_path / "boom.db")
    app = create_app(
        static_dir=static_dir,
        config=cfg,
        secrets=secrets,
        air_adapter=_BoomAirAdapter(),
        store=store,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/layers/air/snapshot")

    assert resp.status_code == 500
    body = resp.json()
    # The distinguishing assertion: the api.md envelope, not a bare Starlette
    # 500 (which has no top-level "error" key).
    assert "error" in body
    assert body["error"]["code"] == "internal"
    assert "message" in body["error"]


def test_retry_after_header_is_integer_delta_seconds():
    """Review finding #2: RFC 7231 `Retry-After` as delta-seconds must be an
    integer. `_adapter_error_to_http` currently renders the header via
    `str(exc.retry_after)`, so a whole-number `retry_after` of `42.0` yields the
    header `"42.0"` -- not a valid integer delta-seconds.

    Lock: for a whole-number `retry_after`, the `Retry-After` header string is
    `"42"` (integer, no trailing `.0`), while the envelope body's
    `retry_after_s` still carries the numeric value `42`. Pure unit on the
    helper -- no HTTP needed.
    """
    from backend.main import _adapter_error_to_http
    from backend.sources.base import RateLimitedError

    exc = _adapter_error_to_http(RateLimitedError(retry_after=42.0))

    assert exc.status_code == 429
    # RFC 7231 integer delta-seconds: "42", not "42.0".
    assert exc.headers["Retry-After"] == "42"
    # The envelope body still carries the numeric retry_after_s.
    assert exc.detail["error"]["code"] == "rate_limited"
    assert exc.detail["error"]["retry_after_s"] == 42
