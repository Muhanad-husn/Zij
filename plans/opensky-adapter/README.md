# Feature: OpenSky adapter (`backend/sources/opensky.py`)

The aviation `PollAdapter` (PRD §6.1, D5): OAuth2 client-credentials token management, a
bbox `/states/all` fetch parsed into `Feature` points, and credit accounting against the
4,000/day budget. Implements [`opensky.md`](../../design/specs/opensky.md) against the
[`adapter-interface.md`](../../design/contracts/adapter-interface.md) contract. Validating
the credit math with a real Hormuz payload is one of v0's three purposes.

- **Slug:** opensky-adapter
- **Subproject:** v0
- **New system?** yes (`backend/sources/`)
- **Project directory:** `.`

## Slices

Develop top to bottom.

| # | Slice | Goal (one line) | Status | PR |
|---|-------|-----------------|--------|----|
| 01 | [token-manager](01-token-manager.md) | Single-flight, proactively-refreshed OAuth2 token | ☑ merged | [#26](https://github.com/Muhanad-husn/Zij/pull/26) |
| 02 | [fetch-states](02-fetch-states.md) ⭐ | Parse the real Hormuz `/states/all` fixture → `LayerSnapshot(AIR)` + credit accounting | ☑ PR open | [#29](https://github.com/Muhanad-husn/Zij/pull/29) |

⭐ = walking skeleton (first real upstream data; validates credit math).

## Out of scope (whole feature)

- The scheduler / cadence / coalescing (v1); v0 calls `fetch` directly on manual refresh.
- Marine and land sources; integrity flags (land/marine v1, integrity v1).

## Depends on

`models`, `config` (both slices); `fixtures` (slice 02 needs the committed OpenSky fixture).
Also needs `backend/sources/base.py` (the ABCs, `Region`, error taxonomy) — introduced by
slice 01 as the first adapter to need it.
