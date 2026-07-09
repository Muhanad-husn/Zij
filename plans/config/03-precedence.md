# Slice 03: Config precedence chain + active-region persistence

- **Feature:** config
- **Slice slug:** precedence
- **Issue:** #46
- **Branch:** feat/config/03-precedence
- **Project directory:** `backend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

Implement the full precedence chain (ADR-6 / config.md §Precedence), lowest → highest: code
defaults < bundled `config.toml` < user `config.toml` (at `platformdirs.user_config_dir("zij")/
config.toml`, path override `ZIJ_CONFIG_PATH`) < `ZIJ_`-prefixed env tunables < DB
`config_presets(kind='config_override')` rows (applied at read time). Secrets remain env-only,
never sourced from any TOML (NFR5). The persisted last active region is a `config_override` row
(`name='active_region'`, `payload_json={"region_id":...}`) read at startup to restore the last
region, falling back to the configured default when absent or invalid.

## INVEST check

- **Independent:** builds on slice 02's sections; reads DB overrides via `store` (config_presets, store/03).
- **Valuable:** operator overrides without editing the bundle (FR11) + last-region restore (ARCHITECTURE §4.1).
- **Small:** the ordered merge, the `ZIJ_CONFIG_PATH` resolution, the active-region read + fallback.
- **Testable:** pytest layering fake TOMLs, env vars, and an in-memory DB override, asserting who wins.

## Acceptance criterion (outer loop — the failing test)

```gherkin
Given a bundled default, a user config.toml, a ZIJ_ env var, and a DB config_override for one key
When  load_config() merges them
Then  the DB override wins over env, which wins over the user file, which wins over the bundle
And   a persisted active_region config_override is restored as the active region
And   when no active_region override exists, the configured default region is used
And   no secret is ever read from any TOML (env only)
```

- **Boundary:** `load_config()` with layered fake TOMLs + env + an injected `store` override reader.
- **test type:** pytest; **file:** `backend/tests/test_config.py`.

## Inner loop — initial unit test list

- [ ] Each precedence layer overrides the one below it (bundle < user < env < DB override).
- [ ] `ZIJ_CONFIG_PATH` is honored for the user-TOML location; absent → platformdirs default.
- [ ] `active_region` override restored at load; absent/invalid → default region fallback.
- [ ] Secrets never come from a TOML layer (env/.env only), even if a TOML sets a secret-shaped key.

## Out of scope (deferred)

- Writing the `active_region` override (the scheduler does that on region switch, scheduler/04).
- The `config_presets` table + override read/write plumbing (store/03) — consumed here.

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner units covered; `uv run pytest`, `uv run ruff` green; refactor on green.
- [ ] Evidence: pytest transcript (layer-precedence + active-region restore). CI green; PR via `safe-pr`.

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: config/02, store/03.
- 2026-07-09 built ✅ — outer test red (`e8e4cd9`) → impl → review fix (`active_region_id` excluded from `/api/config`) → regression-locked. 165 tests green, ruff clean. Two-stage review PASS. PR [#76](https://github.com/Muhanad-husn/Zij/pull/76) prepared into `main` (Closes #46).
