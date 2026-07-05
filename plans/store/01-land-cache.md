# Slice 01: land_cache round-trips a region's cached land snapshot

- **Feature:** store
- **Slice slug:** land-cache
- **Issue:** #11
- **Branch:** feat/store/01-land-cache
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer test **red** (strict-xfail, DEC-33) before implementation; **implementer** drives inner cycles, may not edit the outer test or `design/`; **test-author** removes the marker on green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

`backend.store` creates the `land_cache` table from `schema.sql` (idempotent) and
round-trips one region's cache row: `put_land_cache(region_id, geojson, osm_base,
fetched_at, feature_count)` then `get_land_cache(region_id)` returns the same values, with
`osm_base` preserved as UTC-aware and `geojson` as a valid FeatureCollection.

## INVEST check

- **Independent:** needs only `models` + stdlib `sqlite3`; unblocks the API land path.
- **Valuable:** enables the <2 s warm-cache land load (FR4) and spares public Overpass mirrors during dev.
- **Small:** one table, three functions, no policy.
- **Testable:** a temp DB file makes the round-trip fully deterministic.

## Acceptance criterion (outer loop — the failing integration test)

```gherkin
Given a fresh SQLite database initialised from backend/schema.sql
When  put_land_cache("hormuz", <FeatureCollection>, osm_base=2026-07-04T00:00:00Z, fetched_at=<now>, feature_count=1234) is called
And   get_land_cache("hormuz") is then called
Then  it returns the stored row with the same feature_count and geojson
And   osm_base comes back as a UTC-aware datetime equal to 2026-07-04T00:00:00Z
And   get_land_cache("gulf-of-oman") returns None (no row)
```

- **Boundary / endpoint:** `backend.store` public functions (`init_schema`, `get_land_cache`, `put_land_cache`) — module boundary, exercised over HTTP later by the land snapshot endpoint.
- **e2e test type:** integration test against a temp SQLite file.
- **e2e test file (planned):** `backend/tests/test_store_acceptance.py`

## Inner loop — initial unit test list

- [ ] `init_schema` creates `land_cache`; calling it twice is idempotent (no error, no dup).
- [ ] `put_land_cache` then `get_land_cache` returns identical `geojson`/`feature_count`.
- [ ] `osm_base`/`fetched_at` persist and re-hydrate as UTC-aware datetimes (NFR6), not naive/strings.
- [ ] A second `put_land_cache` for the same `region_id` replaces the row (one cache row per region).
- [ ] `get_land_cache` for an unknown region returns `None`.

## Out of scope (deferred)

- `fallback_snapshots`, `config_presets` (v1).
- The freshness (serve-vs-refetch) decision — backend-api wiring owns it.

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1; strict-xfail DEC-33), seen red, now GREEN.
- [ ] Inner behaviours covered; `uv run pytest` green; `uv run ruff check` clean; refactor on green.
- [ ] CI (`tdd-ci`); evidence; PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-05 planned (sprint v0).
