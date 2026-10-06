<#
.SYNOPSIS
    Runs the daily story agent against policy-back's ready-labeled GitHub
    issues, using the local Claude Code CLI and ~/.claude/agents/.

.DESCRIPTION
    Invoked by a Windows Scheduled Task at 10:00 AM daily. Because Task
    Scheduler simply does not fire while the machine is off/asleep, this
    naturally satisfies "only run if my PC is active" — no extra check
    needed. If the PC is asleep (not off) at trigger time, Task Scheduler
    is configured to run the task as soon as the system wakes.

    Uses `claude -p` (headless/non-interactive) with the prompt in
    .claude/daily-story-agent.md. Runs with --permission-mode
    bypassPermissions since nobody is present to approve prompts — the
    story agent's own guardrails (see that file) are what keep it safe,
    not interactive confirmation.

.NOTES
    Register once with:
        schtasks /create /tn "PolicyPlatform Daily Story Agent" ^
            /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"C:\VarunProjects\2026\MistrV\PolicyPlatform\policy-back\scripts\daily-story-agent.ps1\"" ^
            /sc daily /st 10:00 /rl LIMITED

    Or use scripts/register-daily-story-agent-task.ps1 (recommended —
    also sets wake-to-run and battery options).
#>

$ErrorActionPreference = 'Stop'

$RepoRoot   = 'C:\VarunProjects\2026\MistrV\PolicyPlatform\policy-back'
$PromptFile = Join-Path $RepoRoot '.claude\daily-story-agent.md'
$LogDir     = Join-Path $RepoRoot '.claude\logs'
$Timestamp  = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$LogFile    = Join-Path $LogDir "daily-story-agent_$Timestamp.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Set-Location $RepoRoot

# Refuse to run against a dirty tree — avoid the agent committing on top
# of unrelated local changes.
$gitStatus = git status --porcelain
if ($gitStatus) {
    "[$Timestamp] Skipped: working tree is dirty, refusing to run unattended." |
        Tee-Object -FilePath $LogFile -Append
    exit 1
}

$prompt = Get-Content -Raw -Path $PromptFile

"[$Timestamp] Starting daily story agent run..." | Tee-Object -FilePath $LogFile -Append

# claude.cmd on PATH; -p = headless print mode, exits when done.
& claude -p $prompt `
    --permission-mode bypassPermissions `
    --output-format stream-json `
    *>&1 | Tee-Object -FilePath $LogFile -Append

"[$(Get-Date -Format 'yyyy-MM-dd_HHmmss')] Run finished, exit code $LASTEXITCODE." |
    Tee-Object -FilePath $LogFile -Append

exit $LASTEXITCODE
