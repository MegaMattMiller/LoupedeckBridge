<#
Check a signed Windows release the way a friend's PC will (milestone 7), in PowerShell 7 on Windows:
  pwsh -File tools\check_windows_release.ps1 -Dir DIR [-Pinned SHA256]
DIR holds LoupedeckBridge-v<ver>-windows-x64.zip, its .sha256 and its .p7s. Checks, in a temporary folder:
  1. the release's own LoupedeckBridge.exe accepts it (--check-signature, with the key that build pins)
  2. a changed byte is refused
  3. tools\install.ps1, served the release on 127.0.0.1 as GitHub would, refuses it against another key ('0' * 64),
     then installs it (with -Pinned, or install.ps1's own pin when it's left out), and the installed copy accepts it too
CI's rehearsal passes the throwaway key's -Pinned; the release workflow leaves it out, so the real pins are what's
checked. Nothing is started, and nothing outside the temporary folder (and a temporary registry key) is touched.
#>
param(
    [Parameter(Mandatory = $true)][string]$Dir,
    [string]$Pinned
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3
$repo = Split-Path -Parent $PSScriptRoot

$zips = @(Get-ChildItem -Path $Dir -Filter 'LoupedeckBridge-v*-windows-x64.zip')
if ($zips.Count -ne 1) { throw "expected one Windows release zip in $Dir, found $($zips.Count)" }
$zip = $zips[0].FullName
$tag = $zips[0].Name -replace '^LoupedeckBridge-(v[0-9]+\.[0-9]+\.[0-9]+)-windows-x64\.zip$', '$1'
foreach ($suffix in '.sha256', '.p7s') { if (-not (Test-Path "$zip$suffix")) { throw "no $($zips[0].Name)$suffix in $Dir" } }

$work = Join-Path ([IO.Path]::GetTempPath()) ("lb-check-" + [guid]::NewGuid().ToString('N'))
$key = "HKCU:\Software\LoupedeckBridgeCheck\" + [guid]::NewGuid().ToString('N')
$server = $null

# The app is a Windows (not console) program: Start-Process -Wait gives its exit code; its output goes to a file.
function Invoke-App([string]$Exe, [string[]]$Arguments) {
    $out = Join-Path $work ([guid]::NewGuid().ToString('N') + '.txt')
    $p = Start-Process -FilePath $Exe -ArgumentList $Arguments -Wait -PassThru -NoNewWindow -RedirectStandardOutput $out
    Write-Host "  $(Split-Path -Leaf $Exe) $($Arguments -join ' '): $((Get-Content -Raw $out).Trim()) (exit $($p.ExitCode))"
    return $p.ExitCode
}

function Invoke-Installer([hashtable]$Env) {
    foreach ($name in $Env.Keys) { [Environment]::SetEnvironmentVariable($name, $Env[$name]) }
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $repo 'tools\install.ps1') -Version $tag | Write-Host
    return $LASTEXITCODE
}

try {
    New-Item -ItemType Directory -Force $work | Out-Null

    Write-Host "1. the release's own check"
    $unzipped = Join-Path $work 'unzipped'
    [IO.Compression.ZipFile]::ExtractToDirectory($zip, $unzipped)
    $exe = Join-Path $unzipped 'LoupedeckBridge\LoupedeckBridge.exe'
    if ((Invoke-App $exe @('--check-signature', $zip)) -ne 0) { throw "the release's own check refused it" }

    Write-Host '2. a changed byte'
    $tampered = Join-Path $work 'tampered.zip'
    $bytes = [IO.File]::ReadAllBytes($zip)
    $bytes[[int]($bytes.Length / 2)] = $bytes[[int]($bytes.Length / 2)] -bxor 1
    [IO.File]::WriteAllBytes($tampered, $bytes)
    Copy-Item "$zip.p7s" "$tampered.p7s"
    if ((Invoke-App $exe @('--check-signature', $tampered)) -eq 0) { throw "the release's own check accepted a changed zip" }

    Write-Host '3. install.ps1, as on a friend''s PC'
    $root = Join-Path $work 'server'
    New-Item -ItemType Directory -Force (Join-Path $root "download\$tag"), (Join-Path $root 'api') | Out-Null
    Copy-Item $zip, "$zip.sha256", "$zip.p7s" (Join-Path $root "download\$tag")
    [IO.File]::WriteAllText((Join-Path $root 'api\latest'), "{`"tag_name`": `"$tag`"}")
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = $listener.LocalEndpoint.Port
    $listener.Stop()
    $python = Join-Path $unzipped 'LoupedeckBridge\python\python.exe'
    $server = Start-Process -FilePath $python -ArgumentList '-m', 'http.server', $port, '--bind', '127.0.0.1', '--directory', $root `
        -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 2
    $install = Join-Path $work 'Programs\LoupedeckBridge'
    $env = @{
        LB_RELEASES_API = "http://127.0.0.1:$port/api"; LB_DOWNLOAD_BASE = "http://127.0.0.1:$port/download"
        LB_INSTALL_DIR = $install; LB_START_MENU_DIR = (Join-Path $work 'Start Menu'); LB_RUN_KEY = "$key\Run"
        LB_UNINSTALL_KEY = "$key\Uninstall\LoupedeckBridge"; LB_INSTALL_NO_START = '1'
        LB_PINNED_SIGNER_SHA256 = ('0' * 64)
    }
    if ((Invoke-Installer $env) -eq 0) { throw 'install.ps1 accepted the release against another key' }
    if (Test-Path $install) { throw 'install.ps1 installed something anyway' }
    $env['LB_PINNED_SIGNER_SHA256'] = if ($Pinned) { $Pinned } else { $null }      # $null: install.ps1's own pin
    if ((Invoke-Installer $env) -ne 0) { throw 'install.ps1 refused the release' }
    $installed = Join-Path $install 'LoupedeckBridge.exe'
    if ((Invoke-App $installed @('--check-signature', $zip)) -ne 0) { throw 'the installed copy refused the release' }
    Write-Host "ok: $($zips[0].Name) passes the app's check and install.ps1, and a changed byte and another key are refused"
} finally {
    if ($server) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $key
    Remove-Item -Force -ErrorAction SilentlyContinue 'HKCU:\Software\LoupedeckBridgeCheck'
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $work
}
