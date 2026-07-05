"""Locked outer acceptance test for backend-api slice 01 (issue #17): the
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

This is the behavioral contract (DEC-1), transcribed from
plans/backend-api/01-app-health-config.md and design/contracts/api.md ("GET
/api/health", "GET /api/config", "Error envelope") and
design/contracts/config.md / backend/config.py (`load_config()` ->
`(AppConfig, Secrets)`, `Secrets` never folded into `AppConfig`).

Design seam this test locks in for the implementer (backend/main.py):

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

It was authored and committed red by the test-author before any
implementation existed, guarded by a strict xfail (DEC-33): `backend.main`
had no `create_app`/`app`, so the import raised `ImportError` and the test
xfailed rather than errored. The implementer has since built `backend/main.py`
to satisfy this exact seam -- the test now genuinely passes and the marker is
removed below to finalize the contract. This assertion itself is never
weakened.
"""

import pytest
from fastapi.testclient import TestClient


def test_health_and_config(tmp_path, monkeypatch):
    # --- Given: a real, known pair of OpenSky secret values wired through
    # env (config.py's Secrets is env/.env-only, NFR5) so the "never leaks"
    # assertion below is meaningful rather than vacuous ---
    client_id = "outer-test-opensky-client-id-4f2a"
    client_secret = "outer-test-opensky-client-secret-9b7d"
    monkeypatch.setenv("OPENSKY_CLIENT_ID", client_id)
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", client_secret)
    monkeypatch.delenv("AISSTREAM_API_KEY", raising=False)
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


# --- Inner unit tests (DEC-34) --------------------------------------------
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
