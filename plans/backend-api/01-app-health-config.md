# Slice 01: FastAPI app serves health, config, and static frontend

- **Feature:** backend-api
- **Slice slug:** app-health-config
- **Issue:** #17
- **Branch:** feat/backend-api/01-app-health-config
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no (backend liveness; the frontend walking skeleton is frontend-map/01)

> **Zij roles (DEC-1):** **test-author** commits the outer test **red** (strict-xfail, DEC-33) before implementation; **implementer** drives inner cycles, may not edit the outer test or `design/`; **test-author** removes the marker on green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

`backend.main:app` is a FastAPI application exposing `GET /api/health` (`{"status":"ok",
"version":...,"uptime_s":...}`) and `GET /api/config` (the effective `AppConfig` as JSON —
regions + layers — **never** secrets), and mounts the built frontend as static files at `/`
with `/api/*` taking precedence.

## INVEST check

- **Independent:** needs `config` (+ `models`); mounts static without needing the adapters.
- **Valuable:** the app boots and proves config-over-HTTP + secret isolation; every other route hangs off this app.
- **Small:** app construction + two routes + a `StaticFiles` mount + the error envelope.
- **Testable:** FastAPI `TestClient` asserts status, bodies, and secret absence.

## Acceptance criterion (outer loop — the failing integration test)

```gherkin
Given the FastAPI app built with loaded config and secrets
When  GET /api/health is requested
Then  it returns 200 with status "ok", a version string, and a numeric uptime_s
And   GET /api/config returns 200 with the 7 regions and the air/land layer settings
And   the /api/config body contains neither OPENSKY_CLIENT_ID nor OPENSKY_CLIENT_SECRET (NFR5)
And   a request to an unknown /api/ path returns the api.md error envelope ({"error":{"code":...}})
```

- **Boundary / endpoint:** HTTP routes `GET /api/health`, `GET /api/config`, static `/` (real FastAPI endpoints via `TestClient`).
- **e2e test type:** integration test with `fastapi.testclient.TestClient`.
- **e2e test file (planned):** `backend/tests/test_api.py::test_health_and_config`

## Inner loop — initial unit test list

- [ ] `GET /api/health` → 200 with the three fields; `uptime_s` increases across two calls.
- [ ] `GET /api/config` → 200 with `regions` (7) and `layers.air`/`layers.land`.
- [ ] `/api/config` never includes any `Secrets` field (NFR5).
- [ ] Unknown `/api/*` path → the error envelope with the matching HTTP status.
- [ ] Static mount serves `index.html` at `/`; `/api/*` is matched before the static fallback.

## Out of scope (deferred)

- Data/refresh endpoints (slice 02); SSE, region activation, toggles, caveats (v1).

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1; strict-xfail DEC-33), seen red, now GREEN.
- [ ] Inner behaviours covered; `uv run pytest` green; `uv run ruff check` clean; refactor on green.
- [ ] CI (`tdd-ci`); evidence; PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-05 planned (sprint v0). Adds runtime deps `fastapi`, `uvicorn`. Blocked-by: config/01.
