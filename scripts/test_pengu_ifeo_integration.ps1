[CmdletBinding()]
param(
    [switch]$Run
)

if (-not $Run) {
    Write-Output "Use .\scripts\test_pengu_ifeo_integration.ps1 -Run from an elevated administrator PowerShell."
    exit 0
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "This integration test requires an administrator session."
    exit 1
}

python (Join-Path $PSScriptRoot 'test_pengu_ifeo_integration.py')
exit $LASTEXITCODE