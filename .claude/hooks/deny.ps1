# deny.ps1 — per-role path guard (Phase 3, DEC-17).
# Fired from a role subagent's own PreToolUse frontmatter on every Edit|Write.
# Reads the hook payload from stdin, extracts the target file path, and applies
# per-role allow/deny. Fail-closed: anything unparseable or unknown is denied.
#
# Allowed write roots:
#   spec-author  -> design/ only
#   test-author  -> any **/tests/ directory only
#   implementer  -> everything EXCEPT design/ and **/tests/
#
# Block via the documented PreToolUse contract: emit a permissionDecision=deny
# JSON object on stdout and exit 0 (see https://code.claude.com/docs/en/hooks).
# Allow = exit 0 with no output (defers to normal permission flow, so global
# hooks like spec-freeze still apply).

param([Parameter(Mandatory = $true)][string]$Role)

$ErrorActionPreference = 'Stop'

function Deny([string]$reason) {
    $payload = @{
        hookSpecificOutput = @{
            hookEventName            = 'PreToolUse'
            permissionDecision       = 'deny'
            permissionDecisionReason = $reason
        }
    }
    $payload | ConvertTo-Json -Compress -Depth 5
    exit 0
}

$raw = [Console]::In.ReadToEnd()
try {
    $hook = $raw | ConvertFrom-Json
}
catch {
    Deny "path-guard ($Role): could not parse hook input (fail-closed)."
}

$path = $hook.tool_input.file_path
if ([string]::IsNullOrWhiteSpace($path)) {
    Deny "path-guard ($Role): no file_path in tool input (fail-closed)."
}

# Normalize to a project-relative, forward-slash path.
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

$underDesign = $rel -match '(?i)^design/'
$underTests = $rel -match '(?i)(^|/)tests/'

switch ($Role) {
    'spec-author' {
        if (-not $underDesign) {
            Deny "spec-author may write only under design/ (got '$rel')."
        }
    }
    'test-author' {
        if (-not $underTests) {
            Deny "test-author may write only under a tests/ directory (got '$rel')."
        }
    }
    'implementer' {
        if ($underDesign) {
            Deny "implementer may not edit specs under design/ (got '$rel'). Raise a spec-drift issue instead."
        }
        if ($underTests) {
            Deny "implementer may not edit tests (got '$rel'). The outer test is the locked contract."
        }
    }
    default {
        Deny "path-guard: unknown role '$Role' (fail-closed)."
    }
}

# Allowed: no output, defer to normal flow.
exit 0
