[CmdletBinding()]
param(
    [switch]$Run
)

$ErrorActionPreference = 'Stop'

if (-not $Run) {
    Write-Host 'Opt-in only. Re-run with -Run from an elevated administrator PowerShell.'
    exit 2
}

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error 'This integration test requires an elevated administrator PowerShell.'
    exit 2
}

$target = "RosePenguIntegration-$([guid]::NewGuid().ToString('N')).exe"
if (-not $target.StartsWith('RosePenguIntegration-', [StringComparison]::Ordinal)) {
    throw "Refusing unsafe integration target: $target"
}

$root = Split-Path -Parent $PSScriptRoot
$project = Join-Path $root 'vendor/PenguLoader-1.1.6/tests/PenguLoader.Tests.csproj'
$registryKey = "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\$target"
$exitCode = 1

try {
    $env:ROSE_PENGU_IFEO_INTEGRATION = '1'
    $env:ROSE_PENGU_IFEO_TARGET = $target

    # Restore is intentional: test/obj/project.assets.json is generated and
    # may not exist in a clean checkout.
    dotnet test $project -c Release /p:SignAssembly=false --filter 'FullyQualifiedName~OptIn_fake_target_preserves_sentinel_and_key'
    $exitCode = $LASTEXITCODE
}
finally {
    try {
        $null = reg.exe query $registryKey 2>$null
        if ($LASTEXITCODE -eq 0) {
            reg.exe delete $registryKey /f | Out-Host
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "IFEO cleanup returned exit code $LASTEXITCODE for $registryKey"
            }
        }
        else {
            Write-Host "No integration target key existed; cleanup was not needed."
        }
    }
    catch {
        Write-Warning "IFEO cleanup failed for ${registryKey}: $($_.Exception.Message)"
    }
    Remove-Item Env:ROSE_PENGU_IFEO_INTEGRATION -ErrorAction SilentlyContinue
    Remove-Item Env:ROSE_PENGU_IFEO_TARGET -ErrorAction SilentlyContinue
}

exit $exitCode
