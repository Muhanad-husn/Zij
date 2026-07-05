# tests-green.ps1 — no commit on a red suite (Phase 3, DEC-3/DEC-8).
# Wired as a Bash PreToolUse hook gated by `if: Bash(git commit *)`, so it only
# runs the suite on a commit attempt. Runs the profile's test command
# (uv run pytest); denies the commit if it is red.

$ErrorActionPreference = 'Stop'

$projRaw = $env:CLAUDE_PROJECT_DIR
if ([string]::IsNullOrWhiteSpace($projRaw)) { $projRaw = (Get-Location).Path }
Set-Location $projRaw

$null = [Console]::In.ReadToEnd()

$output = & uv run pytest -q 2>&1
$code = $LASTEXITCODE

if ($code -eq 0) { exit 0 }

$tail = ($output | Select-Object -Last 15) -join "`n"
$reason = "BLOCKED: test suite is red (uv run pytest exit $code). Get to green before committing.`n--- tail ---`n$tail"
@{
    hookSpecificOutput = @{
        hookEventName            = 'PreToolUse'
        permissionDecision       = 'deny'
        permissionDecisionReason = $reason
    }
} | ConvertTo-Json -Compress -Depth 5
exit 0
