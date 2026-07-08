# block-merge.ps1 — GitHub-plugin write gate (Phase 3, DEC-3/DEC-7, revised by DEC-37).
# Wired globally on the plugin's merge + direct-write MCP tools. Blocks, for EVERYONE
# (orchestrator included): the plugin merge tool, and any plugin direct-write
# (create_or_update_file / push_files / delete_file) whose target branch is `main`.
# The orchestrator merges via `gh pr merge` in Bash after founder approval, not through
# the plugin — so blocking the plugin merge tool for everyone costs it nothing.
# The Bash merge paths (git merge / gh pr merge / push-to-main / branch delete) are
# handled for subagents by git-guard.ps1 (DEC-37), not here.

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
try { $hook = $raw | ConvertFrom-Json } catch { exit 0 }
$tool = "$($hook.tool_name)"

# The plugin merge tool: never, for anyone.
if ($tool -match '(?i)merge') {
    Deny "BLOCKED: the GitHub plugin merge tool is never used. Prepare the PR and pause for founder approval; on approval the orchestrator merges via 'gh pr merge' from the main session."
}

# Direct writes to main through the plugin bypass git entirely — block them.
if ($tool -match '(?i)(create_or_update_file|push_files|delete_file)$') {
    $branch = "$($hook.tool_input.branch)"
    if ($branch -eq 'main' -or $branch -eq 'refs/heads/main') {
        Deny "BLOCKED: no direct writes to main through the GitHub plugin. Commit to a branch and open a PR; the main session merges after founder approval."
    }
}

exit 0
