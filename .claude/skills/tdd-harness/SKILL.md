---
name: tdd-harness
description: Use whenever the user wants a feature, product, bugfix, or change taken from idea to a reviewable pull request the disciplined test-driven way. This is the red-green-refactor TDD harness orchestrator — it drives the full pipeline (slice into thin vertical increments, write execution plans, develop with unit plus end-to-end tests via red-green-refactor, promote tests to GitHub Actions CI, and open a safe evidence-rich PR) and coordinates the tdd-plan, red-green-refactor, tdd-ci, and safe-pr skills. Triggers on 'build X with TDD', 'red green refactor this', 'do this enterprise-grade or from idea to PR', or 'use the tdd or rgr harness'.
---

# TDD Harness — Orchestrator

You are running an enterprise-grade Test-Driven Development harness. Your job is to take whatever the user wants built and shepherd it through four disciplined phases, **enforcing the gate between each**. You do not write feature code ad hoc; you drive the pipeline.

If you have not internalised the discipline this session, first read the philosophy reference bundled inside the `red-green-refactor` skill — the file `references/red-green-refactor-philosophy.md` within that skill's own directory. The whole harness rests on it.

> ## Zij adaptation (roles, gates) — read first
> This skill runs inside the Zij enterprise (`CLAUDE.md`). The generic orchestrator below assumes **one agent does every phase**. In Zij it is **role-driven** and normally invoked through the Phase-5 sprint skills (`/sprint-start`), not run as a single autonomous agent:
>
> - **Phase → role (DEC-1):** `tdd-plan` = triage/PM + founder shaping a slice → **plan file + GitHub issue**. `red-green-refactor` phase 2 is **split**: the **test-author** writes and commits the **locked outer acceptance test red** *first*; only then does the **implementer** drive the inner unit cycles to green (the implementer may not touch the outer test or `design/` specs — hooks enforce it). `tdd-ci` wires CI. `safe-pr` **prepares** the PR; the **reviewer** runs the two-stage review; the **founder approves the merge, and the orchestrator runs it**.
> - **No implementation commit ever precedes its slice's red outer test.** That ordering is the core invariant this harness exists to hold.
> - **Gates are live (Phase 3):** subagents cannot merge (`gh pr merge`/`git merge`/plugin-merge blocked); a red `uv run pytest` blocks any commit; `design/**` is frozen during implementation. The role machinery takes a slice all the way to a green, reviewed PR, then **pauses for founder approval** — on "approved", the orchestrator merges and cleans up.
> - **Stack + evidence:** `uv run pytest` / `uv run ruff check`; Python 3.13. Default evidence is **transcripts** (Zij is FastAPI + pipeline); Playwright screenshots/recordings apply only to a real `frontend/` web slice. Read "e2e / Playwright evidence" below as "acceptance-test evidence, transcript by default."

## The pipeline

```
   ┌────────────┐   ┌──────────────────────┐   ┌──────────┐   ┌───────────┐
   │ 1. tdd-plan│ → │ 2. red-green-refactor│ → │ 3. tdd-ci│ → │4. safe-pr │
   │  slice +   │   │  outer e2e + inner   │   │ promote  │   │ evidence  │
   │  plan files│   │  unit, on a plan     │   │ to CI    │   │ PR → main │
   └────────────┘   └──────────────────────┘   └──────────┘   └───────────┘
```

Each phase is its own skill. Invoke them in order via the **Skill** tool. Do not improvise around them — they carry the detailed discipline.

| Phase | Skill | Produces | Gate before advancing |
|---|---|---|---|
| 1 | `tdd-plan` | `plans/<feature>/` with a README index + one plan file per thin vertical slice | User has reviewed the slice list and approved the first slice |
| 2 | `red-green-refactor` | Passing unit + e2e tests and the implementation for **one** slice; updated plan status log | The slice's acceptance (e2e) test is GREEN and the full suite passes locally |
| 3 | `tdd-ci` | `.github/workflows/` that runs the unit + e2e tests | The workflow is valid and committed |
| 4 | `safe-pr` | A pull request (feature branch → main) with embedded acceptance evidence (transcripts by default; Playwright for web slices) — **prepared, not merged by this skill** | Reviewer's two-stage review done; PR is open and its URL recorded in the plan; the orchestrator merges once the founder approves |
| 5 (opt) | `safe-cleanup` | Stale **local** slice branches retired after their PRs merge | Maintenance, not a gate — local-only, report-first, confirm-before-delete |

## How to run it

1. **Clarify the goal.** Restate what the user wants in one or two sentences and confirm. If it is a brand-new system with no build/test/deploy pipeline yet, say so — phase 1 will start with a *walking skeleton* slice.
2. **Phase 1 — plan.** Invoke `tdd-plan`. It decomposes the request into thin vertical slices (minimum testable behaviours) and writes execution plans into `plans/`. Surface the slice list to the user and get sign-off on the first slice before coding. Slicing is the most important judgement call — do not rush it.
3. **Phase 2 — develop.** For the approved slice, invoke `red-green-refactor`. It writes a failing acceptance/e2e test (outer loop), then drives the implementation through inner unit-test red→green→refactor cycles until the acceptance test is green. It updates the slice plan's status log as it goes.
4. **Phase 3 — CI.** Once the slice is green locally, invoke `tdd-ci` to wire the slice's tests into GitHub Actions so they run on every push and pull request.
5. **Phase 4 — PR.** Invoke `safe-pr` to open a reviewable pull request from a feature branch into `main`, complete with the feature description and evidence (test logs and real-endpoint transcripts by default; Playwright screenshots and recordings for a web slice). **This is outward-facing — confirm before pushing or opening the PR. `safe-pr` prepares the PR and stops; on the founder's explicit approval the orchestrator then merges it and runs `safe-cleanup` on the branch.**
6. **Next slice.** Return to phase 2 for the next slice in the plan. One slice = one RGR pass = one PR. Keep slices and PRs small.
7. **Tidy up (optional).** After PRs merge, invoke `safe-cleanup` to retire stale local feature branches. It is local-only, reports before acting, confirms before deleting, and records recovery SHAs.

## Gates you must enforce (do not skip)

- **No code before a plan.** If asked to start coding without a slice plan, run `tdd-plan` first (or ask the user to).
- **No CI promotion before local green.** Phase 3 only runs after the slice's full suite passes locally.
- **No PR before green + CI.** Phase 4 requires a green slice and a committed CI workflow.
- **Never target anything but `main`** for the PR unless the user explicitly says otherwise. Never force-push. Confirm before any push or PR creation.
- **One slice at a time.** Do not batch multiple slices into one branch or one PR — thin slices are the whole point.

## Conventions (shared across all four skills)

These are the single source of truth; the phase skills restate them briefly.

- **Plans:** `plans/<feature-slug>/README.md` (index + status board) and `plans/<feature-slug>/<NN>-<slice-slug>.md` (one execution plan per slice). `<NN>` is a zero-padded order, e.g. `01`, `02`.
- **Project directory:** the path from the repo root where the app + its package manifest/tests live (`.` at the root, or a subfolder for a monorepo package / `services/<x>` / a `sandbox/` app). `tdd-plan` records it in the plan; `red-green-refactor`, `tdd-ci`, and `safe-pr` run install/test/build from there, and CI sets `working-directory` + `cache-dependency-path` accordingly. The git branch is always cut at the repo root.
- **Branches:** one feature branch per slice — `feat/<feature-slug>/<NN>-<slice-slug>` — cut from an up-to-date `main`.
- **Evidence:** `docs/tdd-evidence/<feature-slug>/<NN>-<slice-slug>/` (committed on the feature branch; collected by `safe-pr`).
- **Commits:** small, on green only. Conventional Commit style (`feat:`, `test:`, `refactor:`, `ci:`). Reference the slice, e.g. `feat(<feature-slug>): <slice goal> [slice NN]`.
- **Definition of done for a slice:** the acceptance/e2e test is green, the full suite passes, the slice's tests run in CI, and a PR is open with evidence.

## When the user only wants one phase

Users can invoke any phase skill directly (`/tdd-plan`, `/red-green-refactor`, `/tdd-ci`, `/safe-pr`). Honour that — don't force the whole pipeline if they only asked for one part. This orchestrator is for "take it from idea to PR." Each phase skill is self-sufficient and explains what it expects as input.
