# spec-freeze.ps1 — the spec area is frozen during implementation (Phase 3, DEC-5/DEC-10).
# Global PreToolUse hook on Edit|Write. Denies any write whose target is under
# design/ (Zij's spec/contract/ADR layer). The script decides from the stdin path
# rather than an `if: Edit(design/**)` filter, so it is robust to Windows absolute
# paths. Non-design writes pass through (exit 0).
#
# SPEC-AUTHORING MODE (DEC-37): this global hook also blocks the spec-author subagent
# (global hooks apply to subagents too). To run a deliberate spec-authoring pass, the
# orchestrator (on founder approval) creates the gitignored flag file
# `.claude/spec-mode`; while it exists the freeze is lifted. Delete it when the pass
# ends. No settings edits, no commented-out hook to forget to restore.
# See docs/agentic-build.md.

$ErrorActionPreference = 'Stop'

$raw = [Console]::In.ReadToEnd()
try { $hook = $raw | ConvertFrom-Json } catch { exit 0 }
$path = $hook.tool_input.file_path
if ([string]::IsNullOrWhiteSpace($path)) { exit 0 }

$projRaw = $env:CLAUDE_PROJECT_DIR
if ([string]::IsNullOrWhiteSpace($projRaw)) { $projRaw = (Get-Location).Path }

# Spec-authoring mode: the founder-toggled flag file lifts the freeze entirely.
if (Test-Path (Join-Path $projRaw '.claude/spec-mode')) { exit 0 }

$proj = ($projRaw -replace '\\', '/').TrimEnd('/')
$p = $path -replace '\\', '/'

if ($p.ToLower().StartsWith(($proj.ToLower() + '/'))) {
    $rel = $p.Substring($proj.Length + 1)
}
else {
    $rel = $p
}
if ($rel.StartsWith('./')) { $rel = $rel.Substring(2) }
$rel = $rel.TrimStart('/')

if ($rel -match '(?i)^design/') {
    @{
        hookSpecificOutput = @{
            hookEventName            = 'PreToolUse'
            permissionDecision       = 'deny'
            permissionDecisionReason = "BLOCKED (spec-freeze): design/ is frozen during implementation (got '$rel'). If the spec is wrong, raise a spec-drift issue; the founder enables spec-authoring mode for a deliberate fix."
        }
    } | ConvertTo-Json -Compress -Depth 5
    exit 0
}

exit 0
