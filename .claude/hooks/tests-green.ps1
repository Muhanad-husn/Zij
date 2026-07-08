# tests-green.ps1 — no commit on a red suite (Phase 3, DEC-3/DEC-8; revised by DEC-37).
# Wired on the whole Bash matcher (no `if:` filter — DEC-16: an `if: Bash(git commit *)`
# filter is dodged by compound commands like `ruff check && git commit`). The script
# decides for itself: it acts only when the Bash command contains a `git commit`,
# then runs the profile's FULL test command (uv run pytest) and denies a red suite.
#
# Zij keeps the full suite per commit and uses strict-xfail (DEC-33), NOT the skill's
# `.claude/allow-red-commit` flag — the one intended red commit (the outer acceptance
# test) lands green-to-the-gate via @pytest.mark.xfail(strict=True). So there is no
# allow-red-commit escape hatch here by design.
# No-commit-on-`main` is git-guard.ps1's job; this script only gates redness.

$ErrorActionPreference = 'Stop'

$raw = [Console]::In.ReadToEnd()
try { $hook = $raw | ConvertFrom-Json } catch { exit 0 }
$cmd = "$($hook.tool_input.command)"
if ($cmd -notmatch '(?i)\bgit\s+commit\b') { exit 0 }

# Resolve the worktree this commit actually targets from the tool's cwd (DEC-37,
# hooks rule 4): CLAUDE_PROJECT_DIR stays bound to the launching checkout and misfires
# under git worktrees.
$opDir = "$($hook.cwd)"
if ([string]::IsNullOrWhiteSpace($opDir)) { $opDir = $env:CLAUDE_PROJECT_DIR }
if ([string]::IsNullOrWhiteSpace($opDir)) { $opDir = (Get-Location).Path }
$projectDir = (& git -C $opDir rev-parse --show-toplevel 2>$null)
if ([string]::IsNullOrWhiteSpace($projectDir)) { $projectDir = $opDir }

# Docs-only fast path: if every file in this commit is documentation or a plan, the
# suite result cannot change. Fails safe — any non-docs file, empty set, or error
# falls through to the suite run. `git commit -a/--all` sweeps in unstaged tracked
# edits, so fold those in when the command carries -a/--all.
try {
    $staged = @(& git -C $projectDir diff --cached --name-only 2>$null | Where-Object { $_ })
    if ($cmd -match '(^|\s)-[A-Za-z]*a[A-Za-z]*(\s|$)' -or $cmd -match '--all\b') {
        $staged += @(& git -C $projectDir diff --name-only 2>$null | Where-Object { $_ })
    }
    $files = @($staged | Select-Object -Unique)
    $nonDocs = @($files | Where-Object { -not ($_ -imatch '\.(md|txt|rst)$' -or $_ -imatch '^(plans|docs)/') })
    if ($files.Count -gt 0 -and $nonDocs.Count -eq 0) {
        [Console]::Error.WriteLine("Docs-only commit ($($files.Count) file(s)); skipping the test suite - no code changed.")
        exit 0
    }
} catch { }

Set-Location $projectDir
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
