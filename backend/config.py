"""Configuration loader (contract: design/contracts/config.md; spec:
design/specs/config-module.md).

Merges the full ADR-6 precedence chain, lowest -> highest: code defaults <
bundled `config.toml` < user `config.toml` (`ZIJ_CONFIG_PATH`, else
`platformdirs.user_config_dir("zij")/config.toml`) < `ZIJ_`-prefixed env
tunables < an optional caller-supplied `overrides` dict mirroring
`Store.get_config_overrides()`'s `{name: payload}` shape (config.md
"Precedence"). The reserved `overrides["active_region"]` entry
(`{"region_id": ...}`) is not merged into the config dict -- it resolves
`AppConfig.active_region_id`, falling back to `regions[0].id` when absent or
naming an unknown region (ARCHITECTURE §4.1).

Secrets are loaded separately, from env/`.env` only (NFR5), and are never
folded into `AppConfig` -- so they can never leak into `GET /api/config`'s
serialized body (api.md), even when a TOML layer happens to set a
secret-shaped key (e.g. `[opensky] client_id = ...`).
"""

from __future__ import annotations

import os
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import platformdirs
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# config.md "Precedence" #5 -- the reserved override name for the persisted
# last-active-region row; never deep-merged into the AppConfig-shaped dict.
_ACTIVE_REGION_OVERRIDE_KEY = "active_region"

# The env var that names the user-TOML path (layer 3) is a loader control
# knob, not a `ZIJ_`-prefixed tunable (layer 4) -- excluded from env-tunable
# parsing below even though it shares the `ZIJ_` prefix.
_CONFIG_PATH_ENV_VAR = "ZIJ_CONFIG_PATH"
_ENV_TUNABLE_PREFIX = "ZIJ_"
_ENV_TUNABLE_DELIMITER = "__"

_BUNDLED_CONFIG_PATH = Path(__file__).with_name("config.toml")

# Code defaults (ADR-6 precedence layer 1). Only the air/land layers,
# opensky, and overpass get non-trivial code defaults here; marine and the
# aisstream/integrity/server sections default to an empty dict/absent layer
# at this precedence layer -- their real values come from the bundled
# `config.toml` (layer 2), which every slice-02 assertion reads from.
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
    # Resolved separately from the reserved `overrides["active_region"]`
    # entry after the merge/validate above -- never itself part of the
    # deep-merged config dict (config.md "Precedence" #5; ARCHITECTURE
    # §4.1). The default here is a placeholder always replaced by
    # `load_config` before the value is returned.
    active_region_id: str = ""


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


def _resolve_user_config_path() -> Path:
    """`ZIJ_CONFIG_PATH` if set, else `platformdirs.user_config_dir("zij")/
    config.toml` (config.md "Precedence" #3)."""
    override = os.environ.get(_CONFIG_PATH_ENV_VAR)
    if override:
        return Path(override)
    return Path(platformdirs.user_config_dir("zij")) / "config.toml"


def _load_user_toml() -> dict[str, Any]:
    """Parse the user `config.toml` (layer 3). A missing file is not an
    error -- that layer simply contributes nothing (config-module.md)."""
    path = _resolve_user_config_path()
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _load_env_tunables() -> dict[str, Any]:
    """Parse `ZIJ_`-prefixed, `__`-nested-delimited env vars into a nested
    dict (layer 4), e.g. `ZIJ_LAYERS__AIR__CADENCE_S` ->
    `{"layers": {"air": {"cadence_s": "<value>"}}}` (config.md "Precedence"
    #4, pydantic-settings nested-delimiter convention). Values are left as
    raw strings; `AppConfig.model_validate` coerces them to the right type
    (int/float/bool) during validation, same as any other layer.
    `ZIJ_CONFIG_PATH` itself is a loader control knob, not a tunable, and is
    excluded."""
    result: dict[str, Any] = {}
    for env_name, raw_value in os.environ.items():
        if env_name == _CONFIG_PATH_ENV_VAR:
            continue
        if not env_name.startswith(_ENV_TUNABLE_PREFIX):
            continue
        remainder = env_name[len(_ENV_TUNABLE_PREFIX) :]
        parts = [
            part.lower() for part in remainder.split(_ENV_TUNABLE_DELIMITER) if part
        ]
        if not parts:
            continue
        node = result
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = raw_value
    return result


def _resolve_active_region_id(
    regions: list[RegionCfg], overrides: Mapping[str, Any] | None
) -> str:
    """Restore the persisted `active_region` override (config.md
    "Precedence" #5), falling back to the configured default (`regions[0]
    .id`) when the override is absent or names a region that isn't one of
    the predefined regions (ARCHITECTURE §4.1)."""
    default_id = regions[0].id if regions else ""
    if not overrides:
        return default_id
    active_region_override = overrides.get(_ACTIVE_REGION_OVERRIDE_KEY)
    if not isinstance(active_region_override, Mapping):
        return default_id
    region_id = active_region_override.get("region_id")
    if region_id in {region.id for region in regions}:
        return region_id
    return default_id


def _check_required_secrets(cfg: AppConfig, secrets: Secrets) -> None:
    """Fail fast (named error) when an enabled layer's required secret is
    missing. Air (OpenSky) and marine (aisstream) are gated here; aishub is
    still out of scope (no layer currently requires it)."""
    air = cfg.layers.get("air")
    if air is not None and air.enabled:
        if not secrets.opensky_client_id:
            raise MissingSecretError("OPENSKY_CLIENT_ID", "air")
        if not secrets.opensky_client_secret:
            raise MissingSecretError("OPENSKY_CLIENT_SECRET", "air")

    marine = cfg.layers.get("marine")
    if marine is not None and marine.enabled:
        if not secrets.aisstream_api_key:
            raise MissingSecretError("AISSTREAM_API_KEY", "marine")


def load_config(
    *, overrides: Mapping[str, Any] | None = None
) -> tuple[AppConfig, Secrets]:
    """Merge the full ADR-6 precedence chain -- code defaults < bundled
    `config.toml` < user `config.toml` < `ZIJ_`-prefixed env tunables <
    `overrides` (an optional injected `{name: payload}` dict mirroring
    `Store.get_config_overrides()`, highest precedence) -- into an
    `AppConfig`, and load `Secrets` from env/`.env` only (NFR5). Fails fast
    with `MissingSecretError` if an enabled layer's required secret is
    absent (config.md).

    `overrides` defaults to `None`, matching every pre-existing no-arg call
    site exactly (no DB layer, no active-region restore beyond the
    configured default). The reserved `overrides["active_region"]` entry is
    never deep-merged into the config dict -- it resolves
    `AppConfig.active_region_id` separately (config.md "Precedence" #5).
    """
    merged = _deep_merge(_DEFAULTS, _load_bundled_toml())
    merged = _deep_merge(merged, _load_user_toml())
    merged = _deep_merge(merged, _load_env_tunables())
    if overrides:
        db_layer = {
            key: value
            for key, value in overrides.items()
            if key != _ACTIVE_REGION_OVERRIDE_KEY
        }
        merged = _deep_merge(merged, db_layer)

    cfg = AppConfig.model_validate(merged)
    active_region_id = _resolve_active_region_id(cfg.regions, overrides)
    cfg = cfg.model_copy(update={"active_region_id": active_region_id})

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
