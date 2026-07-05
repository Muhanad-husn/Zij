# block-merge.ps1 — subagents-never-merge (Phase 3, DEC-3/DEC-7, revised by DEC-35).
# Always denies. Wired to (a) the GitHub plugin's merge tool (global matcher) and
# (b) each Bash-capable subagent's `gh pr merge *` frontmatter guard. The
# orchestrator's `gh pr merge` path stays open because this hook is NOT wired
# globally onto that command: merging requires founder approval, and on approval
# the orchestrator (main session) runs it itself.
$reason = "BLOCKED: subagents never merge. Prepare the PR and pause for founder approval; on approval the orchestrator merges via 'gh pr merge' from the main session."
$null = [Console]::In.ReadToEnd()
@{
    hookSpecificOutput = @{
        hookEventName            = 'PreToolUse'
        permissionDecision       = 'deny'
        permissionDecisionReason = $reason
    }
} | ConvertTo-Json -Compress -Depth 5
exit 0
