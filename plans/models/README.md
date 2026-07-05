# Feature: Models foundation (`backend/models.py`)

The shared vocabulary every other backend module speaks: the `Feature` /
`LayerSnapshot` / `LayerSnapshotMeta` Pydantic v2 models and the five enums, copied
**verbatim** from [`feature-schema.md`](../../design/contracts/feature-schema.md). No
source, SQLite, or HTTP knowledge — pure schema (STRUCTURE §4). Everything written
here survives unchanged into v1.

- **Slug:** models
- **Subproject:** v0 (source-validation spike)
- **New system?** yes (first product module)
- **Project directory:** `.`

## Slices

| # | Slice | Goal (one line) | Status | PR |
|---|-------|-----------------|--------|----|
| 01 | [feature-schema](01-feature-schema.md) | `Feature`/`LayerSnapshot`/enums validate per the contract | ☐ todo | — |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. -->

## Out of scope (whole feature)

- Integrity flag *computation* (v1 `integrity.py`); the `IntegrityFlag` enum + the
  `integrity_flags` field exist here, but nothing sets them in v0.
- Any persistence, adapter, or API wiring — those consume `models`, they don't live here.

## Notes

- The contract is the source of truth; this module copies it exactly (marine attrs and
  enums included, even though v0 exercises only air + land — they cost nothing and keep
  the module whole for v1).
