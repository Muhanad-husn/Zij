# git-guard.ps1 — global Bash gate (Phase 3, DEC-3).
# Fires on EVERY Bash tool call (fast string checks). Denies the merge/push paths
# the orchestrator never needs, so they are closed for orchestrator AND subagents:
#   - local `git merge`
#   - `gh api ...merges...` (REST merge of a PR)
#   - `git push ... main` (push to the protected branch)
#   - direct `git commit` while on the `main` branch
# It deliberately does NOT match `gh pr merge` — that path is left open so the
# orchestrator can merge on founder approval. Subagents are blocked from
# `gh pr merge` by their own frontmatter (block-merge.ps1), not here.

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

# Local git merge (but not "gh pr merge", which has no "git merge" token).
if ($cmd -match '(?i)\bgit\s+merge\b') {
    Deny "BLOCKED: agents never merge. No local 'git merge'. Prepare the PR; the founder merges."
}
# REST merge via gh api: PR merge is /pulls/{n}/merge (singular); branch merge is
# /merges (plural). Match either.
if ($cmd -match '(?i)\bgh\s+api\b' -and $cmd -match '(?i)merge') {
    Deny "BLOCKED: agents never merge. No 'gh api ...merge'. Prepare the PR; the founder merges."
}
# Push to main (origin main, HEAD:main, origin/main; not 'main-foo').
if ($cmd -match '(?i)\bgit\s+push\b' -and $cmd -match '(?i)(^|[\s/:])main(\s|:|$)') {
    Deny "BLOCKED: no push to main. Push your setup/* branch and open a PR; the founder merges."
}
# Direct commit on the main branch.
if ($cmd -match '(?i)\bgit\s+commit\b') {
    $projRaw = $env:CLAUDE_PROJECT_DIR
    if ([string]::IsNullOrWhiteSpace($projRaw)) { $projRaw = (Get-Location).Path }
    $branch = (& git -C $projRaw rev-parse --abbrev-ref HEAD 2>$null)
    if ($branch -eq 'main') {
        Deny "BLOCKED: no direct commits on main. Work on a setup/* branch; the founder merges."
    }
}

exit 0
