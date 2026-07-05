---
description: Start the next sprint issue — select it by dependency from the GitHub backlog, then drive the role subagents through the harness (outer test red → implementer greens → two-stage review → safe-pr prepares the PR). Never merges; stops at a prepared PR for the founder.
---
Start work on the next sprint issue: `$ARGUMENTS`

You are the **orchestrator**. Drive one issue from selection to a **prepared PR into
`main`** — and no further. The founder merges (their third decision moment). Every
step below runs under the Phase-3 gates: subagents cannot merge, no commit lands on
a red suite, the implementer cannot touch the outer test or `design/`.

1. **Select the issue.** If `$ARGUMENTS` names an issue (`#<n>`), use it. Otherwise
   read the open backlog through the plugin (`mcp__plugin_github_github__list_issues`
   / `issue_read`) and pick the highest-priority issue whose dependencies (blocked-by)
   are already closed. **Skip anything labeled `blocked` or `needs-context`** and say
   why. State which issue you chose and its linked `plans/<feature>/NN-*.md`.

2. **Cut the branch.** Create a feature branch off `main` for the slice (e.g.
   `feat/<issue>-<slug>`). All work happens here; never on `main`.

3. **Spec (only if the contract is missing/thin).** If the slice needs a spec or
   contract that isn't already frozen under `design/`, dispatch the **spec-author**
   subagent to write it. If a spec already exists, do not touch it — it is frozen
   during implementation (drift → a `spec-drift` issue, never an in-place edit).

4. **Outer test red (test-author — DEC-1, DEC-33).** Dispatch the **test-author**
   subagent to write the slice's **outer acceptance test** encoding the plan's
   Given/When/Then, and **commit it red** before any implementation. Under the
   tests-green gate the red commit is achieved with
   `@pytest.mark.xfail(reason="… not yet implemented", strict=True)` (DEC-33): the
   absent behavior makes it `xfailed` → pytest exits 0 → the red commit lands. This is
   the locked behavioral contract. **No implementation commit may precede this red
   commit** — verify the red commit exists (and that it carries the strict-xfail
   marker) before step 5.

5. **Green the inner cycles (implementer).** Dispatch the **implementer** subagent to
   drive inner unit red→green→refactor cycles (the `red-green-refactor` skill) until
   the outer test passes. The implementer writes only under `backend/`/`frontend/`;
   the hooks block it from editing the outer test or `design/`. Escalate the
   implementer to Opus only if the slice genuinely warrants it. **Marker-removal
   handoff (DEC-33):** when the behavior is complete the strict-xfail outer test
   XPASSes → the suite goes red → the implementer's final commit is blocked and it
   cannot clear the marker (path guard). The implementer greens the behavior, leaves
   the final state in the working tree, and hands back. Then dispatch the
   **test-author** once more to **remove the `xfail` marker** and land the final
   fully-green commit (finalizing the locked contract). Only after that is the slice
   green end-to-end.

6. **Two-stage review (reviewer).** Dispatch the **reviewer** subagent: spec-
   compliance first (does the outer test truly encode intent?), then code-quality. On
   a stage-1 failure, loop back — do not proceed to a PR on an unaddressed finding.

7. **Prepare the PR (`safe-pr`) — do not merge.** Use the `safe-pr` skill (non-web
   transcript evidence path) to push the branch and open a PR into `main` with the
   feature/slice description, test evidence, and a reviewer checklist. Link the PR to
   its issue (`Closes #<n>`). **safe-pr prepares only; it must not merge** — if it or
   anything else attempts a merge, the block-merge gate stops it.

8. **Hand off.** Report the prepared PR URL and the review outcome to the founder,
   with one status (DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT). If the
   slice shipped with caveats, apply `done-with-concerns` to the issue/PR. **Stop
   here. Do not merge.**
