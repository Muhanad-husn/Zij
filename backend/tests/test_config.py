"""Unit tests for the config loader (issue #10).

Covers the parts of the loader that the acceptance test
(test_config_acceptance.py) does not already exercise:
missing-secret fail-fast, effective_cadence_s/stale_after_s math, deep-merge
sibling preservation, bundled-TOML-over-code-default precedence, secrets never
serializing (checked structurally, by key, not just by value), and full
region bbox/label coverage for the six regions the acceptance test only checks
by id. The acceptance test remains the authoritative contract -- these units
may not weaken or replace it.
"""

import pytest

from backend.config import (
    _DEFAULTS,
    AppConfig,
    LayerCfg,
    MissingSecretError,
    Secrets,
    _deep_merge,
    _load_bundled_toml,
    effective_cadence_s,
    estimate_credits,
    load_config,
    stale_after_s,
)

# The config.md "Predefined regions" table (design/contracts/config.md lines
# 43-49), mirrored by backend/config.toml -- used to check every region's
# bbox and label, not just hormuz (which the acceptance test already covers).
PREDEFINED_REGIONS = {
    "hormuz": ("Strait of Hormuz", (55.0, 25.0, 57.5, 27.5)),
    "persian-gulf": ("Persian Gulf", (47.5, 23.5, 57.0, 30.5)),
    "gulf-of-oman": ("Gulf of Oman", (56.5, 22.0, 62.0, 26.5)),
    "iraq-corridor": ("Iraq corridor", (42.0, 29.5, 48.5, 35.0)),
    "syria-corridor": ("Syria corridor", (35.5, 32.0, 42.0, 37.5)),
    "eastern-med": ("Eastern Mediterranean", (31.0, 31.0, 36.5, 37.0)),
    "suez-canal": ("Suez Canal", (31.8, 29.0, 34.5, 32.2)),
}


def _set_valid_opensky_secrets(
    monkeypatch, client_id="unit-id", client_secret="unit-secret"
):
    monkeypatch.setenv("OPENSKY_CLIENT_ID", client_id)
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", client_secret)
    # Marine is enabled in the bundled config.toml (#42); a
    # non-empty value keeps its own secret gate from firing for an unrelated
    # reason in these air/opensky-focused unit tests.
    monkeypatch.setenv("AISSTREAM_API_KEY", "unit-aisstream-api-key")
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)


# --- Missing-secret fail-fast (NFR5, config-module.md) ----------------------


def test_missing_opensky_client_id_raises_named_error_when_air_enabled(monkeypatch):
    # Set to empty string, not delenv: a local dev `.env` on disk carries real
    # OpenSky credentials (config.md "Secrets, env-only"), and pydantic-settings
    # reads that dotenv file whenever the process env doesn't already define
    # the var -- so delenv alone would silently fall through to the .env file's
    # value. An explicit empty-string env var takes priority over the dotenv
    # source and is still falsy, so `_check_required_secrets` treats it as
    # missing.
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "unit-secret")
    # Marine is enabled in the bundled config.toml (#42); a
    # non-empty value here isolates this test to the air/OPENSKY_CLIENT_ID
    # failure it targets, independent of _check_required_secrets's internal
    # check ordering.
    monkeypatch.setenv("AISSTREAM_API_KEY", "unit-aisstream-api-key")
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)

    with pytest.raises(MissingSecretError) as exc_info:
        load_config()

    assert exc_info.value.env_var == "OPENSKY_CLIENT_ID"
    assert exc_info.value.layer == "air"
    assert "OPENSKY_CLIENT_ID" in str(exc_info.value)
    assert "air" in str(exc_info.value)


def test_missing_opensky_client_secret_raises_named_error_when_air_enabled(monkeypatch):
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "unit-id")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "")
    # Marine is enabled in the bundled config.toml (#42); a
    # non-empty value here isolates this test to the air/
    # OPENSKY_CLIENT_SECRET failure it targets, independent of
    # _check_required_secrets's internal check ordering.
    monkeypatch.setenv("AISSTREAM_API_KEY", "unit-aisstream-api-key")
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)

    with pytest.raises(MissingSecretError) as exc_info:
        load_config()

    assert exc_info.value.env_var == "OPENSKY_CLIENT_SECRET"
    assert exc_info.value.layer == "air"


def test_disabled_air_layer_needs_no_secret(monkeypatch):
    # FR5: a disabled layer's secret is not required. Build the LayerCfg
    # directly rather than routing through the bundled TOML (which enables
    # air), so this test targets `_check_required_secrets`'s "disabled skips
    # the check" branch in isolation.
    from backend.config import _check_required_secrets

    # Set to empty string, not delenv: a local dev `.env` on disk carries real
    # OpenSky credentials (config.md "Secrets, env-only"), so delenv alone
    # would silently fall through to the .env file's value and this test
    # would pass even if the "disabled skips the check" branch were dropped.
    # An explicit empty-string env var is still falsy but takes priority over
    # the dotenv source, so the secrets really are absent here.
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "")

    cfg = AppConfig(
        regions=[],
        layers={
            "air": LayerCfg(
                enabled=False,
                cadence_s=600,
                cadence_floor_s=60,
                custom_bbox_cap_sq_deg=100,
            )
        },
        overpass={},
        opensky={},
        aisstream={},
        integrity={},
        server={},
    )
    secrets = Secrets()

    # Must not raise -- the disabled layer's secret requirement is skipped.
    _check_required_secrets(cfg, secrets)


# --- effective_cadence_s (FR6) -----------------------------------------------


def test_effective_cadence_s_applies_the_floor_when_cadence_below_floor():
    layer = LayerCfg(cadence_s=10, cadence_floor_s=60, custom_bbox_cap_sq_deg=100)
    assert effective_cadence_s(layer) == 60


def test_effective_cadence_s_returns_cadence_when_above_floor():
    layer = LayerCfg(cadence_s=600, cadence_floor_s=60, custom_bbox_cap_sq_deg=100)
    assert effective_cadence_s(layer) == 600


def test_effective_cadence_s_never_returns_below_floor_at_the_boundary():
    # cadence_s exactly equal to the floor -- still the floor, not below it.
    layer = LayerCfg(cadence_s=60, cadence_floor_s=60, custom_bbox_cap_sq_deg=100)
    assert effective_cadence_s(layer) == 60


# --- stale_after_s (FR7) ------------------------------------------------------


def test_stale_after_s_is_cadence_times_stale_multiplier():
    layer = LayerCfg(
        cadence_s=600,
        cadence_floor_s=60,
        stale_multiplier=2,
        custom_bbox_cap_sq_deg=100,
    )
    assert stale_after_s(layer) == 1200


def test_stale_after_s_is_independent_per_layer():
    air = LayerCfg(
        cadence_s=600,
        cadence_floor_s=60,
        stale_multiplier=2,
        custom_bbox_cap_sq_deg=100,
    )
    land = LayerCfg(
        cadence_s=86400,
        cadence_floor_s=3600,
        stale_multiplier=2,
        custom_bbox_cap_sq_deg=40,
    )
    assert stale_after_s(air) == 1200
    assert stale_after_s(land) == 172800
    # Changing one layer's cadence does not affect the other's stale_after_s.
    air_changed = air.model_copy(update={"cadence_s": 120})
    assert stale_after_s(air_changed) == 240
    assert stale_after_s(land) == 172800


# --- Deep-merge preserves siblings (ADR-6, config-module.md) -----------------


def test_deep_merge_overriding_one_key_preserves_sibling_keys():
    base = {
        "layers": {
            "air": {
                "cadence_s": 600,
                "cadence_floor_s": 60,
                "custom_bbox_cap_sq_deg": 100,
            }
        }
    }
    override = {"layers": {"air": {"cadence_s": 55}}}

    merged = _deep_merge(base, override)

    assert merged["layers"]["air"]["cadence_s"] == 55
    # Siblings under layers.air survive untouched.
    assert merged["layers"]["air"]["cadence_floor_s"] == 60
    assert merged["layers"]["air"]["custom_bbox_cap_sq_deg"] == 100
    # Inputs are not mutated.
    assert base["layers"]["air"]["cadence_s"] == 600
    assert override["layers"]["air"] == {"cadence_s": 55}


def test_deep_merge_does_not_mutate_inputs_and_replaces_lists_wholesale():
    base = {"regions": [{"id": "a"}], "layers": {"air": {"cadence_s": 600}}}
    override = {"regions": [{"id": "b"}]}

    merged = _deep_merge(base, override)

    assert merged["regions"] == [{"id": "b"}]
    assert merged["layers"]["air"]["cadence_s"] == 600
    # base untouched.
    assert base["regions"] == [{"id": "a"}]


# --- Precedence: bundled TOML overrides code default (ADR-6) -----------------


def test_bundled_toml_value_overrides_code_default_for_same_key(tmp_path):
    # A minimal bundled TOML overriding only layers.air.cadence_s, run through
    # the real _load_bundled_toml + _deep_merge + AppConfig.model_validate
    # pipeline load_config() itself drives -- proves layer-2 (bundled TOML)
    # beats layer-1 (code default) for the same key, per ADR-6 precedence.
    override_toml = tmp_path / "config.toml"
    override_toml.write_text("[layers.air]\ncadence_s = 55\n", encoding="utf-8")

    bundled = _load_bundled_toml(override_toml)
    merged = _deep_merge(_DEFAULTS, bundled)
    cfg = AppConfig.model_validate(merged)

    # Code default for layers.air.cadence_s is 600 (backend/config.py
    # _DEFAULTS); the bundled value of 55 must win.
    assert _DEFAULTS["layers"]["air"]["cadence_s"] == 600
    assert cfg.layers["air"].cadence_s == 55
    # Sibling defaults not present in the override TOML survive the merge.
    assert cfg.layers["air"].cadence_floor_s == 60
    assert cfg.layers["air"].custom_bbox_cap_sq_deg == 100


# --- Secrets never serialize (NFR5) ------------------------------------------


def test_secrets_field_names_never_appear_as_keys_in_appconfig(monkeypatch):
    _set_valid_opensky_secrets(monkeypatch, "unit-id-abcd", "unit-secret-wxyz")
    # As of #42, aisstream_api_key is also a Secrets field now
    # that marine is enabled -- extend this structural guard to cover it too,
    # not just the OpenSky pair.
    monkeypatch.setenv("AISSTREAM_API_KEY", "unit-aisstream-api-key-mnop")

    cfg, secrets = load_config()

    # Sanity: the secrets really were loaded (so this test would fail loudly
    # if load_config stopped reading them at all).
    assert secrets.opensky_client_id == "unit-id-abcd"
    assert secrets.opensky_client_secret == "unit-secret-wxyz"
    assert secrets.aisstream_api_key == "unit-aisstream-api-key-mnop"

    dumped = cfg.model_dump()

    def flatten_keys(obj):
        keys: set[str] = set()
        if isinstance(obj, dict):
            for key, value in obj.items():
                keys.add(key)
                keys |= flatten_keys(value)
        elif isinstance(obj, list):
            for item in obj:
                keys |= flatten_keys(item)
        return keys

    all_keys = flatten_keys(dumped)
    # No secret-named field anywhere in the dumped structure -- a structural
    # check distinct from the acceptance test's "value not in JSON string" check.
    assert "opensky_client_id" not in all_keys
    assert "opensky_client_secret" not in all_keys
    assert "aisstream_api_key" not in all_keys
    assert not any("secret" in key for key in all_keys)
    # And AppConfig's own model fields never include a Secrets field.
    assert set(Secrets.model_fields).isdisjoint(set(AppConfig.model_fields))


# --- All 7 predefined regions: bbox + label (config.md) ----------------------
# (The acceptance test checks all 7 ids are present and hormuz's bbox; this fills
# in bbox + label for the remaining six so a wrong bbox/label on any region
# fails a test, not just a spot check.)


def test_all_predefined_regions_have_config_md_bboxes_and_labels(monkeypatch):
    _set_valid_opensky_secrets(monkeypatch)

    cfg, _ = load_config()

    regions_by_id = {region.id: region for region in cfg.regions}
    assert set(regions_by_id) == set(PREDEFINED_REGIONS)

    for region_id, (label, bbox) in PREDEFINED_REGIONS.items():
        region = regions_by_id[region_id]
        assert region.label == label
        assert tuple(region.bbox) == bbox


# --- Credit-tier coverage: all 7 predefined regions (config.md) -------------
# All 7 predefined regions should match the config.md tier table, not just a
# spot check. Expected
# credits are hand-copied from config.md's "computed cost" table (not
# recomputed with estimate_credits itself), so this is a genuine independent
# check against the contract, not a tautology against the function under
# test.
EXPECTED_REGION_CREDITS = {
    "hormuz": 1,  # area 6.25
    "persian-gulf": 2,  # area 66.5
    "gulf-of-oman": 1,  # area 24.75
    "iraq-corridor": 2,  # area 35.75
    "syria-corridor": 2,  # area 35.75
    "eastern-med": 2,  # area 33.0
    "suez-canal": 1,  # area 8.64
}


def test_estimate_credits_matches_config_md_for_all_predefined_regions():
    assert set(EXPECTED_REGION_CREDITS) == set(PREDEFINED_REGIONS)

    for region_id, (_, bbox) in PREDEFINED_REGIONS.items():
        expected = EXPECTED_REGION_CREDITS[region_id]
        assert estimate_credits(bbox) == expected, (
            f"{region_id}: expected {expected} credits per config.md, "
            f"got {estimate_credits(bbox)}"
        )


# --- Credit-tier boundaries (config.md tier table) ---------------------------
# No predefined region's area lands exactly on a tier boundary, so an
# off-by-one (`<` vs `<=`) in estimate_credits would go uncaught by the
# region-based tests above. These synthetic bboxes pin the exact boundary
# values from config.md: <=25 -> 1, <=100 -> 2, <=400 -> 3, else 4.
#
# Each bbox is (0.0, 0.0, area, 1.0): area = (east - west) * (north - south)
# = area * 1.0 = area exactly (per estimate_credits's area formula in
# backend/config.py), so the boundary areas land on the exact float values
# below with no rounding.
@pytest.mark.parametrize(
    "area, expected_credits",
    [
        (25.0, 1),  # exactly on the 25 boundary -- still tier 1 (<=25)
        (25.001, 2),  # just over 25 -- tier 2
        (100.0, 2),  # exactly on the 100 boundary -- still tier 2 (<=100)
        (100.001, 3),  # just over 100 -- tier 3
        (400.0, 3),  # exactly on the 400 boundary -- still tier 3 (<=400)
        (400.001, 4),  # just over 400 -- tier 4
    ],
)
def test_estimate_credits_tier_boundaries(area, expected_credits):
    bbox = (0.0, 0.0, area, 1.0)
    assert estimate_credits(bbox) == expected_credits


# ===========================================================================
# Unit tests for the v1 config sections (issue #42) --
# marine, aisstream, integrity, server. The acceptance test
# (test_config_sections_acceptance.py) drives the full load_config() ->
# GET /api/config -> secret-gate scenario end to end; these target the
# lower-level collaborators (the bare _load_bundled_toml/_deep_merge/
# AppConfig.model_validate pipeline, independent of Secrets/create_app) and
# mirror the existing air missing-secret/disabled-layer units above for the
# new marine gate.
# ===========================================================================


def test_v1_sections_parse_from_bundled_toml_via_deep_merge_pipeline():
    """The four new sections parse with their config.md default values
    through the bare parsing pipeline (_load_bundled_toml + _deep_merge +
    AppConfig.model_validate) -- no Secrets, no HTTP, no env at all. This is
    a lower-level check than the acceptance test's `load_config()` (which also
    threads Secrets and drives `_check_required_secrets`): it isolates
    "does the bundled TOML parse into the right model shape" from "does the
    secret gate behave correctly".
    """
    bundled = _load_bundled_toml()
    merged = _deep_merge(_DEFAULTS, bundled)
    cfg = AppConfig.model_validate(merged)

    marine = cfg.layers["marine"]
    assert marine.enabled is True
    assert marine.cadence_s == 60
    assert marine.cadence_floor_s == 60
    assert marine.stale_multiplier == 2
    assert marine.deemphasize_after_s == 1800
    assert marine.drop_after_s == 7200
    assert marine.custom_bbox_cap_sq_deg == 40

    assert cfg.aisstream["ws_url"] == "wss://stream.aisstream.io/v0/stream"
    assert cfg.aisstream["reconnect_base_s"] == 2
    assert cfg.aisstream["reconnect_max_s"] == 60

    assert cfg.integrity["landmask_path"] == ""
    assert cfg.integrity["max_speed_kn_marine"] == 120
    assert cfg.integrity["max_speed_kn_air"] == 990

    assert cfg.server["sse_ping_s"] == 15
    assert cfg.server["static_dir"] == "frontend/dist"


def test_missing_aisstream_api_key_raises_named_error_when_marine_enabled(monkeypatch):
    # Empty-string, not delenv -- see the identical rationale on the OpenSky
    # missing-secret tests above (a local dev `.env` may carry a real
    # AISSTREAM_API_KEY; an explicit empty-string env var wins over the
    # dotenv fallback and is still falsy).
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "unit-id")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "unit-secret")
    monkeypatch.setenv("AISSTREAM_API_KEY", "")
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)

    with pytest.raises(MissingSecretError) as exc_info:
        load_config()

    assert exc_info.value.env_var == "AISSTREAM_API_KEY"
    assert exc_info.value.layer == "marine"
    assert "AISSTREAM_API_KEY" in str(exc_info.value)
    assert "marine" in str(exc_info.value)


def test_disabled_marine_layer_needs_no_secret(monkeypatch):
    # FR5: a disabled layer's secret is not required. Build the LayerCfg
    # directly rather than routing through the bundled TOML (which enables
    # marine), so this test targets `_check_required_secrets`'s "disabled
    # skips the check" branch for marine in isolation -- mirrors
    # test_disabled_air_layer_needs_no_secret above.
    from backend.config import _check_required_secrets

    monkeypatch.setenv("AISSTREAM_API_KEY", "")

    cfg = AppConfig(
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
    secrets = Secrets()

    # Must not raise -- the disabled layer's secret requirement is skipped.
    _check_required_secrets(cfg, secrets)
