# path-guard.test.ps1 — exit-decision battery for deny.ps1 (the per-role path guard).
#
# Added with the fixer role (DEC-39). Proves the new 'fixer' arm denies design/ and
# **/tests/ while allowing product code, on BOTH wirings (frontmatter -Role and the
# global agent_type backstop), and re-checks the three pre-existing roles so the new
# arm did not disturb them.
#
# Self-contained: no Pester, no product suite. Run directly:
#   pwsh -NoProfile -File .claude/hooks/tests/path-guard.test.ps1
# Exits 0 only if every assertion passes; prints one line per check.

$ErrorActionPreference = 'Stop'
$hooksDir = Split-Path -Parent $PSScriptRoot
$deny = Join-Path $hooksDir 'deny.ps1'

# Resolve the repo this test lives in, so target paths land under a real git toplevel
# (deny.ps1 normalizes against the target's own toplevel — the file need not exist,
# only an ancestor dir must, which backend/, design/, backend/tests/ all satisfy).
$repo = (& git -C $PSScriptRoot rev-parse --show-toplevel 2>$null)
if ([string]::IsNullOrWhiteSpace($repo)) { Write-Host "cannot resolve repo toplevel"; exit 1 }

$fails = 0
function Check([string]$name, [bool]$ok) {
    if ($ok) { Write-Host "  ok   $name" }
    else { Write-Host "  FAIL $name"; $script:fails++ }
}

# Feed deny.ps1 a payload and report whether it denied. $role='' exercises the global
# backstop (role read from agent_type); a non-empty $role exercises the frontmatter
# layer (passed as -Role, agent_type omitted).
function IsDenied([string]$role, [string]$agentType, [string]$relPath) {
    $target = (Join-Path $repo $relPath)
    $payload = @{ tool_input = @{ file_path = $target } }
    if (-not [string]::IsNullOrWhiteSpace($agentType)) { $payload.agent_type = $agentType }
    $json = $payload | ConvertTo-Json -Compress
    if ([string]::IsNullOrWhiteSpace($role)) {
        $out = $json | & pwsh -NoProfile -File $deny 2>$null
    } else {
        $out = $json | & pwsh -NoProfile -File $deny -Role $role 2>$null
    }
    return ("$out" -match '"permissionDecision"\s*:\s*"deny"')
}

# --- fixer, frontmatter layer (-Role fixer) ----------------------------------
Check "fixer: design/ denied (frontmatter)"       (IsDenied 'fixer' '' 'design/docs/x.md')
Check "fixer: backend/tests/ denied (frontmatter)" (IsDenied 'fixer' '' 'backend/tests/test_x.py')
Check "fixer: backend/ allowed (frontmatter)"      (-not (IsDenied 'fixer' '' 'backend/x.py'))
Check "fixer: frontend/ allowed (frontmatter)"     (-not (IsDenied 'fixer' '' 'frontend/x.js'))

# --- fixer, global backstop layer (agent_type=fixer, no -Role) ----------------
# This is the DEC-37 double-wiring: without the 'fixer' switch arm this path would
# hit default and pass through, silently un-guarding the fixer.
Check "fixer: design/ denied (global agent_type)"       (IsDenied '' 'fixer' 'design/docs/x.md')
Check "fixer: backend/tests/ denied (global agent_type)" (IsDenied '' 'fixer' 'backend/tests/test_x.py')
Check "fixer: backend/ allowed (global agent_type)"      (-not (IsDenied '' 'fixer' 'backend/x.py'))

# --- regression: the three pre-existing roles are unchanged -------------------
Check "implementer: tests denied"     (IsDenied 'implementer' '' 'backend/tests/test_x.py')
Check "implementer: design denied"    (IsDenied 'implementer' '' 'design/docs/x.md')
Check "implementer: backend allowed"  (-not (IsDenied 'implementer' '' 'backend/x.py'))
Check "test-author: backend denied"   (IsDenied 'test-author' '' 'backend/x.py')
Check "test-author: tests allowed"    (-not (IsDenied 'test-author' '' 'backend/tests/test_x.py'))
Check "spec-author: backend denied"   (IsDenied 'spec-author' '' 'backend/x.py')
Check "spec-author: design allowed"   (-not (IsDenied 'spec-author' '' 'design/specs/x.md'))

if ($fails -gt 0) { Write-Host "`n$fails check(s) FAILED"; exit 1 }
Write-Host "`nAll checks passed"; exit 0
