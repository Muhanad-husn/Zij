# Slice 02: v1 config sections — marine, aisstream, integrity, server

- **Feature:** config
- **Slice slug:** sections
- **Issue:** #42
- **Branch:** feat/config/02-sections
- **Project directory:** `backend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

Extend bundled `config.toml` and the `AppConfig` models with the v1 sections, values verbatim
from config.md: `[layers.marine]` (enabled, cadence_s=60, cadence_floor_s=60, stale_multiplier=2,
deemphasize_after_s=1800, drop_after_s=7200, custom_bbox_cap_sq_deg=40), `[aisstream]`
(ws_url, reconnect_base_s=2, reconnect_max_s=60), `[integrity]` (landmask_path="",
max_speed_kn_marine=120, max_speed_kn_air=990), and `[server]` (sse_ping_s=15, static_dir).
`GET /api/config`'s `layers` object expands to the full air/marine/land shape in api.md (marine
carries deemphasize_after_s + drop_after_s; land carries simplify_tolerance_deg +
max_rendered_features) and still returns no secrets (NFR5). The `AISSTREAM_API_KEY` secret is
required (fail-fast, named error) **only when the marine layer is enabled** — a disabled layer
needs no secret (FR5).

## INVEST check

- **Independent:** extends v0 `config.py`/`config.toml`; no scheduler/store/API dependency.
- **Valuable:** unblocks the marine, aisstream, integrity and SSE-server slices that read these knobs.
- **Small:** four TOML sections + matching model fields + the /api/config shape + the secret gate.
- **Testable:** pytest against the bundled TOML asserting parsed defaults + the endpoint shape + secret gating.

## Acceptance criterion (outer loop — the failing test)

```gherkin
Given the bundled config.toml with the v1 sections
When  load_config() runs
Then  the marine/aisstream/integrity/server sections load with their config.md defaults
And   GET /api/config returns the full air/marine/land layers shape and leaks no secrets
When  the marine layer is enabled and AISSTREAM_API_KEY is unset
Then  startup fails fast with a named error
When  the marine layer is disabled and AISSTREAM_API_KEY is unset
Then  startup succeeds (disabled layers need no secret)
```

- **Boundary:** `load_config()` + `GET /api/config` against the bundled TOML and env.
- **test type:** pytest; **file:** `backend/tests/test_config.py` (+ `test_api.py` for the endpoint shape).

## Inner loop — initial unit test list

- [ ] Each new section parses with its config.md default values.
- [ ] `/api/config` `layers` matches api.md for all three domains (marine drop/deemphasize; land simplify/max features).
- [ ] Neither the OpenSky nor aisstream secret appears in the `AppConfig` dump.
- [ ] Marine-enabled + missing `AISSTREAM_API_KEY` → fail-fast named error; marine-disabled → no error.

## Out of scope (deferred)

- User-TOML / `ZIJ_` env tunables / DB `config_override` precedence + active-region restore (slice 03).
- The marine adapter / integrity module that consume these knobs (their own features).

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner units covered; `uv run pytest`, `uv run ruff` green; refactor on green.
- [ ] Evidence: pytest transcript (section defaults + endpoint shape + secret gate). CI green; PR via `safe-pr`.

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: none new (extends v0 config).
- 2026-07-09 PR #69 prepared into `main` (commits: red `cca5f25` → green `2396fa7` → evidence `a458bd5`).
  Outer acceptance test green; 121 passed hermetically; ruff clean. Two-stage review PASS (ship).
  Follow-ups (non-blocking): file a `spec-drift` on api.md's `/api/config` top-level
  `stale_multiplier`/`custom_bbox_caps` example; consider a "no module-scope `backend.main`
  import in tests" convention check. Awaiting founder merge approval.
