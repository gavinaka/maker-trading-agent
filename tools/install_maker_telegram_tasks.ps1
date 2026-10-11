[CmdletBinding()]
param(
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$runner = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'run_maker_slot.ps1')).Path
$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
if (-not $user -or $user -match '^(NT AUTHORITY\\SYSTEM|SYSTEM)$') {
    throw 'Maker Telegram tasks must be installed by the interactive desktop user.'
}

$definitions = @(
    @{ Name = 'Maker Trading Agent - Morning'; Slot = 'morning'; At = [datetime]'09:00:00' },
    @{ Name = 'Maker Trading Agent - Midday'; Slot = 'midday'; At = [datetime]'16:30:00' },
    @{ Name = 'Maker Trading Agent - Evening'; Slot = 'evening'; At = [datetime]'20:30:00' }
)

if ($Uninstall) {
    $removed = @()
    foreach ($definition in $definitions) {
        $task = Get-ScheduledTask -TaskName $definition.Name -ErrorAction SilentlyContinue
        if ($task) {
            if ($task.State -eq 'Running') {
                Stop-ScheduledTask -TaskName $definition.Name -ErrorAction SilentlyContinue
            }
            Unregister-ScheduledTask -TaskName $definition.Name -Confirm:$false
            $removed += $definition.Name
        }
    }
    [pscustomobject]@{ status = 'uninstalled'; task_names = $removed } | ConvertTo-Json -Compress
    exit 0
}

$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$installed = @()
foreach ($definition in $definitions) {
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Slot {1}' -f $runner, $definition.Slot
    $action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Daily -At $definition.At
    Register-ScheduledTask `
        -TaskName $definition.Name `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description 'Send only a same-day, sealed Maker strategy. Missing evidence, certification, or credentials blocks without a Telegram message.' `
        -Force | Out-Null
    $task = Get-ScheduledTask -TaskName $definition.Name
    $installed += [pscustomobject]@{
        task_name = $definition.Name
        slot = $definition.Slot
        trigger_time = $definition.At.ToString('HH:mm')
        state = $task.State.ToString()
        user = $task.Principal.UserId
        logon_type = $task.Principal.LogonType.ToString()
    }
}
[pscustomobject]@{
    status = 'installed'
    timezone = 'Asia/Shanghai (local Windows time)'
    tasks = $installed
} | ConvertTo-Json -Depth 4
