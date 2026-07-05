# spec-freeze.ps1 — the spec area is frozen during implementation (Phase 3, DEC-5/DEC-10).
# Global PreToolUse hook on Edit|Write. Denies any write whose target is under
# design/ (Zij's spec/contract/ADR layer). The script decides from the stdin path
# rather than an `if: Edit(design/**)` filter, so it is robust to Windows absolute
# paths. Non-design writes pass through (exit 0).
#
# SPEC-AUTHORING MODE: this global hook also blocks the spec-author subagent
# (global hooks apply to subagents too). To run a deliberate spec-authoring pass,
# the founder comments this hook out of .claude/settings.json (the "Spec-freeze"
# PreToolUse entry), lets the spec-author work against an adjudicated spec-drift
# issue, then restores it. See docs/agentic-build.md.

$ErrorActionPreference = 'Stop'

$raw = [Console]::In.ReadToEnd()
try { $hook = $raw | ConvertFrom-Json } catch { exit 0 }
$path = $hook.tool_input.file_path
if ([string]::IsNullOrWhiteSpace($path)) { exit 0 }

$projRaw = $env:CLAUDE_PROJECT_DIR
if ([string]::IsNullOrWhiteSpace($projRaw)) { $projRaw = (Get-Location).Path }
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
