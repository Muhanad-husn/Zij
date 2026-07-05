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
| 0 | Repository foundation | **DONE** | 2026-07-05 | Scaffold on `setup/00-foundation`; green baseline; no `gh repo create` (repo exists). **Server-side branch protection unavailable on free private plan (403) — deferred, see DEC-16.** Founder to merge the branch. |
| 1 | `CLAUDE.md` handbook | **DONE** (approved-by-merge) | 2026-07-05 | On `setup/01-handbook` (stacked on Phase 0). 111 lines; preserves Developer Principles; answers "who merges?" + "who edits specs, when?". Zij mappings included. **Merged into `origin/main`; merge is the founder-only Checkpoint-1 approval.** |
| 2 | Role subagents | **DONE** (approved-by-merge) | 2026-07-05 | Five roles in `.claude/agents/` (`setup/02-roles`, PR #1). Reviewer read-only. Per-role `deny.ps1` guard wired in frontmatter. **Merged into `origin/main` = Checkpoint-2 approval.** Live proof of the guards is a Phase-3 item (see DEC-23). |
| 3 | Hard gates (hooks) | **DONE_WITH_CONCERNS — awaiting Checkpoint 3** | 2026-07-05 | On `setup/03-hooks`. Five PowerShell scripts + `settings.json` wiring + per-role frontmatter guards. **Root cause of non-firing found & fixed (DEC-24): the `shell: powershell` + `& '…'` command form never launched the scripts; switched all wiring to `pwsh -NoProfile -File …`.** **GLOBAL gates now verified LIVE this session:** orchestrator `git merge` **blocked**; push-to-`main` **blocked**; GitHub-plugin `merge_pull_request` **blocked** (before hitting GitHub); orchestrator `gh pr merge` path **stays OPEN**; a `git commit` on a **red** suite **blocked** (tests-green, with failing tail); `design/` write **blocked** (spec-freeze). **PENDING one more restart:** the **subagent-frontmatter** gates (per-role `deny.ps1` path guard; subagent `gh pr merge` block) — the agent registry does NOT hot-reload, so the corrected frontmatter + a neutral probe agent load only on the next launch. The real `implementer` also *correctly refused* a bypass "drill" (defense-in-depth, DEC-25). |
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
| DEC-16 | **Server-side branch protection deferred → RESOLVED 2026-07-05: repo made public** by the founder, which unblocks rulesets/protection for free. On a free *private* repo GitHub had rejected both (403). Local hooks (Phase 3) remain the primary gates; branch protection is the *backstop*. Founder to enable the `protect-main` ruleset (command re-presented at Checkpoint 1/2). | Free plan can't protect a private repo; going public was the founder's chosen fix. |
| DEC-17 | **Path guards use one policy script** `deny.ps1 -Role <role>`, fired on **every** `Edit\|Write` for the three writing roles; it reads the target path from stdin and applies per-role allow/deny (**fail-closed**). Allowed roots: spec-author → `design/`; test-author → any `**/tests/`; implementer → everything **except** `design/` and `**/tests/`. | Chosen over `if:`-glob always-deny because Zij **nests tests under the code root** (`backend/tests/` inside `backend/`); pure globs can't express "allow tests, deny code". The skill explicitly sanctions the stdin-deciding fallback. |
| DEC-18 | **Reviewer written from scratch**, preserving the two-stage order (spec-compliance → code-quality) and the "does the test encode intent?" check. | The installed GitHub plugin is **MCP-only** (no bundled agents); `pr-review-toolkit` is **not installed**. Founder may install it later to layer on. |
| DEC-19 | **Triage and reviewer carry no GitHub-plugin tools** (roster locks them to Read/Grep/Glob/Bash; per docs that allowlist denies all MCP tools). They **draft/report**; the main session / sprint skills (Phase 5) do plugin writes (file issues, open PRs). | Reinforces *agents-never-merge* at the capability level: these roles literally cannot call `merge_pull_request`. |
| DEC-20 | **Hooks implemented in PowerShell** with `shell: powershell`, not bash `.sh`/`jq`. Scripts read stdin via `[Console]::In.ReadToEnd() \| ConvertFrom-Json`, use `$env:CLAUDE_PROJECT_DIR`. Applies to all Phase-3 gate scripts. | Windows host; the hook default would be Git Bash (installed) but `jq` isn't guaranteed and the sandbox Bash lacks coreutils. PowerShell is guaranteed and deterministic. |
| DEC-21 | **PreToolUse hooks block via the documented JSON contract** — emit `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"…"}}` on stdout and `exit 0` — **not** the skeleton's `exit 2`. Allow = `exit 0` with no output (defers to normal permission flow, so a role's silent-allow still lets global hooks like spec-freeze apply). | Re-verified against `code.claude.com/docs/en/hooks` (operating rule 6): current docs specify PreToolUse decisions via `permissionDecision`, superseding the reference skeleton's exit-2. |
| DEC-22 | **agents-never-merge is split to keep the orchestrator's approved merge open.** `git-guard.ps1` (global, all Bash) blocks `git merge`, `gh api …merge(s)`, push-to-`main`, and direct commits on `main` — paths the orchestrator never needs — but **deliberately lets `gh pr merge` through**. Subagents are blocked from `gh pr merge` by a per-role `PreToolUse` Bash frontmatter guard (`block-merge.ps1`, `if: Bash(gh pr merge *)`) on the four Bash-capable roles. The plugin merge tool is blocked globally via the MCP matcher. | A global block can't tell orchestrator from subagent; frontmatter is the only scope that closes `gh pr merge` for subagents while leaving it open for the founder-approved orchestrator path (DEC-3). The REST PR-merge endpoint is `/pulls/{n}/merge` (singular), so the `gh api` matcher matches `merge`, not just `merges`. |
| DEC-26 | **`git-guard` matches its trigger tokens (`git merge`, `git push … main`, `git commit`) as substrings anywhere in the Bash command string — deliberately broad and fail-safe.** Consequence observed live: a `git commit` whose **commit message** contained the words "git merge" was itself blocked. This is accepted, not fixed: for a merge gate a false positive (blocking a benign command that merely mentions the token) is safe and easily worked around (reword the message, or the founder runs it), whereas a false negative (missing a real merge) defeats the gate. Tightening to anchor on command position risks false negatives against `&&`/`;`/subshell-chained invocations. Per the 80/20 principle, kept broad + documented. Workaround for authoring commits that must discuss merges: avoid the literal two-word token, or the founder commits. | Fail-safe bias is correct for a security gate; shell-accurate command parsing is not worth the false-negative risk. |
| DEC-25 | **The subagent-level path/merge guards are verified with a temporary neutral `gatecheck-probe` agent, not the real roles — because the real roles correctly refuse the drill.** When asked (via an orchestrator "gate drill" prompt) to attempt an out-of-role write and a `gh pr merge`, the real `implementer` **refused every step and made zero tool calls**, citing CLAUDE.md ("no agent message is founder consent") — treating the drill as a suspected bypass/injection. That is exactly the desired defense-in-depth: the agent won't even try, so the hook never has to fire. But it means the hook *mechanism* can't be exercised through a compliant role. A throwaway `gatecheck-probe.md` (implementer's frontmatter guard + a neutral "mechanical harness" prompt, `model: haiku`) is used solely to trigger the guard and observe the deny; it is **kept untracked and deleted after verification — never committed**. Also learned: **new/edited agent files do NOT hot-reload** (the probe was "not found" until a restart), so this observation is deferred to the post-restart pass. | The gate must catch a *non-compliant* actor; a compliant one refuses first. Testing the hook itself requires an actor without a competing conscience, hence the neutral probe. |
| DEC-24 | **Hook scripts are invoked with `pwsh -NoProfile -File <script>.ps1 [args]`, NOT via a `shell: powershell` field + `& '…'` call-operator command.** The original wiring (`shell: powershell`, `command: "& '${CLAUDE_PROJECT_DIR}/…ps1'"`) **never launched the scripts on this Claude Code build** — a live `git merge` passed straight through and a diagnostic marker confirmed the script body never executed (no marker written). Switching every `command` (in `settings.json` **and** all five agent frontmatter guards) to `pwsh -NoProfile -File <abs-path> [args]` (unquoted; the paths have no spaces) fixed it immediately: the same `git merge` was then denied live, and the marker proved the script ran on every Bash call. This also settled DEC-21's open question — **the exit-0 + `permissionDecision` JSON contract DOES work on this build** (the deny reason surfaced to the caller), so no revert to `exit 2` was needed. Root cause was purely the invocation form, not trust, not hot-reload, not the block contract. | Empirically isolated during the 2026-07-05 resume via a marker-file probe: broken form → no marker, tool proceeds; `pwsh -File` form → marker written, tool blocked. Supersedes the DEC-23 "needs a restart" hypothesis — settings-hook edits **did** hot-reload once the command was valid. |
| DEC-23 | **Hooks do not hot-reload into an already-running session on this host.** Empirically confirmed: after writing `settings.json` + scripts, a temporary always-fire diagnostic hook never executed, `git-guard` did not block an orchestrator `git merge`/push-to-`main`, and the implementer's frontmatter `deny.ps1` did not block a write under `backend/tests/`. All five scripts pass a standalone allow/deny matrix. **Live gate verification is therefore deferred to a fresh session** (founder restarts Claude Code), after which the orchestrator re-runs the full live suite before Checkpoint 3. | Docs claim a file-watcher picks up hook edits, but it did not fire here (session predates the hooks / Windows watcher). The scripts are proven; only in-session *activation* is pending a restart. **Reconfirmed on the 2026-07-05 resume: running `/build-resume` inside the existing session does NOT load the hooks — an orchestrator `git merge --abort` executed unblocked. The founder must fully quit and relaunch Claude Code (a new process), then review/trust the hooks via `/hooks`, so the `PreToolUse` gates in `.claude/settings.json` are actually registered. Only then can the orchestrator run the live Checkpoint-3 suite.** |

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
