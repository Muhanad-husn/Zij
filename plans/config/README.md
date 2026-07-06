# Feature: Configuration loader (`backend/config.py` + `backend/config.toml`)

Loads and merges configuration per [`config.md`](../../design/contracts/config.md) /
[`config-module.md`](../../design/specs/config-module.md): bundled TOML through
`pydantic-settings`, secrets from env only (NFR5), the predefined-region registry, and
the aviation credit-tier estimate (FR1 math). v0 populates only the `regions` +
`[opensky]`/`[overpass]`/`[layers.air]`/`[layers.land]` sections (STRUCTURE §7).

- **Slug:** config
- **Subproject:** v0 (slice 01) → v1 (slices 02–03)
- **New system?** no (v1 extends existing)
- **Project directory:** `backend`

## Slices

| # | Slice | Goal (one line) | Blocked-by | Status | PR |
|---|-------|-----------------|-----------|--------|----|
| 01 | [config-loader](01-config-loader.md) | `load_config()` merges precedence, exposes regions, keeps secrets separate | — | ✅ built (PR #24) | [#24](https://github.com/Muhanad-husn/Zij/pull/24) |
| 02 | [sections](02-sections.md) | add `[layers.marine]`/`[aisstream]`/`[integrity]`/`[server]` + full `/api/config` shape; marine-enabled secret gate | — (new) | ▹ planned (v1) | — |
| 03 | [precedence](03-precedence.md) | user-TOML < `ZIJ_` env < DB `config_override` merge + active-region restore | config/02, store/03 | ▹ planned (v1) | — |

## Out of scope (whole feature)

- The marine adapter / integrity module / SSE server that *consume* these knobs — their own features.
- Writing the `active_region` override (the scheduler does that on region switch, scheduler/04);
  the `config_presets` override read/write plumbing (store/03) — consumed by slice 03, not built here.
- Custom-bbox *activation* endpoint wiring (api-core/02); the credit-tier helper already landed in v0.
