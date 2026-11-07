#requires -Version 5.1
<#
.SYNOPSIS
    Collect local support diagnostics for Rose's client UI and game patcher.
.DESCRIPTION
    Does not activate Pengu, run the patcher, inject, restart processes, change
    registry/security settings, download files, or upload anything. Writes only
    report.txt and report.json to a new report directory. Supports Windows
    PowerShell 5.1, including machines without Python or PowerShell 7.
.PARAMETER RosePath
    Rose installation/source directory (or Rose.exe). Auto-detected if omitted.
.PARAMETER LeaguePath
    League client directory (or LeagueClient.exe). Optional override.
.PARAMETER DataPath
    Rose user data directory. Normally the running client's user profile.
.PARAMETER OutputDirectory
    Parent folder for a new Rose-Diagnostics-* directory. Defaults to Rose logs/diagnostics.
.PARAMETER ReportDirectory
    Exact run folder reserved by the Rose tray. Enables partial report checkpoints.
.PARAMETER RoseVersion
    Version of the Rose app requesting this collection.
.PARAMETER Days
    Security event lookback, default 7 days. Queries are capped at 500 events/log.
.PARAMETER SkipNetworkChecks
    Skip the external time.windows.com clock comparison. Local checks still run.
#>
[CmdletBinding()]
param(
    [string]$RosePath,
    [string]$LeaguePath,
    [string]$DataPath,
    [string]$OutputDirectory,
    [string]$ReportDirectory,
    [string]$RoseVersion,
    [ValidateRange(1, 30)][int]$Days = 7,
    [switch]$SkipNetworkChecks
)

$ErrorActionPreference = 'Stop'
$script:Findings = New-Object 'System.Collections.Generic.List[object]'
$script:Files = New-Object 'System.Collections.Generic.List[object]'
$script:Processes = @()
$script:KnownPaths = New-Object 'System.Collections.Generic.List[string]'
$script:ProfilePaths = New-Object 'System.Collections.Generic.List[string]'
if ($env:USERPROFILE) { $script:ProfilePaths.Add($env:USERPROFILE) }
$script:NativeAvailable = $false
$script:Started = Get-Date
$script:IfeoBase = 'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options'

function Protect-Text([AllowNull()][object]$Value) {
    $text = [string]$Value
    # Never collect lockfiles, command lines, full config files, or entire logs.
    # Also scrub credentials from the small selected error excerpts we retain.
    foreach ($profilePath in $script:ProfilePaths) {
        if ($profilePath) { $text = [regex]::Replace($text, '(?i)' + [regex]::Escape($profilePath.TrimEnd('\')) + '(?=[\\/\s"'']|$)', '%USERPROFILE%') }
    }
    $text = [regex]::Replace($text, '(?i)[A-Z]:[\\/]Users[\\/][^\\/\r\n"<>]+', '%USERPROFILE%')
    $text = [regex]::Replace($text, '(?i)(--(?:remoting-auth-token|riotclient-auth-token|auth-token)=)(?:"[^"]*"|[^\s]+)', '$1<redacted>')
    $text = [regex]::Replace($text, '(?i)(authorization\s*[:=]\s*(?:basic|bearer)\s+)[A-Za-z0-9+/=_\-.]+', '$1<redacted>')
    $text = [regex]::Replace($text, '(?i)(["'']?(?:password|token|access_token|refresh_token|auth_token|api_key|installation_id|session_id|puuid|summonerName|gameName|tagLine)["'']?\s*[:=]\s*)(?:"[^"]*"|''[^'']*''|[^\s,;]+)', '$1<redacted>')
    $text = [regex]::Replace($text, '(?i)\bS-1-5-21-(?:\d+-){2,3}\d+\b', '<redacted-sid>')
    $text = [regex]::Replace($text, '\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b', '<redacted-id>')
    return $text
}

function Add-Finding([string]$Id, [string]$Stage, [string]$Status, [string]$Summary,
                     [object]$Evidence = '', [string]$NextStep = '') {
    $script:Findings.Add([pscustomobject][ordered]@{
        id = $Id; stage = $Stage; status = $Status; summary = Protect-Text $Summary
        evidence = Protect-Text $Evidence; nextStep = Protect-Text $NextStep
    })
}

function Invoke-Check([string]$Id, [string]$Stage, [scriptblock]$Action) {
    Write-Host ("Checking {0}..." -f $Id)
    try { & $Action }
    catch {
        Add-Finding $Id $Stage 'UNKNOWN' 'This check could not finish.' $_.Exception.Message `
            'If access was denied, run the checker as administrator under the same Windows account and compare reports.'
    }
    finally {
        # Preserve completed checks if a later Windows query hangs or Rose exits.
        if ($ReportDirectory) { Write-Reports -Incomplete -Quiet }
    }
}

function Test-AntivirusProducts([object[]]$Products) {
    foreach ($product in $Products) {
        Add-Finding 'antivirus.product' 'Security' 'INFO' 'Registered antivirus product (registration is not proof of blocking or current activity).' "$($product.displayName); productState=$($product.productState)" 'Third-party protection can block silently. Review its quarantine, behavior protection and block history around the failed launch; Defender events do not cover it.'
        if ($product.displayName -match '(?i)\b360\b|Qihoo') {
            Add-Finding 'antivirus.360' 'Security' 'WARN' '360/Qihoo detected: a known Rose support lead for silent interference.' $product.displayName 'Rose support has resolved a similar case by removing 360. First confirm it is still installed and review its history; presence alone does not prove the cause. If confirmed, discuss normal uninstallation and a restart with support, ensuring Windows protection is active afterward. This checker does not remove or disable protection.'
        }
    }
}

function Test-ClockSamples([string]$Output) {
    $samples = @([regex]::Matches($Output, '(?m)([+-]\d+[.,]\d+)s\s*$') | ForEach-Object {
        [double]::Parse($_.Groups[1].Value.Replace(',', '.'), [Globalization.CultureInfo]::InvariantCulture)
    } | Sort-Object)
    if ($samples.Count -lt 2) {
        Add-Finding 'clock.offset' 'Environment' 'UNKNOWN' 'Could not obtain enough time-server samples to check clock drift.' '' 'An unavailable or blocked NTP server is not proof of a wrong clock. Check Windows Date & time manually.'
        return
    }
    if (($samples[-1] - $samples[0]) -gt 10) {
        Add-Finding 'clock.offset' 'Environment' 'UNKNOWN' 'Time-server samples were inconsistent.' '' 'Check Windows Date & time and retry on a stable connection.'
        return
    }
    $offset = $samples[[int][Math]::Floor($samples.Count / 2)]
    $status = 'PASS'; if ([Math]::Abs($offset) -gt 60) { $status = 'WARN' }
    Add-Finding 'clock.offset' 'Environment' $status 'Clock comparison with time.windows.com (single source, not authenticated).' ('Median server-minus-local offset: {0:F3} seconds; samples: {1}; warning threshold: 60 seconds.' -f $offset, $samples.Count) 'If the offset is large, correct Windows Date & time, enable automatic time and use Sync now (or your organization time source), then restart Rose and League. Incorrect time can break certificate checks and time-sensitive startup. Do not backdate Windows to bypass an expired patcher.'
}

function Invoke-BoundedReadOnlyQuery([string]$FilePath, [string]$Arguments, [int]$TimeoutMs = 8000) {
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $FilePath; $start.Arguments = $Arguments
    $start.UseShellExecute = $false; $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true; $start.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process; $process.StartInfo = $start
    try {
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync(); $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutMs)) {
            $process.Kill() # Only this collector's query process.
            throw 'Read-only query timed out.'
        }
        if ($process.ExitCode -ne 0) { throw ('Read-only query exited with code ' + $process.ExitCode) }
        return $stdout.Result
    } finally { $process.Dispose() }
}

function Add-PenguConfigurationGuidance {
    $configIssues = @($script:Findings | Where-Object {
        $_.id -in @('pengu.config', 'pengu.disabled', 'pengu.loaderpath') -and $_.status -in @('FAIL', 'UNKNOWN')
    })
    if ($configIssues.Count -eq 0) { return }
    $loaded = @($script:Findings | Where-Object { $_.id -like 'pengu.loaded.*' -and $_.status -eq 'PASS' })
    $registered = @($script:Findings | Where-Object { $_.id -eq 'pengu.ifeo' -and $_.status -eq 'PASS' })
    $summary = 'Rose profile configuration needs attention; activation and configuration are separate checks.'
    if ($loaded.Count -gt 0) { $summary = 'The selected Pengu core.dll is loaded, but the inspected Rose profile configuration is missing, disabled or incomplete.' }
    elseif ($registered.Count -gt 0) { $summary = 'Pengu activation is registered, but the inspected Rose profile configuration is missing, disabled or incomplete.' }
    $configFile = if ($script:UserData) { Join-Path $script:UserData 'config.ini' } else { '(profile path unavailable)' }
    $evidence = "Config=$configFile; related findings=$($configIssues.id -join ', ')"
    $status = 'WARN'
    if ($configIssues | Where-Object status -eq 'FAIL') { $status = 'FAIL' }
    $nextStep = 'Verify the inspected DataPath belongs to the Windows account running League, especially if Rose was elevated under another account. With Rose and League closed, restore the [General] section in that account''s Rose config.ini: disabled=0 and loaderpath=<absolute Pengu Loader directory containing plugins>. Preserve other settings and save using the Windows ANSI encoding expected by this build. Then reopen Rose and League and rerun the checker. Activation success or a loaded core.dll does not prove that Rose plugins initialized. This checker does not create or overwrite config.ini.'
    if ($script:PenguDir -and (Test-Path -LiteralPath (Join-Path $script:PenguDir 'plugins') -PathType Container)) {
        $evidence += "`r`nSuggested settings (verify the loader location; replace redacted profile paths):`r`n[General]`r`ndisabled=0`r`nloaderpath=$script:PenguDir"
    } else {
        $nextStep += ' A usable plugins directory was not found at the selected loader path; locate or restore the matching Rose runtime before setting loaderpath.'
    }
    Add-Finding 'pengu.profile-config' 'Client UI' $status $summary $evidence $nextStep
}

function Add-ManualActivationGuidance {
    $hasConfigIssues = @($script:Findings | Where-Object {
        $_.id -in @('pengu.config', 'pengu.disabled', 'pengu.loaderpath') -and $_.status -in @('FAIL', 'UNKNOWN')
    }).Count -gt 0
    $issues = @($script:Findings | Where-Object {
        ($_.stage -eq 'Client UI' -and $_.id -match '^pengu\.(ifeo|symlink)' -and $_.status -in @('FAIL', 'WARN')) -or
        (-not $hasConfigIssues -and $_.id -like 'pengu.loaded.*' -and $_.status -eq 'WARN') -or
        ($_.id -eq 'log.excerpt' -and $_.evidence -match '(?i)Pengu command failed|(?:Pengu|activation|IFEO).*(?:unauthorized|access.*denied|failed)')
    })
    if ($issues.Count -eq 0) { return }
    $exe = if ($script:PenguDir) { Join-Path $script:PenguDir 'Pengu Loader.exe' } else { $null }
    if (-not $exe -or -not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        Add-Finding 'pengu.manual-activation' 'Client UI' 'UNKNOWN' 'Manual activation cannot be suggested for a missing loader executable.' $exe 'Restore the matching Pengu Loader files from your trusted Rose installation first.'
        return
    }
    $normal = Join-Path $env:LOCALAPPDATA 'Rose\Pengu Loader\Pengu Loader.exe'
    $command = 'Start-Process -FilePath "' + $exe.Replace('`', '``').Replace('$', '`$').Replace('"', '`"') + '" -ArgumentList "--install" -Wait'
    if ($exe -ieq $normal) { $command = 'Start-Process -FilePath "$env:LOCALAPPDATA\Rose\Pengu Loader\Pengu Loader.exe" -ArgumentList "--install" -Wait' }
    Add-Finding 'pengu.manual-activation' 'Client UI' 'INFO' 'Manual Pengu activation has fixed similar cases; this is a suggested repair, not a completed check.' $command 'Only if activation is still failing: close Rose and League, then run the displayed command in an administrator PowerShell under the same Windows account. For a redacted/custom path, substitute the actual loader location. This modifies Pengu activation/IFEO or its configured symlink; it is not run by this checker. Reopen Rose and League and collect a new report. If access is denied, preserve the exact error for support; do not reset registry permissions blindly.'
}

function Get-RegValues([string]$SubKey, [string]$View = 'Registry64', [string]$Hive = 'LocalMachine') {
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::$Hive, [Microsoft.Win32.RegistryView]::$View)
    try {
        $key = $base.OpenSubKey($SubKey, $false)
        if ($null -eq $key) { return $null }
        try {
            $values = @{}
            foreach ($name in $key.GetValueNames()) {
                $values[$name] = $key.GetValue($name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
            }
            return ,$values
        } finally { $key.Dispose() }
    } finally { $base.Dispose() }
}

function Get-RegChildren([string]$SubKey, [string]$View = 'Registry64') {
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine,
        [Microsoft.Win32.RegistryView]::$View)
    try {
        $key = $base.OpenSubKey($SubKey, $false)
        if ($null -eq $key) { return @() }
        try { return $key.GetSubKeyNames() } finally { $key.Dispose() }
    } finally { $base.Dispose() }
}

function Get-IniValues([string]$Path, [switch]$WindowsAnsi) {
    $values = @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return ,$values }
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -gt 1048576) { throw 'Config is unexpectedly larger than 1 MB.' }
    if ($bytes.Length -ge 2 -and $bytes[0] -eq 255 -and $bytes[1] -eq 254) {
        $text = [Text.Encoding]::Unicode.GetString($bytes, 2, $bytes.Length - 2)
    } elseif ($bytes.Length -ge 3 -and $bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191) {
        $text = [Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
    } else {
        # Match the native Windows INI API, not PowerShell 7's UTF-8 default.
        $encoding = [Text.Encoding]::UTF8
        if ($WindowsAnsi) {
            # User culture can differ from the system non-Unicode code page.
            # ACP also reflects Windows' optional UTF-8 system locale setting.
            $codePages = Get-RegValues 'SYSTEM\CurrentControlSet\Control\Nls\CodePage'
            if (-not $codePages -or -not $codePages['ACP']) { throw 'Windows ANSI code page could not be determined; refusing to guess how the native hook reads config.ini.' }
            $encoding = [Text.Encoding]::GetEncoding([int]$codePages['ACP'])
        }
        $text = $encoding.GetString($bytes)
    }
    $section = ''
    foreach ($line in ($text -split '\r?\n')) {
        if ($line -match '^\s*\[([^\]]+)\]') { $section = $Matches[1].Trim(); continue }
        if ($line -match '^\s*([^;#=]+?)\s*=\s*(.*?)\s*$') {
            $values[($section + '/' + $Matches[1].Trim()).ToLowerInvariant()] = $Matches[2]
        }
    }
    return ,$values
}

function Get-FullPath([string]$Path) {
    return [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($Path.Trim().Trim('"'))).TrimEnd('\', '/')
}

function Test-SamePath([string]$Left, [string]$Right) {
    if (-not $Left -or -not $Right) { return $false }
    try { return (Get-FullPath $Left) -ieq (Get-FullPath $Right) } catch { return $false }
}

function Get-HookTarget([string]$Debugger) {
    if ($Debugger -match '^\s*rundll32\s+"([^"]+)"\s*,\s*#6000\s*$') { return $Matches[1] }
    return $null
}

function Get-EnvironmentPathEntries([AllowNull()][string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return }
    foreach ($raw in ($Value -split ';')) {
        if ([string]::IsNullOrWhiteSpace($raw)) { continue }
        $entry = $raw.Trim()
        $badQuotes = $false
        if ($entry.StartsWith('"') -and $entry.EndsWith('"') -and $entry.Length -ge 2) {
            $entry = $entry.Substring(1, $entry.Length - 2)
        }
        if ($entry.Contains('"')) { $badQuotes = $true }
        $expanded = [Environment]::ExpandEnvironmentVariables($entry)
        $normalized = ''
        $absolute = $expanded -match '^(?:[A-Za-z]:[\\/]|\\\\[^\\]+[\\/])'
        if ($absolute -and -not $badQuotes) {
            try { $normalized = [IO.Path]::GetFullPath($expanded).TrimEnd('\', '/') } catch { }
        }
        [pscustomobject]@{
            raw = $raw; normalized = $normalized; badQuotes = $badQuotes
            unresolvedVariable = $expanded -match '%[^%]+%'
            selfReference = $entry -match '(?i)%PATH%'
            absolute = $absolute
        }
    }
}

function Test-EnvironmentPath([AllowNull()][string]$ProcessValue,
                              [AllowNull()][string]$MachineValue,
                              [AllowNull()][string]$UserValue) {
    # These are the checker's process/account values. Do not claim to have read
    # another running process' environment or another account's user PATH.
    $scopes = @(
        @{ name = 'Process'; value = $ProcessValue },
        @{ name = 'Machine'; value = $MachineValue },
        @{ name = 'User'; value = $UserValue }
    )
    foreach ($scope in $scopes) {
        $name = $scope.name
        if ([string]::IsNullOrWhiteSpace($scope.value)) {
            $status = 'WARN'; $summary = "$name PATH is missing or empty."
            $next = 'Review Windows Environment Variables and the environment used to start Rose. This is a possible cause, not proof of failed injection; applications and Windows can also use absolute/system paths.'
            if ($name -eq 'User') {
                $status = 'INFO'; $summary = 'User PATH is missing or empty; a separate user PATH is optional.'
                $next = 'Check the effective Process PATH and Machine PATH before treating this as a problem.'
            }
            Add-Finding "environment.path.$name" 'Environment' $status $summary '' $next
            continue
        }
        $entries = @(Get-EnvironmentPathEntries $scope.value)
        Add-Finding "environment.path.$name" 'Environment' 'INFO' "$name PATH is set (full value omitted for privacy)." `
            "characters=$($scope.value.Length); nonempty entries=$($entries.Count); process/user scope belongs to the checker account."
        $suspicious = @($entries | Where-Object { $_.badQuotes -or $_.unresolvedVariable -or $_.selfReference -or ($_.absolute -and -not $_.normalized) })
        if ($suspicious.Count -gt 0) {
            $examples = @($suspicious | Select-Object -First 3 | ForEach-Object { $_.raw }) -join '; '
            Add-Finding "environment.path.$name.entries" 'Environment' 'WARN' 'PATH contains malformed quotes, an unresolved variable, a self-reference, or an invalid absolute path.' `
                "$name; suspect entries=$($suspicious.Count); examples=$examples" `
                'Review these entries in Windows Environment Variables. User/machine variables are expanded using the checker environment, so confirm the affected app account too.'
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($ProcessValue)) {
        $windows = [Environment]::GetFolderPath([Environment+SpecialFolder]::Windows)
        if (-not $windows) { throw 'Windows directory could not be determined for the PATH check.' }
        $system32 = Join-Path $windows 'System32'
        $processEntries = @(Get-EnvironmentPathEntries $ProcessValue)
        if (-not ($processEntries | Where-Object { Test-SamePath $_.normalized $system32 })) {
            Add-Finding 'environment.path.system32' 'Environment' 'WARN' 'The checker Process PATH does not contain the Windows System32 directory.' $system32 `
                'Review the system PATH and how Rose was launched. Windows also searches system/application folders independently of PATH, so this is a clue rather than a proven blocker.'
        }
    }
    Add-Finding 'environment.path.scope' 'Environment' 'INFO' 'PATH checks inspect this checker and saved machine/current-user settings, not Rose/League environment blocks.' '' `
        'A running app can retain an older inherited PATH. After correcting environment settings, fully exit and relaunch Rose and the client outside a match, then collect another report.'
}

function Test-RuntimeInstances([object[]]$ProcessList) {
    foreach ($name in @('Rose.exe', 'LeagueClientUx.exe', 'ltk_patcher_host.exe')) {
        $instances = @($ProcessList | Where-Object { $_.name -ieq $name })
        if ($instances.Count -gt 1) {
            $paths = @($instances | ForEach-Object { "pid=$($_.pid); path=$($_.path)" }) -join '; '
            Add-Finding "instances.$name" 'Environment' 'WARN' 'Multiple instances of a relevant app are running in this Windows session.' "$name; $paths" `
                'Check whether an old/portable copy or another patcher is running. Multiple instances are a clue, not proof of a conflict; close duplicate apps outside a match.'
        }
    }
}

function Test-PluginEntry([string]$Folder, [string]$Plugin) {
    $enabled = Join-Path $Folder 'index.js'; $disabled = Join-Path $Folder 'index.js_'
    if (Test-Path -LiteralPath $disabled -PathType Leaf) {
        if (Test-Path -LiteralPath $enabled -PathType Leaf) {
            Add-Finding "plugin.$Plugin" 'Client UI' 'WARN' 'Plugin has both enabled and disabled entrypoints; sync/enable state is inconsistent.' $Folder 'Check plugin state through Rose/Pengu. Rose normally parks a reintroduced enabled file when the disabled marker is present.'
        } else { Add-Finding "plugin.$Plugin" 'Client UI' 'WARN' 'A required Rose plugin has a disabled entrypoint.' $Folder 'Check plugin enable state in Pengu. Rose preserves disabled plugins when syncing updates.' }
        return
    }
    if (-not (Test-Path -LiteralPath $enabled -PathType Leaf)) {
        Add-Finding "plugin.$Plugin" 'Client UI' 'FAIL' 'Required Rose plugin entrypoint is missing.' $Folder 'Repair/reinstall the Rose plugin files.'; return
    }
    if ((Get-Item -LiteralPath $enabled).Length -eq 0) {
        Add-Finding "plugin.$Plugin" 'Client UI' 'FAIL' 'Required Rose plugin entrypoint is empty.' $enabled 'Repair the plugin from the current Rose build.'; return
    }
    $stream = [IO.File]::Open($enabled, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    try { [void]$stream.ReadByte() } finally { $stream.Dispose() }
    Add-Finding "plugin.$Plugin" 'Client UI' 'PASS' 'Required plugin entrypoint is enabled, nonempty and readable by the checker.' $Folder 'This does not validate JavaScript syntax or prove initialization in the client.'
}

function Read-ActivationSession([string]$UserData, [object[]]$ProcessList) {
    $path = Join-Path $UserData 'state\pengu_session.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Add-Finding 'pengu.session' 'Client UI' 'INFO' 'Pengu activation session file is absent; activation timing cannot be correlated.' $path
        return $null
    }
    if ((Get-Item -LiteralPath $path).Length -gt 65536) { throw 'Pengu session file is unexpectedly larger than 64 KiB.' }
    try { $session = [IO.File]::ReadAllText($path) | ConvertFrom-Json }
    catch { Add-Finding 'pengu.session' 'Client UI' 'WARN' 'Pengu activation session file is malformed JSON.' $path 'Check Rose startup/recovery errors. No session data was modified or included in the report.'; return $null }
    $sessionPid = 0
    if (-not [int]::TryParse([string]$session.rose_pid, [ref]$sessionPid) -or $sessionPid -le 0) {
        Add-Finding 'pengu.session.pid' 'Client UI' 'WARN' 'Pengu session has an invalid or missing Rose PID.' $path
    } elseif (-not ($ProcessList | Where-Object { $_.name -eq 'Rose.exe' -and $_.pid -eq $sessionPid })) {
        Add-Finding 'pengu.session.stale' 'Client UI' 'WARN' 'Pengu session does not belong to an observed packaged Rose process in this Windows session.' "sessionPID=$sessionPid" `
            'This can follow a crash, an old app instance, a source run or a different Windows session. Correlate recovery errors; the checker does not clear or deactivate anything.'
    }
    $activated = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse([string]$session.activated_at, [ref]$activated)) {
        Add-Finding 'pengu.session.time' 'Client UI' 'UNKNOWN' 'Pengu session activation timestamp is absent or invalid.' $path
        return $null
    }
    Add-Finding 'pengu.session.time' 'Client UI' 'INFO' 'Recorded Rose/Pengu activation session time (not proof the hook loaded).' $activated.ToString('o')
    return $activated
}

function Test-ClientActivationTiming([int]$ClientPid, [AllowNull()][object]$ClientStarted,
                                   [AllowNull()][object]$ActivatedAt) {
    if ($null -eq $ClientStarted -or $null -eq $ActivatedAt) { return }
    if ($ClientStarted.ToUniversalTime() -lt $ActivatedAt.UtcDateTime) {
        Add-Finding "pengu.restart-needed.$ClientPid" 'Client UI' 'WARN' 'Client without an observed core.dll started before the recorded Rose activation session.' `
            "clientPID=$ClientPid; clientStarted=$($ClientStarted.ToString('o')); activationRecorded=$($ActivatedAt.ToString('o'))" `
            'After confirming activation, fully restart the League client outside a match. The session time is a correlation clue; it does not establish exactly when the registry changed.'
    }
}

function Test-PenguRuntimeCopies([string]$Runtime, [string]$Bundled) {
    if (-not $Runtime -or -not $Bundled -or (Test-SamePath $Runtime $Bundled)) { return }
    foreach ($name in @('core.dll', 'Pengu Loader.exe')) {
        $runtimeFile = Join-Path $Runtime $name; $bundledFile = Join-Path $Bundled $name
        if (-not (Test-Path -LiteralPath $runtimeFile -PathType Leaf) -or -not (Test-Path -LiteralPath $bundledFile -PathType Leaf)) { continue }
        $runtimeHash = (Get-FileHash -LiteralPath $runtimeFile -Algorithm SHA256).Hash
        $bundledHash = (Get-FileHash -LiteralPath $bundledFile -Algorithm SHA256).Hash
        if ($runtimeHash -ne $bundledHash) {
            Add-Finding "pengu.copy.$name" 'Client UI' 'WARN' 'Selected Pengu runtime binary differs from the copy bundled with the inspected Rose installation.' `
                "runtime=$runtimeFile; bundled=$bundledFile; runtimeSHA256=$runtimeHash; bundledSHA256=$bundledHash" `
                'Check for stale AppData copies, sync failures or deliberate customization. A difference alone does not establish which version is correct; do not compare user config/datastore as bundled assets.'
        }
    }
}

function Test-StorageEnvironment([hashtable]$Variables, [string[]]$StateFiles) {
    foreach ($name in $Variables.Keys) {
        $value = [string]$Variables[$name]
        if ([string]::IsNullOrWhiteSpace($value)) {
            Add-Finding "environment.folder.$name" 'Environment' 'WARN' 'A relevant app-data/temp environment variable is missing or empty.' $name 'Check the affected Windows account and its environment. Known-folder APIs or another temp variable may still provide a valid fallback.'
        } elseif (-not (Test-Path -LiteralPath $value -PathType Container)) {
            Add-Finding "environment.folder.$name" 'Environment' 'WARN' 'An app-data/temp variable points to a missing or inaccessible directory.' "$name=$value" 'Check folder existence and permissions for the Rose/League account. No folder or write-test file was created.'
        } else { Add-Finding "environment.folder.$name" 'Environment' 'INFO' 'Relevant app-data/temp directory exists; effective write permission was not tested.' "$name=$value" }
    }
    foreach ($path in $StateFiles) {
        if (-not $path -or -not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        if (((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReadOnly) -ne 0) {
            Add-Finding 'state.read-only' 'Environment' 'WARN' 'An app config/state file has the read-only attribute.' $path 'Correlate config/datastore/sync errors with this file. Read-only DLLs and directory attributes are not treated as app-state write failures.'
        }
    }
}

function Test-BridgeDiscoveryRange([int]$Port, [string]$PluginFile) {
    if (-not (Test-Path -LiteralPath $PluginFile -PathType Leaf)) { return }
    if ((Get-Item -LiteralPath $PluginFile).Length -gt 1048576) { throw 'SkinMonitor entrypoint is unexpectedly larger than 1 MiB.' }
    $source = [IO.File]::ReadAllText($PluginFile)
    $start = [regex]::Match($source, '\bconst\s+DISCOVERY_START_PORT\s*=\s*(\d+)\s*;')
    $end = [regex]::Match($source, '\bconst\s+DISCOVERY_END_PORT\s*=\s*(\d+)\s*;')
    if (-not $start.Success -or -not $end.Success) {
        Add-Finding 'bridge.discovery-range' 'Client UI' 'UNKNOWN' 'Plugin automatic bridge discovery range could not be recognized.' $PluginFile; return
    }
    $first = [int]$start.Groups[1].Value; $last = [int]$end.Groups[1].Value
    if ($Port -lt $first -or $Port -gt $last) {
        Add-Finding 'bridge.discovery-range' 'Client UI' 'WARN' 'Recorded Rose port is outside SkinMonitor automatic discovery range.' "recordedPort=$Port; pluginDiscovery=$first-$last" `
            'A previously cached working port can still connect, but fresh discovery may fail. Check competing listeners in this range and align backend allocation with plugin discovery in the app.'
    } else { Add-Finding 'bridge.discovery-range' 'Client UI' 'PASS' 'Recorded Rose port is within the installed plugin discovery range.' "recordedPort=$Port; pluginDiscovery=$first-$last" }
}

function Test-BridgeHttp([ValidateRange(1, 65535)][int]$Port) {
    # Only this fixed read-only endpoint on numeric loopback is queried. Never
    # use a proxy, follow redirects, send credentials, or print an arbitrary body.
    $request = [Net.HttpWebRequest]::Create("http://127.0.0.1:$Port/port")
    $request.Proxy = $null; $request.AllowAutoRedirect = $false; $request.KeepAlive = $false
    $request.Timeout = 1500; $request.ReadWriteTimeout = 1500
    $response = $null; $reader = $null
    try {
        $response = $request.GetResponse()
        $reader = New-Object IO.StreamReader($response.GetResponseStream())
        $characters = New-Object char[] 64
        $count = $reader.Read($characters, 0, $characters.Length)
        $body = ([string]::new($characters, 0, $count)).Trim()
        if ([int]$response.StatusCode -ne 200 -or $body -notmatch '^\d{1,5}$' -or [int]$body -ne $Port) {
            Add-Finding 'bridge.http' 'Client UI' 'WARN' 'Listening port did not return the expected Rose /port response.' "127.0.0.1:$Port; HTTP=$([int]$response.StatusCode); response body omitted" 'The port may belong to another app, or the bridge may be unhealthy. Correlate listener ownership and Rose backend errors.'
        } else { Add-Finding 'bridge.http' 'Client UI' 'PASS' 'Loopback /port returned the expected recorded port.' "127.0.0.1:$Port" 'This is stronger than a TCP connection, but does not prove WebSocket/plugin initialization.' }
    } catch { Add-Finding 'bridge.http' 'Client UI' 'WARN' 'Recorded bridge did not complete the bounded loopback /port check.' "127.0.0.1:$Port; $($_.Exception.Message)" 'Check backend startup, event-loop stalls, port ownership and local loopback filtering.' }
    finally { if ($reader) { $reader.Dispose() }; if ($response) { $response.Dispose() }; $request.Abort() }
}

function Test-BridgeOwner([ValidateRange(1, 65535)][int]$Port) {
    if (-not (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue)) { throw 'TCP listener ownership cmdlet is unavailable.' }
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop |
        Where-Object { $_.LocalAddress -in @('127.0.0.1', '0.0.0.0', '::', '::1') })
    if ($listeners.Count -eq 0) { Add-Finding 'bridge.owner' 'Client UI' 'UNKNOWN' 'No matching loopback/wildcard listener was observed; it may have closed since the probe.' "port=$Port"; return }
    foreach ($ownerPid in @($listeners.OwningProcess | Select-Object -Unique)) {
        $owner = Get-Process -Id $ownerPid -ErrorAction Stop
        $status = 'INFO'
        if ($owner.ProcessName -notin @('Rose', 'python', 'pythonw')) { $status = 'WARN' }
        Add-Finding 'bridge.owner' 'Client UI' $status 'Process owning the recorded bridge listener (Python source runs are not identified conclusively).' `
            "port=$Port; ownerPID=$ownerPid; ownerName=$($owner.ProcessName).exe" 'If the owner is unrelated to Rose, inspect duplicate apps or a stale port file. No process was stopped.'
    }
}

function Get-PeInfo([string]$Path) {
    if ((Get-Item -LiteralPath $Path).Length -gt 536870912) { throw 'Binary is unexpectedly larger than 512 MB; static parsing skipped.' }
    $data = [IO.File]::ReadAllBytes($Path)
    if ($data.Length -lt 64 -or $data[0] -ne 77 -or $data[1] -ne 90) { throw 'Not a Windows PE binary (possibly an HTML download or truncated file).' }
    $pe = [BitConverter]::ToInt32($data, 60)
    if ($pe -lt 64 -or $pe + 24 -gt $data.Length -or [BitConverter]::ToUInt32($data, $pe) -ne 17744) { throw 'Invalid/truncated PE header.' }
    $machine = [BitConverter]::ToUInt16($data, $pe + 4)
    $count = [BitConverter]::ToUInt16($data, $pe + 6)
    $optSize = [BitConverter]::ToUInt16($data, $pe + 20)
    $opt = $pe + 24; $table = $opt + $optSize
    if ($optSize -lt 96 -or $table + $count * 40 -gt $data.Length) { throw 'Invalid/truncated optional header or section table.' }
    $magic = [BitConverter]::ToUInt16($data, $opt)
    if ($magic -notin @(267, 523)) { throw 'Unsupported PE optional header.' }
    $sections = @()
    for ($i = 0; $i -lt $count; $i++) {
        $entry = $table + $i * 40
        $sections += [pscustomobject]@{
            name = [Text.Encoding]::ASCII.GetString($data, $entry, 8).Trim([char]0)
            rva = [BitConverter]::ToUInt32($data, $entry + 12)
            size = [BitConverter]::ToUInt32($data, $entry + 16)
            raw = [BitConverter]::ToUInt32($data, $entry + 20)
        }
        $section = $sections[-1]
        if ($section.size -gt 0 -and ([long]$section.raw + $section.size) -gt $data.Length) { throw 'Truncated PE section data.' }
    }
    $directories = $opt + 96
    if ($magic -eq 523) { $directories = $opt + 112 }
    $imports = @()
    if ($directories -gt $table) { throw 'Truncated PE data directories.' }
    $directoryCount = [BitConverter]::ToUInt32($data, $directories - 4)
    if ($directoryCount -ge 2 -and $directories + 16 -le $table) {
        $importRva = [BitConverter]::ToUInt32($data, $directories + 8)
        $importOffset = Convert-Rva $sections $importRva
        if ($importRva -ne 0 -and $null -eq $importOffset) { throw 'Invalid import directory RVA.' }
        if ($null -ne $importOffset -and $importRva -ne 0) {
            for ($i = 0; $i -lt 256; $i++) {
                $entry = $importOffset + $i * 20
                if ($entry + 20 -gt $data.Length) { throw 'Truncated import directory.' }
                $nameRva = [BitConverter]::ToUInt32($data, $entry + 12)
                if ($nameRva -eq 0) { break }
                $offset = Convert-Rva $sections $nameRva
                if ($null -eq $offset) { throw 'Invalid import name RVA.' }
                $imports += Read-AsciiZ $data $offset
            }
        }
    }
    $managed = $false
    if ($directoryCount -ge 15 -and $directories + 120 -le $table) { $managed = [BitConverter]::ToUInt32($data, $directories + 112) -ne 0 }
    $arch = 'unknown (0x{0:X4})' -f $machine
    if ($machine -eq 34404) { $arch = 'x64' }
    if ($machine -eq 332) { $arch = 'x86'; if ($managed) { $arch = 'managed PE32 (may be AnyCPU)' } }
    if ($machine -eq 43620) { $arch = 'ARM64' }
    return [pscustomobject]@{
        architecture = $arch; machine = $machine; managed = $managed
        timestamp = [BitConverter]::ToUInt32($data, $pe + 8)
        imports = @($imports | Select-Object -Unique); sections = $sections; data = $data
    }
}

function Convert-Rva($Sections, [long]$Rva) {
    foreach ($section in $Sections) {
        if ($Rva -ge $section.rva -and $Rva -lt ([long]$section.rva + $section.size)) {
            return [long]$section.raw + $Rva - $section.rva
        }
    }
    return $null
}

function Read-AsciiZ([byte[]]$Data, [long]$Offset) {
    if ($Offset -lt 0 -or $Offset -ge $Data.Length) { throw 'String outside file.' }
    $end = $Offset
    while ($end -lt $Data.Length -and $end - $Offset -lt 260 -and $Data[$end] -ne 0) { $end++ }
    if ($end -eq $Data.Length -or $end - $Offset -eq 260) { throw 'Invalid import name.' }
    return [Text.Encoding]::ASCII.GetString($Data, [int]$Offset, [int]($end - $Offset))
}

function Get-LtkCutoff($PeInfo) {
    # Same static heuristic as injection/tools/patcher.py. No DLL loading.
    $data = $PeInfo.data
    $message = [Text.Encoding]::ASCII.GetBytes('end of life reached, please update: ')
    $msgOffset = -1
    for ($i = 0; $i -le $data.Length - $message.Length; $i++) {
        if ($data[$i] -ne $message[0]) { continue }
        $same = $true
        for ($k = 1; $k -lt $message.Length; $k++) { if ($data[$i + $k] -ne $message[$k]) { $same = $false; break } }
        if ($same) { $msgOffset = $i; break }
    }
    if ($msgOffset -lt 0) { return $null }
    $msgRva = $null
    foreach ($section in $PeInfo.sections) {
        if ($msgOffset -ge $section.raw -and $msgOffset -lt ([long]$section.raw + $section.size)) {
            $msgRva = $section.rva + $msgOffset - $section.raw; break
        }
    }
    $code = $PeInfo.sections | Where-Object { $_.name -eq '.text' } | Select-Object -First 1
    if ($null -eq $msgRva -or $null -eq $code) { return $null }
    $end = [Math]::Min([long]$code.raw + $code.size, $data.Length) - 7
    for ($i = [long]$code.raw; $i -lt $end; $i++) {
        if ($data[$i] -notin @(72, 76) -or $data[$i + 1] -ne 141 -or ($data[$i + 2] -band 199) -ne 5) { continue }
        $delta = $msgRva - ($code.rva + $i - $code.raw + 7 + [BitConverter]::ToInt32($data, [int]$i + 3))
        if ($delta -lt 0 -or $delta -gt 16) { continue }
        for ($j = $i - 11; $j -ge [Math]::Max($code.raw, $i - 256); $j--) {
            if ($data[$j] -eq 61 -and $data[$j + 5] -eq 15 -and $data[$j + 6] -eq 134) {
                return [BitConverter]::ToUInt32($data, [int]$j + 1)
            }
        }
    }
    return $null
}

function Test-Binary([string]$Path, [string]$Stage, [string]$Id, [switch]$RequireX64) {
    $script:KnownPaths.Add($Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Add-Finding $Id $Stage 'FAIL' 'Required file is missing.' $Path `
            'Check this exact folder and Windows Security Protection history. Repair Rose files; for LTK, copy both files from the same trusted LTK Manager installation.'
        return
    }
    try { $pe = Get-PeInfo $Path }
    catch { Add-Finding $Id $Stage 'FAIL' 'Binary is unreadable or malformed.' "$Path : $($_.Exception.Message)" 'Replace it from the trusted installation/build.'; return }
    $signatureStatus = 'Unavailable'; $signer = ''; $hash = ''
    try { $sig = Get-AuthenticodeSignature -LiteralPath $Path; $signatureStatus = [string]$sig.Status; if ($sig.SignerCertificate) { $signer = $sig.SignerCertificate.Subject } }
    catch { Add-Finding "$Id.signature" $Stage 'UNKNOWN' 'Signature could not be checked.' $_.Exception.Message }
    try { $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash } catch { }
    $script:Files.Add([pscustomobject][ordered]@{
        path = Protect-Text $Path; architecture = $pe.architecture; bytes = (Get-Item -LiteralPath $Path).Length
        version = [Diagnostics.FileVersionInfo]::GetVersionInfo($Path).FileVersion
        sha256 = $hash; signature = $signatureStatus; signer = Protect-Text $signer; imports = $pe.imports
    })
    if ($RequireX64 -and $pe.machine -ne 34404) {
        Add-Finding "$Id.architecture" $Stage 'FAIL' 'Native binary has the wrong architecture for x64 League.' $pe.architecture 'Install the correct x64 binary.'
    } else { Add-Finding $Id $Stage 'PASS' 'File is present and has a readable PE header.' "$Path; $($pe.architecture); signature=$signatureStatus" }
    if ($signatureStatus -in @('HashMismatch', 'NotTrusted', 'UnknownError')) {
        Add-Finding "$Id.trust" $Stage 'WARN' 'Signature validation reports a problem.' "$Path; $signatureStatus" `
            'Compare SHA-256 with your trusted build. This can reflect modification, certificate trust, revocation/network availability, or the system clock; a security block requires corroborating events.'
    } elseif ($signatureStatus -eq 'NotSigned') {
        Add-Finding "$Id.trust" $Stage 'INFO' 'File is unsigned; this alone does not prove Windows blocked it.' $Path
    }
    try {
        $zone = Get-Item -LiteralPath $Path -Stream Zone.Identifier -ErrorAction Stop
        if ($zone) {
            $zoneText = Get-Content -LiteralPath $Path -Stream Zone.Identifier -Raw
            if ($zoneText -match 'ZoneId=([34])') {
                Add-Finding "$Id.download-mark" $Stage 'WARN' 'File carries an Internet/restricted-zone download mark.' "$Path; ZoneId=$($Matches[1])" `
                    'Verify its source/signature and review the matching security events. A download mark is a clue, not proof of an injection block.'
            }
        }
    } catch {
        if ($_.Exception -is [UnauthorizedAccessException]) { Add-Finding "$Id.download-mark" $Stage 'UNKNOWN' 'Download mark could not be read.' $Path }
    }
    foreach ($dependency in $pe.imports) {
        if ($dependency -match '^(api-ms-|ext-ms-)') { continue } # API-set contracts need not be files.
        if ($dependency -notmatch '^[A-Za-z0-9_.-]+\.dll$') { continue }
        $system = Join-Path $env:windir 'System32'
        if ($pe.machine -eq 332 -and -not $pe.managed -and [Environment]::Is64BitOperatingSystem) { $system = Join-Path $env:windir 'SysWOW64' }
        if (-not [Environment]::Is64BitProcess -and $pe.machine -eq 34404) { $system = Join-Path $env:windir 'Sysnative' }
        if (-not (Test-Path -LiteralPath (Join-Path (Split-Path $Path) $dependency)) -and
            -not (Test-Path -LiteralPath (Join-Path $system $dependency))) {
            Add-Finding "$Id.import.$dependency" $Stage 'WARN' 'Imported DLL was not found beside the binary or in its system directory.' "$Path -> $dependency" `
                'Check loader/SideBySide errors. Repair the matching Microsoft runtime if needed. Static checking does not cover every DLL search location or delay-loaded dependency.'
        }
    }
}

function Initialize-NativeQueries {
    if ('RoseDiagnostics.Native' -as [type]) { $script:NativeAvailable = $true; return }
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
namespace RoseDiagnostics {
    public class TokenSnapshot {
        public bool Elevated; public int Integrity; public string Profile; public string Sid;
    }
    public static class Native {
        [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr OpenProcess(uint a, bool b, int c);
        [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
        [DllImport("advapi32.dll", SetLastError=true)] static extern bool OpenProcessToken(IntPtr p, uint a, out IntPtr t);
        [DllImport("advapi32.dll", SetLastError=true)] static extern bool GetTokenInformation(IntPtr t, int c, IntPtr b, int n, out int r);
        [DllImport("advapi32.dll")] static extern IntPtr GetSidSubAuthorityCount(IntPtr s);
        [DllImport("advapi32.dll")] static extern IntPtr GetSidSubAuthority(IntPtr s, uint n);
        [DllImport("userenv.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool GetUserProfileDirectory(IntPtr t, StringBuilder p, ref uint n);
        [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetProcessMitigationPolicy(IntPtr p, int k, out uint flags, UIntPtr size);
        static IntPtr Info(IntPtr t, int kind) {
            int size; GetTokenInformation(t, kind, IntPtr.Zero, 0, out size);
            if (size <= 0) throw new Win32Exception(Marshal.GetLastWin32Error());
            IntPtr b = Marshal.AllocHGlobal(size);
            if (!GetTokenInformation(t, kind, b, size, out size)) { Marshal.FreeHGlobal(b); throw new Win32Exception(Marshal.GetLastWin32Error()); }
            return b;
        }
        public static TokenSnapshot Token(int pid) {
            IntPtr p = OpenProcess(0x1000, false, pid); // PROCESS_QUERY_LIMITED_INFORMATION only
            if (p == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
            IntPtr t = IntPtr.Zero;
            try {
                if (!OpenProcessToken(p, 8, out t)) throw new Win32Exception(Marshal.GetLastWin32Error());
                TokenSnapshot result = new TokenSnapshot();
                IntPtr b = Info(t, 20); try { result.Elevated = Marshal.ReadInt32(b) != 0; } finally { Marshal.FreeHGlobal(b); }
                b = Info(t, 25); try {
                    IntPtr sid = Marshal.ReadIntPtr(b); byte count = Marshal.ReadByte(GetSidSubAuthorityCount(sid));
                    result.Integrity = Marshal.ReadInt32(GetSidSubAuthority(sid, (uint)(count - 1)));
                } finally { Marshal.FreeHGlobal(b); }
                uint len = 32768; StringBuilder profile = new StringBuilder((int)len);
                if (GetUserProfileDirectory(t, profile, ref len)) result.Profile = profile.ToString();
                using (WindowsIdentity identity = new WindowsIdentity(t)) { result.Sid = identity.User.Value; }
                return result;
            } finally { if (t != IntPtr.Zero) CloseHandle(t); CloseHandle(p); }
        }
        public static uint Mitigation(int pid, int kind) {
            IntPtr p = OpenProcess(0x1000, false, pid);
            if (p == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
            try { uint flags; if (!GetProcessMitigationPolicy(p, kind, out flags, (UIntPtr)4)) throw new Win32Exception(Marshal.GetLastWin32Error()); return flags; }
            finally { CloseHandle(p); }
        }
    }
}
'@
    $script:NativeAvailable = $true
}

function Resolve-RoseRoot {
    if ($RosePath) {
        $path = Get-FullPath $RosePath
        if (Test-Path -LiteralPath $path -PathType Leaf) { $path = Split-Path $path }
        return $path
    }
    $running = $script:Processes | Where-Object { $_.name -eq 'Rose.exe' -and $_.path } | Select-Object -First 1
    if ($running) { return Split-Path $running.path }
    $sourceDirectory = $PSScriptRoot
    if (-not $sourceDirectory -and $env:ROSE_DIAG_SELF) { $sourceDirectory = Split-Path -Parent $env:ROSE_DIAG_SELF }
    if (-not $sourceDirectory) { $sourceDirectory = (Get-Location).Path }
    $candidates = @($sourceDirectory, (Get-Location).Path)
    $sourceParent = Split-Path -Parent $sourceDirectory
    if ($sourceParent) { $candidates += $sourceParent; $sourceGrandparent = Split-Path -Parent $sourceParent; if ($sourceGrandparent) { $candidates += $sourceGrandparent } }
    if ($env:ProgramW6432) { $candidates += Join-Path $env:ProgramW6432 'Rose' }
    if ($env:ProgramFiles) { $candidates += Join-Path $env:ProgramFiles 'Rose' }
    foreach ($view in @('Registry64', 'Registry32')) {
        try {
            $uninstall = Get-RegValues 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}_is1' $view
            if ($uninstall -and $uninstall['InstallLocation']) { $candidates += $uninstall['InstallLocation'] }
        } catch { }
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if ((Test-Path -LiteralPath (Join-Path $candidate 'Rose.exe')) -or
            ((Test-Path -LiteralPath (Join-Path $candidate 'main.py')) -and (Test-Path -LiteralPath (Join-Path $candidate 'Pengu Loader')))) {
            return Get-FullPath $candidate
        }
    }
    return $null
}

function Test-RelevantText([string]$Text) {
    if ($Text -match '(?i)(\bRose\.exe\b|\bPengu Loader\b|\bltk_patcher_(?:host\.exe|dll\.dll)\b|\bmod-tools\.exe\b|\bcslol-dll\.(?:dll|stub)\b|\bDiagnose-Rose\.(?:ps1|cmd)\b)') { return $true }
    foreach ($path in $script:KnownPaths) {
        if ($path -and $Text.IndexOf($path, [StringComparison]::OrdinalIgnoreCase) -ge 0) { return $true }
    }
    return $false
}

function Get-EventStatus([string]$Log, [int]$EventId) {
    if ($Log -like '*CodeIntegrity*') {
        if ($EventId -in @(3076, 3034, 3064, 3065, 3080, 3089)) { return 'INFO' }
        if ($EventId -in @(3077, 3033)) { return 'FAIL' }
        return 'WARN'
    }
    if ($Log -like '*AppLocker*') {
        if ($EventId -in @(8004, 8007, 8029)) { return 'FAIL' }
        return 'INFO'
    }
    if ($Log -like '*Windows Defender*') {
        if ($EventId -in @(1121, 1123, 1127)) { return 'FAIL' }
        if ($EventId -in @(1122, 1124, 1128)) { return 'INFO' }
        return 'WARN' # Detection/remediation does not always mean a block/quarantine.
    }
    return 'WARN'
}

function Read-RelevantEvents([string]$Log, [int[]]$EventIds) {
    $logInfo = Get-WinEvent -ListLog $Log -ErrorAction Stop
    if (-not $logInfo.IsEnabled) {
        Add-Finding "events.$Log" 'Security' 'UNKNOWN' 'Event channel is disabled; blocks cannot be ruled out from this channel.' $Log; return
    }
    $queryErrors = @()
    $events = @(Get-WinEvent -FilterHashtable @{ LogName = $Log; Id = $EventIds; StartTime = $script:Started.AddDays(-$Days) } `
        -MaxEvents 500 -ErrorAction SilentlyContinue -ErrorVariable queryErrors)
    foreach ($err in $queryErrors) {
        if ($err.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*') { throw $err }
    }
    $matched = 0
    foreach ($event in $events) {
        # XML survives missing localized message resources on stripped Windows.
        $xml = [xml]$event.ToXml()
        $fields = @($xml.Event.EventData.Data | ForEach-Object { "{0}={1}" -f $_.Name, $_.'#text' }) -join '; '
        $message = ''
        try { $message = $event.Message } catch { }
        if (-not (Test-RelevantText "$fields $message")) { continue }
        $matched++
        $status = Get-EventStatus $Log $event.Id
        $summary = 'Relevant security/error event; inspect the timestamp and file named.'
        if ($status -eq 'FAIL') { $summary = 'Windows recorded an enforced block affecting a Rose component.' }
        if ($status -eq 'INFO') { $summary = 'Relevant audit/signature event; this event is not an enforced block.' }
        $details = $fields
        if (-not $details) { $details = $message }
        if ($details.Length -gt 3500) { $details = $details.Substring(0, 3500) + ' [truncated]' }
        Add-Finding "event.$($event.RecordId).$($event.Id)" 'Security' $status $summary `
            "$($event.TimeCreated.ToString('o')); $Log; event=$($event.Id); $details" `
            'Correlate this with the failed attempt and the current file SHA-256. Old events can describe a problem already resolved. Review the policy or Protection history before replacing files.'
        if ($matched -ge 40) { break }
    }
    Add-Finding "events.$Log" 'Security' 'INFO' 'Event search completed.' `
        "$Log; matched=$matched; scanned=$($events.Count); lookback=$Days days; cap=500 events (40 relevant entries). Absence of a matching event does not rule out blocking."
}

function Write-Reports([switch]$Incomplete, [switch]$Quiet) {
    if ($ReportDirectory) { $folder = Get-FullPath $ReportDirectory }
    else {
        if (-not $OutputDirectory) {
            $data = $script:UserData
            if (-not $data) { $data = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Rose' }
            $OutputDirectory = Join-Path $data 'logs\diagnostics'
        }
        $parent = Get-FullPath $OutputDirectory
        $folder = Join-Path $parent ('Rose-Diagnostics-' + $script:Started.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 6))
    }
    [void][IO.Directory]::CreateDirectory($folder)
    $report = [ordered]@{
        schemaVersion = 1; toolVersion = '1.4.0'; collectedAt = $script:Started.ToString('o')
        roseVersion = Protect-Text $RoseVersion; complete = -not [bool]$Incomplete
        scope = 'Client UI (Pengu) and game skins (LTK) are separate stages.'
        limitations = 'Snapshot only; cannot prove successful injection. UNKNOWN means unavailable, not healthy. Recent events can be historical. No raw command lines, lockfiles, full configs, logs, usernames or machine identifiers are intentionally collected; review excerpts before sharing.'
        findings = @($script:Findings.ToArray()); files = @($script:Files.ToArray())
    }
    $encoding = New-Object Text.UTF8Encoding($true)
    [IO.File]::WriteAllText((Join-Path $folder 'report.json'), ($report | ConvertTo-Json -Depth 8), $encoding)
    $lines = New-Object 'System.Collections.Generic.List[string]'
    $lines.Add('Rose startup diagnostics - ' + $script:Started.ToString('o'))
    if ($RoseVersion) { $lines.Add('Rose version: ' + (Protect-Text $RoseVersion)) }
    if ($Incomplete) { $lines.Add('INCOMPLETE: collection is still running or was interrupted. Missing checks are not healthy results.') }
    $lines.Add('Missing client icon: check Client UI findings first. LTK findings concern game skins.')
    $lines.Add('FAIL = observed blocker/error; WARN = possible cause; UNKNOWN = not checked; INFO/PASS = evidence only.')
    $lines.Add($report.limitations)
    $lines.Add('')
    $rank = @{ FAIL = 0; WARN = 1; UNKNOWN = 2; INFO = 3; PASS = 4 }
    foreach ($finding in ($script:Findings | Sort-Object @{ Expression = { $rank[$_.status] } }, stage, id)) {
        $lines.Add("[$($finding.status)] [$($finding.stage)] $($finding.id): $($finding.summary)")
        if ($finding.evidence) { $lines.Add('  Evidence: ' + $finding.evidence) }
        if ($finding.nextStep) { $lines.Add('  Next: ' + $finding.nextStep) }
        $lines.Add('')
    }
    $lines.Add('Binary inventory (hashes are for comparison with trusted builds; no reference hashes are pinned):')
    foreach ($file in $script:Files) {
        $lines.Add("$($file.path): $($file.architecture); version=$($file.version); bytes=$($file.bytes); signature=$($file.signature)")
        $lines.Add("  SHA256=$($file.sha256); signer=$($file.signer); imports=$($file.imports -join ', ')")
    }
    [IO.File]::WriteAllLines((Join-Path $folder 'report.txt'), $lines.ToArray(), $encoding)
    if ($Quiet) { return }
    Write-Host ''
    Write-Host ("Report saved to: {0}" -f $folder) -ForegroundColor Cyan
    foreach ($status in @('FAIL', 'WARN', 'UNKNOWN')) {
        Write-Host ("{0}: {1}" -f $status, @($script:Findings | Where-Object { $_.status -eq $status }).Count)
    }
    Write-Host 'Read report.txt, then share it with Rose support. Nothing was uploaded.'
}

# Dot-sourcing exposes pure helpers for the fixture tests without collecting data.
if ($MyInvocation.InvocationName -eq '.') { return }
if ($env:OS -ne 'Windows_NT') { throw 'Run this checker on the affected Windows PC.' }

Write-Host 'Rose diagnostics: reproduce the problem, leave Rose and the League client open, then run this checker.'
Write-Host 'It only reads system/app state and writes local reports. Some checks may require administrator access.'

Invoke-Check 'windows' 'Environment' {
    $os = Get-RegValues 'SOFTWARE\Microsoft\Windows NT\CurrentVersion'
    $build = [int]$os['CurrentBuildNumber']
    $family = 'Windows (pre-10)'
    if ($build -ge 10240) { $family = 'Windows 10' }
    if ($build -ge 22000) { $family = 'Windows 11' }
    Add-Finding 'windows.version' 'Environment' 'INFO' 'Windows and PowerShell version (registry ProductName can be stale).' `
        "$family; registryProductName=$($os['ProductName']); DisplayVersion=$($os['DisplayVersion']); build=$build.$($os['UBR']); PowerShell=$($PSVersionTable.PSVersion); languageMode=$($ExecutionContext.SessionState.LanguageMode); 64bitOS=$([Environment]::Is64BitOperatingSystem); 64bitShell=$([Environment]::Is64BitProcess)"
    if ($build -lt 10240 -or -not [Environment]::Is64BitOperatingSystem) {
        Add-Finding 'windows.support' 'Environment' 'FAIL' 'Rose expects 64-bit Windows 10/11.' 'Detected an older OS or a 32-bit OS.' 'Use a supported 64-bit Windows installation.'
    } elseif ($build -lt 19041) {
        Add-Finding 'windows.age' 'Environment' 'WARN' 'This is an old Windows 10 build.' "build=$build" 'Check the affected binaries and events for missing APIs. Build age alone does not establish the cause.'
    }
    if (-not [Environment]::Is64BitProcess) {
        Add-Finding 'shell.bitness' 'Environment' 'WARN' 'The checker is running in a 32-bit shell; module inspection may fail.' '' 'Use 64-bit Windows PowerShell for a more complete report.'
    }
    Add-Finding 'clock' 'Environment' 'INFO' 'Local and UTC clock; incorrect time can affect signature validation.' ("Local=$((Get-Date).ToString('o')); UTC=$([DateTime]::UtcNow.ToString('o')); timezone=$([TimeZoneInfo]::Local.Id)") 'Compare with the clock.offset finding; a local timestamp alone does not prove correct time.'
}

Invoke-Check 'native-query-support' 'Environment' { Initialize-NativeQueries }
Invoke-Check 'processes' 'Environment' {
    $names = @('Rose', 'LeagueClient', 'LeagueClientUx', 'LeagueClientUxRender', 'League of Legends', 'League of Legends (TM) Client', 'ltk_patcher_host', 'mod-tools', 'Pengu Loader', 'RiotClientServices', 'explorer')
    $session = (Get-Process -Id $PID).SessionId
    $script:Processes = @(Get-Process -ErrorAction Stop | Where-Object { $_.ProcessName -in $names -and $_.SessionId -eq $session } | ForEach-Object {
        $path = ''; $start = $null; $token = $null
        try { $path = $_.MainModule.FileName } catch { }
        try { $start = $_.StartTime } catch { }
        if ($script:NativeAvailable) { try { $token = [RoseDiagnostics.Native]::Token($_.Id); if ($token.Profile -and -not $script:ProfilePaths.Contains($token.Profile)) { $script:ProfilePaths.Add($token.Profile) } } catch { } }
        [pscustomobject]@{ name = $_.ProcessName + '.exe'; pid = $_.Id; path = $path; start = $start; token = $token; session = $_.SessionId }
    })
    foreach ($process in ($script:Processes | Where-Object { $_.name -ne 'explorer.exe' })) {
        $privileges = 'token unavailable'
        if ($process.token) { $privileges = "elevated=$($process.token.Elevated); integrityRID=$($process.token.Integrity)" }
        Add-Finding "process.$($process.pid)" 'Environment' 'INFO' 'Relevant running process.' `
            "$($process.name); pid=$($process.pid); path=$($process.path); started=$($process.start); $privileges"
        if (-not $process.path -or -not $process.token) {
            Add-Finding "process.$($process.pid).access" 'Environment' 'UNKNOWN' 'Process path or token could not be inspected.' $process.name 'Try the checker as administrator; an inaccessible process is not proof of failed injection.'
        }
    }
    if (-not ($script:Processes | Where-Object { $_.name -eq 'Rose.exe' })) {
        Add-Finding 'rose.running' 'Environment' 'WARN' 'No packaged Rose.exe process was found.' '' 'Leave Rose open during the check. Source runs under python.exe are not identified by name.'
    }
    if (-not ($script:Processes | Where-Object { $_.name -eq 'LeagueClientUx.exe' })) {
        Add-Finding 'client.running' 'Client UI' 'UNKNOWN' 'League client UI is not running; live injection checks are unavailable.' '' 'Reproduce the missing icon, leave the client open, and rerun.'
    }
    Test-RuntimeInstances $script:Processes
}

$script:Root = $null; $script:UserData = $null; $script:PenguDir = $null
$script:ToolsDir = $null; $script:ClientDir = $null; $script:Config = @{}; $script:LoaderConfig = @{}
Invoke-Check 'paths' 'Environment' {
    $script:Root = Resolve-RoseRoot
    if (-not $script:Root -or -not (Test-Path -LiteralPath $script:Root -PathType Container)) {
        Add-Finding 'rose.path' 'Environment' 'UNKNOWN' 'Rose installation could not be located.' $script:Root 'Rerun with -RosePath pointing to the Rose.exe folder.'
    } else { Add-Finding 'rose.path' 'Environment' 'INFO' 'Rose installation/source directory.' $script:Root }
    $profile = $env:USERPROFILE
    $currentSession = (Get-Process -Id $PID).SessionId
    $desktop = $script:Processes | Where-Object { $_.name -eq 'explorer.exe' -and $_.session -eq $currentSession -and $_.token.Profile } | Select-Object -First 1
    $client = $script:Processes | Where-Object { $_.name -eq 'LeagueClientUx.exe' -and $_.session -eq $currentSession -and $_.token.Profile } | Select-Object -First 1
    if ($desktop) { $profile = $desktop.token.Profile }
    if ($client) { $profile = $client.token.Profile }
    if ($DataPath) { $script:UserData = Get-FullPath $DataPath }
    elseif (Test-SamePath $profile $env:USERPROFILE) {
        $localData = $env:LOCALAPPDATA
        if (-not $localData) { $localData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData) }
        if (-not $localData) { $localData = Join-Path $profile 'AppData\Local' }
        $script:UserData = Join-Path $localData 'Rose'
    }
    else { $script:UserData = Join-Path $profile 'AppData\Local\Rose' }
    Add-Finding 'rose.data-path' 'Environment' 'INFO' 'Rose data folder inspected (client/desktop profile, or explicit override).' $script:UserData
    if (-not (Test-SamePath $profile $env:USERPROFILE)) {
        Add-Finding 'accounts.checker' 'Environment' 'WARN' 'Checker and League/desktop use different Windows profiles.' '' 'Use the same Windows account as League, or verify the selected DataPath.'
    }
    $script:Config = Get-IniValues (Join-Path $script:UserData 'config.ini') -WindowsAnsi
    $loaderPath = $script:Config['general/loaderpath']
    $runtime = Join-Path $script:UserData 'Pengu Loader'
    if ($loaderPath) { $script:PenguDir = Get-FullPath $loaderPath }
    elseif (Test-Path -LiteralPath $runtime) { $script:PenguDir = $runtime }
    elseif ($script:Root) {
        $script:PenguDir = Join-Path $script:Root 'Pengu Loader'
        if (-not (Test-Path -LiteralPath $script:PenguDir)) { $script:PenguDir = Join-Path $script:Root '_internal\Pengu Loader' }
    }
    if ($script:PenguDir) {
        $script:LoaderConfig = Get-IniValues (Join-Path $script:PenguDir 'config')
        Add-Finding 'pengu.path' 'Client UI' 'INFO' 'Selected Pengu runtime (loaderpath first).' $script:PenguDir
    }
    if ($script:Root) {
        # Match SkinInjector's direct-injection-before-_internal precedence.
        $injection = Join-Path $script:Root 'injection'
        if (-not (Test-Path -LiteralPath $injection)) { $injection = Join-Path $script:Root '_internal\injection' }
        $script:ToolsDir = Join-Path $injection 'tools'
        Add-Finding 'tools.path' 'Game skins' 'INFO' 'Tools folder selected using Rose injection directory precedence.' $script:ToolsDir
    }
    $script:ClientDir = $LeaguePath
    if (-not $script:ClientDir) {
        $running = $script:Processes | Where-Object { $_.name -eq 'LeagueClientUx.exe' -and $_.path } | Select-Object -First 1
        if ($running) { $script:ClientDir = Split-Path $running.path }
    }
    if (-not $script:ClientDir) { $script:ClientDir = $script:Config['general/clientpath'] }
    if (-not $script:ClientDir) { $script:ClientDir = $script:LoaderConfig['/leaguepath'] }
    if (-not $script:ClientDir -and (Test-Path -LiteralPath 'C:\Riot Games\League of Legends\LeagueClient.exe')) { $script:ClientDir = 'C:\Riot Games\League of Legends' }
    if ($script:ClientDir) {
        $script:ClientDir = Get-FullPath $script:ClientDir
        if (Test-Path -LiteralPath $script:ClientDir -PathType Leaf) { $script:ClientDir = Split-Path $script:ClientDir }
        if ((Split-Path $script:ClientDir -Leaf) -eq 'Game') { $script:ClientDir = Split-Path $script:ClientDir }
        foreach ($name in @('LeagueClient.exe', 'LeagueClientUx.exe', 'Game\League of Legends.exe')) { $script:KnownPaths.Add((Join-Path $script:ClientDir $name)) }
    }
}

$script:ActivatedAt = $null
Invoke-Check 'activation-session' 'Client UI' {
    if (-not $script:UserData) { throw 'Rose user data directory unavailable.' }
    $script:ActivatedAt = Read-ActivationSession $script:UserData $script:Processes
}

Invoke-Check 'storage-environment' 'Environment' {
    $stateFiles = @()
    if ($script:UserData) { $stateFiles += Join-Path $script:UserData 'config.ini'; $stateFiles += Join-Path $script:UserData 'state\bridge_port.txt' }
    if ($script:PenguDir) { $stateFiles += Join-Path $script:PenguDir 'config'; $stateFiles += Join-Path $script:PenguDir 'datastore' }
    Test-StorageEnvironment @{ LOCALAPPDATA = $env:LOCALAPPDATA; TEMP = $env:TEMP; TMP = $env:TMP } $stateFiles
}

Invoke-Check 'pengu-runtime-sync' 'Client UI' {
    if (-not $script:Root -or -not $script:PenguDir) { throw 'Rose/Pengu paths unavailable for bundled/runtime comparison.' }
    $bundled = Join-Path $script:Root 'Pengu Loader'
    if (Test-Path -LiteralPath (Join-Path $script:Root '_internal\Pengu Loader')) { $bundled = Join-Path $script:Root '_internal\Pengu Loader' }
    Test-PenguRuntimeCopies $script:PenguDir $bundled
}

Invoke-Check 'environment-path' 'Environment' {
    Test-EnvironmentPath `
        ([Environment]::GetEnvironmentVariable('PATH', [EnvironmentVariableTarget]::Process)) `
        ([Environment]::GetEnvironmentVariable('PATH', [EnvironmentVariableTarget]::Machine)) `
        ([Environment]::GetEnvironmentVariable('PATH', [EnvironmentVariableTarget]::User))
}

Invoke-Check 'dotnet-framework' 'Client UI' {
    $full = Get-RegValues 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' 'Registry32'
    $release = 0
    if ($full) { $release = [int]$full['Release'] }
    if ($release -lt 461808) {
        Add-Finding 'dotnet-framework' 'Client UI' 'FAIL' 'Pengu Loader requires .NET Framework 4.7.2 or newer; registry does not report it.' "Release=$release" 'Install/repair Microsoft .NET Framework 4.7.2 or newer. Modern .NET (6/8/10) is a separate runtime.'
    } else { Add-Finding 'dotnet-framework' 'Client UI' 'PASS' '.NET Framework prerequisite is registered.' "Release=$release (minimum 461808); registry presence does not prove runtime files are intact." }
    $framework = Join-Path $env:windir 'Microsoft.NET\Framework64\v4.0.30319'
    foreach ($relative in @('clr.dll', 'System.Management.dll', 'WPF\PresentationFramework.dll', 'WPF\PresentationCore.dll')) {
        $runtimeFile = Join-Path $framework $relative
        if (-not (Test-Path -LiteralPath $runtimeFile -PathType Leaf)) {
            Add-Finding "dotnet.file.$relative" 'Client UI' 'WARN' 'Expected .NET Framework/WPF file is missing; registry alone may hide a stripped or damaged runtime.' $runtimeFile 'Repair the Windows .NET Framework installation; Pengu Loader uses WPF and System.Management.'
        }
    }
}

Invoke-Check 'pengu-files' 'Client UI' {
    if (-not $script:PenguDir) { throw 'Pengu path unavailable; specify -RosePath or -DataPath.' }
    Test-Binary (Join-Path $script:PenguDir 'core.dll') 'Client UI' 'pengu.core' -RequireX64
    Test-Binary (Join-Path $script:PenguDir 'Pengu Loader.exe') 'Client UI' 'pengu.loader'
    foreach ($name in @('ModernWpf.dll', 'ModernWpf.Controls.dll', 'Ookii.Dialogs.Wpf.dll', 'System.ValueTuple.dll')) {
        Test-Binary (Join-Path $script:PenguDir $name) 'Client UI' "pengu.dependency.$name"
    }
    foreach ($plugin in @('ROSE-SettingsPanel', 'ROSE-SkinMonitor', 'ROSE-UI')) {
        $folder = Join-Path $script:PenguDir "plugins\$plugin"
        Invoke-Check "plugin.$plugin" 'Client UI' { Test-PluginEntry $folder $plugin }
    }
    try {
        $acl = Get-Acl -LiteralPath $script:PenguDir
        $denies = @($acl.Access | Where-Object { $_.AccessControlType -eq 'Deny' })
        Add-Finding 'pengu.acl' 'Client UI' 'INFO' 'Runtime directory ACL inspected; effective read/write permission is not proven.' "Explicit/inherited deny entries=$($denies.Count)" 'Correlate access-denied log messages with folder permissions. No write probe was performed.'
    } catch { Add-Finding 'pengu.acl' 'Client UI' 'UNKNOWN' 'Runtime directory ACL could not be read.' $_.Exception.Message }
}

Invoke-Check 'pengu-config' 'Client UI' {
    $configFile = Join-Path $script:UserData 'config.ini'
    if (-not (Test-Path -LiteralPath $configFile -PathType Leaf)) { Add-Finding 'pengu.config' 'Client UI' 'FAIL' 'Rose config.ini is missing from the inspected user profile.' $configFile 'Activation can succeed and core.dll can load while this file is missing. Check pengu.profile-config for the required [General] settings and confirm the League user profile.'; return }
    $disabled = $script:Config['general/disabled']; $loader = $script:Config['general/loaderpath']
    Add-Finding 'pengu.switches' 'Client UI' 'INFO' 'Only hook-related config values were collected.' "disabled=$disabled; loaderpath=$loader"
    $configBytes = [IO.File]::ReadAllBytes($configFile)
    if ($configBytes.Length -ge 3 -and $configBytes[0] -eq 239 -and $configBytes[1] -eq 187 -and $configBytes[2] -eq 191) {
        Add-Finding 'pengu.config-encoding' 'Client UI' 'WARN' 'config.ini has a UTF-8 BOM; current Rose normally writes native ANSI config.' '' 'Check whether the native hook reads the General section correctly; rewriting through current Rose can normalize legacy config encoding.'
    }
    if ($disabled -in @('1', 'true')) { Add-Finding 'pengu.disabled' 'Client UI' 'FAIL' 'Native client hook is disabled in Rose config.' '' 'Enable Rose through its normal UI and check the activation log.' }
    elseif ($disabled -notin @('0', 'false')) { Add-Finding 'pengu.disabled' 'Client UI' 'UNKNOWN' 'Native hook disabled value is missing or unrecognized.' $disabled 'Check whether Rose completed activation.' }
    if (-not $loader -or -not (Test-Path -LiteralPath (Join-Path $loader 'plugins') -PathType Container)) {
        Add-Finding 'pengu.loaderpath' 'Client UI' 'FAIL' 'Native plugin loaderpath is empty or points to a missing plugins directory.' $loader 'Restore [General] loaderpath in the League account config.ini to the actual Pengu Loader directory containing plugins; see pengu.profile-config. Activation alone does not establish correct configuration.'
    }
    if ($loader -and $loader -match '[^\x00-\x7F]') {
        Add-Finding 'pengu.path-encoding' 'Client UI' 'WARN' 'Native loaderpath contains non-ASCII characters.' $loader 'Check for an older UTF-8 config or a path garbled by the Windows INI API. Current Rose writes this file using the Windows ANSI code page.'
    }
}

Invoke-Check 'pengu-accounts' 'Client UI' {
    foreach ($process in ($script:Processes | Where-Object { $_.name -eq 'Rose.exe' -and $_.token.Profile })) {
        $client = $script:Processes | Where-Object { $_.name -eq 'LeagueClientUx.exe' -and $_.token.Profile } | Select-Object -First 1
        if ($client -and -not (Test-SamePath $process.token.Profile $client.token.Profile)) {
            Add-Finding 'accounts.rose-client' 'Client UI' 'WARN' 'Rose and the League client run under different Windows profiles.' '' 'Verify Rose writes the desktop/client user config. This can occur when elevation uses another administrator account.'
        }
    }
}

Invoke-Check 'pengu-activation' 'Client UI' {
    $target = 'LeagueClientUx.exe'
    $reg64 = Get-RegValues "$script:IfeoBase\$target" 'Registry64'
    $reg32 = Get-RegValues "$script:IfeoBase\$target" 'Registry32'
    $debug64 = ''; $debug32 = ''
    if ($reg64) { $debug64 = [string]$reg64['Debugger'] }
    if ($reg32) { $debug32 = [string]$reg32['Debugger'] }
    $symlinkMode = $script:LoaderConfig['/usesymlink'] -in @('1', 'true')
    $expectedCore = ''
    if ($script:PenguDir) { $expectedCore = Join-Path $script:PenguDir 'core.dll' }
    if ($symlinkMode) {
        if (-not $script:ClientDir) { throw 'UseSymlink is enabled but League directory is unavailable.' }
        $linkPath = Join-Path $script:ClientDir 'version.dll'
        if (-not (Test-Path -LiteralPath $linkPath)) {
            Add-Finding 'pengu.symlink' 'Client UI' 'FAIL' 'UseSymlink is enabled but version.dll is missing or its target is unavailable.' $linkPath 'Reactivate through Rose/Pengu and verify the League folder.'
            return
        }
        $link = Get-Item -LiteralPath $linkPath -Force -ErrorAction Stop
        Add-Finding 'pengu.symlink' 'Client UI' 'INFO' 'Pengu is configured to activate through version.dll.' "$linkPath; LinkType=$($link.LinkType); Target=$($link.Target -join ', ')"
        if (-not $link.Target -or -not (Test-SamePath ([string]@($link.Target)[0]) $expectedCore)) {
            Add-Finding 'pengu.symlink-target' 'Client UI' 'WARN' 'version.dll link does not resolve to the selected core.dll.' $linkPath 'Check Pengu activation and the configured League installation.'
        }
    } else {
        $hook = Get-HookTarget $debug64
        if (-not $debug64) {
            Add-Finding 'pengu.ifeo' 'Client UI' 'FAIL' '64-bit LeagueClientUx IFEO Debugger activation is absent.' '' 'Start/enable Rose and inspect Pengu activation errors. Writing this HKLM setting requires elevation.'
        } elseif (-not $hook) {
            Add-Finding 'pengu.ifeo' 'Client UI' 'FAIL' 'LeagueClientUx has an unexpected or malformed Debugger value.' $debug64 'Identify the application that owns this value. Reactivate through Rose after resolving the conflict; do not blindly delete unrelated registry settings.'
        } elseif (-not (Test-Path -LiteralPath $hook -PathType Leaf)) {
            Add-Finding 'pengu.ifeo' 'Client UI' 'FAIL' 'Pengu activation references a missing DLL.' $debug64 'Reactivate Rose from the current install/runtime path.'
        } elseif (-not $expectedCore) {
            Add-Finding 'pengu.ifeo' 'Client UI' 'UNKNOWN' 'Hook target exists but selected Pengu runtime is unavailable.' $debug64
        } elseif (-not (Test-SamePath $hook $expectedCore)) {
            Add-Finding 'pengu.ifeo' 'Client UI' 'WARN' 'Client activation points to a different Pengu installation.' "actual=$hook; expected=$expectedCore" 'Check old installs and account-specific runtime directories; activate the intended Rose copy.'
        } else { Add-Finding 'pengu.ifeo' 'Client UI' 'PASS' 'IFEO activation points to the selected core.dll.' $debug64 }
    }
    if ($debug32 -and $debug32 -ne $debug64) {
        Add-Finding 'pengu.ifeo-views' 'Client UI' 'WARN' '32-bit and 64-bit IFEO Debugger values differ.' "64-bit=$debug64; 32-bit=$debug32" 'Current Rose uses the 64-bit view; check for stale loader registrations.'
    }
    if ($reg64 -and $reg64['UseFilter']) {
        Add-Finding 'pengu.ifeo-filter' 'Client UI' 'WARN' 'IFEO UseFilter is enabled; path-specific subkeys can affect activation.' "UseFilter=$($reg64['UseFilter'])" 'Inspect the filter entries against the running League path.'
        foreach ($child in (Get-RegChildren "$script:IfeoBase\$target")) {
            $filter = Get-RegValues "$script:IfeoBase\$target\$child"
            Add-Finding "pengu.ifeo-filter.$child" 'Client UI' 'INFO' 'Path-specific IFEO filter.' "FilterFullPath=$($filter['FilterFullPath']); Debugger=$($filter['Debugger'])"
        }
    }
    foreach ($process in ($script:Processes | Where-Object { $_.name -eq 'LeagueClientUx.exe' })) {
        try {
            $modules = @([Diagnostics.Process]::GetProcessById($process.pid).Modules | Where-Object { $_.ModuleName -ieq 'core.dll' })
            if ($modules.Count -eq 0) {
                Add-Finding "pengu.loaded.$($process.pid)" 'Client UI' 'WARN' 'No core.dll was observed in the running League client.' "pid=$($process.pid)" 'Check activation and block events. If activation changed after this client started, fully restart the client when outside a match.'
                Test-ClientActivationTiming $process.pid $process.start $script:ActivatedAt
            } else {
                foreach ($module in $modules) {
                    if (Test-SamePath $module.FileName $expectedCore) { $status = 'PASS' } else { $status = 'WARN' }
                    Add-Finding "pengu.loaded.$($process.pid)" 'Client UI' $status 'A core.dll module was observed in the client; this does not prove plugins initialized.' $module.FileName 'If the icon is still missing, inspect config, plugin enable state and JavaScript/client logs.'
                }
            }
        } catch { Add-Finding "pengu.loaded.$($process.pid)" 'Client UI' 'UNKNOWN' 'Loaded client modules could not be read.' $_.Exception.Message 'Try 64-bit PowerShell as administrator.' }
    }
}

Invoke-Check 'league-paths' 'Environment' {
    if (-not $script:ClientDir) { throw 'League path unavailable; use -LeaguePath or leave the client running.' }
    Add-Finding 'league.path' 'Environment' 'INFO' 'League client folder inspected.' $script:ClientDir
    foreach ($name in @('LeagueClient.exe', 'LeagueClientUx.exe')) {
        if (-not (Test-Path -LiteralPath (Join-Path $script:ClientDir $name))) {
            Add-Finding "league.file.$name" 'Client UI' 'FAIL' 'Selected League client folder is missing an expected executable.' $name 'Select the correct installation or repair League through Riot Client.'
        }
    }
    if ($script:LoaderConfig['/leaguepath'] -and -not (Test-SamePath $script:ClientDir $script:LoaderConfig['/leaguepath'])) {
        Add-Finding 'league.loader-path' 'Client UI' 'WARN' 'Pengu LeaguePath differs from the inspected/running client installation.' $script:LoaderConfig['/leaguepath'] 'Select the running League install through Rose.'
    }
    if ($script:Config['general/clientpath'] -and -not (Test-SamePath $script:ClientDir $script:Config['general/clientpath'])) {
        Add-Finding 'league.rose-path' 'Environment' 'WARN' 'Rose clientPath differs from the inspected/running client.' $script:Config['general/clientpath'] 'Check Rose game/client path settings.'
    }
}

Invoke-Check 'ifeo-other-settings' 'Environment' {
    foreach ($name in @('LeagueClient.exe', 'LeagueClientUx.exe', 'LeagueClientUxRender.exe', 'League of Legends.exe', 'League of Legends (TM) Client.exe', 'ltk_patcher_host.exe', 'Rose.exe')) {
        $values = Get-RegValues "$script:IfeoBase\$name"
        if (-not $values) { continue }
        if ($name -ne 'LeagueClientUx.exe' -and $values['Debugger']) {
            Add-Finding "ifeo.debugger.$name" 'Environment' 'WARN' 'Another relevant executable has an IFEO Debugger override.' "$name; Debugger=$($values['Debugger'])" 'Confirm the owner of the override and inspect related launch errors. Pengu normally registers only LeagueClientUx.exe.'
        }
        foreach ($setting in @('GlobalFlag', 'VerifierDlls', 'VerifierFlags', 'MitigationOptions', 'MitigationAuditOptions')) {
            if (-not $values.ContainsKey($setting)) { continue }
            $value = $values[$setting]
            if ($value -is [byte[]]) { $value = [BitConverter]::ToString($value) }
            Add-Finding "ifeo.$setting.$name" 'Environment' 'INFO' 'Additional IFEO instrumentation/mitigation setting is present.' "$name; $setting=$value" 'Presence alone does not prove failure. Correlate with live mitigations, process errors and relevant security events.'
        }
    }
}

Invoke-Check 'ltk-files' 'Game skins' {
    if (-not $script:ToolsDir) { throw 'Tools directory unavailable; specify -RosePath.' }
    foreach ($name in @('ltk_patcher_host.exe', 'ltk_patcher_dll.dll', 'mod-tools.exe', 'cslol-dll.dll')) {
        Test-Binary (Join-Path $script:ToolsDir $name) 'Game skins' "tools.$name" -RequireX64
    }
    Add-Finding 'tools.cslol-role' 'Game skins' 'INFO' 'LTK does game patching; this Rose build still requires its cslol-dll.dll stand-in to start mod-tools.exe.' '' 'Use the stand-in supplied by Rose, not an old CSLOL injection DLL.'
    $dll = Join-Path $script:ToolsDir 'ltk_patcher_dll.dll'
    if (Test-Path -LiteralPath $dll) {
        $cutoff = Get-LtkCutoff (Get-PeInfo $dll)
        if ($null -eq $cutoff) {
            Add-Finding 'ltk.cutoff' 'Game skins' 'UNKNOWN' 'Built-in LTK cutoff could not be recognized by the static parser.' '' 'Consult actual patcher errors and update both LTK files together if needed.'
        } else {
            $date = ([datetime]'1970-01-01Z').ToUniversalTime().AddSeconds($cutoff)
            $status = 'INFO'
            if ([datetime]::UtcNow -gt $date) { $status = 'WARN' }
            Add-Finding 'ltk.cutoff' 'Game skins' $status 'LTK cutoff found using Rose static parsing heuristic.' $date.ToString('o') `
                'The DLL compares the game PE build timestamp against this date; current Rose also rejects a cutoff older than the current clock. Update both LTK files from the same installation if the cutoff is past.'
            $game = $null
            if ($script:ClientDir) { $game = Join-Path $script:ClientDir 'Game\League of Legends.exe' }
            if ($game -and (Test-Path -LiteralPath $game)) {
                $gamePe = Get-PeInfo $game
                if ($gamePe.timestamp -gt $cutoff) {
                    Add-Finding 'ltk.game-cutoff' 'Game skins' 'FAIL' 'Game PE build timestamp exceeds the detected LTK cutoff.' "gameTimestamp=$($gamePe.timestamp); cutoff=$cutoff" 'Replace both LTK files with a compatible pair from a current trusted LTK Manager installation.'
                }
            }
        }
    }
}

Invoke-Check 'compatibility-flags' 'Environment' {
    foreach ($hive in @('CurrentUser', 'LocalMachine')) {
        foreach ($view in @('Registry64', 'Registry32')) {
            $layers = Get-RegValues 'SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers' $view $hive
            if (-not $layers) { continue }
            foreach ($path in $layers.Keys) {
                if (-not (Test-RelevantText $path)) { continue }
                if ($layers[$path] -match '(?i)RUNASADMIN|WIN7|WIN8|VIST|WINXP') {
                    Add-Finding "compatibility.$hive.$view" 'Environment' 'WARN' 'Relevant executable has elevation/old compatibility flags.' "$path; flags=$($layers[$path])" 'Review Properties > Compatibility. Confirm these flags are intentional and compare live process privileges.'
                }
            }
        }
    }
}

Invoke-Check 'process-mitigations' 'Security' {
    if (-not $script:NativeAvailable) { throw 'Native read-only queries unavailable.' }
    foreach ($process in ($script:Processes | Where-Object { $_.name -in @('LeagueClientUx.exe', 'League of Legends.exe', 'League of Legends (TM) Client.exe') })) {
        try {
            $signature = [RoseDiagnostics.Native]::Mitigation($process.pid, 8)
            $dynamic = [RoseDiagnostics.Native]::Mitigation($process.pid, 2)
            Add-Finding "mitigation.$($process.pid)" 'Security' 'INFO' 'Live process mitigation flags.' "$($process.name); signatureFlags=0x$($signature.ToString('X')); dynamicCodeFlags=0x$($dynamic.ToString('X'))"
            if (($signature -band 3) -ne 0) {
                Add-Finding "mitigation.signature.$($process.pid)" 'Security' 'WARN' 'Process enforces Microsoft/Store-only image signatures, which can reject third-party DLLs.' $process.name 'Correlate Code Integrity events and exploit-protection settings with the exact DLL. Do not assume this policy is the cause without matching evidence.'
            }
            if (($dynamic -band 1) -ne 0) {
                Add-Finding "mitigation.dynamic.$($process.pid)" 'Security' 'WARN' 'Process restricts dynamic executable code; hook compatibility may be affected.' $process.name 'Correlate loader failures and exploit-protection events before changing settings.'
            }
        } catch { Add-Finding "mitigation.$($process.pid)" 'Security' 'UNKNOWN' 'Live process mitigation query failed.' $_.Exception.Message }
    }
    $hosts = @($script:Processes | Where-Object { $_.name -eq 'ltk_patcher_host.exe' -and $_.token })
    $games = @($script:Processes | Where-Object { $_.name -like 'League of Legends*.exe' -and $_.token })
    foreach ($hostProcess in $hosts) {
        foreach ($gameProcess in $games) {
            if ($gameProcess.token.Integrity -gt $hostProcess.token.Integrity) {
                Add-Finding 'ltk.privileges' 'Game skins' 'WARN' 'Game integrity level is higher than the running patcher host.' "game=$($gameProcess.token.Integrity); host=$($hostProcess.token.Integrity)" 'Review elevation/compatibility flags for both programs and the actual patcher access-denied error.'
            }
        }
    }
}

Invoke-Check 'windows-time-service' 'Environment' {
    $service = Get-Service -Name W32Time -ErrorAction SilentlyContinue
    if ($service) {
        $status = 'INFO'; if ($service.StartType -eq 'Disabled') { $status = 'WARN' }
        Add-Finding 'clock.service' 'Environment' $status 'Windows Time service state (stopped can be normal with trigger start).' "Status=$($service.Status); StartType=$($service.StartType)" 'If time is wrong, review Windows automatic time settings or the organization time policy.'
    } else { Add-Finding 'clock.service' 'Environment' 'UNKNOWN' 'Windows Time service was not found.' }
    $settings = Get-RegValues 'SYSTEM\CurrentControlSet\Services\W32Time\Parameters'
    if ($settings -and $settings['Type'] -eq 'NoSync') { Add-Finding 'clock.sync-disabled' 'Environment' 'WARN' 'Windows Time is configured not to synchronize.' '' 'Review automatic time settings. This setting alone does not establish clock drift.' }
}
Invoke-Check 'clock-comparison' 'Environment' {
    if ($SkipNetworkChecks) {
        Add-Finding 'clock.offset' 'Environment' 'UNKNOWN' 'External time comparison skipped by request.' '' 'Check Windows Date & time manually.'
        return
    }
    Write-Host 'Comparing clock with time.windows.com (NTP only; no report data sent)...'
    $system = Join-Path $env:SystemRoot 'System32'
    if (-not [Environment]::Is64BitProcess -and [Environment]::Is64BitOperatingSystem) { $system = Join-Path $env:SystemRoot 'Sysnative' }
    $before = [DateTime]::UtcNow; $watch = [Diagnostics.Stopwatch]::StartNew()
    try {
        $samples = Invoke-BoundedReadOnlyQuery (Join-Path $system 'w32tm.exe') '/stripchart /computer:time.windows.com /dataonly /samples:3 /period:1'
        $elapsed = ([DateTime]::UtcNow - $before).TotalSeconds
        if ([Math]::Abs($elapsed - $watch.Elapsed.TotalSeconds) -gt 5) {
            Add-Finding 'clock.offset' 'Environment' 'UNKNOWN' 'The Windows clock changed during measurement.' '' 'Let synchronization finish, then rerun the checker.'
        } else { Test-ClockSamples $samples }
    } catch {
        Add-Finding 'clock.offset' 'Environment' 'UNKNOWN' 'External time comparison unavailable; clock drift was not measured.' $_.Exception.Message 'NTP may be blocked, the machine may be offline, or w32tm may be missing. None proves a wrong clock. Compare Windows Date & time manually.'
    } finally { $watch.Stop() }
}

Invoke-Check 'security-products' 'Security' {
    $sac = Get-RegValues 'SYSTEM\CurrentControlSet\Control\CI\Policy'
    if ($sac -and $sac.ContainsKey('VerifiedAndReputablePolicyState')) {
        $state = [int]$sac['VerifiedAndReputablePolicyState']; $label = 'unrecognized'
        if ($state -eq 0) { $label = 'off' }; if ($state -eq 1) { $label = 'enforced' }; if ($state -eq 2) { $label = 'evaluation' }
        Add-Finding 'sac.state' 'Security' 'INFO' 'Smart App Control registry state (corroborate with events).' "$state ($label)" 'Enabled or evaluation state alone does not establish a block; Code Integrity 3077 is an enforced App Control event and 3076 is audit.'
    } else { Add-Finding 'sac.state' 'Security' 'UNKNOWN' 'Smart App Control state is not present in this registry location.' '' 'This is normal on many Windows versions. Other App Control policies can still apply.' }
    if (Get-Command Get-MpComputerStatus -ErrorAction SilentlyContinue) {
        try {
            $mp = Get-MpComputerStatus
            Add-Finding 'defender.state' 'Security' 'INFO' 'Defender status; enabled protection is not itself a failure.' "AntivirusEnabled=$($mp.AntivirusEnabled); RealTimeProtectionEnabled=$($mp.RealTimeProtectionEnabled); AMRunningMode=$($mp.AMRunningMode)"
        } catch { Add-Finding 'defender.state' 'Security' 'UNKNOWN' 'Defender status could not be read.' $_.Exception.Message }
    } else { Add-Finding 'defender.state' 'Security' 'UNKNOWN' 'Defender status cmdlet is unavailable.' '' 'A stripped system or another antivirus can still block files; review that product history.' }
    try {
        $products = @(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntivirusProduct -OperationTimeoutSec 5)
        Test-AntivirusProducts $products
    } catch { Add-Finding 'antivirus.products' 'Security' 'UNKNOWN' 'Security Center antivirus inventory unavailable.' $_.Exception.Message }
}

Invoke-Check 'app-control-policies' 'Security' {
    $system = Join-Path $env:windir 'System32'
    if (-not [Environment]::Is64BitProcess -and [Environment]::Is64BitOperatingSystem) { $system = Join-Path $env:windir 'Sysnative' }
    $ciTool = Join-Path $system 'CiTool.exe'
    if (-not (Test-Path -LiteralPath $ciTool)) {
        Add-Finding 'app-control-policies' 'Security' 'UNKNOWN' 'Windows CiTool is unavailable; active App Control policies were not enumerated.' '' 'Use the security events and Smart App Control state. CiTool is absent on older Windows builds.'
        return
    }
    # Windows read-only policy query. Bound its lifetime; do not execute any
    # third-party injection tools. The clock check also queries Windows w32tm.
    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = $ciTool; $startInfo.Arguments = '-lp -json'
    $startInfo.UseShellExecute = $false; $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true; $startInfo.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(5000)) {
            $process.Kill() # Only our own CiTool query, never Rose/League/patcher.
            throw 'CiTool read-only policy query timed out after 5 seconds.'
        }
        if ($process.ExitCode -ne 0) { throw "CiTool policy query exited with $($process.ExitCode): $($stderr.Result)" }
        $policies = ($stdout.Result | ConvertFrom-Json).Policies
        foreach ($policy in $policies) {
            Add-Finding 'app-control.policy' 'Security' 'INFO' 'Windows App Control policy inventory (not proof of an app block).' `
                "$($policy.FriendlyName); enforced=$($policy.IsEnforced); authorized=$($policy.IsAuthorized); onDisk=$($policy.IsOnDisk)" `
                'Use a matching enforced file-block event to establish which policy affected the failed attempt. An active policy may itself be an audit policy.'
        }
    } finally { $process.Dispose() }
}

Invoke-Check 'services-and-wmi' 'Environment' {
    foreach ($name in @('Winmgmt', 'EventLog', 'WinDefend', 'SecurityHealthService', 'vgc')) {
        $service = Get-Service -Name $name -ErrorAction SilentlyContinue
        if ($service) { Add-Finding "service.$name" 'Environment' 'INFO' 'Relevant Windows/service state; stopped does not automatically mean injection failure.' "$name; status=$($service.Status); startType=$($service.StartType)" }
        else { Add-Finding "service.$name" 'Environment' 'INFO' 'Service was not found; this alone is not a root cause.' $name }
    }
    try {
        [void](Get-CimInstance Win32_OperatingSystem -Property Version -OperationTimeoutSec 5)
        Add-Finding 'wmi.query' 'Environment' 'PASS' 'Basic CIM/WMI query succeeded.' '' 'This tests provider availability, not the integrity of every Windows component.'
    } catch { Add-Finding 'wmi.query' 'Environment' 'WARN' 'Basic WMI query failed; Pengu uses WMI for its credential fallback.' $_.Exception.Message 'Check Windows Management Instrumentation/service health and whether the client lockfile fallback was needed. WMIC.exe itself is not required by the current loader.' }
}

Invoke-Check 'bridge' 'Client UI' {
    $path = Join-Path $script:UserData 'state\bridge_port.txt'
    if (-not (Test-Path -LiteralPath $path)) { Add-Finding 'bridge.port-file' 'Client UI' 'WARN' 'Rose bridge discovery file is missing.' $path 'Leave Rose open; check its backend startup log and the selected user profile.'; return }
    $port = 0; $text = ([IO.File]::ReadAllText($path)).Trim()
    if (-not [int]::TryParse($text, [ref]$port) -or $port -lt 1 -or $port -gt 65535) { Add-Finding 'bridge.port-file' 'Client UI' 'FAIL' 'Bridge port file is invalid.' '' 'Restart Rose outside a match and inspect backend startup errors.'; return }
    if ($script:PenguDir) { Invoke-Check 'bridge.discovery-range' 'Client UI' { Test-BridgeDiscoveryRange $port (Join-Path $script:PenguDir 'plugins\ROSE-SkinMonitor\index.js') } }
    $tcp = New-Object Net.Sockets.TcpClient
    try {
        $async = $tcp.BeginConnect('127.0.0.1', $port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(1500)) { throw 'Loopback TCP connection timed out.' }
        $tcp.EndConnect($async)
        Add-Finding 'bridge.tcp' 'Client UI' 'PASS' 'Something accepts loopback TCP connections on the recorded Rose port.' "127.0.0.1:$port" 'TCP reachability alone does not prove a working Rose WebSocket or loaded plugin.'
    } catch { Add-Finding 'bridge.tcp' 'Client UI' 'WARN' 'Recorded bridge port is unreachable (could be stale, backend stopped, or blocked).' "127.0.0.1:$port; $($_.Exception.Message)" 'Check Rose backend logs and local loopback filtering.' }
    finally { $tcp.Close() }
    Invoke-Check 'bridge.owner' 'Client UI' { Test-BridgeOwner $port }
    Test-BridgeHttp $port
}

$eventQueries = @(
    # Signature-detail 3089 events can drown out actual blocks in a bounded query.
    @{ log = 'Microsoft-Windows-CodeIntegrity/Operational'; ids = @(3033, 3034, 3036, 3076, 3077) },
    @{ log = 'Microsoft-Windows-AppLocker/EXE and DLL'; ids = @(8003, 8004) },
    @{ log = 'Microsoft-Windows-AppLocker/MSI and Script'; ids = @(8006, 8007, 8028, 8029) },
    @{ log = 'Microsoft-Windows-Windows Defender/Operational'; ids = @(1116, 1117, 1118, 1119, 1121, 1122, 1123, 1124, 1127, 1128) },
    @{ log = 'Application'; ids = @(33, 59, 1000, 1001, 1026) }
)
foreach ($query in $eventQueries) {
    Invoke-Check "events.$($query.log)" 'Security' { Read-RelevantEvents $query.log $query.ids }
}

Invoke-Check 'rose-error-excerpts' 'Logs' {
    $paths = @()
    $logDir = Join-Path $script:UserData 'logs'
    if (Test-Path -LiteralPath $logDir) {
        $logs = @(Get-ChildItem -LiteralPath $logDir -File)
        $paths += @($logs | Where-Object { $_.Name -match '^rose_(?!runoverlay_).*\.log' } | Sort-Object LastWriteTime -Descending | Select-Object -First 2)
        $paths += @($logs | Where-Object { $_.Name -match '^(rose_runoverlay_|log_runoverlay_).*\.log' } | Sort-Object LastWriteTime -Descending | Select-Object -First 2)
    }
    if ($script:PenguDir) {
        foreach ($name in @('pengu.log', 'rose.log', 'crash.log')) {
            $path = Join-Path $script:PenguDir $name
            if (Test-Path -LiteralPath $path -PathType Leaf) { $paths += Get-Item -LiteralPath $path }
        }
    }
    $pattern = '(?i)(Pengu.*(?:fail|error|unavailable|restart|defer)|(?:activation|loaderpath|IFEO).*(?:fail|error|denied)|LTK.*(?:fail|error|missing|end of life|too late)|(?:could not|failed to) (?:start|copy).*Pengu|(?:0xC000007B|0xC0000135|0xC0000142|WinError (?:5|126|193|577|225))|overlay verification failed|end of life reached|joined.*too late|SetWindowsHookEx.*failed|hook install failed|Host injection failed|Server stopped unexpectedly|bind.*(?:fail|error)|core\.dll.*(?:fail|error)|(?:ERROR|Exception).*(?:plugins|bridge|access.*denied))'
    $scanned = 0
    foreach ($file in $paths) {
        if ($file.LastWriteTime -lt $script:Started.AddDays(-$Days)) { continue }
        $scanned++
        $stream = [IO.File]::Open($file.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        try {
            $offset = [Math]::Max(0, $stream.Length - 262144)
            [void]$stream.Seek($offset, [IO.SeekOrigin]::Begin)
            $reader = New-Object IO.StreamReader($stream, [Text.Encoding]::UTF8, $true)
            try { if ($offset -gt 0) { [void]$reader.ReadLine() }; $tail = $reader.ReadToEnd() } finally { $reader.Dispose() }
        } finally { $stream.Dispose() }
        $matchesInLog = @($tail -split '\r?\n' | Where-Object { $_ -match $pattern } | Select-Object -Last 12)
        foreach ($line in $matchesInLog) {
            if ($line.Length -gt 1800) { $line = $line.Substring(0, 1800) + ' [truncated]' }
            Add-Finding 'log.excerpt' 'Logs' 'WARN' 'Recent selected error/activation excerpt (may predate the current attempt).' "$($file.FullName): $line" 'Use the timestamp and the findings above to narrow the cause.'
        }
        Add-Finding 'log.scanned' 'Logs' 'INFO' 'Bounded log scan completed.' "$($file.FullName); modified=$($file.LastWriteTime.ToString('o')); last 256 KiB only; selected excerpts=$($matchesInLog.Count)"
    }
    if ($scanned -eq 0) { Add-Finding 'log.available' 'Logs' 'UNKNOWN' 'No recent Rose/Pengu logs were found at the selected paths.' "Lookback=$Days days" 'Start Rose, reproduce the failure and rerun with the correct DataPath.' }
}

Invoke-Check 'profile-config-guidance' 'Client UI' { Add-PenguConfigurationGuidance }
Invoke-Check 'manual-activation-guidance' 'Client UI' { Add-ManualActivationGuidance }
Write-Reports
