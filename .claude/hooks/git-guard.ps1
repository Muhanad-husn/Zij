# git-guard.ps1 — Bash gate (Phase 3, DEC-3/DEC-22, revised by DEC-35, double-wired by DEC-37,
# tightened by #71).
# Two wirings, one script (DEC-18/DEC-37):
#   - Global (settings.json, no -Scope): fires on EVERY Bash call. It applies the
#     no-commit-on-`main` rule to everyone, and additionally applies the full
#     subagents-never-merge set WHEN the stdin payload carries `agent_type` (i.e. a
#     subagent is running). The orchestrator has no agent_type, so its approval-gated
#     merge / push / cleanup paths stay open.
#   - Frontmatter (-Scope subagent): the same subagent set, wired on each Bash-capable
#     role as a second layer in case a global-hook edit hasn't reloaded.
# Subagents-never-merge set: local `git merge`, `gh pr merge`, `gh api` merge endpoints,
# push to `main`, and `git branch -d/-D/--delete` (cleanup is the orchestrator's, on approval).
#
# Matching stays deliberately broad (DEC-26: for a gate a false positive is safe, a false
# negative defeats it) but is SEGMENT-SCOPED since #71: every two-token rule requires both
# tokens inside one command segment (no `| ; &` or newline between them). Whole-blob
# scanning let unrelated text in a compound/multiline command — a Python `for` loop in a
# heredoc, a file path, a commit-message mention — satisfy the second token of a rule whose
# first token matched elsewhere, denying commands that mutate nothing.
# $SEG matches the allowed filler between two tokens of the same invocation.

param([string]$Scope = 'global')

$ErrorActionPreference = 'Stop'

# Filler between tokens of one command segment: anything except a pipe, command
# separator, or newline. Conservative on purpose — quoted separators inside one
# segment still end the match window, which can only over-block, never under-block.
$SEG = "[^|;&`r`n]*"

function Deny([string]$reason) {
    @{
        hookSpecificOutput = @{
            hookEventName            = 'PreToolUse'
            permissionDecision       = 'deny'
            permissionDecisionReason = $reason
        }
    } | ConvertTo-Json -Compress -Depth 5
    exit 0
}

$raw = [Console]::In.ReadToEnd()
try { $hook = $raw | ConvertFrom-Json } catch { exit 0 }  # unparseable: let normal flow decide
$cmd = $hook.tool_input.command
if ([string]::IsNullOrWhiteSpace($cmd)) { exit 0 }

# A subagent is running if the frontmatter said so OR stdin carries agent_type.
$isSubagent = ($Scope -eq 'subagent') -or (-not [string]::IsNullOrWhiteSpace("$($hook.agent_type)"))

if ($isSubagent) {
    # Local git merge (but not "gh pr merge", which has no "git merge" token).
    if ($cmd -match '(?i)\bgit\s+merge\b') {
        Deny "BLOCKED: subagents never merge. Prepare the PR; the main session merges after founder approval."
    }
    # gh pr merge — the PR merge path.
    if ($cmd -match '(?i)\bgh\s+pr\s+merge\b') {
        Deny "BLOCKED: subagents never merge PRs. Prepare the PR and pause; on approval the orchestrator merges via 'gh pr merge' from the main session."
    }
    # REST merge via gh api: PR merge is /pulls/{n}/merge (singular); branch merge is
    # /merges (plural). #71: key on a merge PATH inside the same gh api segment, not the
    # bare substring 'merge' anywhere in the blob (which tripped on issue bodies and
    # unrelated compound-command text). GraphQL stays blob-broad: any gh api graphql
    # call that mentions merge is denied — mutation names vary and under-blocking a
    # merge mutation defeats the gate.
    if ($cmd -match "(?i)\bgh\s+api\b$SEG/merges?\b") {
        Deny "BLOCKED: subagents never merge. No 'gh api' merge endpoints. Prepare the PR; the main session merges after founder approval."
    }
    if ($cmd -match "(?i)\bgh\s+api\b$SEG\bgraphql\b" -and $cmd -match '(?i)merge') {
        Deny "BLOCKED: subagents never merge. No GraphQL merge mutations via 'gh api graphql'. Prepare the PR; the main session merges after founder approval."
    }
    # Push to main (origin main, HEAD:main, origin/main; not 'main-foo'). #71: the
    # 'main' token must sit in the SAME segment as 'git push', so a later command or
    # heredoc line mentioning main (e.g. backend/main) no longer trips it.
    if ($cmd -match "(?i)\bgit\s+push\b$SEG(^|[\s/:])main(\s|:|`"|'|$)") {
        Deny "BLOCKED: subagents never push to main. Push the feature branch and prepare a PR; the main session merges after founder approval."
    }
    # Branch deletion — cleanup is the orchestrator's job, gated on founder approval.
    # #71: the delete flag must sit in the SAME segment as 'git branch' (a `-d`/`-D` or
    # loop keyword elsewhere in a compound command no longer trips it). Also closes a
    # pre-existing false negative: `--delete` now matches alongside -d/-D.
    if ($cmd -match "(?i)\bgit\s+branch\b$SEG(\s)(-(d|D)\b|--delete\b)") {
        Deny "BLOCKED: subagents never delete branches. Report the candidate; the main session runs safe-cleanup after founder approval."
    }
    # Remote branch deletion via push (`git push --delete origin foo`).
    if ($cmd -match "(?i)\bgit\s+push\b$SEG\s--delete\b") {
        Deny "BLOCKED: subagents never delete branches (remote included). Report the candidate; the main session runs safe-cleanup after founder approval."
    }
}

# Direct commit on the main branch (everyone). #71 / DEC-37 hooks rule 4: resolve the
# branch from the tool call's cwd — CLAUDE_PROJECT_DIR stays bound to the launching
# checkout and misfires under git worktrees (both directions: it would allow a commit
# in a worktree sitting on main, and block a feature-branch worktree commit whenever
# the launching checkout happens to be on main). Same resolution tests-green.ps1 uses.
if ($cmd -match '(?i)\bgit\s+commit\b') {
    $opDir = "$($hook.cwd)"
    if ([string]::IsNullOrWhiteSpace($opDir)) { $opDir = $env:CLAUDE_PROJECT_DIR }
    if ([string]::IsNullOrWhiteSpace($opDir)) { $opDir = (Get-Location).Path }
    $branch = (& git -C $opDir rev-parse --abbrev-ref HEAD 2>$null)
    if ($branch -eq 'main') {
        Deny "BLOCKED: no direct commits on main. Work on a branch; merge via PR after founder approval."
    }
}

exit 0
