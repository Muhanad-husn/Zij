# Slice 04: Caveats endpoint + raw-feature + presets (P1 designed now)

- **Feature:** api-core
- **Slice slug:** caveats-raw-presets
- **Issue:** #56
- **Branch:** feat/api-core/04-caveats-raw-presets
- **Project directory:** `backend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

Three remaining endpoints. **`GET /api/layers/{domain}/caveats`** (P0, FR9) returns the static
`integrity.CAVEATS[domain]` bullets plus `active_flags` counts computed from the current registry
snapshot (e.g. how many features currently carry `spoof_suspect_on_land`). **`GET
/api/features/{domain}/{source_id}/raw`** (P1, designed now) returns the untouched upstream
`raw_payload` from the live registry, `404 not_found` if the feature has rotated out. **Presets**
(P1, designed now, UI ships v2): `GET /api/presets`, `POST /api/presets {name, bbox}` (`201`;
`409 conflict` on a duplicate name), `DELETE /api/presets/{id}` (`204`) — persisted via
`store` `config_presets`.

## INVEST check

- **Independent:** caveats read `integrity.CAVEATS` + the registry; presets delegate to `store`.
- **Valuable:** FR9 caveat panel data (P0) + the FR11 raw-inspection/presets contract (P1, frozen now).
- **Small:** three thin read/CRUD routes over already-built integrity + store surfaces.
- **Testable:** httpx asserting caveat text + counts, raw payload passthrough/404, preset CRUD + 409.

## Acceptance criterion (outer loop — the failing test)

```gherkin
Given a registry whose marine snapshot has 3 spoof-suspect features
When  GET /api/layers/marine/caveats is called
Then  it returns the verbatim marine caveat bullets and active_flags.spoof_suspect_on_land == 3
When  GET /api/features/air/{id}/raw is called for a feature in the current snapshot
Then  it returns that feature's untouched raw_payload; a rotated-out id returns 404 not_found
When  POST /api/presets {name,bbox} is called, then again with the same name
Then  the first returns 201 and the duplicate returns 409 conflict; DELETE returns 204
```

- **Boundary:** the three routes over httpx; integrity CAVEATS + registry + store injected.
- **test type:** pytest-asyncio integration; **file:** `backend/tests/test_api.py`.

## Inner loop — initial unit test list

- [ ] Caveats: verbatim per-domain bullets + `active_flags` counts from the current snapshot.
- [ ] Raw: returns `{domain, source_id, source, raw_payload}` for a live feature; `404` once rotated out.
- [ ] Presets: list/create/delete round-trip via `config_presets`; `409` on duplicate name; `204` on delete.
- [ ] `raw_payload` reaches the raw endpoint but never rides `snapshot`/`caveats` responses.

## Out of scope (deferred)

- The caveat-panel / preset / raw-popup **UI** (frontend/05 caveats; presets+raw UI ship v2 per FR11/FR12).
- Integrity flag computation (integrity/01) and CAVEATS text (integrity/02) — consumed, not built here.

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner units covered; `uv run pytest`, `uv run ruff` green; refactor on green.
- [ ] Evidence: pytest transcript (caveat counts + raw 404 + preset 409/204). CI green; PR via `safe-pr`.

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: integrity/02, store/03, api-core/01.
  Note: caveats endpoint is P0; raw-feature + presets endpoints are P1 (contract frozen now, UI v2).
