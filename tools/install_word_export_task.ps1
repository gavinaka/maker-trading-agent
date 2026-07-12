[CmdletBinding()]
param(
    [string]$TaskName = 'AkaGavin-TradingSystem-WordExport',
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path

if ($Uninstall) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    $heartbeat = Join-Path $root 'runtime_state\word_export_broker_heartbeat.json'
    if (Test-Path -LiteralPath $heartbeat) {
        Remove-Item -LiteralPath $heartbeat -Force
    }
    [pscustomobject]@{
        task_name = $TaskName
        status = 'uninstalled'
        existed = [bool]$existing
    } | ConvertTo-Json
    exit 0
}

$python = (Get-Command py.exe -ErrorAction Stop).Source
$broker = (Resolve-Path -LiteralPath (Join-Path $root 'outputs\word_export_broker.py')).Path
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
if (-not $user -or $user -match '^(NT AUTHORITY\\SYSTEM|SYSTEM)$') {
    throw 'The Word export task must be installed by the interactive desktop user.'
}
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and $existing.State -eq 'Running') {
    Stop-ScheduledTask -TaskName $TaskName
    do {
        Start-Sleep -Milliseconds 200
        $existing = Get-ScheduledTask -TaskName $TaskName
    } while ($existing.State -eq 'Running')
}

$arguments = '"{0}" --root "{1}" --watch' -f $broker, $root
$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $arguments `
    -WorkingDirectory $root
$principal = New-ScheduledTaskPrincipal `
    -UserId $user `
    -LogonType Interactive `
    -RunLevel Limited
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Persistent hash-bound interactive Word PDF export broker for Trading-System Word QA.' `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2
$task = Get-ScheduledTask -TaskName $TaskName
[pscustomobject]@{
    task_name = $TaskName
    status = $task.State.ToString()
    user = $user
    logon_type = $task.Principal.LogonType.ToString()
    run_level = $task.Principal.RunLevel.ToString()
    executable = $python
    broker = $broker
    heartbeat = (Join-Path $root 'runtime_state\word_export_broker_heartbeat.json')
} | ConvertTo-Json
