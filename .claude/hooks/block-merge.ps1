# block-merge.ps1 — agents-never-merge (Phase 3, DEC-3/DEC-7).
# Always denies. Wired to (a) the GitHub plugin's merge tool (global matcher) and
# (b) each Bash-capable subagent's `gh pr merge *` frontmatter guard. The
# orchestrator's approved `gh pr merge` path stays open because this hook is NOT
# wired globally onto that command.
$reason = "BLOCKED: agents never merge. Prepare the PR and ask the founder to merge; the founder merges via 'gh pr merge' from the main session."
$null = [Console]::In.ReadToEnd()
@{
    hookSpecificOutput = @{
        hookEventName            = 'PreToolUse'
        permissionDecision       = 'deny'
        permissionDecisionReason = $reason
    }
} | ConvertTo-Json -Compress -Depth 5
exit 0
