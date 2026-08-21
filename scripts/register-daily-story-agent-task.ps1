<#
.SYNOPSIS
    Registers (or re-registers) the Windows Scheduled Task that runs the
    daily story agent at 10:00 AM.

.DESCRIPTION
    One-time setup. Run this once from an elevated or normal PowerShell
    prompt (elevation not required for a per-user task):

        cd C:\VarunProjects\2026\MistrV\PolicyPlatform\policy-back
        .\scripts\register-daily-story-agent-task.ps1

    Behavior:
      - Fires daily at 10:00 AM.
      - Only actually runs if the PC is on at that time (Task Scheduler
        does not fire on a powered-off machine) — this is what
        satisfies "if my PC is active".
      - WakeToRun is left OFF by default (does not force-wake a sleeping
        PC just to run this). Flip -WakeToRun to enable that if you'd
        rather it ran even through sleep.
      - If the PC was off/asleep at 10am and misses the run, it does
        NOT auto-catch-up later — by design, so you don't come back to
        a surprise PR from 6 hours ago with no context. Run manually via
        the same script's underlying .ps1, or `claude -p` with the
        prompt file, if you want to catch up by hand.

.PARAMETER Time
    Trigger time, 24h HH:mm. Default 10:00.

.PARAMETER WakeToRun
    If set, allows Task Scheduler to wake a sleeping machine to run this.
#>

param(
    [string]$Time = '10:00',
    [switch]$WakeToRun
)

$ErrorActionPreference = 'Stop'

$TaskName   = 'PolicyPlatform Daily Story Agent'
$ScriptPath = Join-Path $PSScriptRoot 'daily-story-agent.ps1'

if (-not (Test-Path $ScriptPath)) {
    throw "Expected script not found at $ScriptPath"
}

$taskArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $ScriptPath + '"'
$action   = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $taskArgs

$trigger = New-ScheduledTaskTrigger -Daily -At $Time

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -WakeToRun:$WakeToRun.IsPresent

# Runs as the current interactive user, only when logged on — matches
# "if my PC is active" (a headless/off machine or the logon screen alone
# won't trigger it). Prompts once for your Windows password to store
# credentials for unattended execution.
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Limited `
    -Force

Write-Host "Registered scheduled task '$TaskName' - daily at $Time." -ForegroundColor Green
$viewCmd = 'Get-ScheduledTask -TaskName "' + $TaskName + '"'
Write-Host "View/edit: taskschd.msc, or $viewCmd" -ForegroundColor DarkGray
