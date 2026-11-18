<#
Build the Windows tray app (milestone 7), in PowerShell 7:
  pwsh -File tools\build_windows_app.ps1 [-Dev]          the dev build, "LoupedeckBridge Dev", in build\LoupedeckBridge Dev\:
                                                         it runs this repo's code with its .venv (editing the Python never
                                                         needs a rebuild) and never checks for updates
  pwsh -File tools\build_windows_app.ps1 -Release OUT    the release folder OUT\LoupedeckBridge\: the tray app, its own
                                                         Python 3.12 with the locked wheels, and this repo's code
                                                         (package it with tools\package_windows_release.ps1)
Needs the .NET SDK and the .NET Framework 4.8 reference assemblies (Visual Studio or the 4.8 Developer Pack); no NuGet
packages. The .NET CLI's telemetry is turned off for the build.
Downloads (the release only): the Python in tools\python-standalone-windows.lock (once, into .cache\; its SHA-256 is
checked on every build) and the wheels in tools\release-requirements-windows.txt (pip checks their hashes). The
release pins the key tools/install.sh pins (LB_SIGNER_SHA256 overrides it: CI's rehearsal).
#>
param([switch]$Dev, [string]$Release)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3
$repo = Split-Path -Parent $PSScriptRoot
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_NOLOGO = '1'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
if ($Dev -and $Release) { throw 'either -Dev or -Release OUT, not both' }

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

function Write-BuildInfo([string]$Out, [System.Collections.Specialized.OrderedDictionary]$Fields) {
    # LoupedeckBridge.json: what kind of build this is (windows/launcher/BuildInfo.cs). UTF-8 without a BOM.
    [IO.File]::WriteAllText((Join-Path $Out 'LoupedeckBridge.json'), ($Fields | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
}

if (-not $Release) {
    $out = Join-Path $repo 'build\LoupedeckBridge Dev'
    Build-Exe $out 'LoupedeckBridge Dev'
    Write-BuildInfo $out ([ordered]@{ runtime = 'repo'; repo = $repo; version = $version; is_dev = $true; signer_sha256 = '' })
    if (-not (Test-Path (Join-Path $repo '.venv\Scripts\python.exe'))) {
        Write-Warning "no .venv yet: py -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt"
    }
    Write-Output "built $out\LoupedeckBridge.exe (v$version, runs this repo's code)"
    exit 0
}

# ---- the release ------------------------------------------------------------------------------------------------
$signer = if ($null -ne $env:LB_SIGNER_SHA256) { $env:LB_SIGNER_SHA256 } else {
    $pin = Select-String -Path (Join-Path $repo 'tools\install.sh') -Pattern '^PINNED_SIGNER_SHA256_DEFAULT="(.*)"$'
    $pin.Matches[0].Groups[1].Value
}
$lock = @{}
foreach ($line in Get-Content -Encoding utf8 (Join-Path $repo 'tools\python-standalone-windows.lock')) {
    if ($line -and -not $line.StartsWith('#')) { $k, $v = $line -split '=', 2; $lock[$k] = $v }
}
if (-not $lock['url'] -or -not $lock['sha256']) { throw "couldn't read tools\python-standalone-windows.lock" }

# The Python: downloaded once, checked every time
$cache = Join-Path $repo '.cache'
$tarball = Join-Path $cache ([Uri]::UnescapeDataString(($lock['url'] -split '/')[-1]))
if (-not (Test-Path $tarball)) {
    New-Item -ItemType Directory -Force $cache | Out-Null
    Write-Output "downloading $(Split-Path -Leaf $tarball)"
    Invoke-WebRequest -Uri $lock['url'] -OutFile "$tarball.part" -MaximumRetryCount 3
    Move-Item -Force "$tarball.part" $tarball
}
if ((Get-FileHash -Algorithm SHA256 $tarball).Hash.ToLowerInvariant() -ne $lock['sha256']) {
    Remove-Item -Force $tarball
    throw "The Python download didn't match tools\python-standalone-windows.lock's SHA-256, so it was deleted."
}

New-Item -ItemType Directory -Force $Release | Out-Null
$app = Join-Path (Resolve-Path $Release).Path 'LoupedeckBridge'
Build-Exe $app 'LoupedeckBridge'
# Windows' own tar (bsdtar): Git's GNU tar, first on PATH in Git Bash, would read "C:\…" as a remote host
& (Join-Path $env:SystemRoot 'System32\tar.exe') -xzf $tarball -C $app      # → LoupedeckBridge\python
if ($LASTEXITCODE -ne 0) { throw "couldn't unpack $tarball" }
$py = Join-Path $app 'python\python.exe'
$lib = Join-Path $app 'python\Lib'

# Its packages: exactly the locked wheels
$env:PYTHONDONTWRITEBYTECODE = '1'
& $py -E -m pip install --quiet --no-cache-dir --disable-pip-version-check --no-warn-script-location `
    --only-binary=:all: --no-deps `
    --require-hashes -r (Join-Path $repo 'tools\release-requirements-windows.txt')
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
Remove-Item Env:PYTHONDONTWRITEBYTECODE

# The code
$code = Join-Path $app 'app'
New-Item -ItemType Directory -Force (Join-Path $code 'docs') | Out-Null
Copy-Item -Recurse (Join-Path $repo 'bridge'), (Join-Path $repo 'config') $code
Copy-Item (Join-Path $repo 'docs\lr_parameters_10.0.json') (Join-Path $code 'docs')
Copy-Item (Join-Path $repo 'tools\install.ps1') $app        # Settings → Apps → Uninstall runs it (install.ps1 -Uninstall)

# Strip what the app never uses, then precompile everything
# (pip stays: CI runs the test suite with this Python, through a venv that shares its packages)
foreach ($rel in 'Lib\test', 'Lib\idlelib', 'Lib\tkinter', 'Lib\turtledemo', 'Lib\ensurepip', 'tcl', 'include', 'libs',
                 'DLLs\_tkinter.pyd', 'DLLs\tcl86t.dll', 'DLLs\tk86t.dll') {
    $path = Join-Path $app "python\$rel"
    if (Test-Path $path) { Remove-Item -Recurse -Force $path }
}
Get-ChildItem -Path $app -Recurse -Directory -Force | Where-Object { $_.Name -in '__pycache__', 'test', 'tests' } |
    Sort-Object { $_.FullName.Length } -Descending | Remove-Item -Recurse -Force
Get-ChildItem -Path $app -Recurse -File -Force -Include '*.pyc', '*.pdb' | Remove-Item -Force   # .pdb: debug symbols
# unchecked-hash: Python uses the .pyc without comparing it to the source, and with -B (as the app runs it) never
# writes one
& $py -E -m compileall -q -j 0 --invalidation-mode unchecked-hash $lib $code | Out-Null
if ($LASTEXITCODE -ne 0) { throw "compileall failed" }

Write-BuildInfo $app ([ordered]@{ runtime = 'bundled'; version = $version; is_dev = $false; signer_sha256 = $signer })
$size = '{0:N0} MB' -f ((Get-ChildItem -Recurse -File $app | Measure-Object -Sum Length).Sum / 1MB)
Write-Output "built $app (v$version, $size)"
