# Feature: Recorded real-payload fixtures (`scripts/fetch_fixtures.py`)

v0's stated purpose is *validation with real data* (credit math, Overpass payload sizes,
render performance). That requires **real recorded upstream responses** committed to the
repo, against which the two walking-skeleton slices (OpenSky fetch, Overpass fetch) write
their locked outer tests. This feature is the dev-time capture tooling that produces them.

- **Slug:** fixtures
- **Subproject:** v0
- **New system?** yes (`scripts/`)
- **Project directory:** `.`

## Slices

| # | Slice | Goal (one line) | Status | PR |
|---|-------|-----------------|--------|----|
| 01 | [fixture-capture](01-fixture-capture.md) | A script captures + commits the two real Hormuz payloads | ☐ todo | — |

## Out of scope (whole feature)

- The adapters that parse these fixtures (own features).
- Marine/aisstream fixtures (v1).

## Notes

- **This is a chore/tooling slice, not a product behavior.** It lives under `scripts/`
  (dev-time only, never imported by `backend/` at runtime — STRUCTURE §3), so it uses a
  lightweight acceptance (the script runs and emits two well-formed fixtures) rather than
  the full DEC-1 product-endpoint ceremony. The tests-green gate still applies to its commit.
- **Founder runs it once** with valid `OPENSKY_CLIENT_ID`/`OPENSKY_CLIENT_SECRET` in `.env`
  (Overpass is public, no auth). The committed JSON is what CI and every other slice use —
  no slice depends on a live upstream.
- **Blocks:** `opensky-adapter/02-fetch` and `overpass-adapter/01-fetch`.
