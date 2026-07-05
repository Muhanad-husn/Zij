---
description: Start the next sprint issue — select it by dependency from the GitHub backlog, then drive the role subagents through the harness (outer test red → implementer greens → two-stage review → safe-pr prepares the PR). Pauses at the prepared PR; on founder approval the orchestrator merges and cleans up.
---
Start work on the next sprint issue: `$ARGUMENTS`

You are the **orchestrator**. Drive one issue from selection to a **prepared PR into
`main`**, then pause for founder approval (their third decision moment). Approval is
the only requirement: on an explicit "approved" you run the merge yourself, then
`safe-cleanup` on the merged branch. Every step below runs under the Phase-3 gates:
subagents cannot merge, no commit lands on a red suite, the implementer cannot touch
the outer test or `design/`.

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
   the outer test passes. The implementer writes only product code under
   `backend/`/`frontend/`; the path guard blocks it from editing **any test** (all of
   `**/tests/`, not just the outer one) or `design/`. Escalate the implementer to Opus
   only if the slice genuinely warrants it.
   **Inner-test authorship is the test-author's, never the implementer's (DEC-34).**
   Do **not** brief the implementer to write inner unit tests — it physically cannot
   (the guard denies every `**/tests/` write), and being asked to is the wrong
   routing. Two sanctioned cases: **(a)** if the outer acceptance test fully pins the
   slice's behavior, no separate inner unit tests are needed — the implementer drives
   production code straight against the locked outer test as its red/green signal;
   **(b)** if the slice genuinely needs inner unit tests for internal collaborators,
   the **test-author** authors them from the plan's unit list — most simply folded
   into the marker-removal pass below (the tests-green gate + strict-xfail make
   authoring them then, against the now-built behavior, the lowest-ceremony fit).
   **Marker-removal handoff (DEC-33/DEC-34):** when the behavior is complete the
   strict-xfail outer test XPASSes → the suite goes red → the implementer's final
   commit is blocked and it cannot clear the marker (path guard). The implementer
   greens the behavior, leaves the final state in the working tree, and hands back.
   Then dispatch the **test-author** once more to **author any inner unit tests the
   slice needs (case b) and remove the `xfail` marker**, landing the final fully-green
   commit (which finalizes the locked contract and sweeps in the implementer's
   uncommitted production delta). Only after that is the slice green end-to-end.

6. **Two-stage review (reviewer).** Dispatch the **reviewer** subagent: spec-
   compliance first (does the outer test truly encode intent?), then code-quality. On
   a stage-1 failure, loop back — do not proceed to a PR on an unaddressed finding.

7. **Prepare the PR (`safe-pr`).** Use the `safe-pr` skill (non-web transcript
   evidence path) to push the branch and open a PR into `main` with the
   feature/slice description, test evidence, and a reviewer checklist. Link the PR to
   its issue (`Closes #<n>`). `safe-pr` prepares only — the merge is a separate,
   approval-gated step (step 9). If a **subagent** attempts a merge, the block-merge
   gate stops it.

8. **Hand off for approval.** Report the prepared PR URL and the review outcome to
   the founder, with one status (DONE / DONE_WITH_CONCERNS / BLOCKED /
   NEEDS_CONTEXT). If the slice shipped with caveats, apply `done-with-concerns` to
   the issue/PR. **Pause here and ask for merge approval — do not infer it.**

9. **Merge and clean up (on approval only).** On the founder's explicit "approved",
   run the merge yourself from the main session (`gh pr merge`), then run
   `safe-cleanup` on the now-merged local branch (report first; delete under the same
   approval, recording the recovery SHA). Approval is all that is needed — never make
   the founder run the commands.
