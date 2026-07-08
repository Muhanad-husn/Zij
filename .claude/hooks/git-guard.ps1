# git-guard.ps1 — Bash gate (Phase 3, DEC-3/DEC-22, revised by DEC-35, double-wired by DEC-37).
# Two wirings, one script (DEC-18/DEC-37):
#   - Global (settings.json, no -Scope): fires on EVERY Bash call. It applies the
#     no-commit-on-`main` rule to everyone, and additionally applies the full
#     subagents-never-merge set WHEN the stdin payload carries `agent_type` (i.e. a
#     subagent is running). The orchestrator has no agent_type, so its approval-gated
#     merge / push / cleanup paths stay open.
#   - Frontmatter (-Scope subagent): the same subagent set, wired on each Bash-capable
#     role as a second layer in case a global-hook edit hasn't reloaded.
# Subagents-never-merge set: local `git merge`, `gh pr merge`, `gh api ...merge...`,
# push to `main`, and `git branch -d/-D` (cleanup is the orchestrator's, on approval).
# Matching is deliberately broad substring scanning (DEC-26): for a gate, a false
# positive is safe; a false negative defeats it. Because the merge tokens are now
# gated only for subagents, orchestrator commits / PR bodies that merely mention them
# no longer trip the gate.

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

# Direct commit on the main branch (everyone).
if ($cmd -match '(?i)\bgit\s+commit\b') {
    $projRaw = $env:CLAUDE_PROJECT_DIR
    if ([string]::IsNullOrWhiteSpace($projRaw)) { $projRaw = (Get-Location).Path }
    $branch = (& git -C $projRaw rev-parse --abbrev-ref HEAD 2>$null)
    if ($branch -eq 'main') {
        Deny "BLOCKED: no direct commits on main. Work on a branch; merge via PR after founder approval."
    }
}

exit 0
