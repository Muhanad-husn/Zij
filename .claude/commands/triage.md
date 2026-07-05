---
description: Triage / groom the backlog or scope an issue by delegating to the tool-locked triage role subagent. Thin entry point — the subagent reads and drafts; it files nothing.
---
Delegate to the **triage** role subagent (`.claude/agents/triage.md`) to triage or
scope: `$ARGUMENTS`

Do this by dispatching a single `triage` subagent via the Task tool. Pass it:

- **What to scope.** The issue number, PR, backlog area, or feature described in
  `$ARGUMENTS`. If `$ARGUMENTS` is empty, ask the founder what to triage before
  dispatching — do not guess.
- **What to produce.** Scoping, decomposition into behavioral slices (each a single
  observable behavior at a real endpoint per DEC-1), priority/dependency order, and,
  for anything that should become work, **drafted issue content** (title, body,
  acceptance criterion as Given/When/Then, suggested labels, linked slice) — because
  triage has no GitHub-plugin tools and files nothing itself.

The subagent returns a four-status report (DONE / DONE_WITH_CONCERNS / BLOCKED /
NEEDS_CONTEXT). Relay its findings.

**You (the orchestrator) file nothing here.** `/triage` only shapes work. To turn a
drafted backlog into real GitHub issues, run `/sprint-plan` (which files through the
GitHub plugin after founder review). Triage never writes code, never opens/closes/
merges anything; its Bash is read-only.
