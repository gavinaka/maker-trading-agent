[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('morning', 'midday', 'evening')]
    [string]$Slot
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = (Get-Command py.exe -ErrorAction Stop).Source

& $python -m runtime_vnext.maker_schedule --root $root --slot $Slot --send
exit $LASTEXITCODE
