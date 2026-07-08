# format.ps1 — PostToolUse formatter (Phase 3, DEC-37). Never blocks.
# Runs the profile's formatter (ruff format) on an edited Python file. Any failure is
# swallowed: formatting is a convenience, never a gate.

$ErrorActionPreference = 'Continue'

try { $hook = [Console]::In.ReadToEnd() | ConvertFrom-Json } catch { exit 0 }
$path = "$($hook.tool_input.file_path)"
if ($path -and $path -match '(?i)\.py$' -and (Test-Path $path)) {
    $projRaw = $env:CLAUDE_PROJECT_DIR
    if ([string]::IsNullOrWhiteSpace($projRaw)) { $projRaw = (Get-Location).Path }
    Push-Location $projRaw
    try { & uv run ruff format $path 2>$null | Out-Null } catch { } finally { Pop-Location }
}
exit 0
