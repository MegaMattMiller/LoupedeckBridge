<#
Build the Windows tray app (milestone 7), in PowerShell 7:
  pwsh -File tools\build_windows_app.ps1 [-Dev]          the dev build, "LoupedeckBridge Dev", in build\LoupedeckBridge Dev\:
                                                         it runs this repo's code with its .venv (editing the Python never
                                                         needs a rebuild) and never checks for updates
Needs the .NET SDK and the .NET Framework 4.8 reference assemblies (Visual Studio or the 4.8 Developer Pack); no NuGet
packages. The .NET CLI's telemetry is turned off for the build.
#>
param([switch]$Dev)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3
$repo = Split-Path -Parent $PSScriptRoot
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_NOLOGO = '1'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'

$match = Select-String -Path (Join-Path $repo 'bridge\__init__.py') -Pattern '^__version__ = "(.*)"$'
if (-not $match) { throw "couldn't read the version from bridge\__init__.py" }
$version = $match.Matches[0].Groups[1].Value

function Build-Exe([string]$Out, [string]$Title) {
    if (Test-Path $Out) {
        try { Remove-Item -Recurse -Force $Out }
        catch { throw "couldn't replace $Out (is it running? pwsh -File tools\bridgectl.ps1 stop -Dev): $_" }
    }
    dotnet build (Join-Path $repo 'windows\launcher\LoupedeckBridge.csproj') -c Release -nologo -v q `
        "-p:Version=$version" "-p:AssemblyTitle=$Title" -o $Out
    if ($LASTEXITCODE -ne 0) { throw "dotnet build failed" }
}

function Write-BuildInfo([string]$Out, [hashtable]$Fields) {
    # LoupedeckBridge.json: what kind of build this is (windows/launcher/BuildInfo.cs). UTF-8 without a BOM.
    $json = [ordered]@{} + $Fields | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $Out 'LoupedeckBridge.json'), $json, [Text.UTF8Encoding]::new($false))
}

$out = Join-Path $repo 'build\LoupedeckBridge Dev'
Build-Exe $out 'LoupedeckBridge Dev'
Write-BuildInfo $out ([ordered]@{ runtime = 'repo'; repo = $repo; version = $version; is_dev = $true; signer_sha256 = '' })
if (-not (Test-Path (Join-Path $repo '.venv\Scripts\python.exe'))) {
    Write-Warning "no .venv yet: py -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt"
}
Write-Output "built $out\LoupedeckBridge.exe (v$version, runs this repo's code)"
