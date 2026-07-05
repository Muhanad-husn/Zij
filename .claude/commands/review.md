---
description: Run the two-stage review (spec-compliance then code-quality) on a PR, branch, or working diff by delegating to the read-only reviewer role subagent. Thin entry point.
---
Delegate to the **reviewer** role subagent (`.claude/agents/reviewer.md`) to review:
`$ARGUMENTS`

Dispatch a single `reviewer` subagent via the Task tool. Pass it:

- **What to review.** The PR number, branch, or "the current working diff" from
  `$ARGUMENTS`. If empty, default to the current branch's diff against `main`
  (`git diff main...HEAD` plus unstaged changes) and say so. Give the subagent the
  concrete refs so it can read the diff with its read-only Bash (`git diff`, `git
  log`), not guess.
- **The two-stage contract, in order (do not let it reorder):**
  1. **Spec-compliance.** Does the change satisfy the spec under `design/`? Does the
     outer acceptance test genuinely encode the intended behavior — not a tautology
     that would pass against a stub (DEC-1)? A test that doesn't pin the behavior is
     a stage-1 failure regardless of code quality. Stage 2 does not begin until
     stage 1 passes.
  2. **Code-quality.** Correctness, clarity, edge cases, inner-cycle coverage, and
     the module-boundary / dependency-direction rules in `design/docs/STRUCTURE.md`.

The reviewer has **no Edit/Write** by design: it points to specific files and lines
and proposes changes; it never makes or merges them. It returns a four-status
report — relay it. If review surfaces that the **spec itself** is wrong, that is a
`spec-drift` issue for the founder to adjudicate (see CLAUDE.md), not an in-place
edit.
