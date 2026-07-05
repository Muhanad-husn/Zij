"""Locked outer acceptance test for config slice 01 (issue #10): config loader.

Given a bundled config.toml with the 7 predefined regions and
      [opensky]/[overpass]/[layers.air]/[layers.land] sections
And   env vars OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET are set
When  load_config() is called
Then  AppConfig.regions contains "hormuz" with bbox [55.0, 25.0, 57.5, 27.5]
And   the aviation credit estimate for the Hormuz bbox is 1 (per the config.md
      tier table)
And   Secrets carries the two OpenSky values
And   dumping AppConfig to JSON contains neither the client id nor the secret
      (NFR5)

This is the behavioral contract (DEC-1), transcribed from
plans/config/01-config-loader.md and design/contracts/config.md (predefined
regions table §"Predefined regions", credit tier table) and
design/specs/config-module.md (`load_config()`/`AppConfig`/`Secrets`/
`estimate_credits` shapes). `load_config()` takes no arguments (config-module.md
"Public interface") -- it reads the bundled `backend/config.toml` the loader
ships with, so this test exercises the real production artifact rather than an
injected fixture file; the only "Given" this test controls directly is the env.

Marine/aisstream/integrity sections and the full `validate_bbox` activation
path are explicitly out of scope for this slice (plans/config/01-config-loader.md
"Out of scope"), so this test does not require AISSTREAM_API_KEY/
AISHUB_USERNAME to be set even though those layers appear (disabled or absent)
in the full config.md contract.

It is authored and committed red by the test-author before any implementation
exists, guarded by a strict xfail (DEC-33). The implementer will make it
genuinely pass; the xfail marker is removed only then, to finalize the
contract.
"""

import pytest

HORMUZ_BBOX = (55.0, 25.0, 57.5, 27.5)

ALL_PREDEFINED_REGION_IDS = (
    "hormuz",
    "persian-gulf",
    "gulf-of-oman",
    "iraq-corridor",
    "syria-corridor",
    "eastern-med",
    "suez-canal",
)


@pytest.mark.xfail(
    reason="backend.config.load_config not yet implemented", strict=True
)
def test_load_config_returns_regions_credit_tier_and_isolated_secrets(monkeypatch):
    # --- Given: env vars carrying the OpenSky secret pair are set (NFR5: env
    # only) ---
    client_id = "test-opensky-client-id-9f3c"
    client_secret = "test-opensky-client-secret-7e21"
    monkeypatch.setenv("OPENSKY_CLIENT_ID", client_id)
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", client_secret)
    # Layers this slice does not enable/cover must not force these to be set.
    monkeypatch.delenv("AISSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("AISHUB_USERNAME", raising=False)
    # Don't let a stray operator user-config override path leak into this test
    # (user-TOML layering is out of scope for this slice).
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)

    from backend.config import estimate_credits, load_config

    # --- When: load_config() is called ---
    cfg, secrets = load_config()

    # --- Then: AppConfig.regions contains "hormuz" with the contract bbox ---
    regions_by_id = {region.id: region for region in cfg.regions}
    assert "hormuz" in regions_by_id
    hormuz = regions_by_id["hormuz"]
    assert tuple(hormuz.bbox) == HORMUZ_BBOX

    # The bundled config.toml carries all 7 predefined regions (config.md).
    assert len(cfg.regions) == 7
    for expected_id in ALL_PREDEFINED_REGION_IDS:
        assert expected_id in regions_by_id

    # The bundled sections this slice covers are present.
    assert cfg.opensky
    assert cfg.overpass
    assert "air" in cfg.layers
    assert "land" in cfg.layers

    # --- And: the aviation credit estimate for the Hormuz bbox is 1 (tier
    # table: area 6.25 sq deg <= 25 -> 1 credit) ---
    assert estimate_credits(HORMUZ_BBOX) == 1

    # Prove the estimate against the tier table generally, not just the
    # Hormuz case, using two more predefined regions with known costs
    # (config.md): persian-gulf (66.5 sq deg -> 2) and eastern-med
    # (33.0 sq deg -> 2).
    assert estimate_credits((47.5, 23.5, 57.0, 30.5)) == 2  # persian-gulf
    assert estimate_credits((31.0, 31.0, 36.5, 37.0)) == 2  # eastern-med

    # --- And: Secrets carries the two OpenSky values, read from env only ---
    assert secrets.opensky_client_id == client_id
    assert secrets.opensky_client_secret == client_secret

    # --- And: dumping AppConfig to JSON contains neither the client id nor
    # the secret (NFR5) -- secrets must never leak into the config object
    # that GET /api/config eventually serializes. ---
    dumped_json = cfg.model_dump_json()
    assert client_id not in dumped_json
    assert client_secret not in dumped_json
