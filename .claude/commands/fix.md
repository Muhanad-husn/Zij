---
description: The fast lane for a bug or small change that doesn't warrant a full slice. Classifies the change, routes it (fixer alone, or a stripped test→fix loop), then prepares a PR into main. Pauses for founder approval; on approval the orchestrator merges and cleans up. Bounces feature-scale work to /sprint-start.
---
Fix or change: `$ARGUMENTS`

You are the **orchestrator**. This is the fast lane for work that does not deserve the
full behavior-first pipeline — a bug, a refactor, a rename, a config or dependency
tweak, a copy change. It skips the *process ceremony* (spec, outer acceptance test,
two-stage review) but keeps every *safety gate*: subagents never merge, no commit lands
on a red suite, the change becomes a PR the founder approves. Use `/sprint-start`, not
this, for anything that adds a behavior or spans a feature.

1. **Classify the change.** Decide which of three buckets it falls in and say which:
   - **Non-behavioral** — refactor, rename, config, dependency bump, docs/copy, a fix
     already covered by an existing test. No new test needed; the current suite is the
     oracle.
   - **Behavioral bug** — a wrong observable behavior with no test pinning it. Needs
     exactly one regression test that reproduces the bug.
   - **Feature-scale** — new behavior, a new endpoint or module, several files across
     modules, or anything needing a spec change. **Do not fix it here.** Bounce it to
     `/sprint-start` (file or name the issue) and stop. This bucket is the guard that
     keeps the fast lane from becoming the default.

   Brief the founder in one or two plain lines: what breaks or changes, and which
   bucket. Do not cut a branch for the feature-scale bucket.

2. **Cut the branch.** Create `fix/<slug>` off `main`. All work happens here; never on
   `main`.

3. **Route by bucket.**
   - **Non-behavioral →** dispatch the **fixer** subagent (Sonnet; escalate to Opus only
     for a genuinely gnarly fix). It makes the change under the path guard (product code
     only), runs `uv run pytest`, and commits **green** on the branch. The tests-green
     gate blocks a red commit; if the change can't stay green, the fixer hands back
     BLOCKED. Pure docs/copy/config with no logic may skip the review step at your
     discretion — the gate already protects it.
   - **Behavioral bug →** run a stripped test-first loop, same DEC-1/DEC-33/DEC-34 roles
     as a slice but no spec and no outer-acceptance ceremony beyond the one test:
     **(a)** dispatch the **test-author** to write **one regression test** that
     reproduces the bug and **commit it red** (`@pytest.mark.xfail(reason="…", strict=True)`
     → `xfailed` → exit 0 → the red commit lands). Verify the red commit exists before
     (b). **(b)** dispatch the **fixer** to green it (product code only; it cannot touch
     the test). **(c)** when the fix XPASSes the strict-xfail test → suite red → the
     fixer's commit is blocked and it hands back; dispatch the **test-author** once more
     to remove the marker and land the final green commit.

   If the fixer reports the change is actually feature-scale (bucket 3 discovered
   mid-flow), stop, abandon the `fix/` branch, and re-route to `/sprint-start`.

4. **Review (one pass).** Dispatch the **reviewer** subagent. For a non-behavioral
   change this is a code-quality pass. For a behavioral bug, the reviewer's first job is
   the DEC-1 question at fix scale: **does the regression test genuinely reproduce the
   bug** (would it have failed before the fix), or is it a tautology? Loop back on a
   blocking finding.

5. **Prepare the PR (`safe-pr`).** Push the branch and open a PR into `main` with the
   change description and test evidence (the failing-then-passing transcript for a bug;
   the green suite for a non-behavioral change). Link the issue if there is one
   (`Closes #<n>`). `safe-pr` prepares only — it never merges.

6. **Hand off for approval, then merge on approval only.** Report the prepared PR URL
   and one status (DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT) with a one- or
   two-line plain summary of what changed. **Pause and ask for merge approval — do not
   infer it.** On the founder's explicit "approved", run the merge yourself
   (`gh pr merge`), then `safe-cleanup` on the merged branch (report first, record the
   recovery SHA).
