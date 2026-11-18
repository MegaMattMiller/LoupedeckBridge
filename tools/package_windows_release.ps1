<#
Zip a Windows release folder for GitHub (milestone 7), in PowerShell 7:
  pwsh -File tools\package_windows_release.ps1 APP_DIR OUT_DIR
makes OUT_DIR\LoupedeckBridge-v<version>-windows-x64.zip (one LoupedeckBridge\ folder inside) and its .sha256
("<hex>  <name>", like shasum). The release workflow signs the zip itself (tools/sign_windows_zip.sh → .p7s).
#>
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$AppDir,
    [Parameter(Mandatory = $true, Position = 1)][string]$OutDir
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3
$AppDir = (Resolve-Path $AppDir).Path
if ((Split-Path -Leaf $AppDir) -ne 'LoupedeckBridge') { throw "expected a folder named LoupedeckBridge, not $AppDir" }
$info = Get-Content -Raw -Encoding utf8 (Join-Path $AppDir 'LoupedeckBridge.json') | ConvertFrom-Json
if ($info.runtime -ne 'bundled' -or $info.is_dev) { throw "$AppDir isn't a release build (runtime $($info.runtime), dev $($info.is_dev))" }
if (-not (Test-Path (Join-Path $AppDir 'LoupedeckBridge.exe'))) { throw "no LoupedeckBridge.exe in $AppDir" }
if ($info.version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') { throw "unreadable version '$($info.version)'" }

$name = "LoupedeckBridge-v$($info.version)-windows-x64.zip"
New-Item -ItemType Directory -Force $OutDir | Out-Null
$zip = Join-Path (Resolve-Path $OutDir).Path $name
Remove-Item -Force -ErrorAction SilentlyContinue $zip, "$zip.sha256"
# includeBaseDirectory: the entries are LoupedeckBridge/…, with forward slashes
[IO.Compression.ZipFile]::CreateFromDirectory($AppDir, $zip, [IO.Compression.CompressionLevel]::Optimal, $true)
$hash = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$zip.sha256", "$hash  $name`n", [Text.UTF8Encoding]::new($false))
Write-Output $zip
