"""Locked outer acceptance test for config step (issue #42): v1 config
sections -- marine, aisstream, integrity, server.

Given the bundled config.toml extended with the v1 sections (marine/
      aisstream/integrity/server), values verbatim from
      design/contracts/config.md
When  load_config() runs
Then  the marine/aisstream/integrity/server sections load with their
      config.md defaults
And   GET /api/config returns the full air/marine/land layers shape (api.md)
      and leaks no secrets (NFR5)
When  the marine layer is enabled and AISSTREAM_API_KEY is unset
Then  startup fails fast with a named error (MissingSecretError, env_var ==
      "AISSTREAM_API_KEY", layer == "marine")
When  the marine layer is disabled and AISSTREAM_API_KEY is unset
Then  startup succeeds (FR5: disabled layers need no secret)

This is the behavioral contract (), transcribed from
plans/config/02-sections.md ("Acceptance criterion") and
design/contracts/config.md ("[layers.marine]", "aisstream", "Integrity",
"SSE / server", "Loading design") and design/contracts/api.md ("GET
/api/config"). Committed RED before implementation (strict xfail, ):
the bundled config.toml carried no [layers.marine]/[aisstream]/[integrity]/
[server] sections yet, so the very first assertion below (`"marine" in
cfg.layers`) failed, and `_check_required_secrets` did not yet gate the
marine layer's secret either -- the test genuinely xfailed rather than
passing vacuously. the developer has since built the sections + the secret
gate to satisfy this exact contract -- every assertion in this single
scenario now holds and the marker has been removed by the author to
finalize the contract (never loosened, never removed early).

Note on import hermeticity: `from backend.main import create_app` is
deliberately NOT at module scope here. `backend/main.py` builds its
module-level `app` eagerly via `_build_default_app()` -> `load_config()` at
import time, which would run during pytest *collection* -- before the
session-scoped conftest fixture (`backend/tests/conftest.py::
_hermetic_opensky_secrets`) has set any secret baseline -- and raise
`MissingSecretError` as a collection error that aborts the whole suite in a
CI environment carrying zero ambient secrets. The import is therefore
deferred into the test function body below, matching the lazy-import
convention already used throughout `backend/tests/test_api.py`.

Scope note (spec discrepancy candidate, NOT asserted here): api.md's `/api/config`
example additionally shows top-level `stale_multiplier` and
`custom_bbox_caps` fields alongside `regions`/`layers`. Neither
plans/config/02-sections.md's acceptance criterion nor
design/contracts/config.md's `AppConfig` model (`Loading design`) defines
such top-level fields -- `AppConfig` has no `stale_multiplier`/
`custom_bbox_caps` attributes for `GET /api/config` to derive them from, and
the existing (already-green) `test_api.py::test_health_and_config` doesn't
assert them either. This test intentionally scopes to
plans/config/02-sections.md's stated acceptance ("the full air/marine/land
layers shape ... leaks no secrets") and does not assert those two extra
top-level keys.
"""

import pytest
from fastapi.testclient import TestClient

from backend.config import (
    AppConfig,
    LayerCfg,
    MissingSecretError,
    Secrets,
    _check_required_secrets,
    load_config,
)

# config.md "[layers.marine]" (lines 68-75).
MARINE_DEFAULTS = {
    "enabled": True,
    "cadence_s": 60,
    "cadence_floor_s": 60,
    "stale_multiplier": 2,
    "deemphasize_after_s": 1800,
    "drop_after_s": 7200,
    "custom_bbox_cap_sq_deg": 40,
}

# config.md "aisstream (§6.2, D2)".
AISSTREAM_DEFAULTS = {
    "ws_url": "wss://stream.aisstream.io/v0/stream",
    "reconnect_base_s": 2,
    "reconnect_max_s": 60,
}

# config.md "Integrity (FR9, §7.3, OQ4)".
INTEGRITY_DEFAULTS = {
    "landmask_path": "",
    "max_speed_kn_marine": 120,
    "max_speed_kn_air": 990,
}

# config.md "SSE / server".
SERVER_DEFAULTS = {
    "sse_ping_s": 15,
    "static_dir": "frontend/dist",
}


def _set_hermetic_secrets(monkeypatch, *, aisstream_api_key: str) -> None:
    """Wire valid OpenSky secrets (air is enabled, so its own gate must not
    fire) plus a controlled `AISSTREAM_API_KEY` value.

    Empty-string technique (not `delenv`), matching test_config.py's
    documented rationale: a local dev `.env` on disk may carry a real
    `AISSTREAM_API_KEY`, and `pydantic-settings` gives actual process env
    vars priority over `.env` only when the var is *set* (even to "") --
    `delenv` alone would silently fall through to the `.env` value via the
    dotenv fallback, making the fail-fast assertion below vacuous.
    """
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "sections-outer-opensky-client-id")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "sections-outer-opensky-client-secret")
    monkeypatch.setenv("AISSTREAM_API_KEY", aisstream_api_key)
    monkeypatch.delenv("AISHUB_USERNAME", raising=False)
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)


def test_v1_sections_load_endpoint_shape_and_marine_secret_gate(tmp_path, monkeypatch):
    # Deferred import (not module scope) -- see module docstring's "Note on
    # import hermeticity".
    from backend.main import create_app

    # === Given/When/Then: the bundled config.toml's v1 sections load with
    # their config.md defaults ===
    _set_hermetic_secrets(monkeypatch, aisstream_api_key="outer-test-aisstream-api-key")

    cfg, secrets = load_config()

    assert "marine" in cfg.layers
    marine = cfg.layers["marine"]
    assert marine.enabled is MARINE_DEFAULTS["enabled"]
    assert marine.cadence_s == MARINE_DEFAULTS["cadence_s"]
    assert marine.cadence_floor_s == MARINE_DEFAULTS["cadence_floor_s"]
    assert marine.stale_multiplier == MARINE_DEFAULTS["stale_multiplier"]
    assert marine.deemphasize_after_s == MARINE_DEFAULTS["deemphasize_after_s"]
    assert marine.drop_after_s == MARINE_DEFAULTS["drop_after_s"]
    assert marine.custom_bbox_cap_sq_deg == MARINE_DEFAULTS["custom_bbox_cap_sq_deg"]

    assert cfg.aisstream["ws_url"] == AISSTREAM_DEFAULTS["ws_url"]
    assert cfg.aisstream["reconnect_base_s"] == AISSTREAM_DEFAULTS["reconnect_base_s"]
    assert cfg.aisstream["reconnect_max_s"] == AISSTREAM_DEFAULTS["reconnect_max_s"]

    assert cfg.integrity["landmask_path"] == INTEGRITY_DEFAULTS["landmask_path"]
    assert (
        cfg.integrity["max_speed_kn_marine"]
        == INTEGRITY_DEFAULTS["max_speed_kn_marine"]
    )
    assert cfg.integrity["max_speed_kn_air"] == INTEGRITY_DEFAULTS["max_speed_kn_air"]

    assert cfg.server["sse_ping_s"] == SERVER_DEFAULTS["sse_ping_s"]
    assert cfg.server["static_dir"] == SERVER_DEFAULTS["static_dir"]

    # Secrets are wired but never folded into AppConfig (NFR5) -- checked
    # structurally below via the serialized /api/config body.
    assert secrets.aisstream_api_key == "outer-test-aisstream-api-key"

    # === And: GET /api/config returns the full air/marine/land layers shape
    # (api.md) and leaks no secrets (NFR5) ===
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        "<!doctype html><html><body>Zij</body></html>", encoding="utf-8"
    )
    app = create_app(static_dir=static_dir, config=cfg, secrets=secrets)
    client = TestClient(app)

    config_resp = client.get("/api/config")
    assert config_resp.status_code == 200
    config_body = config_resp.json()

    layers = config_body["layers"]
    assert set(layers) >= {"air", "marine", "land"}

    air_layer = layers["air"]
    assert air_layer["enabled"] is True
    assert air_layer["cadence_s"] == 600
    assert air_layer["cadence_floor_s"] == 60
    assert air_layer["deemphasize_after_s"] == 60
    assert air_layer["stale_multiplier"] == 2
    assert air_layer["custom_bbox_cap_sq_deg"] == 100

    marine_layer = layers["marine"]
    assert marine_layer["enabled"] is True
    assert marine_layer["cadence_s"] == 60
    assert marine_layer["cadence_floor_s"] == 60
    assert marine_layer["deemphasize_after_s"] == 1800
    assert marine_layer["drop_after_s"] == 7200
    assert marine_layer["stale_multiplier"] == 2
    assert marine_layer["custom_bbox_cap_sq_deg"] == 40

    land_layer = layers["land"]
    assert land_layer["enabled"] is True
    assert land_layer["cadence_s"] == 86400
    assert land_layer["cadence_floor_s"] == 3600
    assert land_layer["stale_multiplier"] == 2
    assert land_layer["simplify_tolerance_deg"] == 0.0005
    assert land_layer["max_rendered_features"] == 5000

    # NFR5: neither the OpenSky nor the aisstream secret VALUE ever appears
    # anywhere in the serialized /api/config body -- the app above is wired
    # to real, known secret literals (not placeholders), so this assertion
    # is meaningful rather than vacuous. Field names are guarded too, so a
    # future refactor folding Secrets into the response under a renamed key
    # still trips this.
    config_raw_text = config_resp.text
    assert "sections-outer-opensky-client-id" not in config_raw_text
    assert "sections-outer-opensky-client-secret" not in config_raw_text
    assert "outer-test-aisstream-api-key" not in config_raw_text
    assert "opensky_client_id" not in config_raw_text
    assert "opensky_client_secret" not in config_raw_text
    assert "aisstream_api_key" not in config_raw_text

    # === When: the marine layer is enabled (bundled config.toml) and
    # AISSTREAM_API_KEY is unset (empty-string technique -- see
    # _set_hermetic_secrets) ===
    # Then: startup fails fast with a named error.
    _set_hermetic_secrets(monkeypatch, aisstream_api_key="")

    with pytest.raises(MissingSecretError) as exc_info:
        load_config()

    assert exc_info.value.env_var == "AISSTREAM_API_KEY"
    assert exc_info.value.layer == "marine"
    assert "AISSTREAM_API_KEY" in str(exc_info.value)
    assert "marine" in str(exc_info.value)

    # === When: the marine layer is disabled and AISSTREAM_API_KEY is unset
    # === Then: startup succeeds (FR5: disabled layers need no secret) ===
    # Built directly (not through the bundled TOML, which enables marine) so
    # this drives `_check_required_secrets`'s "disabled skips the check"
    # branch for marine in isolation, independent of the bundled TOML --
    # mirrors test_config.py::test_disabled_air_layer_needs_no_secret.
    monkeypatch.setenv("AISSTREAM_API_KEY", "")

    disabled_marine_cfg = AppConfig(
        regions=[],
        layers={
            "marine": LayerCfg(
                enabled=False,
                cadence_s=60,
                cadence_floor_s=60,
                custom_bbox_cap_sq_deg=40,
            )
        },
        overpass={},
        opensky={},
        aisstream={},
        integrity={},
        server={},
    )
    disabled_marine_secrets = Secrets()

    # Must not raise -- FR5: a disabled layer's secret is not required.
    _check_required_secrets(disabled_marine_cfg, disabled_marine_secrets)
