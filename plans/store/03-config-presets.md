# Slice 03: config_presets — region presets + config overrides (active region)

- **Feature:** store
- **Slice slug:** config-presets
- **Issue:** #41
- **Branch:** feat/store/03-config-presets
- **Project directory:** `backend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

Extend `backend/schema.sql` (idempotent) with the `config_presets` table (`id` AUTOINCREMENT,
`kind` CHECK IN ('region_preset','config_override'), `name`, `payload_json`, `created_at`,
`updated_at`, `UNIQUE(kind,name)`) and add: `list_presets()`, `add_preset(name, bbox, label)`
(raises a conflict error on the `UNIQUE(kind,name)` clash — the api.md `409`), `delete_preset(id)`,
and config-override get/put. The persisted **last active region** is a `config_override` row
(`name='active_region'`, `payload_json={"region_id": ...}`) written on region switch and read at
startup to restore the last region (config.md §Precedence, ARCHITECTURE §4.1). Timestamps are
passed in / injectable (UTC), following the v0 store's stamping — no ambient clock.

## INVEST check

- **Independent:** extends the v0 `store.py`/`schema.sql`; needs only stdlib `sqlite3`.
- **Valuable:** backs FR11 presets and the highest-precedence config layer (persisted active region), so startup restores the operator's last region.
- **Small:** one table, four methods, `UNIQUE` conflict handling.
- **Testable:** a temp DB file makes CRUD + conflict fully deterministic.

## Acceptance criterion (outer loop — the failing integration test)

```gherkin
Given a fresh SQLite database initialised from backend/schema.sql
When  add_preset("My Box", bbox=[52,26,55,28], label="My Box") is called then list_presets()
Then  the returned list contains that region_preset with its bbox and label
And   adding a second preset with the same (kind, name) raises the conflict error (409)
And   delete_preset(id) removes it from list_presets()
And   put then get of the active_region config_override round-trips {"region_id": "gulf-of-oman"}
```

- **Boundary:** `backend.store` public functions (`init_schema`, `list_presets`, `add_preset`, `delete_preset`, config-override get/put).
- **e2e test type:** integration test against a temp SQLite file.
- **e2e test file (planned):** `backend/tests/test_store_acceptance.py`

## Inner loop — initial unit test list

- [ ] `init_schema` creates `config_presets`; idempotent on re-run.
- [ ] `add_preset` → `list_presets` returns it; `region_preset` payload holds `{bbox,label}`.
- [ ] A duplicate `(kind, name)` raises the conflict error (maps to api.md `409`).
- [ ] `delete_preset(id)` removes the row; deleting a missing id is a defined no-op/error.
- [ ] `config_override` upsert then read of `active_region` returns `{region_id}`; `created_at`/`updated_at` stamped UTC.

## Out of scope (deferred)

- `fallback_snapshots` table (slice 02).
- Applying `config_override` rows in the precedence chain — `config` slice 03 owns that read-time merge.
- The presets HTTP surface (`/api/presets`) — `api-core` slice 04 owns it.

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner units covered; `uv run pytest` green; `uv run ruff check` clean; refactor on green.
- [ ] CI (`tdd-ci`); evidence; PR into `main` (`safe-pr`).

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: none new (extends v0 store).
