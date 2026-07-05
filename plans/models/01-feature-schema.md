# Slice 01: Feature schema and enums validate per the contract

- **Feature:** models
- **Slice slug:** feature-schema
- **Issue:** #9
- **Branch:** feat/models/01-feature-schema
- **Project directory:** `.`
- **Status:** ◐ in-review (PR [#22](https://github.com/Muhanad-husn/Zij/pull/22))
- **Walking skeleton?** no

> **Zij roles (DEC-1):** the **test-author** transcribes the Acceptance criterion below into the **locked outer acceptance test** and commits it **red** before any implementation (via `@pytest.mark.xfail(strict=True)`, DEC-33); the **implementer** then drives the inner unit list to green and **may not edit the outer test or `design/` specs**. On green the strict-xfail flips the suite red — the **test-author** removes the marker to land the final green commit. If the locked test looks wrong mid-build, raise a `spec-drift` issue — never edit it to force green.

## Goal — the minimum testable behaviour

`backend.models` defines `Feature`, `LayerSnapshot`, `LayerSnapshotMeta` and the enums
(`Domain`, `GeometryType`, `FeatureStatus`, `IntegrityFlag`, `LayerStatus`) exactly as
[`feature-schema.md`](../../design/contracts/feature-schema.md) specifies, so every
downstream module has one validated vocabulary.

## INVEST check

- **Independent:** depends only on stdlib + pydantic; blocks config, adapters, api.
- **Valuable:** the single shared contract; every wire body and adapter return is one of these.
- **Small:** one module, ~200 lines, mechanical transcription of a written contract.
- **Testable:** field constraints, nullability, and `raw_payload` exclusion are all assertable.

## Acceptance criterion (outer loop — the failing integration test)

```gherkin
Given the backend.models module
When  a Feature is built from the air wire example in feature-schema.md and dumped with model_dump()/model_dump_json()
Then  it validates (UTC-aware datetimes, lat in [-90,90], lon in [-180,180], extra="forbid")
And   raw_payload is excluded from the dumped output
And   a LayerSnapshot wrapping that Feature round-trips through model_validate() unchanged
```

- **Boundary / endpoint:** the public model layer `backend.models` (an internal boundary — this is a schema module with no endpoint; the API slices exercise it over HTTP later).
- **e2e test type:** integration test constructing + serializing the models (no FastAPI route yet).
- **e2e test file (planned):** `backend/tests/test_models_acceptance.py`

## Inner loop — initial unit test list

- [ ] `Domain`/`GeometryType`/`FeatureStatus`/`IntegrityFlag`/`LayerStatus` have exactly the contract's members and string values.
- [ ] `Feature` rejects `lat=91`/`lon=181` and rejects unknown fields (`extra="forbid"`).
- [ ] Naive (tz-unaware) `timestamp_fetched` is rejected / coerced per the UTC rule; aware UTC accepted.
- [ ] `raw_payload` is populated in-memory but absent from `model_dump()` and `model_dump_json()`.
- [ ] Air nullability: `timestamp_source=None` ⇒ `position_age_s=None` is representable and valid.
- [ ] `LayerSnapshot`/`LayerSnapshotMeta` validate and round-trip; `stale_after_s` carries as given.

## Out of scope (deferred)

- Setting `integrity_flags` (v1 `integrity.py`); the field/enum exist but stay empty in v0.
- Any I/O, persistence, or HTTP — pure schema only.

## Definition of done

- [ ] Outer acceptance test authored by **test-author**, committed **RED before any implementation** (DEC-1; strict-xfail per DEC-33).
- [ ] Acceptance test seen to fail for the right reason, now GREEN (implementer drove inner cycles; outer test unchanged; marker removed on green).
- [ ] All seeded unit behaviours covered; `uv run pytest` green; `uv run ruff check` clean.
- [ ] Refactor pass complete on green.
- [ ] Slice's tests run in CI (`tdd-ci`); evidence collected; PR opened into `main` (`safe-pr`).

## Status / progress log

- 2026-07-05 planned (sprint v0).
- 2026-07-05 built via `/sprint-start`: outer test red (`99619f6`, strict-xfail) → implementer greened `backend/models.py` → marker removed on green (`b3f332f`). Two-stage review: stage-1 spec-compliance PASS; stage-2 found aware-non-UTC timestamps mis-serialized (not `Z`), fixed (`fa38395`) + regression test (`00af112`). Suite 16 green, ruff clean. PR #22 prepared into `main` (awaiting founder merge — Checkpoint).
