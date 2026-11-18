<#
Install or update LoupedeckBridge on Windows from its GitHub releases (milestone 7): no admin rights, no GitHub account.

On a PC without this repo, in PowerShell:
  irm https://raw.githubusercontent.com/MegaMattMiller/LoupedeckBridge/main/tools/install.ps1 -OutFile install.ps1
  powershell -ExecutionPolicy Bypass -File install.ps1
(The second line relaxes PowerShell's script policy for that one run only. Read install.ps1 first if you like.)

  install.ps1 [-Version latest|vX.Y.Z] [-AllowOlder]    install, or update to that version
  install.ps1 -Uninstall                                remove it (Settings → Apps runs this too); your settings stay

It downloads the release with Invoke-WebRequest (so Windows adds no "downloaded from the internet" mark, and there's no
SmartScreen step), checks its SHA-256, checks that its signature (the .p7s) was made with the LoupedeckBridge release
key (the certificate's SHA-256 is pinned below), and checks what's inside. Only then does it stop a running
LoupedeckBridge, keep the old version as LoupedeckBridge.previous, put the new one in place and start it. If any check
fails, nothing is changed. It prints the release key's fingerprint first: on a new PC, compare it with the one in the
README (or one you noted elsewhere).

It installs to %LOCALAPPDATA%\Programs\LoupedeckBridge, adds a Start menu entry and an entry in Settings → Apps.
Exit codes: 0 done, 1 refused or failed (nothing replaced), 2 usage. Runs on Windows PowerShell 5.1.
#>
param(
    [string]$Version = 'latest',
    [switch]$AllowOlder,
    [switch]$Uninstall
)

Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'          # Windows PowerShell's progress bar slows downloads to a crawl

if ($PSVersionTable.PSVersion.Major -ge 6) {
    Write-Host 'install.ps1: run it with Windows PowerShell: powershell -ExecutionPolicy Bypass -File install.ps1'
    exit 2
}
# Started from a PowerShell 7 window, Windows PowerShell can inherit 7's module folders and fail to load its own
# commands (Get-FileHash, ConvertFrom-Json): use Windows PowerShell's own.
$env:PSModulePath = @((Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'WindowsPowerShell\Modules'),
                      (Join-Path $env:ProgramFiles 'WindowsPowerShell\Modules'), (Join-Path $PSHOME 'Modules')) -join ';'

# The LoupedeckBridge release certificate's SHA-256 (public, not a secret): the same key as the Mac's (tools/install.sh).
$PinnedSignerSha256Default = "4927ccbb8cc8c7e3c32afa79d58f11f2129b84b3c7638cb530cb2ced0faa2cf4"

function Setting([string]$Name, [string]$Default) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ($null -ne $value) { return $value } else { return $Default }
}
$Pinned = Setting 'LB_PINNED_SIGNER_SHA256' $PinnedSignerSha256Default
$Slug = 'MegaMattMiller/LoupedeckBridge'
$Api = Setting 'LB_RELEASES_API' "https://api.github.com/repos/$Slug/releases"
$Downloads = Setting 'LB_DOWNLOAD_BASE' "https://github.com/$Slug/releases/download"
$InstallDir = Setting 'LB_INSTALL_DIR' (Join-Path $env:LOCALAPPDATA 'Programs\LoupedeckBridge')
$StartMenuDir = Setting 'LB_START_MENU_DIR' (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs')
$RunKey = Setting 'LB_RUN_KEY' 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$UninstallKey = Setting 'LB_UNINSTALL_KEY' 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\LoupedeckBridge'
$MaxBytes = [long](Setting 'LB_MAX_DOWNLOAD_BYTES' '209715200')   # 200 MB: a release is about 30 MB
$Exe = Join-Path $InstallDir 'LoupedeckBridge.exe'
$Previous = "$InstallDir.previous"
$New = "$InstallDir.new"
$Older = "$InstallDir.older"                       # the older .previous, kept until the new version is in place
$UserAgent = 'LoupedeckBridge-installer'

function Say([string]$Message) { Write-Host "install.ps1: $Message" }
function Fail([string]$Message) { Write-Host "install.ps1: $Message; nothing was changed."; exit 1 }

[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.Security
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

# ---- the running app ----------------------------------------------------------------------------------------------
# Asks a running LoupedeckBridge to quit as from its menu (it lets go of held keys and stops its bridge). The app is a
# Windows program, not a console one: Start-Process -Wait is how to wait for it and get its exit code.
function Stop-LoupedeckBridge {
    if (-not (Test-Path $Exe)) { return $true }
    $quit = Start-Process -FilePath $Exe -ArgumentList '--quit' -Wait -PassThru -WindowStyle Hidden
    return $quit.ExitCode -eq 0
}

# `--quit` returns once the app has let go of its single-instance lock, a moment before its process (and its bridge's
# Python) have exited: wait for every process running from the install folder.
function Wait-InstalledProcesses {
    $prefix = $InstallDir.TrimEnd('\') + '\'
    $ids = @(Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) } |
        ForEach-Object { $_.ProcessId })
    if ($ids.Count) { Wait-Process -Id $ids -Timeout 15 -ErrorAction SilentlyContinue }
}

# Renames a folder in one step, trying for a few seconds (a program that has just exited, or an antivirus scanner, can
# hold it for a moment). [IO.Directory]::Move, not Move-Item: when the rename fails, Move-Item moves what it can file by
# file, and leaves the app split between two folders.
function Move-Folder([string]$From, [string]$To) {
    for ($attempt = 1; ; $attempt++) {
        try { [IO.Directory]::Move($From, $To); return }
        catch {
            if ($attempt -ge 10) {
                $e = $_.Exception
                if ($e.InnerException) { $e = $e.InnerException }
                throw $e
            }
            Start-Sleep -Milliseconds 300
        }
    }
}

function Start-LoupedeckBridge {
    if ($env:LB_INSTALL_NO_START -eq '1') { return }
    if (Test-Path $Exe) { Start-Process -FilePath $Exe | Out-Null }
}

# ---- uninstall ------------------------------------------------------------------------------------------------------
if ($Uninstall) {
    Set-Location $env:TEMP                     # not inside the folder about to be removed
    if (-not (Stop-LoupedeckBridge)) { Fail "LoupedeckBridge won't quit (quit it from its tray icon, then try again)" }
    Wait-InstalledProcesses
    Remove-ItemProperty -Path $RunKey -Name 'LoupedeckBridge' -ErrorAction SilentlyContinue
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $StartMenuDir 'LoupedeckBridge.lnk')
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $UninstallKey
    foreach ($dir in $InstallDir, $Previous, $New, $Older) {
        if (Test-Path $dir) {
            try { Remove-Item -Recurse -Force $dir }
            catch { Start-Sleep -Seconds 2; Remove-Item -Recurse -Force $dir }
        }
    }
    Say "LoupedeckBridge was removed."
    Say "Your layout, presets and Lightroom client ID are kept in $env:APPDATA\loupedeck-lr-bridge and $env:LOCALAPPDATA\loupedeck-lr-bridge (with the logs); delete those folders to remove them too."
    exit 0
}

# ---- checks -----------------------------------------------------------------------------------------------------------
# The same rules as windows/launcher/Signature.cs: one signer, a signature that verifies over these exact bytes, and a
# signer certificate whose SHA-256 is the pinned one (self-signed, so there's no chain to check).
function Get-SignatureProblem([byte[]]$Content, [byte[]]$P7s) {
    if ($Pinned -notmatch '^[0-9A-Fa-f]{64}$') { return 'no release key is pinned in this script' }
    $info = New-Object System.Security.Cryptography.Pkcs.ContentInfo -ArgumentList (, $Content)
    $cms = New-Object System.Security.Cryptography.Pkcs.SignedCms -ArgumentList $info, $true
    try { $cms.Decode($P7s) } catch { return 'the signature is unreadable' }
    if ($cms.SignerInfos.Count -ne 1) { return 'the signature should have exactly one signer' }
    $signer = $cms.SignerInfos[0]
    if ($null -eq $signer.Certificate) { return 'the signature is unreadable' }
    try { $signer.CheckSignature($true) } catch { return "the signature doesn't match the download" }
    $sha = [Security.Cryptography.SHA256]::Create()
    $leaf = -join ($sha.ComputeHash($signer.Certificate.RawData) | ForEach-Object { $_.ToString('x2') })
    if ($leaf -ne $Pinned.ToLowerInvariant()) { return "it's signed with another key" }
    return $null
}

# The same rules as windows/launcher/Policies.cs Updates.ZipLayoutProblem: nothing may land outside LoupedeckBridge\.
function Get-LayoutProblem([string[]]$Names) {
    $names = @($Names | ForEach-Object { $_.Replace('\', '/') })
    if ($names.Count -eq 0) { return 'the download is empty' }
    foreach ($name in $names) {
        if ($name.StartsWith('/') -or $name.Contains(':') -or (@($name.Split('/')) -contains '..')) {
            return "it holds an unsafe path ($name)"
        }
        if (-not $name.StartsWith('LoupedeckBridge/')) { return "it should hold only a LoupedeckBridge folder (it holds $name)" }
    }
    if ($names -notcontains 'LoupedeckBridge/LoupedeckBridge.exe') { return 'it has no LoupedeckBridge.exe' }
    if ($names -notcontains 'LoupedeckBridge/LoupedeckBridge.json') { return 'it has no LoupedeckBridge.json' }
    return $null
}

# Downloads to a file, refusing more than $MaxBytes (streamed, so a huge answer can't fill the disk).
function Save-Download([string]$Url, [string]$Path) {
    $request = [Net.WebRequest]::Create($Url)
    $request.UserAgent = $UserAgent
    $response = $request.GetResponse()
    try {
        $in = $response.GetResponseStream()
        $out = [IO.File]::Create($Path)
        try {
            $buffer = New-Object byte[] 81920
            $total = 0L
            while (($read = $in.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $total += $read
                if ($total -gt $MaxBytes) { throw "it's bigger than $([math]::Floor($MaxBytes / 1MB)) MB, so it isn't a release" }
                $out.Write($buffer, 0, $read)
            }
        } finally { $out.Dispose(); $in.Dispose() }
    } finally { $response.Dispose() }
}

function Read-InstalledVersion {
    $json = Join-Path $InstallDir 'LoupedeckBridge.json'
    if (-not (Test-Path $json)) { return $null }
    try { return [version]((Get-Content -Raw -Encoding UTF8 $json | ConvertFrom-Json).version) } catch { return $null }
}

# ---- install ------------------------------------------------------------------------------------------------------------
if ($null -ne [Environment]::GetEnvironmentVariable('LB_PINNED_SIGNER_SHA256')) {
    Say "the key to accept (set by LB_PINNED_SIGNER_SHA256, not the release key): $Pinned"
} else {
    Say "the LoupedeckBridge release key's fingerprint (SHA-256): $Pinned"
}
if ($Pinned -notmatch '^[0-9A-Fa-f]{64}$') { Fail 'no release key is pinned in this script' }

if ($Version -eq 'latest') {
    try {
        $tag = (Invoke-RestMethod -Uri "$Api/latest" -UserAgent $UserAgent -Headers @{ Accept = 'application/vnd.github+json' }).tag_name
    } catch { Fail "couldn't ask GitHub for the newest release ($($_.Exception.Message))" }
} else {
    $tag = 'v' + ($Version -replace '^v', '')
}
if ($tag -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+$') { Fail "'$tag' isn't a version like v0.6.0" }
$wanted = $tag.Substring(1)
$name = "LoupedeckBridge-v$wanted-windows-x64.zip"
$work = Join-Path ([IO.Path]::GetTempPath()) ("LoupedeckBridge-install-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $work | Out-Null
try {
    $zip = Join-Path $work $name
    Say "downloading $name"
    try {
        foreach ($suffix in '', '.sha256', '.p7s') { Save-Download "$Downloads/$tag/$name$suffix" "$zip$suffix" }
    } catch { Fail "couldn't download $name$suffix ($($_.Exception.Message))" }

    $expected = ((Get-Content -Raw -Encoding UTF8 "$zip.sha256").Trim() -split '\s+')[0].ToLowerInvariant()
    if ((Get-FileHash -Algorithm SHA256 $zip).Hash.ToLowerInvariant() -ne $expected) {
        Fail "the download is damaged (its SHA-256 doesn't match)"
    }
    $problem = Get-SignatureProblem ([IO.File]::ReadAllBytes($zip)) ([IO.File]::ReadAllBytes("$zip.p7s"))
    if ($problem) { Fail "it isn't signed with your LoupedeckBridge release key: $problem" }
    try {
        $archive = [IO.Compression.ZipFile]::OpenRead($zip)
        try { $entries = @($archive.Entries | ForEach-Object { $_.FullName }) } finally { $archive.Dispose() }
    } catch { Fail "it isn't a valid zip ($($_.Exception.Message))" }
    $problem = Get-LayoutProblem $entries
    if ($problem) { Fail $problem }

    $unzipped = Join-Path $work 'unzipped'
    try { [IO.Compression.ZipFile]::ExtractToDirectory($zip, $unzipped) }
    catch { Fail "couldn't unzip it ($($_.Exception.Message))" }
    try { $info = Get-Content -Raw -Encoding UTF8 (Join-Path $unzipped 'LoupedeckBridge\LoupedeckBridge.json') | ConvertFrom-Json }
    catch { Fail "its LoupedeckBridge.json is unreadable" }
    if ($info.runtime -ne 'bundled' -or $info.is_dev) { Fail "it isn't a LoupedeckBridge release" }
    if ($info.version -ne $wanted) { Fail "it holds v$($info.version), not v$wanted" }
    $installed = Read-InstalledVersion
    if ($installed -and [version]$wanted -le $installed -and -not $AllowOlder) {
        Fail "v$wanted isn't newer than the installed v$installed (-AllowOlder installs it anyway)"
    }

    # ---- the swap: everything is checked; now stop the running app and put the new version in place. The older
    # .previous waits as .older until the new version is in place, so a failed swap leaves both versions as they were.
    New-Item -ItemType Directory -Force (Split-Path -Parent $InstallDir) | Out-Null
    if (Test-Path $New) { Remove-Item -Recurse -Force $New }
    Move-Item (Join-Path $unzipped 'LoupedeckBridge') $New
    if (-not (Stop-LoupedeckBridge)) { Remove-Item -Recurse -Force $New; Fail "LoupedeckBridge won't quit (quit it from its tray icon, then try again)" }
    Wait-InstalledProcesses
    $hadOld = Test-Path $InstallDir
    $hadPrevious = $hadOld -and (Test-Path $Previous)
    if ($hadOld) {
        try {
            if (Test-Path $Older) { Remove-Item -Recurse -Force $Older }            # left by an install cut short
            if ($hadPrevious) { Move-Folder $Previous $Older }
            Move-Folder $InstallDir $Previous
        } catch {
            $why = $_.Exception.Message
            if ($hadPrevious -and (Test-Path $Older) -and -not (Test-Path $Previous)) {
                try { Move-Folder $Older $Previous } catch { }
            }
            Remove-Item -Recurse -Force $New; Start-LoupedeckBridge; Fail "couldn't move the old version aside ($why)"
        }
    }
    # For the tests only: hold one file of the new version open, so the step below fails (a stand-in for an antivirus
    # scanner or another program holding it), and the old version must be put back.
    $held = $null
    if ($env:LB_INSTALL_HOLD_FILE) { $held = [IO.File]::Open((Join-Path $New $env:LB_INSTALL_HOLD_FILE), 'Open', 'Read', 'Read') }
    try {
        Move-Folder $New $InstallDir
    } catch {
        $why = $_.Exception.Message
        if ($held) { $held.Dispose() }
        try {
            if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
            if ($hadOld) { Move-Folder $Previous $InstallDir }
            if ($hadPrevious) { Move-Folder $Older $Previous }
        } catch {
            Say "couldn't put the new version in place ($why), nor the previous one back ($($_.Exception.Message)): it is in $Previous"
            exit 1
        }
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $New
        Start-LoupedeckBridge
        Say "couldn't put the new version in place ($why); the previous version was put back and started again"
        exit 1
    }
    if ($held) { $held.Dispose() }
    if ($hadPrevious) { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Older }

    # ---- the Start menu entry and Settings → Apps
    New-Item -ItemType Directory -Force $StartMenuDir | Out-Null
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $StartMenuDir 'LoupedeckBridge.lnk'))
    $shortcut.TargetPath = $Exe
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.Description = 'LoupedeckBridge: the Loupedeck+ for Adobe Lightroom'
    $shortcut.Save()
    New-Item -Force -Path $UninstallKey | Out-Null
    $size = [int]((Get-ChildItem -Recurse -File $InstallDir | Measure-Object -Sum Length).Sum / 1KB)
    $values = @{
        DisplayName = 'LoupedeckBridge'; DisplayVersion = $wanted; Publisher = 'LoupedeckBridge'; InstallLocation = $InstallDir
        DisplayIcon = $Exe; URLInfoAbout = "https://github.com/$Slug"
        UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $InstallDir 'install.ps1')`" -Uninstall"
    }
    foreach ($key in $values.Keys) { New-ItemProperty -Force -Path $UninstallKey -Name $key -Value $values[$key] -PropertyType String | Out-Null }
    foreach ($key in 'NoModify', 'NoRepair') { New-ItemProperty -Force -Path $UninstallKey -Name $key -Value 1 -PropertyType DWord | Out-Null }
    New-ItemProperty -Force -Path $UninstallKey -Name 'EstimatedSize' -Value $size -PropertyType DWord | Out-Null

    Start-LoupedeckBridge
    Say "installed LoupedeckBridge v$wanted in $InstallDir"
    if ($hadOld) { Say "the version it replaced is kept in $Previous" }
} finally {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $work
}
