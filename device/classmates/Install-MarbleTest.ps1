[CmdletBinding()]
param(
    [switch] $Install,
    [switch] $BootOnly,
    [string] $Serial,
    [string] $FastbootPath
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# Private classroom test utility. It never flashes boot.img; fastboot boot is temporary.
$script:Root = $PSScriptRoot
$script:ManifestPath = Join-Path $script:Root 'manifest.json'
$script:LogPath = Join-Path $script:Root 'installer-result.json'
$script:Actions = New-Object System.Collections.Generic.List[string]

function Write-Result {
    param([string] $Status, [string] $Message)
    $obj = [ordered]@{
        timestampUtc = [DateTime]::UtcNow.ToString('o')
        status = $Status
        message = $Message
        actions = @($script:Actions.ToArray())
    }
    $obj | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $script:LogPath -Encoding UTF8
}

function Stop-Install {
    param([string] $Message)
    Write-Result -Status 'failed' -Message $Message
    throw $Message
}

function Invoke-Fastboot {
    param([string[]] $Arguments, [switch] $CheckExit = $true)
    $displayArgs = @($Arguments | ForEach-Object {
        if ($_ -eq $Serial) { '<selected-device>' } else { $_ }
    })
    $safeArgs = @($displayArgs | ForEach-Object {
        if ($_ -match '\.(simg|img)$') { '<payload>' } else { $_ }
    })
    $script:Actions.Add(('fastboot ' + ($safeArgs -join ' ')))
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $script:Fastboot
    $psi.Arguments = (@($Arguments | ForEach-Object { ConvertTo-WindowsArgument $_ }) -join ' ')
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    try {
        if (-not $proc.Start()) { Stop-Install 'Could not start fastboot.' }
        $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
        $stderrTask = $proc.StandardError.ReadToEndAsync()
        $proc.WaitForExit()
        $captured = @(($stdoutTask.Result -split "`r?`n") + ($stderrTask.Result -split "`r?`n") | Where-Object { $_ -ne '' })
        $exitCode = $proc.ExitCode
    } catch {
        Stop-Install ('Could not execute fastboot: ' + $_.Exception.Message)
    } finally {
        $proc.Dispose()
    }
    if ($CheckExit -and $exitCode -ne 0) {
        Stop-Install ("fastboot exited with code {0} while running: fastboot {1}" -f $exitCode, ($displayArgs -join ' '))
    }
    return [pscustomobject]@{ Lines = $captured; ExitCode = $exitCode }
}

function ConvertTo-WindowsArgument {
    param([string] $Value)
    if ($null -eq $Value) { $Value = '' }
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    $slashes = 0
    foreach ($ch in $Value.ToCharArray()) {
        if ($ch -eq [char]92) { $slashes++; continue }
        if ($ch -eq [char]34) {
            [void]$sb.Append(('\' * (2 * $slashes + 1)))
            [void]$sb.Append('"')
            $slashes = 0
            continue
        }
        if ($slashes -gt 0) { [void]$sb.Append(('\' * $slashes)); $slashes = 0 }
        [void]$sb.Append($ch)
    }
    if ($slashes -gt 0) { [void]$sb.Append(('\' * (2 * $slashes))) }
    [void]$sb.Append('"')
    return $sb.ToString()
}

function Get-Var {
    param([string] $Name)
    $res = Invoke-Fastboot -Arguments (@('-s', $Serial, 'getvar', $Name))
    $joined = $res.Lines -join "`n"
    $pattern = '(?im)(?:\(bootloader\)\s*)?' + [regex]::Escape($Name) + '\s*:\s*(.+?)\s*$'
    $match = [regex]::Match($joined, $pattern)
    if (-not $match.Success) { Stop-Install ("Could not read required device variable: {0}" -f $Name) }
    return $match.Groups[1].Value.Trim()
}

function Convert-SizeToBytes {
    param([string] $Value, [string] $Label)
    $v = $Value.Trim()
    if ($v -match '^0x([0-9a-fA-F]+)$') { return [Convert]::ToInt64($Matches[1], 16) }
    if ($v -match '^([0-9]+)\s*(B|KB|MB|GB|KiB|MiB|GiB)?$') {
        $number = [int64]$Matches[1]
        $unit = [string]$Matches[2]
        $unit = $unit.ToUpperInvariant()
        $factor = [int64]1
        switch ($unit) {
            'KB' { $factor = 1000 }
            'MB' { $factor = 1000000 }
            'GB' { $factor = 1000000000 }
            'KIB' { $factor = 1024 }
            'MIB' { $factor = 1048576 }
            'GIB' { $factor = 1073741824 }
        }
        if ($factor -gt 1 -and $number -gt ([int64]::MaxValue / $factor)) { Stop-Install ("Invalid size returned for {0}" -f $Label) }
        return ($number * $factor)
    }
    Stop-Install ("Unrecognized size returned for {0}" -f $Label)
}

function Resolve-Payload {
    param($Entry, [string] $Name)
    Write-Host ('Checking SHA-256 of {0}; large system images can take several minutes.' -f $Name)
    if ($null -eq $Entry -or [string]::IsNullOrWhiteSpace([string]$Entry.file) -or
        [string]::IsNullOrWhiteSpace([string]$Entry.sha256) -or $null -eq $Entry.bytes) {
        Stop-Install ("Manifest entry '{0}' must contain file, bytes, and sha256" -f $Name)
    }
    if ([IO.Path]::IsPathRooted([string]$Entry.file) -or ([string]$Entry.file -match '(^|[\\/])\.\.([\\/]|$)')) {
        Stop-Install ("Manifest payload path for '{0}' must be a relative path inside this folder" -f $Name)
    }
    $path = Join-Path $script:Root ([string]$Entry.file)
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Stop-Install ("Missing payload file for '{0}'" -f $Name) }
    $expectedBytes = [int64]$Entry.bytes
    if ((Get-Item -LiteralPath $path).Length -ne $expectedBytes) { Stop-Install ("Payload size does not match manifest for '{0}'" -f $Name) }
    if ([string]$Entry.sha256 -notmatch '^[0-9a-fA-F]{64}$') { Stop-Install ("Invalid SHA-256 in manifest for '{0}'" -f $Name) }
    $actualHash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    if ($actualHash -ine [string]$Entry.sha256) { Stop-Install ("Payload SHA-256 does not match manifest for '{0}'" -f $Name) }
    return [pscustomobject]@{ Path = $path; Bytes = $expectedBytes }
}

try {
    if ($Install -and $BootOnly) { Stop-Install 'Choose either -Install or -BootOnly, not both.' }
    if (-not (Test-Path -LiteralPath $script:ManifestPath -PathType Leaf)) { Stop-Install 'manifest.json is required beside this script.' }
    try { $manifest = Get-Content -LiteralPath $script:ManifestPath -Raw | ConvertFrom-Json } catch { Stop-Install 'manifest.json is not valid JSON.' }
    if ([string]$manifest.supportedProduct -cne 'marble') { Stop-Install 'Manifest supportedProduct must be exactly marble.' }
    $expandedRootBytes = [int64]$manifest.expandedRootBytes
    if ($expandedRootBytes -lt 1) { Stop-Install 'Manifest expandedRootBytes must be a positive byte count.' }
    if (-not $BootOnly) { $rootfs = Resolve-Payload -Entry $manifest.payloads.rootfs -Name 'rootfs' }
    $boot = Resolve-Payload -Entry $manifest.payloads.boot -Name 'boot'

    if ([string]::IsNullOrWhiteSpace($FastbootPath)) {
        $FastbootPath = Join-Path $script:Root 'platform-tools\fastboot.exe'
    }
    if (-not (Test-Path -LiteralPath $FastbootPath -PathType Leaf)) { Stop-Install 'fastboot.exe was not found. Supply -FastbootPath or place it in platform-tools beside this folder.' }
    $script:Fastboot = (Resolve-Path -LiteralPath $FastbootPath).Path

    if (-not $Install -and -not $BootOnly -and [string]::IsNullOrWhiteSpace($Serial)) {
        $list = Invoke-Fastboot -Arguments @('devices')
        $serials = @($list.Lines | ForEach-Object { if ($_ -match '^\s*(\S+)\s+fastboot\s*$') { $Matches[1] } })
        if ($serials.Count -eq 0) { Stop-Install 'No fastboot device found. Check-only mode did not select a device.' }
        Write-Host ("Fastboot devices detected: {0}. No device was selected; rerun with -Serial <serial> to inspect one." -f $serials.Count)
        Write-Result -Status 'check-only' -Message 'Payload integrity passed; device not selected or inspected.'
        exit 0
    }
    if (($Install -or $BootOnly) -and [string]::IsNullOrWhiteSpace($Serial)) { Stop-Install '-Serial is required for -Install and -BootOnly.' }
    if ([string]::IsNullOrWhiteSpace($Serial)) { Stop-Install 'Use -Serial <serial> to inspect a specific device.' }
    if ($Serial -match '[\x00-\x1f\x7f"]') { Stop-Install 'Serial must not contain control characters or quotation marks.' }

    $product = Get-Var 'product'
    if ($product -cne 'marble') { Stop-Install 'Selected device product is not exactly marble.' }
    $unlocked = Get-Var 'unlocked'
    if ($unlocked -notmatch '^(?i:yes|true|1)$') { Stop-Install 'Selected device bootloader is not unlocked.' }
    $userspace = Get-Var 'is-userspace'
    if ($userspace -match '^(?i:yes|true|1)$') { Stop-Install 'Device is in fastbootd; reboot to bootloader fastboot and retry.' }
    if ($userspace -notmatch '^(?i:no|false|0)$') { Stop-Install 'Could not confirm bootloader fastboot mode.' }
    $userdataBytes = Convert-SizeToBytes -Value (Get-Var 'partition-size:userdata') -Label 'partition-size:userdata'
    if (-not $BootOnly -and $userdataBytes -lt $expandedRootBytes) { Stop-Install 'userdata partition is smaller than manifest expandedRootBytes.' }

    if (-not $BootOnly) {
        $maxDownload = Convert-SizeToBytes -Value (Get-Var 'max-download-size') -Label 'max-download-size'
        if ($maxDownload -lt 268435456) { Stop-Install 'Device max-download-size is less than 256 MiB required by -S 256M.' }
    }

    if ($Install) {
        $expected = 'ERASE USERDATA ' + $Serial
        Write-Host 'WARNING: This installs the marble test root and erases all user data on the selected device.' -ForegroundColor Yellow
        Write-Host ('To continue, type exactly: {0}' -f $expected) -ForegroundColor Yellow
        $typed = Read-Host 'Confirmation'
        if ($typed -cne $expected) { Stop-Install 'Confirmation did not match; no device write was issued.' }
        Write-Host 'Preflight checks and payload SHA-256 verification passed. Writing userdata now.' -ForegroundColor Yellow
        Write-Host 'Writing userdata; wait for completion and do not disconnect USB.'
        [void](Invoke-Fastboot -Arguments (@('-s', $Serial, '-S', '256M', 'flash', 'userdata', $rootfs.Path)))
        Write-Host 'Userdata write completed. Sending temporary boot command.'
        [void](Invoke-Fastboot -Arguments (@('-s', $Serial, 'boot', $boot.Path)))
        Write-Result -Status 'installed-boot-command-accepted' -Message 'Root write and temporary boot commands accepted; iOS startup outcome not verified.'
        Write-Host 'Install and temporary boot commands completed.'
    } elseif ($BootOnly) {
        [void](Invoke-Fastboot -Arguments (@('-s', $Serial, 'boot', $boot.Path)))
        Write-Result -Status 'boot-command-accepted' -Message 'Temporary boot command accepted; no partition flashed and iOS startup outcome not verified.'
        Write-Host 'Temporary boot command completed.'
    } else {
        Write-Result -Status 'checks-passed' -Message 'Selected marble device and payload checks passed; no write command was issued.'
        Write-Host 'Checks passed. No device write command was issued.'
    }
    exit 0
} catch {
    if ($_.Exception.Message -ne '') { Write-Error $_.Exception.Message }
    exit 1
}

