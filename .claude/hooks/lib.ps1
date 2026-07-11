# lib.ps1 — shared helpers dot-sourced by the PreToolUse hooks (#119).
#
# The one function here normalizes a hook-payload `cwd` before it is handed to
# `git -C`. Subagent Bash tool calls can deliver `cwd` in MSYS/POSIX form
# (e.g. `/d/zij-wt/wt-114`), which PowerShell's `git -C` cannot resolve
# (`fatal: cannot change to '/d/...'`). Left un-normalized, git-guard.ps1 and
# tests-green.ps1 both fell back to CLAUDE_PROJECT_DIR — the launching checkout,
# on `main` — and misread a feature-branch worktree commit as a commit on main,
# denying every worktree commit (#119). This is factored into one place so the
# two call sites cannot drift.

function ConvertTo-HookPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $Path }
    # Map a leading POSIX drive segment `/x/...` (or bare `/x`) to Windows `X:/...`.
    # `/tmp`, `/usr`, and other multi-letter roots do NOT match (the drive letter
    # must be immediately followed by `/` or end-of-string), so only genuine
    # single-letter-drive paths are rewritten. Already-Windows paths (`D:\..`,
    # `D:/..`) don't match either and pass through untouched.
    if ($Path -match '^/([A-Za-z])(/.*)?$') {
        $drive = $Matches[1].ToUpper()
        $rest = $Matches[2]
        if ([string]::IsNullOrEmpty($rest)) { $rest = '/' }
        return "${drive}:$rest"
    }
    return $Path
}
