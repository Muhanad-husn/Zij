# git-guard.ps1 — Bash gate (Phase 3, DEC-3/DEC-22, revised by DEC-35).
# Two scopes:
#   -Scope global   (default) — wired in .claude/settings.json, fires on EVERY Bash
#                   call from any session. Denies only direct `git commit` on `main`.
#                   It must NOT block merge/push paths: those are approval-gated
#                   orchestrator actions (founder approves, the main session runs
#                   them), not founder-executed and not globally forbidden.
#   -Scope subagent — wired in each Bash-capable subagent's frontmatter. Adds the
#                   subagents-never-merge checks on top:
#                     - local `git merge`
#                     - `gh api ...merge...` (REST merge of a PR or branch)
#                     - `git push ... main` (push to the protected branch)
#                     - `git branch -d/-D` (branch deletion — cleanup is the
#                       orchestrator's, on founder approval)
#                   (`gh pr merge` stays blocked per-role by block-merge.ps1.)
# Matching is deliberately broad substring scanning (DEC-26): for a gate, a false
# positive is safe; a false negative defeats it. With merge tokens now
# subagent-scoped, orchestrator commits/PR bodies that merely mention them no
# longer trip the gate.

param([string]$Scope = 'global')

$ErrorActionPreference = 'Stop'

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

if ($Scope -eq 'subagent') {
    # Local git merge (but not "gh pr merge", which has no "git merge" token).
    if ($cmd -match '(?i)\bgit\s+merge\b') {
        Deny "BLOCKED: subagents never merge. Prepare the PR; the main session merges after founder approval."
    }
    # REST merge via gh api: PR merge is /pulls/{n}/merge (singular); branch merge is
    # /merges (plural). Match either.
    if ($cmd -match '(?i)\bgh\s+api\b' -and $cmd -match '(?i)merge') {
        Deny "BLOCKED: subagents never merge. No 'gh api ...merge'. Prepare the PR; the main session merges after founder approval."
    }
    # Push to main (origin main, HEAD:main, origin/main; not 'main-foo').
    if ($cmd -match '(?i)\bgit\s+push\b' -and $cmd -match '(?i)(^|[\s/:])main(\s|:|$)') {
        Deny "BLOCKED: subagents never push to main. Push the feature branch and prepare a PR; the main session merges after founder approval."
    }
    # Branch deletion — cleanup is the orchestrator's job, gated on founder approval.
    if ($cmd -match '(?i)\bgit\s+branch\b' -and $cmd -match '(?i)(^|\s)-(d|D)\b') {
        Deny "BLOCKED: subagents never delete branches. Report the candidate; the main session runs safe-cleanup after founder approval."
    }
}

# Direct commit on the main branch (both scopes).
if ($cmd -match '(?i)\bgit\s+commit\b') {
    $projRaw = $env:CLAUDE_PROJECT_DIR
    if ([string]::IsNullOrWhiteSpace($projRaw)) { $projRaw = (Get-Location).Path }
    $branch = (& git -C $projRaw rev-parse --abbrev-ref HEAD 2>$null)
    if ($branch -eq 'main') {
        Deny "BLOCKED: no direct commits on main. Work on a branch; merge via PR after founder approval."
    }
}

exit 0
