# Zij Handbook

## What this is

A one-operator AI software enterprise. The **founder** (the human in the main
session) specifies and decides. Tool-locked **role subagents** build and check.
Two deterministic hooks hold the line so the boundary is real, not advisory.
The founder is not a subagent; every subagent inherits this file.

This handbook is the constitution. It is intentionally short. When a rule and
common sense disagree, raise it rather than produce a nonsensical result (see
Developer Principles).

## Developer Principles

The following govern *how Claude works in this repo*:

- **Balance: practicality over perfectionism.** 80/20 rule. A working solution
  beats a theoretically optimal one.
- **Don't reinvent the wheel.** Check existing tools and libraries before
  building. If you know of something useful that isn't installed, suggest adding it.
- **Measure, don't speculate.** When in doubt, prototype and measure rather than
  analyze indefinitely.

## Hierarchy

Work flows top-down through five levels:

**product → subproject (a lifecycle stage, e.g. v0/v1/v2) → sprint → issue → behavioral slice.**

A *slice* is the unit of work an implementer greens: one behavior, one outer
acceptance test, one inner red→green→refactor loop. Issues are the system of
record (GitHub), driven through the installed GitHub plugin, not raw `gh`.

## Roles & authority

Five addressable subagents live in `.claude/agents/`. Each has a locked tool set
and a pinned model. Path limits are enforced by hooks, not by the tool list.

| Role | Does | Never |
|---|---|---|
| Triage / PM | Reads, files and shapes issues | Writes code |
| Spec author | Writes specs/contracts (spec area only) | Writes code or tests |
| Test author | Writes tests, incl. the locked outer acceptance test | Writes product code or specs |
| Implementer | Writes product code, drives inner unit cycles | Edits specs or tests |
| Reviewer | Reads, reviews in two stages, comments | Writes anything (read-only) |

**Merge authority: founder approval is the gate, not founder execution.** When
work on a branch is complete, the founder's explicit "approved" is all that is
needed — the orchestrator (main session) then runs the merge and, afterwards, the
safe-cleanup of the merged branch itself. Subagents build and check; they never
merge to `main`, never push to `main`, never delete branches, and never change
branch protection. That subagent boundary, plus the approval requirement on the
orchestrator, is the enterprise's core boundary.

## The behavior-first loop (DEC-1)

Test authorship is split, on purpose:

1. The **outer acceptance test is the locked behavioral contract.** The
   spec/test-author writes it and commits it **red**, before any implementation.
2. The **implementer drives inner unit red→green→refactor cycles only.** The
   implementer may not edit the outer test or the specs.

No implementation commit ever precedes its slice's red outer test.

## Spec discipline

Specs are **frozen during implementation**. A spec is never patched in place
mid-build. If implementation reveals the spec is wrong, the implementer stops and
raises a **`spec-drift` issue**; the founder adjudicates; the spec-author fixes it
in a separate, deliberate pass with spec-authoring mode enabled. Drift routes to
an issue, never to an in-place edit.

## The two hard gates

1. **Subagents never merge.** Subagent-scoped hooks block `git merge`, pushes to
   `main`, `gh pr merge`, branch deletion, and the GitHub plugin's merge tool; a
   global hook blocks direct commits on `main` for everyone. The orchestrator's
   own merge and cleanup path stays open and runs only on founder approval.
   Server-side branch protection backstops this where the plan allows it.
2. **No commit on a red suite.** A hook runs the test command before every commit
   and blocks it if the suite is red.

These are hooks, not honor system. You live under your own gates: once they exist,
a red suite blocks your own commits too. That is intended.

## Model tiering

Match the model to the task. **Haiku** for mechanical and triage work. **Sonnet**
for integration and implementation. **Opus** for review and design. Escalate a
slice to Opus only when its complexity genuinely warrants it; do not ask the
founder which model to use, choose per task.

## Writing conventions

For anything generated (prose, commits, issues, comments): plain and direct, no
filler. Prefer short sentences over ceremony. Cap of **two em dashes per 500
words**. Explain the *why* when it helps a reader generalize.

## This project (Zij)

Zij is a FastAPI + MapLibre monitor. Stack profile: **Python 3.13 / uv / pytest /
ruff** (test: `uv run pytest`, lint: `uv run ruff`). Layout mappings the gates and
roles use:

- **Spec area = `design/`** (PRD, ADRs in `design/docs/DECISIONS.md`, contracts in
  `design/contracts/`, specs in `design/specs/`). The spec-freeze hook guards
  `design/**`.
- **Product code = `backend/`** (import root; distribution name `zij`) and
  `frontend/`.
- **Tests = `backend/tests/`** and `frontend/tests/`. The implementer may not
  write here.
- Secrets are **env-only** via `.env` (see `design/contracts/config.md`).

The build of this workflow itself, and every decision that shaped it, is logged in
[`docs/agentic-build.md`](docs/agentic-build.md).
