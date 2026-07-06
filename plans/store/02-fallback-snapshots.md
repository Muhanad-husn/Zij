# Slice 02: fallback_snapshots — one restart-resilience snapshot per mobile layer

- **Feature:** store
- **Slice slug:** fallback-snapshots
- **Issue:** #40
- **Branch:** feat/store/02-fallback-snapshots
- **Project directory:** `backend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

Extend `backend/schema.sql` (idempotent `CREATE TABLE IF NOT EXISTS`) with the
`fallback_snapshots` table (`layer` TEXT PRIMARY KEY CHECK(layer IN ('air','marine')),
`region_id`, `snapshot_json`, `source_ts`, `fetched_at`) and add `put_fallback(snap)` /
`get_fallback(layer) -> LayerSnapshot | None`. `put_fallback` upserts
`ON CONFLICT(layer) DO UPDATE`, so **exactly one row per layer** is retained (FR8) — enforced
by the PK, not cleanup code. Persistence is `LayerSnapshot.model_dump_json()` with
`raw_payload` excluded (feature-schema.md `exclude=True`). `fetched_at` is the true-age basis
the cold-start `cached-fallback` badge reads. Land is **not** stored here — it lives in
`land_cache` (storage.md, NFR2).

## INVEST check

- **Independent:** extends the v0 `store.py`/`schema.sql`; needs only `models` + stdlib `sqlite3`.
- **Valuable:** the FR8 restart-resilience path — a cold start shows the last good air/marine picture immediately.
- **Small:** one table, two methods, upsert semantics; no policy.
- **Testable:** a temp DB file makes the round-trip fully deterministic.

## Acceptance criterion (outer loop — the failing integration test)

```gherkin
Given a fresh SQLite database initialised from backend/schema.sql
When  put_fallback(<LayerSnapshot air>) is called then get_fallback("air")
Then  it returns an equal LayerSnapshot with raw_payload absent and fetched_at preserved (UTC)
And   a second put_fallback for air replaces the row (still exactly one air row)
And   get_fallback("marine") returns None when no marine row exists
And   inserting layer='land' is rejected by the CHECK constraint
```

- **Boundary:** `backend.store` public functions (`init_schema`, `put_fallback`, `get_fallback`).
- **e2e test type:** integration test against a temp SQLite file.
- **e2e test file (planned):** `backend/tests/test_store_acceptance.py`

## Inner loop — initial unit test list

- [ ] `init_schema` creates `fallback_snapshots`; calling it twice is idempotent.
- [ ] `put_fallback` then `get_fallback` returns identical features/meta; a second put for the same layer replaces (one row/layer).
- [ ] Persisted JSON excludes `raw_payload` (feature-schema.md `exclude=True`).
- [ ] `region_id` + `fetched_at` round-trip UTC-aware (NFR6), not naive/strings.
- [ ] The `CHECK (layer IN ('air','marine'))` rejects `'land'`; unknown layer → `None`.

## Out of scope (deferred)

- `config_presets` table (slice 03).
- The cold-start repopulation *policy* (region-matched fallback load) — scheduler slice 04 owns it.

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner units covered; `uv run pytest` green; `uv run ruff check` clean; refactor on green.
- [ ] CI (`tdd-ci`); evidence; PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: none new (extends v0 store).
