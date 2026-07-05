# Slice 01: Config loads with correct precedence and keeps secrets separate

- **Feature:** config
- **Slice slug:** config-loader
- **Issue:** #10
- **Branch:** feat/config/01-config-loader
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no

> **Zij roles (DEC-1):** the **test-author** commits the outer acceptance test **red** (strict-xfail, DEC-33) before any implementation; the **implementer** drives inner cycles and may not edit the outer test or `design/` specs; the **test-author** removes the marker on green. Spec looks wrong mid-build ⇒ raise a `spec-drift` issue, never edit in place.

## Goal — the minimum testable behaviour

`backend.config.load_config()` returns `(AppConfig, Secrets)`: `AppConfig` carries the
seven predefined regions (correct bboxes) and the `[opensky]`/`[overpass]`/`[layers.*]`
sections from the bundled `config.toml`; `Secrets` carries the OpenSky credentials read
**only** from env/`.env`; secrets never appear in `AppConfig`. The aviation credit-tier
estimate (config.md tier table) is exposed for reuse by OpenSky/FR1.

## INVEST check

- **Independent:** needs only `models`; unblocks both adapters and the API.
- **Valuable:** every adapter and the `GET /api/config` endpoint read from here; the credit
  tier is one of v0's validation targets (§13.4).
- **Small:** one loader + one bundled TOML; deep-merge of a fixed set of tables.
- **Testable:** precedence, secret isolation, region table, and tier math all assertable.

## Acceptance criterion (outer loop — the failing integration test)

```gherkin
Given a bundled config.toml with the 7 predefined regions and [opensky]/[overpass]/[layers.air]/[layers.land] sections
And   env vars OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET are set
When  load_config() is called
Then  AppConfig.regions contains "hormuz" with bbox [55.0, 25.0, 57.5, 27.5]
And   the aviation credit estimate for the Hormuz bbox is 1 (per the config.md tier table)
And   Secrets carries the two OpenSky values
And   dumping AppConfig to JSON contains neither the client id nor the secret (NFR5)
```

- **Boundary / endpoint:** `backend.config.load_config()` (module boundary; surfaced over HTTP later by `GET /api/config`, backend-api slice 01).
- **e2e test type:** integration test with a temp bundled TOML + monkeypatched env.
- **e2e test file (planned):** `backend/tests/test_config_acceptance.py`

## Inner loop — initial unit test list

- [ ] Precedence: a value in bundled TOML overrides the code default for the same key.
- [ ] Deep-merge: overriding `layers.air.cadence_s` does not wipe `layers.air.cadence_floor_s`.
- [ ] `regions()` returns all 7 predefined regions with the config.md bboxes and labels.
- [ ] Credit tier: `estimate_credits` returns `≤25→1, ≤100→2, ≤400→3, else 4` for sampled bboxes (all 7 predefined match the config.md table).
- [ ] `Secrets` reads env only; a missing `OPENSKY_CLIENT_ID` while air is enabled fails fast with a named error (config-module.md).
- [ ] Secrets never serialize into `AppConfig`/`model_dump()`.
- [ ] `effective_cadence_s` applies the floor; `stale_after_s = cadence_s * stale_multiplier` per layer.

## Out of scope (deferred)

- User-TOML + `ZIJ_` env layers and `config_presets`/`config_override` DB overrides (v1).
- Marine/aisstream/integrity sections; the full `validate_bbox` activation path (v1 FR1 UI).

## Definition of done

- [ ] Outer acceptance test authored **RED before implementation** (DEC-1; strict-xfail DEC-33).
- [ ] Seen red for the right reason, now GREEN (outer test unchanged; marker removed on green).
- [ ] Inner behaviours covered; `uv run pytest` green; `uv run ruff check` clean; refactor on green.
- [ ] CI (`tdd-ci`); evidence; PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-05 planned (sprint v0). Adds runtime deps `pydantic`, `pydantic-settings`, `platformdirs` if not already added by an earlier-landed slice.
