"""Configuration loader (contract: design/contracts/config.md; spec:
design/specs/config-module.md).

Merges code defaults with the bundled `config.toml` (ADR-6 precedence layers
1-2). The user-TOML, `ZIJ_`-env-tunable, and `config_presets` (DB) precedence
layers, the full `ConfigService` (region presets + `validate_bbox`), and the
marine/aisstream/integrity sections are out of scope for this slice
(plans/config/01-config-loader.md "Out of scope") and land in later slices
once `store.py` exists.

Secrets are loaded separately, from env/`.env` only (NFR5), and are never
folded into `AppConfig` -- so they can never leak into `GET /api/config`'s
serialized body (api.md).
"""

from __future__ import annotations

import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

_BUNDLED_CONFIG_PATH = Path(__file__).with_name("config.toml")

# Code defaults (ADR-6 precedence layer 1). Only the sections this slice
# covers (the air/land layers, opensky, overpass) get non-trivial defaults;
# the remaining AppConfig sections (aisstream/integrity/server) default to an
# empty dict until a later slice populates them.
_DEFAULTS: dict[str, Any] = {
    "regions": [],
    "layers": {
        "air": {
            "enabled": True,
            "cadence_s": 600,
            "cadence_floor_s": 60,
            "stale_multiplier": 2,
            "custom_bbox_cap_sq_deg": 100,
        },
        "land": {
            "enabled": True,
            "cadence_s": 86400,
            "cadence_floor_s": 3600,
            "stale_multiplier": 2,
            "custom_bbox_cap_sq_deg": 40,
        },
    },
    "overpass": {},
    "opensky": {},
    "aisstream": {},
    "integrity": {},
    "server": {},
}


class Secrets(BaseSettings):
    """Secrets read from env/`.env` only (NFR5) -- never from any TOML, and
    never folded into `AppConfig`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    opensky_client_id: str | None = None
    opensky_client_secret: str | None = None
    aisstream_api_key: str | None = None
    aishub_username: str | None = None


class RegionCfg(BaseModel):
    id: str
    label: str
    bbox: tuple[float, float, float, float]


class LayerCfg(BaseModel):
    enabled: bool = True
    cadence_s: int
    cadence_floor_s: int
    stale_multiplier: int = 2
    custom_bbox_cap_sq_deg: float
    # Per-domain extras (config.md per-layer settings); optional because only
    # some layers carry them (air/marine deemphasize_after_s; marine
    # drop_after_s; land simplify_tolerance_deg/max_rendered_features).
    deemphasize_after_s: int | None = None
    drop_after_s: int | None = None
    simplify_tolerance_deg: float | None = None
    max_rendered_features: int | None = None


class AppConfig(BaseModel):
    regions: list[RegionCfg]
    layers: dict[str, LayerCfg]
    overpass: dict[str, Any]
    opensky: dict[str, Any]
    aisstream: dict[str, Any]
    integrity: dict[str, Any]
    server: dict[str, Any]


class MissingSecretError(RuntimeError):
    """Raised at startup when an enabled layer's required secret is absent
    from the environment (config.md "Startup fails fast"; config-module.md
    "Secrets -- separate object"). Disabled layers need no secret (FR5)."""

    def __init__(self, env_var: str, layer: str) -> None:
        self.env_var = env_var
        self.layer = layer
        super().__init__(
            f"missing required secret {env_var!r} for enabled layer {layer!r}"
        )


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `override` into `base` without mutating either
    input. Nested dicts are merged key-by-key so overriding e.g.
    `layers.air.cadence_s` does not wipe a sibling key like
    `layers.air.cadence_floor_s` (config-module.md "Merge is a deep-merge of
    nested tables"). Non-dict values (including lists, e.g. `regions`) are
    replaced wholesale.
    """
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _load_bundled_toml(path: Path = _BUNDLED_CONFIG_PATH) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _check_required_secrets(cfg: AppConfig, secrets: Secrets) -> None:
    """Fail fast (named error) when an enabled layer's required secret is
    missing. Only the air layer's secret (OpenSky) is in scope for this
    slice -- marine/aisstream/aishub are out of scope
    (plans/config/01-config-loader.md "Out of scope")."""
    air = cfg.layers.get("air")
    if air is not None and air.enabled:
        if not secrets.opensky_client_id:
            raise MissingSecretError("OPENSKY_CLIENT_ID", "air")
        if not secrets.opensky_client_secret:
            raise MissingSecretError("OPENSKY_CLIENT_SECRET", "air")


def load_config() -> tuple[AppConfig, Secrets]:
    """Merge code defaults with the bundled `config.toml` (ADR-6 precedence
    layers 1-2) into an `AppConfig`, and load `Secrets` from env/`.env` only
    (NFR5). Fails fast with `MissingSecretError` if an enabled layer's
    required secret is absent (config.md).
    """
    bundled = _load_bundled_toml()
    merged = _deep_merge(_DEFAULTS, bundled)
    cfg = AppConfig.model_validate(merged)
    secrets = Secrets()
    _check_required_secrets(cfg, secrets)
    return cfg, secrets


def estimate_credits(bbox: tuple[float, float, float, float]) -> int:
    """OpenSky aviation credit-tier estimate (config.md tier table): bbox
    area in square degrees `<=25 -> 1, <=100 -> 2, <=400 -> 3, else 4`.
    Reused by `sources/opensky.py` and `ConfigService.validate_bbox`
    (config-module.md) -- single source of truth for the tier table.
    """
    west, south, east, north = bbox
    area = (east - west) * (north - south)
    if area <= 25:
        return 1
    if area <= 100:
        return 2
    if area <= 400:
        return 3
    return 4


def effective_cadence_s(layer: LayerCfg) -> int:
    """FR6: the effective cadence never goes below the configured floor."""
    return max(layer.cadence_s, layer.cadence_floor_s)


def stale_after_s(layer: LayerCfg) -> int:
    """FR7: `stale_after_s = cadence_s * stale_multiplier`, independent per
    layer so changing one layer's cadence never affects another's."""
    return layer.cadence_s * layer.stale_multiplier
