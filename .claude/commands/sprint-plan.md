---
description: Decompose a subproject (a lifecycle stage / PRD) into a GitHub-issue backlog — drafted locally for founder review, then filed through the GitHub plugin with each issue linked to its plans/<feature>/ slice files. Never merges; files only after approval.
---
Plan a sprint backlog for the subproject: `$ARGUMENTS`

You are the **orchestrator** (main session). You hold the GitHub-plugin tools the
role subagents deliberately lack (DEC-19), so the plugin writes happen here — but
**only after the founder approves the drafted plan.** Filing the backlog is one of
the founder's three decision moments (plan approval). Follow this order:

1. **Scope the subproject.** `$ARGUMENTS` names a lifecycle stage (e.g. `v0`) or a
   PRD under `design/`. If empty or ambiguous, ask the founder which subproject and
   which PRD/specs define it before proceeding. Read the relevant `design/` docs
   yourself for orientation.

2. **Decompose (delegate to triage).** Dispatch the **triage** subagent to propose
   the feature → behavioral-slice decomposition, priority, and dependency order.
   Triage drafts; it files nothing.

3. **Write slice plans (the `tdd-plan` skill).** For each feature, produce
   `plans/<feature-slug>/` (a README index + one `NN-<slice>.md` per slice) via the
   `tdd-plan` skill. Each slice's acceptance criterion is the concrete Given/When/
   Then the **test-author** will later encode as the locked outer test (DEC-1).
   Leave each plan's `Issue:` field as `TBD` for now.

4. **Draft the backlog locally — do NOT file yet.** Write one review artifact,
   `plans/backlog-<subproject-slug>.md`, with a section per proposed issue:
   **title, full body, acceptance criterion, dependencies (blocked-by), suggested
   labels, and the linked `plans/<feature>/NN-*.md` paths.** Include the
   `sub:<subproject>` namespace label on every issue. Present this file to the
   founder and **stop for approval.** Do not call any plugin issue-write tool before
   the founder approves.

5. **On approval, file through the GitHub plugin.** For each approved issue, in
   dependency order, call `mcp__plugin_github_github__issue_write` (create) with the
   drafted title/body and labels. Use `sub_issue_write` for parent/child structure
   if the decomposition warrants it. Ensure labels exist first — the four workflow
   labels (`spec-drift`, `blocked`, `needs-context`, `done-with-concerns`) and
   `sub:<subproject>`; create a missing `sub:<name>` via `gh label create` (the
   plugin has no label-create tool — raw `gh` is the sanctioned fallback here).

6. **Back-link.** After each issue is filed, edit its slice plans' `Issue:` field
   from `TBD` to the real `#<n>`, and record the issue numbers in
   `plans/backlog-<subproject-slug>.md`. Commit the plan/back-link changes on the
   working branch (the tests-green hook will run — keep the suite green).

**Never merge and never open a PR here.** `/sprint-plan` only produces the backlog
and its linked plans. Execution is `/sprint-start`. If a `git merge` / `gh pr merge`
/ plugin merge is ever attempted, the Phase-3 gates block it by design.
