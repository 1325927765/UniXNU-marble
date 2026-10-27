[CmdletBinding()]
param()

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$installerSource = Join-Path $PSScriptRoot 'Install-MarbleTest.ps1'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'This test harness needs the .NET Framework 4.x C# compiler at its standard Windows path.' }

function Quote-Argument([string] $Value) {
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    $slashes = 0
    foreach ($ch in $Value.ToCharArray()) {
        if ($ch -eq [char]92) { $slashes++; continue }
        if ($ch -eq [char]34) { [void]$sb.Append(('\' * (2 * $slashes + 1))); [void]$sb.Append('"'); $slashes = 0; continue }
        if ($slashes -gt 0) { [void]$sb.Append(('\' * $slashes)); $slashes = 0 }
        [void]$sb.Append($ch)
    }
    if ($slashes -gt 0) { [void]$sb.Append(('\' * (2 * $slashes))) }
    [void]$sb.Append('"')
    return $sb.ToString()
}

function Run-Installer([string[]] $Arguments, [string] $Mode = 'ok', [string] $InputText = '') {
    if (Test-Path -LiteralPath $logPath) { Remove-Item -LiteralPath $logPath -Force }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = (Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe')
    $all = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $installerCopy) + $Arguments
    $psi.Arguments = (($all | ForEach-Object { Quote-Argument ([string]$_) }) -join ' ')
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardInput = $true
    $psi.EnvironmentVariables['MOCK_MODE'] = $Mode
    $psi.EnvironmentVariables['MOCK_LOG'] = $logPath
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()
    $outTask = $proc.StandardOutput.ReadToEndAsync()
    $errTask = $proc.StandardError.ReadToEndAsync()
    if ($InputText) { $proc.StandardInput.WriteLine($InputText) }
    $proc.StandardInput.Close()
    $proc.WaitForExit()
    return [pscustomobject]@{ ExitCode = $proc.ExitCode; Output = $outTask.Result + $errTask.Result; Log = if (Test-Path -LiteralPath $logPath) { @(Get-Content -LiteralPath $logPath) } else { @() } }
}

$temp = Join-Path $env:TEMP ('marble-installer-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp | Out-Null
try {
    $installerCopy = Join-Path $temp 'Install-MarbleTest.ps1'
    Copy-Item -LiteralPath $installerSource -Destination $installerCopy
    $mockSource = Join-Path $temp 'mock.cs'
    @'
using System;
using System.IO;
class MockFastboot {
 static int Main(string[] a) {
  string mode=Environment.GetEnvironmentVariable("MOCK_MODE")??"ok";
  string log=Environment.GetEnvironmentVariable("MOCK_LOG");
  if(log!=null) File.AppendAllText(log,String.Join("|",a)+Environment.NewLine);
  if(a.Length>=4 && a[2]=="getvar") {
   string n=a[3], v="";
   switch(n) {
    case "product": v=mode=="wrong-product"?"other":"marble"; break;
    case "unlocked": v=mode=="locked"?"no":"yes"; break;
    case "is-userspace": v=mode=="userspace"?"yes":"no"; break;
    case "partition-size:userdata": v="0x400000000"; break;
    case "max-download-size": v="0x10000000"; break;
    default: return 2;
   }
   Console.Error.WriteLine("(bootloader) "+n+": "+v);
   if(mode=="exit-error" && n=="is-userspace") return 7;
   return 0;
  }
  if(a.Length>0 && a[0]=="devices") { Console.WriteLine("MOCK fastboot"); return 0; }
  return 0;
 }
}
'@ | Set-Content -LiteralPath $mockSource -Encoding ASCII
    $mockExe = Join-Path $temp 'mock-fastboot.exe'
    & $compiler /nologo "/out:$mockExe" $mockSource
    if ($LASTEXITCODE -ne 0) { throw 'Could not compile the mocked fastboot executable.' }
    $logPath = Join-Path $temp 'calls.log'
    $root = [Text.Encoding]::ASCII.GetBytes('mock-root-image')
    $boot = [Text.Encoding]::ASCII.GetBytes('mock-boot-image')
    [IO.File]::WriteAllBytes((Join-Path $temp 'rootfs.simg'), $root)
    [IO.File]::WriteAllBytes((Join-Path $temp 'boot.img'), $boot)
    $manifest = [ordered]@{
        supportedProduct = 'marble'
        expandedRootBytes = 1073741824
        payloads = [ordered]@{
            rootfs = [ordered]@{ file = 'rootfs.simg'; bytes = $root.Length; sha256 = ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($root))).Replace('-', '') }
            boot = [ordered]@{ file = 'boot.img'; bytes = $boot.Length; sha256 = ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($boot))).Replace('-', '') }
        }
    }
    $manifestPath = Join-Path $temp 'manifest.json'
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding ASCII

    # All tests run in a copied temporary folder; fastboot.exe is the compiled mock.
    $script:installerCopy = $installerCopy
    $script:logPath = $logPath
    $script:mockExe = $mockExe
    $runner = {
        param([string[]]$a, [string]$m = 'ok', [string]$i = '')
        Run-Installer -Arguments $a -Mode $m -InputText $i
    }

    $default = Run-Installer -Arguments @('-Serial', 'MOCK', '-FastbootPath', $mockExe)
    if ($default.ExitCode -ne 0 -or @($default.Log | Where-Object { $_ -match 'flash|erase|format|boot' }).Count -ne 0) { throw 'Default check mode did not remain read-only.' }
    $wrongProduct = Run-Installer -Arguments @('-Serial', 'MOCK', '-FastbootPath', $mockExe) -Mode 'wrong-product'
    if ($wrongProduct.ExitCode -eq 0 -or @($wrongProduct.Log | Where-Object { $_ -match 'flash|erase|format|boot' }).Count -ne 0) { throw 'Wrong-product check did not fail closed.' }
    $locked = Run-Installer -Arguments @('-Serial', 'MOCK', '-FastbootPath', $mockExe) -Mode 'locked'
    if ($locked.ExitCode -eq 0 -or @($locked.Log | Where-Object { $_ -match 'flash|erase|format|boot' }).Count -ne 0) { throw 'Locked-device check did not fail closed.' }
    $userspace = Run-Installer -Arguments @('-Serial', 'MOCK', '-FastbootPath', $mockExe) -Mode 'userspace'
    if ($userspace.ExitCode -eq 0 -or @($userspace.Log | Where-Object { $_ -match 'flash|erase|format|boot' }).Count -ne 0) { throw 'fastbootd check did not fail closed.' }
    $fastbootError = Run-Installer -Arguments @('-Serial', 'MOCK', '-FastbootPath', $mockExe) -Mode 'exit-error'
    if ($fastbootError.ExitCode -eq 0 -or @($fastbootError.Log | Where-Object { $_ -match 'flash|erase|format|boot' }).Count -ne 0) { throw 'Nonzero fastboot exit did not fail closed.' }
    $badConfirm = Run-Installer -Arguments @('-Install', '-Serial', 'MOCK', '-FastbootPath', $mockExe) -InputText 'wrong'
    if ($badConfirm.ExitCode -eq 0 -or @($badConfirm.Log | Where-Object { $_ -match 'flash|erase|format|boot' }).Count -ne 0) { throw 'Bad confirmation did not fail closed.' }
    $install = Run-Installer -Arguments @('-Install', '-Serial', 'MOCK', '-FastbootPath', $mockExe) -InputText 'ERASE USERDATA MOCK'
    if ($install.ExitCode -ne 0 -or @($install.Log | Where-Object { $_ -match '^\-s\|MOCK\|(-S\|256M\|)?flash\|userdata\|' }).Count -ne 1 -or @($install.Log | Where-Object { $_ -match '^\-s\|MOCK\|boot\|' }).Count -ne 1) { throw 'Confirmed install did not issue only the expected userdata flash and temporary boot.' }

    $listOnly = Run-Installer -Arguments @('-FastbootPath', $mockExe)
    if ($listOnly.ExitCode -ne 0 -or @($listOnly.Log | Where-Object { $_ -match 'getvar|flash|erase|format|boot' }).Count -ne 0) { throw 'No-serial check mode did not stop after listing devices.' }
    Remove-Item -LiteralPath (Join-Path $temp 'rootfs.simg') -Force
    $bootOnly = Run-Installer -Arguments @('-BootOnly', '-Serial', 'MOCK', '-FastbootPath', $mockExe)
    if ($bootOnly.ExitCode -ne 0 -or @($bootOnly.Log | Where-Object { $_ -match '^\-s\|MOCK\|boot\|' }).Count -ne 1 -or @($bootOnly.Log | Where-Object { $_ -match 'flash|erase|format' }).Count -ne 0) { throw 'Boot-only did not work without the rootfs or attempted a partition write.' }
    [IO.File]::WriteAllBytes((Join-Path $temp 'boot.img'), [Text.Encoding]::ASCII.GetBytes('tampered-boot-image'))
    $badHash = Run-Installer -Arguments @('-BootOnly', '-Serial', 'MOCK', '-FastbootPath', $mockExe)
    if ($badHash.ExitCode -eq 0 -or @($badHash.Log).Count -ne 0) { throw 'Boot payload hash mismatch did not stop before fastboot.' }

    Write-Host 'Mocked-fastboot tests passed: read-only preflight, wrong product, locked, fastbootd, nonzero exit, wrong confirmation, userdata-only install, boot-only without rootfs, payload hash mismatch.'
} finally {
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
