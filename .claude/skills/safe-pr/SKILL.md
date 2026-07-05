---
name: safe-pr
description: Use to open a safe, reviewable pull request from a feature branch into main once a slice is built with red-green-refactor and green. Phase 4 of the TDD harness. It assembles everything a reviewer needs — the feature and slice description, evidence of the tests that ran (unit summaries plus Playwright screenshots and recordings for web slices, or terminal transcripts for CLI and API slices), a reviewer checklist, and a link to the plan — then pushes the branch and opens the PR with gh. Trigger on 'raise a PR', 'open a pull request', 'ship this slice', or 'create the PR with evidence'. Deliberately cautious — confirms before pushing, never force-pushes, only targets main.
---

# Safe PR — Evidence-Rich Pull Request (Phase 4)

Open a pull request a senior engineer can approve with confidence, because the evidence is right there. This is the final phase of a slice: build (red-green-refactor) → CI (tdd-ci) → **PR**. Treat opening a PR as an outward-facing action — be careful and confirm before pushing.

> ## Zij adaptation (evidence, gates) — read first
> This skill runs inside the Zij enterprise (`CLAUDE.md`). Adaptations:
>
> - **`safe-pr` PREPARES a PR; it does not merge.** The block-merge hook denies `gh pr merge` / `git merge` / the plugin merge tool for every subagent, and branch protection backstops it. This skill's job ends at an open, evidence-rich PR into `main`. Merging is a separate, approval-gated step: **the founder approves (one of the three human moments), and on that approval the orchestrator runs `gh pr merge` from the main session** — approval is the only requirement. No merge step inside this skill.
> - **Non-web transcript evidence is the DEFAULT.** Zij is a FastAPI + pipeline product, so use the `--type cli|api|service` + `--transcript` path: capture (a) the **`uv run pytest`** run output and (b) a **real-endpoint invocation** (an HTTP request+response against the route, or the CLI/pipeline stdout + exit code) to files, and let the collector embed them. The Playwright screenshot/recording path applies **only** to a real `frontend/` web slice — ignore the "must include a screenshot and a recording" wording for the default case.
> - **Secrets are env-only (`.env`, git-ignored).** Heed the collector's `SECRETS SUSPECTED` report and never commit a `.env`, token, or credential into the evidence folder — committed history is hard to un-publish.
> - **Reviewer role, not self-certification.** In Zij the **reviewer** subagent runs the two-stage review (spec-compliance → code-quality) on the prepared PR before the merge is approved; `safe-pr` assembles the evidence the reviewer and founder read. The evidence must be *real run output*, not claims.
> - **The tests-green gate still applies** to the evidence commit — the suite must be green or the commit is blocked.

The harness builds **web and non-web** apps, so evidence comes in two shapes:
- **Web slice** → Playwright **screenshots + a recording** of the passing acceptance run (plus the HTML report).
- **Non-web slice** (CLI / HTTP API / service) → **terminal transcripts**: the test-run output *and* a real endpoint invocation (CLI stdout, or an HTTP request+response). Transcripts stand in for screenshots/recordings.

Bundled resources:
- `assets/pr-body-template.md` — the PR description structure (with an `<!-- EVIDENCE -->` marker the script fills).
- `scripts/collect-evidence.mjs` — collects evidence into the committed evidence folder and generates the PR body. For web slices it embeds screenshots and links the recording/report; for non-web slices (`--type cli|api|service` with `--transcript`) it embeds the transcripts as code blocks. Modality is auto-detected (Playwright artifacts → web) or forced with `--type`. It runs in two phases — `--copy-only` (copy + secret-scan) before you commit the evidence, then `--body-only` (build the body, pinned to the evidence commit) after — so embedded links resolve. It auto-detects repo visibility and, on **private** repos, renders screenshots as clickable blob links rather than inline images that wouldn't render. Run with Node.

> Requires the GitHub CLI (`gh`) authenticated, and a GitHub remote. Confirm both early (`gh auth status`, `git remote -v`).

## Preconditions (verify, don't assume)

1. **The slice is green.** Re-run the full suite (unit + e2e) and confirm it passes. Never open a PR on red. If anything fails, stop and return to `red-green-refactor`.
2. **CI workflow exists.** `.github/workflows/` runs the unit + e2e tests (from `tdd-ci`). If missing, run `tdd-ci` first.
3. **On the slice's feature branch.** `feat/<feature-slug>/<NN>-<slice-slug>`. If you're on `main` or another branch, create/switch to the slice branch. Never develop or PR a slice from `main`.
4. **Working tree committed.** All slice work is committed in small, green-only commits.

## Procedure

1. **Produce the evidence by actually running the tests.** Show *real* run output, not claims. Always capture the unit-test summary (counts, pass/fail). Then, depending on the slice's boundary:
   - **Web slice:** run the e2e suite with Playwright configured to capture **screenshots + video (`video: 'on'`) + HTML report** (see the `red-green-refactor` test-strategy reference). The PR must include a screenshot **and a recording** of the passing acceptance run — if none was produced, re-run with video on before continuing.
   - **Non-web slice (CLI / API / service):** capture **two transcripts to files** — (a) the test-run output (e.g. `npm test` / `pytest -q`), and (b) a real invocation through the boundary (the CLI run with its stdout + exit code, or the HTTP request + response). Redirect them to files so the collector can attach them, e.g. `npm test > test-run.txt 2>&1` and `node src/cli.js 2 3 > cli-demo.txt 2>&1`.

   Run tests from the slice's **project directory** if the app lives in a subfolder (see the plan's *Project directory* field).

2. **Copy the evidence in (`--copy-only`).** Run the collector from the repo root in copy-only mode — it copies the artifacts into `docs/tdd-evidence/<feature>/<NN-slice>/` and scans them for secrets, but does **not** write the PR body yet. (Two phases matter: the body pins URLs to the current commit, so the evidence must be committed *before* the body is generated — otherwise the links point at a commit that doesn't contain the files. See step 5.) Plain Node, so the same invocation works on Windows/macOS/Linux:

   **Web slice** — point `--report-dir`/`--results-dir` at the project dir if the app is in a subfolder (the collector resolves them from the repo root):

   ```
   node "${CLAUDE_SKILL_DIR}/scripts/collect-evidence.mjs" --feature <feature-slug> --slice <NN-slice-slug> --report-dir <project-dir>/playwright-report --results-dir <project-dir>/test-results --copy-only
   ```

   **Non-web slice** (`--type cli|api|service`, one or more `--transcript`):

   ```
   node "${CLAUDE_SKILL_DIR}/scripts/collect-evidence.mjs" --feature <feature-slug> --slice <NN-slice-slug> --type cli --transcript test-run.txt --transcript cli-demo.txt --copy-only
   ```

   By default it drops raw traces (`*.zip`) and HAR files (which often carry auth tokens); pass `--include-traces` only if you need them and have checked them.

3. **Review the evidence for secrets — BEFORE committing anything.** Read the collector's output: if it reports `SECRETS SUSPECTED`, open the named files and remove or redact any tokens, cookies, passwords, or env dumps (Playwright traces, HAR captures, and HTML reports are the usual culprits). This evidence is about to be committed and pushed and **cannot be un-published once in history**. Do not proceed until it is clean. Keep the project's raw `test-results/` and `playwright-report/` out of git via `.gitignore` — but **anchor those patterns to the project dir** (e.g. `sandbox/web-adder/test-results/`) or add `!docs/tdd-evidence/**`, so the unanchored patterns don't also ignore the committed copies under `docs/tdd-evidence/` (a silent-empty-evidence trap).

4. **Commit the cleaned evidence.** Two statements (Windows PowerShell does not support `&&`):

   ```
   git add docs/tdd-evidence/<feature>/<NN-slice>/
   git commit -m "docs(<feature>): test evidence [slice NN]"
   ```

   Confirm it actually committed (`git show --stat HEAD`) — if the folder is empty, your `.gitignore` swallowed it (step 3).

5. **Generate the PR body (`--body-only`), now pinned to the evidence commit.** Re-run the collector in body-only mode — it does not re-copy; it builds `PR_BODY.md` from the committed evidence, pinning every link to the current `HEAD` (the commit you just made), so the links resolve. **Pass `--force`:** `PR_BODY.md` is git-ignored and fully regenerable, but a leftover one from a *previous* slice will still be sitting at the repo root, and without `--force` the collector refuses to clobber it — it diverts output to `PR_BODY.generated.md` with only a `WARN`, so you'd silently edit the stale prior body instead. `--force` overwrites it cleanly (see the collector's `--out` clobber guard):

   ```
   node "${CLAUDE_SKILL_DIR}/scripts/collect-evidence.mjs" --feature <feature-slug> --slice <NN-slice-slug> [--type cli] --body-only --force --template "${CLAUDE_SKILL_DIR}/assets/pr-body-template.md" --out PR_BODY.md
   ```

   For a **web** slice it embeds screenshots and links the recording/report; for a **non-web** slice it embeds each transcript as a fenced code block (capped via `--max-transcript-lines`, default 200) and links the full file. **Private repos:** the collector auto-detects visibility (`gh repo view`) and, on a private repo, renders screenshots as clickable **blob links** instead of inline `![]()` embeds — because `raw.githubusercontent.com` doesn't render for private repos. Override with `--public`/`--private` if detection is wrong. Then open `PR_BODY.md` and fill the remaining `<placeholders>` from the slice plan (description, what changed, how to review, the unit-test summary, risk notes, plan path); tick the checklist items that hold; be honest about anything partial. The PR body itself is git-ignored (regenerable), so it isn't committed.

6. **Confirm, then push.** Show the user the PR title, the body, and the branch you will push, and **get explicit confirmation** (this is outward-facing). Then push:

   ```
   git push -u origin feat/<feature-slug>/<NN-slice-slug>
   ```

   This also triggers the CI workflow. Never force-push.

7. **Open the PR into main** (single line so it pastes cleanly in any shell):

   ```
   gh pr create --base main --head feat/<feature-slug>/<NN-slice-slug> --title "feat(<feature-slug>): <slice goal> [slice NN]" --body-file PR_BODY.md
   ```

   Never target a base other than `main` unless the user explicitly asks.

8. **Record the result.** Put the PR URL into the slice plan's status log and the feature README's slice table, and tick the Definition-of-Done. Optionally note that CI is now running on the PR and they can require those checks before merge (see `tdd-ci`).

9. **Report to the user (required — this is how branches stay tidy).** End the run with an explicit, scannable summary so nothing is silently left behind:
   - **New branch created:** name the branch you cut and pushed (`feat/<feature-slug>/<NN-slice-slug>`), and that it now exists both locally and on `origin`.
   - **PR opened:** the title and URL, into `main`.
   - **Cleanup reminder:** state plainly that this slice left a feature branch behind, and that **once the PR is merged or closed** they should run **`safe-cleanup`** to retire the now-stale local branch (it reports first and confirms before deleting, and records recovery SHAs). This matters for repo hygiene — every slice adds a branch, so they accumulate fast.

   Surface this every time you open a PR, even mid-pipeline under `tdd-harness` — a one-time reminder at the end of a multi-slice session is easy to miss. Keep it short, but never skip the branch name or the cleanup nudge.

## Safety rules (non-negotiable)

- **Confirm before any push or `gh pr create`** — these are outward-facing and visible to the team.
- **Never force-push**, never rewrite shared history, never push directly to `main`.
- **Base is always `main`** unless the user says otherwise.
- **Open the PR only on green** with evidence attached. A PR without real test evidence defeats the purpose.
- Don't include secrets, tokens, or large binaries beyond the necessary evidence. Keep videos short; rely on `'retain-on-failure'` if artifacts get heavy.

## What the reviewer gets

A PR whose description proves the slice works: the behaviour described in plain language, the failing-then-passing acceptance test, the unit-test summary, a checklist, a link back to the execution plan, and **modality-appropriate evidence of it working** — embedded screenshots plus a linked recording and HTML report for a web slice, or the embedded test-run and real-invocation transcripts for a CLI/API/service slice. That is "everything a developer needs to review it and know the desired feature was built."
