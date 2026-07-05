# Feature: Configuration loader (`backend/config.py` + `backend/config.toml`)

Loads and merges configuration per [`config.md`](../../design/contracts/config.md) /
[`config-module.md`](../../design/specs/config-module.md): bundled TOML through
`pydantic-settings`, secrets from env only (NFR5), the predefined-region registry, and
the aviation credit-tier estimate (FR1 math). v0 populates only the `regions` +
`[opensky]`/`[overpass]`/`[layers.air]`/`[layers.land]` sections (STRUCTURE §7).

- **Slug:** config
- **Subproject:** v0
- **New system?** yes
- **Project directory:** `.`

## Slices

| # | Slice | Goal (one line) | Status | PR |
|---|-------|-----------------|--------|----|
| 01 | [config-loader](01-config-loader.md) | `load_config()` merges precedence, exposes regions, keeps secrets separate | ✅ built (PR #24) | [#24](https://github.com/Muhanad-husn/Zij/pull/24) |

## Out of scope (whole feature)

- `config_presets`/`config_override` runtime overrides + user-TOML/`ZIJ_` env layers (v1;
  v0 needs only code-defaults + bundled TOML + env secrets).
- Marine/aisstream/integrity config sections and the full 7-region *activation* flow (v1);
  the region table is defined, but v0 hardcodes Hormuz at the API layer.
- `validate_bbox` custom-bbox activation endpoint wiring (FR1 UI is v1); the credit-tier
  helper itself lands here because the OpenSky slice reuses it.
