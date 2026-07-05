# Agentic Engineering Org — Build Log

This document tracks the supervised build of the AI-engineering-org workflow
(role subagents + deterministic gates + vendored TDD harness + sprint tooling)
adopted into the **Zij** product repo. It is the system of record for the build
itself; Zij's *product* decisions live separately in
[`design/docs/DECISIONS.md`](../design/docs/DECISIONS.md).

- **Skill:** `agentic-engineering-org`
- **Target repo:** `github.com/Muhanad-husn/Zij` (existing product repo, not a blank template)
- **Stack profile:** default — **Python 3.13 / uv / pytest / ruff** (matches Zij design)

---

## Progress Tracker

| Phase | Title | Status | Date | Notes |
|---|---|---|---|---|
| 0 | Repository foundation | **DONE — awaiting Checkpoint 0** | 2026-07-05 | Scaffold on `setup/00-foundation`; green baseline; branch protection prepared (repo already exists → no `gh repo create`). |
| 1 | `CLAUDE.md` handbook | Not started | — | The constitution: hierarchy, role/merge boundaries, spec-freeze, gates. |
| 2 | Role subagents | Not started | — | triage / spec-author / test-author / implementer / reviewer. |
| 3 | Hard gates (hooks) | Not started | — | deny / block-merge (+ plugin merge tool) / tests-green / spec-freeze. |
| 4 | Vendor & adapt TDD harness | Not started | — | `brainqub3/red-green-refactor`, adapted to roles/gates/Python. |
| 5 | Sprint & role wiring | Not started | — | `/sprint-plan`, `/sprint-start`, `/triage`, `/review`, labels. |
| 6 | Dry run & validation | Not started | — | One throwaway feature end-to-end; founder merges. |

Status legend: `Not started` · `In progress` · `DONE` · `DONE_WITH_CONCERNS` · `BLOCKED` · `NEEDS_CONTEXT`.

---

## Decision Log

Seeded with the skill's locked decisions (DEC-1..7) plus decisions/adaptations
made during this build. Append a row on any divergence from a skeleton or
resolved ambiguity.

| # | Decision | Rationale |
|---|---|---|
| DEC-1 | Test authorship is split: the **outer acceptance test is the behavioral contract** (spec/test-author writes it, commits red, locks it); the implementer drives **inner unit cycles only** and may not edit the outer test or specs. | Locked by skill. |
| DEC-2 | Roles are **addressable subagent files** in `.claude/agents/`, each with a locked `tools` set and a pinned `model`. | Locked by skill. |
| DEC-3 | Two gates are **deterministic hooks**, not advice: *agents-never-merge* and *tests-green-before-commit*. Branch protection backstops them server-side. | Locked by skill. |
| DEC-4 | **GitHub issues and PRs** are the system of record. Sprints, not sessions. | Locked by skill. |
| DEC-5 | One repository. Spec and build separated by **role and a spec-freeze hook**, not by folder. | Locked by skill. |
| DEC-6 | The behavior-first loop is the **vendored `brainqub3/red-green-refactor` harness** (MIT), adapted to roles/gates — not hand-built. | Locked by skill. |
| DEC-7 | DEC-4 runs through the **installed GitHub plugin** (`mcp__plugin_github_github__…`), not raw `gh` in Bash. The *agents-never-merge* gate must also match the plugin's merge tool, not only `Bash(git merge …)`. | Locked by skill. |
| DEC-8 | **Stack profile = default** (Python 3.13 / uv / pytest / ruff). Test command: `uv run pytest`; lint: `uv run ruff`. | Confirmed against Zij `design/docs/STRUCTURE.md §5` (pyproject deps) and detected toolchain (python 3.13.14, uv 0.11.6). |
| DEC-9 | **Adopting into an existing repo**, not building a blank `ai-enterprise-template`. The GitHub remote already exists (`Muhanad-husn/Zij`), so Phase 0 **skips `gh repo create`** and prepares only branch protection. | Repo has a `main` with design already committed + a live `origin`. |
| DEC-10 | **Layout mapping** (template → Zij actual): `specs/ → design/`, `src/ → backend/`, `tests/ → backend/tests/`. The Phase-3 spec-freeze hook will guard **`design/**`** (Zij's spec/contract layer per STRUCTURE.md §3), not a root `specs/`. No redundant root `specs/`/`src/`/`tests/` created. | Zij's design already fixed this layout (STRUCTURE.md §2, §6); a competing `tests/`/`src/` would contradict it. |
| DEC-11 | **Secrets via `.env`** (env-only, per `design/contracts/config.md`), not the template's `secrets/secrets.toml`. Created `.env.example`; `.gitignore` excludes `.env`. | Zij's config contract mandates env-only secrets. |
| DEC-12 | Phase 0 `pyproject.toml` carries **empty runtime `dependencies`** (only dev = pytest, ruff). Real runtime deps land during the v0 spike sprint. | Keep the baseline light + green; avoid front-running the implementation sprint's dependency wiring. |
| DEC-13 | Phase-0 scaffold committed on branch `setup/00-foundation` for the **founder to merge** (dogfooding the workflow), rather than the skill's "one commit on main" (which assumed a brand-new empty repo). | Operating rule 4; repo already has history on `main`. |
| DEC-14 | Branch protection via a **repository ruleset** (`protect-main`), not classic branch-protection. | Repo is **private**; classic protection needs a paid plan, rulesets work on free private repos and are GitHub's current recommendation. |
| DEC-15 | Ruleset requires a **PR before merge but 0 approving reviews** (plus block-deletion, block-force-push). | **Solo operator**: GitHub forbids approving your own PR, so a 1-review requirement would lock the founder out of merging. Direct push to `main` stays blocked; the human still manually merges. Server-side status-check requirement deferred to Phase 4 (no CI workflow exists yet). |

---

## GitHub plugin — recorded tool names (Phase 0 deliverable)

Enumerated from the live tool registry (the `/plugin` slash command belongs to
the founder's main session; **please confirm at Checkpoint 0**). Namespace:
`mcp__plugin_github_github__`.

**Merge-capable / write tools the *agents-never-merge* gate (Phase 3) must cover:**
- `mcp__plugin_github_github__merge_pull_request` — **the merge tool; primary gate target.**
- `mcp__plugin_github_github__pull_request_review_write` — can submit reviews (approve).
- `mcp__plugin_github_github__update_pull_request_branch`
- `mcp__plugin_github_github__create_or_update_file` / `push_files` / `delete_file` — direct writes to a ref.

**Issue/PR tools for the sprint workflow (Phase 5):**
- `issue_write`, `sub_issue_write`, `add_issue_comment`, `issue_read`, `list_issues`, `search_issues`, `list_issue_types`
- `create_pull_request`, `pull_request_read`, `list_pull_requests`, `add_comment_to_pending_review`

The plugin also bundles a `pr-review-toolkit` (inspect in Phase 2 before writing
the reviewer subagent).
