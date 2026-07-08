# deny.ps1 — per-role path guard (Phase 3, DEC-17; double-wired per DEC-37).
# Reads the hook payload from stdin, extracts the target file path, and applies
# per-role allow/deny.
#
# TWO WIRINGS, ONE SCRIPT (DEC-18/DEC-37):
#   - Frontmatter layer: each writing role passes its role explicitly
#     (`deny.ps1 -Role <role>`). Fail-closed there: an unparseable payload,
#     a missing path, or an unknown role is denied.
#   - Global backstop layer: settings.json runs `deny.ps1` with NO -Role on every
#     Edit|Write. The role is then read from the stdin `agent_type` (present only in
#     subagent calls). The orchestrator (no agent_type) and any non-writing subagent
#     pass through — a stale frontmatter snapshot (GH #18392) can no longer silently
#     disable the guard.
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

param([string]$Role = '')

$ErrorActionPreference = 'Stop'

# Whether the role was pinned by frontmatter. Fail-closed applies only then; the
# global layer must never block the orchestrator or a non-role subagent.
$explicit = -not [string]::IsNullOrWhiteSpace($Role)

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
    if ($explicit) { Deny "path-guard ($Role): could not parse hook input (fail-closed)." }
    exit 0  # global layer: unknown actor, defer to normal flow
}

# Global layer: resolve the role from the subagent's agent_type. No agent_type
# means the orchestrator (or a non-subagent context) — pass through.
if (-not $explicit) {
    $Role = "$($hook.agent_type)"
    if ([string]::IsNullOrWhiteSpace($Role)) { exit 0 }
}

$path = $hook.tool_input.file_path
if ([string]::IsNullOrWhiteSpace($path)) {
    if ($explicit) { Deny "path-guard ($Role): no file_path in tool input (fail-closed)." }
    exit 0
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
        # Frontmatter with an unknown role is a misconfiguration -> fail closed.
        # A non-writing-role subagent (Explore, general-purpose, ...) via the global
        # layer just passes through.
        if ($explicit) { Deny "path-guard: unknown role '$Role' (fail-closed)." }
        exit 0
    }
}

# Allowed: no output, defer to normal flow.
exit 0
