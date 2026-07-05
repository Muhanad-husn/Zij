# Vendored skills — provenance

The six TDD-harness skills here (`red-green-refactor`, `tdd-plan`, `tdd-ci`,
`tdd-harness`, `safe-pr`, `safe-cleanup`) are **vendored by copy** from:

- **Source:** https://github.com/brainqub3/red-green-refactor
- **Commit:** `593e7abae2dc74f9a21eba3323e78a8fa9520dba`
- **License:** MIT (© 2026 john-adeojo) — see [`UPSTREAM-LICENSE`](UPSTREAM-LICENSE).
- **Vendored:** 2026-07-05, for the Zij agentic-engineering-org build (Phase 4, DEC-6 / DEC-29).

## Local modifications

Adapted to the Zij enterprise (roles, gates, Python 3.13 / uv / pytest / ruff)
without forking the upstream prose: each `SKILL.md` carries a top **"Zij adaptation"**
override block plus surgical inline edits; `tdd-ci/assets/workflows/python-ci.yml`
was rewritten for the uv stack; `tdd-plan/assets/plan-template.md` gained an `Issue:`
field and DEC-1 role/ordering fields. The two Node scripts (`classify-branches.mjs`,
`collect-evidence.mjs`) are kept unmodified (audited clean, DEC-29).

To re-sync with upstream, diff against the pinned commit and re-apply the override
blocks. Rationale and the full audit are logged in [`docs/agentic-build.md`](../../docs/agentic-build.md) (DEC-29).
