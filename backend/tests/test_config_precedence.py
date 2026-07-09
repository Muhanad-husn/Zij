"""Inner unit tests for config slice 03 (issue #46): precedence chain +
active-region restore.

Covers the seeded inner-loop list in plans/config/03-precedence.md that the
outer acceptance test (test_config_precedence_acceptance.py) does not already
exercise at this granularity: the individual precedence-layer collaborators
(`_resolve_user_config_path`, `_load_user_toml`, `_load_env_tunables`,
`_resolve_active_region_id`) in isolation, adjacent-layer precedence pairs
via `load_config()` (rather than the outer test's single staged saga),
`ZIJ_CONFIG_PATH`'s platformdirs fallback pinned without touching the real
user config dir, a second (aisstream-focused) NFR5 secret-never-from-TOML
probe, and `ZIJ_`-prefixed env-tunable type coercion (bool/float) via
pydantic. The outer test remains the locked contract -- these units may not
weaken or replace it.

Written by the test-author (DEC-1); the implementer is path-guarded out of
backend/tests/ and may not edit this file.
"""

from __future__ import annotations

import platformdirs

from backend.config import (
    RegionCfg,
    Secrets,
    _load_env_tunables,
    _load_user_toml,
    _resolve_active_region_id,
    _resolve_user_config_path,
    load_config,
)


def _hermetic_secrets(monkeypatch) -> None:
    """Both the air (OpenSky) and marine (aisstream) secret gates are live
    for the bundled config.toml (config-01/#10, config-02/#42); every test
    below that calls `load_config()` needs real values for both, and a
    clean `ZIJ_CONFIG_PATH`/env-tunable slate so it isn't polluted by a
    previous test's monkeypatch (each test gets its own `monkeypatch`
    fixture, but this keeps every test explicit about its starting state)."""
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "precedence-unit-opensky-id")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "precedence-unit-opensky-secret")
    monkeypatch.setenv("AISSTREAM_API_KEY", "precedence-unit-aisstream-key")
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)
    monkeypatch.delenv("ZIJ_LAYERS__AIR__CADENCE_S", raising=False)
    monkeypatch.delenv("ZIJ_LAYERS__AIR__ENABLED", raising=False)
    monkeypatch.delenv("ZIJ_LAYERS__AIR__CUSTOM_BBOX_CAP_SQ_DEG", raising=False)


# --- _resolve_user_config_path: ZIJ_CONFIG_PATH / platformdirs fallback ------


def test_resolve_user_config_path_honors_ZIJ_CONFIG_PATH_env_var(monkeypatch, tmp_path):
    custom_path = tmp_path / "somewhere-else" / "config.toml"
    monkeypatch.setenv("ZIJ_CONFIG_PATH", str(custom_path))

    resolved = _resolve_user_config_path()

    assert resolved == custom_path


def test_resolve_user_config_path_falls_back_to_platformdirs_when_unset(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)
    # Pin platformdirs's own answer rather than touching the real user config
    # dir (which varies by OS/CI account and must never be read by a test).
    fake_dir = str(tmp_path / "fake-platformdirs-zij")
    monkeypatch.setattr(platformdirs, "user_config_dir", lambda app_name: fake_dir)

    resolved = _resolve_user_config_path()

    assert resolved == tmp_path / "fake-platformdirs-zij" / "config.toml"


# --- _load_user_toml: honors ZIJ_CONFIG_PATH, absent file contributes nothing


def test_load_user_toml_returns_empty_dict_when_file_absent(monkeypatch, tmp_path):
    missing_path = tmp_path / "does-not-exist" / "config.toml"
    monkeypatch.setenv("ZIJ_CONFIG_PATH", str(missing_path))

    assert _load_user_toml() == {}


def test_load_user_toml_parses_file_at_ZIJ_CONFIG_PATH(monkeypatch, tmp_path):
    user_toml = tmp_path / "user-config.toml"
    user_toml.write_text("[layers.air]\ncadence_s = 111\n", encoding="utf-8")
    monkeypatch.setenv("ZIJ_CONFIG_PATH", str(user_toml))

    parsed = _load_user_toml()

    assert parsed == {"layers": {"air": {"cadence_s": 111}}}


# --- _load_env_tunables: ZIJ_ prefix, __ nesting, ZIJ_CONFIG_PATH excluded --


def test_load_env_tunables_parses_ZIJ_prefixed_nested_env_vars(monkeypatch):
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)
    monkeypatch.setenv("ZIJ_LAYERS__AIR__CADENCE_S", "222")

    tunables = _load_env_tunables()

    assert tunables["layers"]["air"]["cadence_s"] == "222"


def test_load_env_tunables_excludes_ZIJ_CONFIG_PATH_as_a_loader_control_knob(
    monkeypatch,
):
    monkeypatch.setenv("ZIJ_CONFIG_PATH", "/some/path/config.toml")
    monkeypatch.delenv("ZIJ_LAYERS__AIR__CADENCE_S", raising=False)

    tunables = _load_env_tunables()

    # ZIJ_CONFIG_PATH must never be parsed as a ZIJ_-prefixed tunable (it
    # would otherwise land as {"config": {"path": ...}}).
    assert "config" not in tunables


def test_load_env_tunables_ignores_non_ZIJ_prefixed_vars(monkeypatch):
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)
    monkeypatch.setenv("SOME_OTHER_VAR", "should-not-appear")

    tunables = _load_env_tunables()

    assert "some_other_var" not in tunables
    assert "some" not in tunables


# --- _resolve_active_region_id: default fallback, valid/invalid override ----

_REGIONS = [
    RegionCfg(id="hormuz", label="Strait of Hormuz", bbox=(55.0, 25.0, 57.5, 27.5)),
    RegionCfg(id="gulf-of-oman", label="Gulf of Oman", bbox=(56.5, 22.0, 62.0, 26.5)),
]


def test_resolve_active_region_id_defaults_to_regions_first_when_overrides_none():
    assert _resolve_active_region_id(_REGIONS, None) == "hormuz"


def test_resolve_active_region_id_defaults_when_active_region_key_absent():
    overrides = {"layers": {"air": {"cadence_s": 100}}}
    assert _resolve_active_region_id(_REGIONS, overrides) == "hormuz"


def test_resolve_active_region_id_restores_a_valid_override():
    overrides = {"active_region": {"region_id": "gulf-of-oman"}}
    assert _resolve_active_region_id(_REGIONS, overrides) == "gulf-of-oman"


def test_resolve_active_region_id_falls_back_when_region_id_unknown():
    overrides = {"active_region": {"region_id": "atlantis-not-a-real-region"}}
    assert _resolve_active_region_id(_REGIONS, overrides) == "hormuz"


def test_resolve_active_region_id_falls_back_when_active_region_payload_not_a_mapping():
    # A malformed payload (not a {"region_id": ...} mapping) must degrade to
    # the default, not raise.
    overrides = {"active_region": "not-a-mapping"}
    assert _resolve_active_region_id(_REGIONS, overrides) == "hormuz"


def test_resolve_active_region_id_empty_regions_list_defaults_to_empty_string():
    assert _resolve_active_region_id([], None) == ""


def test_active_region_id_excluded_from_model_dump_but_readable_as_an_attribute(
    monkeypatch,
):
    """Regression lock (config slice 03 / #46, review fix 5a9907e):
    `AppConfig.active_region_id` is `Field(exclude=True)` -- it must stay a
    readable attribute internally while never appearing in `model_dump()`
    (the same serialization `/api/config` uses), since it's an internal
    resolved value that api.md's response shape doesn't include."""
    _hermetic_secrets(monkeypatch)

    cfg, _secrets = load_config()

    assert cfg.active_region_id
    assert "active_region_id" not in cfg.model_dump()


# --- Adjacent-layer precedence pairs via load_config() -----------------------
# (The outer test drives one single staged saga bundle->user->env->DB; these
# isolate each *adjacent pair* directly, so a regression in just one hop is
# pinned by its own test rather than only surfacing inside the longer saga.)


def test_env_tunable_overrides_user_toml_for_the_same_key(monkeypatch, tmp_path):
    _hermetic_secrets(monkeypatch)
    user_toml = tmp_path / "user-config.toml"
    user_toml.write_text("[layers.air]\ncadence_s = 450\n", encoding="utf-8")
    monkeypatch.setenv("ZIJ_CONFIG_PATH", str(user_toml))
    monkeypatch.setenv("ZIJ_LAYERS__AIR__CADENCE_S", "300")

    cfg, _secrets = load_config()

    assert cfg.layers["air"].cadence_s == 300
    # Sibling untouched by either override layer.
    assert cfg.layers["air"].cadence_floor_s == 60


def test_db_override_overrides_env_tunable_for_the_same_key(monkeypatch):
    _hermetic_secrets(monkeypatch)
    monkeypatch.setenv("ZIJ_LAYERS__AIR__CADENCE_S", "300")

    cfg, _secrets = load_config(overrides={"layers": {"air": {"cadence_s": 120}}})

    assert cfg.layers["air"].cadence_s == 120
    assert cfg.layers["air"].cadence_floor_s == 60


def test_db_override_overrides_user_toml_directly_with_no_env_layer_present(
    monkeypatch, tmp_path
):
    _hermetic_secrets(monkeypatch)
    user_toml = tmp_path / "user-config.toml"
    user_toml.write_text("[layers.air]\ncadence_s = 450\n", encoding="utf-8")
    monkeypatch.setenv("ZIJ_CONFIG_PATH", str(user_toml))

    cfg, _secrets = load_config(overrides={"layers": {"air": {"cadence_s": 120}}})

    assert cfg.layers["air"].cadence_s == 120


# --- NFR5: secrets never sourced from any TOML layer (second probe) ---------
# The outer test proves this for [opensky]/OPENSKY_CLIENT_*; this probes the
# same guarantee for the aisstream/marine pair, structurally (by key), so a
# regression that leaks *any* secret field from a TOML rather than just the
# opensky-shaped one would still be caught.


def test_aisstream_secret_shaped_toml_key_never_reaches_secrets(monkeypatch, tmp_path):
    _hermetic_secrets(monkeypatch)
    real_key = "real-env-aisstream-key"
    monkeypatch.setenv("AISSTREAM_API_KEY", real_key)

    user_toml = tmp_path / "user-config.toml"
    user_toml.write_text(
        '[aisstream]\napi_key = "toml-leaked-aisstream-key"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ZIJ_CONFIG_PATH", str(user_toml))

    cfg, secrets = load_config()

    # The TOML-provided value legitimately lands in AppConfig.aisstream (a
    # plain dict)...
    assert cfg.aisstream["api_key"] == "toml-leaked-aisstream-key"
    # ...but Secrets is sourced from env/.env only (NFR5) and must still
    # carry the real env value, never the TOML one.
    assert secrets.aisstream_api_key == real_key
    assert secrets.aisstream_api_key != "toml-leaked-aisstream-key"
    # Structural guard: no Secrets field name ever appears as a TOML-parsed
    # key in AppConfig's own model fields.
    assert set(Secrets.model_fields).isdisjoint(set(cfg.__class__.model_fields))


# --- ZIJ_-prefixed env-tunable type coercion (bool / float via pydantic) ----


def test_env_tunable_bool_coerces_to_python_bool(monkeypatch):
    _hermetic_secrets(monkeypatch)
    monkeypatch.setenv("ZIJ_LAYERS__AIR__ENABLED", "false")

    cfg, _secrets = load_config()

    assert cfg.layers["air"].enabled is False


def test_env_tunable_float_coerces_to_python_float(monkeypatch):
    _hermetic_secrets(monkeypatch)
    monkeypatch.setenv("ZIJ_LAYERS__AIR__CUSTOM_BBOX_CAP_SQ_DEG", "55.5")

    cfg, _secrets = load_config()

    assert cfg.layers["air"].custom_bbox_cap_sq_deg == 55.5
    assert isinstance(cfg.layers["air"].custom_bbox_cap_sq_deg, float)
