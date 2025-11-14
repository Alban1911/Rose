Param(
    [Parameter(Mandatory = $false)]
    [string]$SubmoduleMessage = "Update submodule from root repository",

    [Parameter(Mandatory = $false)]
    [switch]$PushSubmodules,

    [Parameter(Mandatory = $false)]
    [switch]$Verbose
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-VerboseLog {
    Param(
        [string]$Message
    )

    if ($Verbose) {
        Write-Host "[submodules] $Message"
    }
}

if (-not (Test-Path ".gitmodules")) {
    throw "No .gitmodules file found. Run this script from the repository root."
}

$submoduleConfig = git config --file .gitmodules --get-regexp path 2>$null
if (-not $submoduleConfig) {
    Write-Host "No submodules configured. Nothing to do."
    exit 0
}

$updatedSubmodules = @()

foreach ($line in $submoduleConfig) {
    $parts = $line -split "\s+", 3
    if ($parts.Length -lt 3) {
        continue
    }

    $path = $parts[2]
    if (-not (Test-Path $path)) {
        Write-Warning "Submodule path '$path' not found. Skipping."
        continue
    }

    Write-VerboseLog "Processing submodule '$path'."
    Push-Location $path
    try {
        $status = git status --porcelain
        if ([string]::IsNullOrWhiteSpace($status)) {
            Write-VerboseLog "No changes detected in '$path'."
            continue
        }

        Write-Host "Staging and committing changes in '$path'."
        git add -A | Out-Null
        git commit -m $SubmoduleMessage | Out-Null
        Write-Host "Committed submodule '$path'."

        if ($PushSubmodules) {
            Write-Host "Pushing '$path'."
            git push | Out-Null
        }

        $updatedSubmodules += $path
    }
    finally {
        Pop-Location
    }
}

if ($updatedSubmodules.Count -eq 0) {
    Write-Host "No dirty submodules were found."
    exit 0
}

Write-Host "Staging updated submodule pointers in root repository."
foreach ($path in $updatedSubmodules) {
    git add $path | Out-Null
}

Write-Host "Done. Submodules updated:`n - " + ($updatedSubmodules -join "`n - ")

