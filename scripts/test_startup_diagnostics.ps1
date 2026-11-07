#requires -Version 5.1
# Local fixtures only: dot-sourcing the collector does not inspect this PC.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\assets\diagnostics\Diagnose-Rose.ps1')

function Assert-True([bool]$Value, [string]$Message) {
    if (-not $Value) { throw $Message }
}

$testDirectory = Join-Path ([IO.Path]::GetTempPath()) ('Rose diagnostic fixtures ' + [Guid]::NewGuid().ToString('N'))
$ReportDirectory = $testDirectory
$RoseVersion = 'fixture-version'
try {
    $scrubbed = Protect-Text 'C:\Users\Example\Rose token=secret Authorization: Bearer sensitive'
    Assert-True (-not ($scrubbed -match 'Example|secret|sensitive')) 'Credential/profile redaction failed.'

    Invoke-Check 'fixture.failure' 'Environment' { throw 'token=hidden' }
    $partial = [IO.File]::ReadAllText((Join-Path $testDirectory 'report.json')) | ConvertFrom-Json
    Assert-True ($partial.complete -eq $false) 'Checkpoint was not marked incomplete.'
    Assert-True ($partial.findings[0].status -eq 'UNKNOWN') 'Unavailable check was not UNKNOWN.'
    Assert-True (-not ($partial.findings[0].evidence -match 'hidden')) 'Check failure leaked a token.'
    Assert-True (([IO.File]::ReadAllText((Join-Path $testDirectory 'report.txt'))) -match 'INCOMPLETE') 'Text checkpoint lacks incomplete marker.'

    Invoke-Check 'fixture.success' 'Environment' { Add-Finding 'fixture.success' 'Environment' 'PASS' 'Fixture succeeded.' }
    Write-Reports -Quiet
    $complete = [IO.File]::ReadAllText((Join-Path $testDirectory 'report.json')) | ConvertFrom-Json
    Assert-True ($complete.complete -eq $true) 'Final report was not marked complete.'
    Assert-True ($complete.roseVersion -eq 'fixture-version') 'Rose version missing.'
    Assert-True ($complete.findings.Count -eq 2) 'Partial findings were lost.'
    Assert-True (-not (([IO.File]::ReadAllText((Join-Path $testDirectory 'report.txt'))) -match 'INCOMPLETE')) 'Completed text report still says incomplete.'
    Write-Output 'Startup diagnostic fixtures passed.'
} finally {
    # Delete only the two known files created by this fixture.
    foreach ($name in @('report.json', 'report.txt')) {
        $path = Join-Path $testDirectory $name
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
    }
    if (Test-Path -LiteralPath $testDirectory) { [IO.Directory]::Delete($testDirectory) }
}
