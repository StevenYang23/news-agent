<#
  Register a Windows Task Scheduler task that runs the daily pipeline.

  Usage (PowerShell, run from project root):
      powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Time "22:00"

  -Time: local time to run daily (default 22:00, i.e. after US market close).
  To remove: Unregister-ScheduledTask -TaskName "BuySideDailyInsights" -Confirm:$false
#>
param(
    [string]$Time = "22:00"
)

$ErrorActionPreference = "Stop"

$root   = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "scripts\run_daily.py"

if (-not (Test-Path $python)) {
    throw "Virtual env not found: $python  (run setup first)"
}

$action    = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $root
$trigger   = New-ScheduledTaskTrigger -Daily -At $Time
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName "BuySideDailyInsights" `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Description "Daily buy-side insights refresh (fetch -> summarize -> rolling retention)" `
    -Force | Out-Null

Write-Output "Scheduled task 'BuySideDailyInsights' registered to run daily at $Time."
