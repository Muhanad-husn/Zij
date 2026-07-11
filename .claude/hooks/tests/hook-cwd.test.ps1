# hook-cwd.test.ps1 — regression test for #119.
#
# Proves the PreToolUse hooks cope with a POSIX-form `cwd` (e.g. `/d/zij-wt/wt-1`)
# the way a subagent Bash call delivers it: the branch must resolve from that cwd's
# real worktree, NOT fall back to CLAUDE_PROJECT_DIR (the launching checkout) and be
# misread as a commit on main.
#
# Self-contained: no Pester, no product suite. Run directly:
#   pwsh -NoProfile -File .claude/hooks/tests/hook-cwd.test.ps1
# Exits 0 only if every assertion passes; prints a one-line-per-check summary.

$ErrorActionPreference = 'Stop'
$hooksDir = Split-Path -Parent $PSScriptRoot
$guard = Join-Path $hooksDir 'git-guard.ps1'

$fails = 0
function Check([string]$name, [bool]$ok) {
    if ($ok) { Write-Host "  ok   $name" }
    else { Write-Host "  FAIL $name"; $script:fails++ }
}

# --- Unit: ConvertTo-HookPath ------------------------------------------------
. (Join-Path $hooksDir 'lib.ps1')
Check "posix drive path -> windows"      ((ConvertTo-HookPath '/d/zij-wt/wt-1') -eq 'D:/zij-wt/wt-1')
Check "posix lowercase c -> uppercase"   ((ConvertTo-HookPath '/c/Users/x')    -eq 'C:/Users/x')
Check "bare posix drive root"            ((ConvertTo-HookPath '/d')             -eq 'D:/')
Check "windows backslash unchanged"      ((ConvertTo-HookPath 'D:\Zij')         -eq 'D:\Zij')
Check "windows forwardslash unchanged"   ((ConvertTo-HookPath 'D:/Zij')         -eq 'D:/Zij')
Check "multi-letter root not a drive"    ((ConvertTo-HookPath '/tmp/x')         -eq '/tmp/x')
Check "empty passes through"             ((ConvertTo-HookPath '')               -eq '')

# --- Integration: git-guard.ps1 resolves the branch from a POSIX cwd ---------
# Build a throwaway git repo on a known branch, hand git-guard the POSIX form of
# its path as `cwd`, and check the commit-on-main verdict.
function ToPosix([string]$winPath) {
    $p = $winPath -replace '\\', '/'
    if ($p -match '^([A-Za-z]):(/.*)$') { return '/' + $Matches[1].ToLower() + $Matches[2] }
    return $p
}
function New-Repo([string]$branch) {
    $dir = Join-Path ([System.IO.Path]::GetTempPath()) ("zij-119-" + [System.IO.Path]::GetRandomFileName())
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    & git -C $dir init -q | Out-Null
    & git -C $dir checkout -q -b $branch 2>$null | Out-Null
    # A real commit so `rev-parse --abbrev-ref HEAD` resolves to $branch — on an
    # unborn branch it errors instead of naming the branch, which would let the
    # main-branch case slip past the guard.
    & git -C $dir -c user.name=t -c user.email=t@t commit -q --allow-empty -m init | Out-Null
    return $dir
}
function Guard-Denies([string]$posixCwd) {
    $payload = @{ cwd = $posixCwd; tool_input = @{ command = 'git commit -m x' } } | ConvertTo-Json -Compress
    $out = $payload | & pwsh -NoProfile -File $guard 2>$null
    return ("$out" -match '"permissionDecision"\s*:\s*"deny"')
}

$featRepo = New-Repo 'feat/test-119'
$mainRepo = New-Repo 'main'
try {
    $featPosix = ToPosix $featRepo
    $mainPosix = ToPosix $mainRepo
    # Sanity: the crafted cwd really is POSIX form (would have broken the old code).
    Check "test feeds a posix cwd"        ($featPosix -match '^/[a-z]/')
    Check "feature-branch worktree: allowed" (-not (Guard-Denies $featPosix))
    Check "main worktree: still denied"      (Guard-Denies $mainPosix)
}
finally {
    Remove-Item -Recurse -Force $featRepo, $mainRepo -ErrorAction SilentlyContinue
}

if ($fails -gt 0) { Write-Host "`n$fails check(s) FAILED"; exit 1 }
Write-Host "`nAll checks passed"; exit 0
