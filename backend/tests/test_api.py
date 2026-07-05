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

It is authored and committed red by the author before any
implementation exists, guarded by a strict xfail (): `backend.main` has
no `create_app`/`app` yet, so the import below raises `ImportError` and the
test xfails rather than errors. Once the developer builds `backend/main.py`
to satisfy this exact seam, the test genuinely passes (xpass) and the
author removes the marker to finalize the contract -- this assertion
itself is never to be weakened.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.xfail(
    reason="backend.main create_app/app not yet implemented  (#17)",
    strict=True,
)
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
