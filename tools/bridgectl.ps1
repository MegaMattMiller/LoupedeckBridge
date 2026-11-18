<#
Control LoupedeckBridge on Windows (milestone 7), the twin of tools/bridgectl. In PowerShell 7:
  pwsh -File tools\bridgectl.ps1 start|stop|restart|status [-Dev]   the installed release, or with -Dev the dev build
  pwsh -File tools\bridgectl.ps1 login on|off|status [-Dev]         Start at login (as the menu's checkmark)
  pwsh -File tools\bridgectl.ps1 build                              build the dev app ("LoupedeckBridge Dev")
  pwsh -File tools\bridgectl.ps1 install [-Version vX.Y.Z] [-AllowOlder]   install a release (tools\install.ps1)
  pwsh -File tools\bridgectl.ps1 logs | settings
Only one bridge runs at a time: `start -Dev` pauses the installed release, `stop -Dev` brings it back.
#>
param(
    [Parameter(Position = 0)][string]$Command,
    [switch]$Dev,
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Rest
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3
$repo = Split-Path -Parent $PSScriptRoot
$releaseExe = if ($env:LB_BRIDGECTL_RELEASE_APP) { $env:LB_BRIDGECTL_RELEASE_APP }
              else { Join-Path $env:LOCALAPPDATA 'Programs\LoupedeckBridge\LoupedeckBridge.exe' }
$devExe = if ($env:LB_BRIDGECTL_DEV_APP) { $env:LB_BRIDGECTL_DEV_APP }
          else { Join-Path $repo 'build\LoupedeckBridge Dev\LoupedeckBridge.exe' }
$state = Join-Path $env:LOCALAPPDATA 'loupedeck-lr-bridge'
$paused = Join-Path $state 'release-paused'          # set by `start -Dev` while it has paused the release
$log = Join-Path $state 'logs\bridge.log'
$exe = if ($Dev) { $devExe } else { $releaseExe }

function Show-Usage {
    Write-Output 'usage: pwsh -File tools\bridgectl.ps1 {start|stop|restart|status|login on|off|status} [-Dev]'
    Write-Output '       pwsh -File tools\bridgectl.ps1 {build|install [-Version vX.Y.Z] [-AllowOlder]|logs|settings}'
    exit 2
}

# Matched by full path, so the release and the dev build are never confused.
function Test-Running([string]$Path) {
    [bool](Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and ($_.Path -ieq $Path) })
}

# The tray app is a Windows (not console) program: Start-Process -Wait is how to wait for it and get its exit code.
function Invoke-App([string]$Path, [string[]]$Arguments) {
    $out = New-TemporaryFile
    try {
        $p = Start-Process -FilePath $Path -ArgumentList $Arguments -Wait -PassThru -NoNewWindow -RedirectStandardOutput $out
        [pscustomobject]@{ Code = $p.ExitCode; Output = (Get-Content -Raw $out) }
    } finally { Remove-Item $out -ErrorAction SilentlyContinue }
}

# Messages go to the host (Write-Host): a function's output is its return value.
function Start-App([string]$Path) {
    if (-not (Test-Path $Path)) {
        Write-Host "Not found: $Path (dev: bridgectl.ps1 build; release: bridgectl.ps1 install)"
        return 1
    }
    if (Test-Running $Path) { Write-Host 'already running'; return 0 }
    Start-Process -FilePath $Path | Out-Null
    Start-Sleep -Milliseconds 1500
    if (Test-Running $Path) {
        Write-Host "started $Path. Logs: bridgectl.ps1 logs"
        return 0
    }
    Write-Host "$Path didn't stay running. Last log lines:"
    if (Test-Path $log) { Get-Content $log -Tail 8 | Write-Host }
    return 1
}

function Stop-App([string]$Path) {
    # --quit: the app stops the bridge (it lets go of any held keys; forced after 5 s) and quits.
    if (-not (Test-Running $Path)) { Write-Host 'not running'; return 0 }
    $result = Invoke-App $Path @('--quit')
    if ($result.Code -eq 0 -and -not (Test-Running $Path)) { Write-Host 'stopped'; return 0 }
    Write-Host 'still running after 10 s'
    return 1
}

$code = 0
switch ($Command) {
    'build' { & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'build_windows_app.ps1') -Dev; $code = $LASTEXITCODE }
    'start' {
        if ($Dev -and (Test-Running $releaseExe)) {
            $null = Stop-App $releaseExe
            New-Item -ItemType Directory -Force $state | Out-Null
            New-Item -ItemType File -Force $paused | Out-Null
            Write-Output 'paused the installed LoupedeckBridge (bridgectl.ps1 stop -Dev brings it back)'
        } elseif (-not $Dev -and (Test-Running $devExe)) {
            Write-Output 'The dev build is running; stop it first: bridgectl.ps1 stop -Dev'
            exit 1
        }
        $code = Start-App $exe
    }
    'stop' {
        $code = Stop-App $exe
        if ($Dev -and (Test-Path $paused)) {
            Remove-Item $paused
            $code = Start-App $releaseExe
        }
    }
    'restart' { $code = Stop-App $exe; if ($code -eq 0) { $code = Start-App $exe } }
    'status' { if (Test-Running $exe) { Write-Output 'running' } else { Write-Output 'not running' } }
    'login' {
        if (-not (Test-Path $exe)) { Write-Output "Not found: $exe"; exit 1 }
        $what = if ($Rest) { $Rest[0] } else { 'status' }
        $result = Invoke-App $exe @('--login', $what)
        Write-Output "$($result.Output)".Trim()
        $code = $result.Code
    }
    'install' {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'install.ps1') @Rest
        $code = $LASTEXITCODE
    }
    'logs' { Get-Content $log -Tail 30 -Wait }
    'settings' { Start-Process 'http://127.0.0.1:7690/' }
    default { Show-Usage }
}
exit $code
