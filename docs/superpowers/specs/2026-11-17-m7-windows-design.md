# Milestone 7: Windows, with a tray app and releases for friends (design)

Date: 2026-11-17 · Status: draft for approval · Part of: [the bridge design](2026-11-16-loupedeck-bridge-design.md),
after [milestone 6](2026-11-17-m6-mac-releases-design.md)

## Intent
Use the Loupedeck+ with Lightroom (the cloud-based desktop app) on the user's Windows PC, and let **some friends**
install it on theirs. Windows gets **everything the Mac has**, including **a tray app just like the Mac's menu-bar
app** (the user's decision): status at a glance, alerts, restarts, Start at login, and updates from the menu that
only install builds signed with the user's own release key. Friends install it with one PowerShell command and no
admin rights.

The roadmap had planned to write the Windows code on the Mac first and test it on Windows afterwards. This milestone
is built **on the Windows PC itself**, where the device and Lightroom are both available for live checks.

## Found on the user's PC (2026-11-17)
- **Loupedeck+:** USB `VID_2EC2&PID_0002`, a MIDI device named **`Loupedeck+`** plus a serial port (COM11), the same
  two interfaces as on the Mac. No Loupedeck or Logi software is running.
- **Lightroom 10.0**, build `20261029-1525-df1be3b` (the same as the Mac), at `C:\Program Files\Adobe\Adobe Lightroom
  CC\lightroom.exe`. `%LOCALAPPDATA%\Adobe\Lightroom CC\Connections\connections.json` = `{"port":7682}`. It listens on
  **127.0.0.1:7682 only** (on the Mac it listened on all interfaces).
- Windows 11 (10.0.26200), x64. .NET Framework 4.8.1. Visual Studio 2022 Community (MSBuild, the 4.8 reference
  assemblies). .NET SDK 8 and 9. Windows PowerShell 5.1 and PowerShell 7.6. Python 3.11.9 (system-wide). Git for
  Windows (bash, openssl) and `gh`.
- **The shared Python mostly runs on Windows already:** `bridge/platform/windows.py` has the paths, and
  `bridge/instance.py`'s lock uses `msvcrt`. Missing:
  - keyboard keys (`keyboard()` returns `None`)
  - a clean stop (Windows has no SIGTERM)
  - the "launcher has gone" watch (`parent_gone`): on Windows a process's parent id doesn't change when the parent
    exits, so it would never fire

## What the user gets (agreed in conversation)
- **The same as the Mac:**
  - dials, dial clicks, buttons, presets, the Fn layer, the --/Col modes and the settings page
  - the tray icon: sliders when all is well, a warning sign otherwise, and the problem in its tooltip
  - the alerts ("Loupedeck disconnected", "Loupedeck is back", "LoupedeckBridge stopped", "LoupedeckBridge v… is
    available"), with the Mac's rules (3 s grace, none for a quick replug, at most one a minute, 15 s quiet after
    the PC wakes)
  - restarts after a crash (after 5 s, at most 3 in 10 minutes), then **Restart bridge** and **Open log**
  - Start at login, off until ticked
  - updates: a daily check, **Check for updates now**, an off switch, **Install…**, and **Go back to the previous
    version** when a new version's bridge keeps failing
- **The tray menu:**
  ```
   LoupedeckBridge v0.6.0
   ─────────────────────────
   ● Loupedeck: connected
   ● Lightroom: connected
     Five buttons: Ratings
   ─────────────────────────
   Open settings…
   ✓ Start at login
   ─────────────────────────
   Update available: v0.6.1 – Install…
   Check for updates now
   ✓ Check for updates automatically
   ─────────────────────────
   Quit LoupedeckBridge
  ```
  There's no "Keyboard keys" line: Windows needs no permission to send keys.
- **Install:** friends paste one PowerShell command, the twin of `install.sh`. It prints the release key's
  fingerprint, checks the download, and needs no admin rights. It installs to the user's own folder and adds a Start
  menu entry. *(Per-user folder and Start menu: my calls, accepted by the user.)*
- **Updates are checked against the existing release key** (the Mac's), so there's no new secret. *(My call,
  accepted.)*
- **Cmd sends Ctrl on Windows** (the user's decision). Lightroom on Windows uses Ctrl where the Mac uses Cmd, so Mac
  habits carry over: Cmd-click adds to a selection, Cmd+Z undoes. This replaces the original design's "Cmd = Windows
  key", whose release alone would open the Start menu.
- **Windows 10 and 11, on x64 PCs.** *(My call, accepted.)*
- **One release carries both downloads**, the Mac zip and the Windows zip, under one version. The first one with
  Windows is **v0.6.0**. *(My call, accepted.)* The Mac apps' update check reads GitHub's latest release, so that
  release must always include the Mac zip.
- **The README** tells friends how to bring the tray icon out from behind the ^ arrow, where Windows hides new icons.
- **Unchanged:** a dev build kept apart from the release; the bridge connects and serves on 127.0.0.1 only; only the
  tray app talks to the internet, and only to GitHub.

## Approaches (the user picked A)
- **A. A C# tray app on .NET Framework 4.8, the version built into Windows (chosen).**
  - Every Windows 10/11 PC already has it, so friends install no runtime. The program is about 100 KB.
  - The same split as the Mac: a small native program that starts and watches the bundled Python. The Swift app's
    rules (alerts, restarts, update timing, versions) port almost line for line.
  - Windows' own code gives it the tray icon and menu, notifications, and the signature check (`SignedCms`).
  - Against: a third language in the repo. CI tests it as it tests the Swift.
- B. Python with ctypes calls into Win32. Rejected:
  - the tray icon, menu and message loop are a lot of fragile hand-written plumbing
  - Python's standard library can't check a signature, so the update check would call into Windows anyway
- C. A PowerShell script with a tray icon. Rejected: slow to start, and a hidden PowerShell started at login is a
  pattern antivirus programs flag.
- Also rejected:
  - tray libraries for Python (pystray needs Pillow): new runtime dependencies
  - .NET 8+: friends would need a runtime install, or the app grows by about 70 MB

## Decided (how it's built)

### The bridge on Windows (Python)
- **Keyboard keys:** `bridge/platform/windows_keys.py`, using `SendInput` through ctypes, with no new packages. Same
  interface as `MacKeyboard`: `key_down`, `key_up`, `key_repeat`, `tap`, `is_trusted` (always true), `close`.
  - Virtual-key codes for every name in `macos_keys.KEYCODES`. Arrows and the other extended keys get the
    extended-key flag.
  - `cmd` sends **Ctrl** (the user's decision). Ctrl and Cmd can be held together, so Ctrl stays down until both are
    released. *(My call.)*
  - A held modifier is expected to combine with the real mouse and keyboard with no help, because Windows keeps one
    key state for all input. So there's no equivalent of the Mac's modifier tap, unless the check below says
    otherwise.
- **Shortcuts:** the `windows` lists already in `config/default_mapping.json` (`\` for Before/After, `f` for screen
  mode). They're checked against Lightroom on Windows.
- **A clean stop without signals:**
  - The tray app asks the bridge to stop through a pipe. The bridge then does what SIGTERM does on the Mac: it lets
    go of held keys, closes its ports and exits.
  - If the bridge is still running after 5 s, the tray app ends it, then sends key-ups for every key the bridge can
    hold, as the Mac app does.
- **Status lines:** the same JSON lines (`bridge/status.py`), through a pipe from the tray app.
- **When the tray app is gone:** on Windows, `parent_gone` watches the parent process itself (for example by holding
  a handle to it from the start). A tray app that's killed must never leave a bridge running, or a key held.
  - Not a job object that kills the bridge with its parent: that would kill the bridge before it lets go of its keys.
    *(My call.)*
- **A Loupedeck in use by another program:** on Windows only one program at a time can open a MIDI input.
  - When opening fails, the bridge logs why and retries every few seconds.
  - It reports a new status field, `"loupedeck_busy": true`. The menu says **"Loupedeck: in use by another program"**,
    and the tooltip says to quit the Loupedeck or Logi software. *(My call: the likeliest problem on a friend's PC.)*
  - The Mac app ignores the new field (Swift's decoder skips unknown keys). On the Mac, CoreMIDI shares inputs, so
    it never happens there.
- **Unplug and replug:** the existing check (the port list, once a second). The check below confirms that the
  Windows port list follows the device.
- **Paths:** as in `windows.py`:
  - `mapping.json` in `%APPDATA%\loupedeck-lr-bridge\`
  - `client.json`, the caches and the lock in `%LOCALAPPDATA%\loupedeck-lr-bridge\`
  - logs in `%LOCALAPPDATA%\loupedeck-lr-bridge\logs\`
  The user's profile folders are already private to the user, so nothing changes their permissions. *(My call.)*
- **The settings page** labels Cmd as "Cmd (sends Ctrl)" on Windows. *(My call.)*

### The tray app (C#, .NET Framework 4.8)
- **Where:** `windows/launcher/`, next to `macos/launcher/`.
  - One program, `LoupedeckBridge.exe`, using WinForms (`NotifyIcon`, `ContextMenuStrip`).
  - No NuGet packages, and no installer framework.
- **Built like the Swift app:**
  - `Policies` holds the logic, ported from `Policies.swift` with its tests ported from `PolicyTests.swift`:
    - the status line and when to alert
    - when to restart, and the supervisor
    - the runtime paths
    - versions, release parsing and the update schedule
    - the install and unzip checks
  - The rest: starting and watching the bridge, the tray menu, the updater, downloads, and the signature check.
- **Behaviour:** as listed under "What the user gets". Also:
  - **Alerts** are `NotifyIcon` balloon tips, which Windows 10/11 shows as notifications.
  - **The 15 s after waking** come from `SystemEvents.PowerModeChanged` (resume).
  - **One copy at a time:** a named mutex, so a second copy quits quietly.
  - **Quit:** stops the bridge cleanly, as above.
  - **`LoupedeckBridge.exe --quit`** asks a running copy to quit as if from its menu, and waits. `install.ps1` and
    `bridgectl.ps1` use it. *(My call.)*
- **Start at login:** a value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. It shows in Task Manager →
  Startup apps.
- **The bundled Python** starts without a console window. Like the Mac, it runs with `-E -s -B`, so the user's own
  site-packages and environment can't plant code in it.
- **Logging:** the tray app writes to the same `bridge.log` as the bridge, which also gets the bridge's stderr, as on
  the Mac.
- **The program's version info** names it "LoupedeckBridge", with the version from `bridge/__init__.py`. That's how
  notifications and Task Manager name it.
- **Update preferences** ("check automatically", the last check, a found update, the previous version) persist
  between runs, as the Mac app's defaults do.

### Releases with Windows
- **The bundled Python:**
  - python-build-standalone CPython 3.12 for `x86_64-pc-windows-msvc` (`install_only`), pinned by SHA-256 like the
    Mac's (`tools/python-standalone.lock`)
  - its packages from a hash-pinned requirements file for `cp312-win_amd64`: mido, packaging, python-rtmidi and
    websockets, at the same versions as `requirements.txt`
- **The zip, and the install folder,** `%LOCALAPPDATA%\Programs\LoupedeckBridge\`:
  ```
  LoupedeckBridge\
    LoupedeckBridge.exe     the tray app
    python\                 the bundled Python and its packages
    app\                    bridge\, config\, docs\lr_parameters_10.0.json (the layout the code expects)
  ```
  The build records in the app that it's a release (bundled runtime), its version, and the pinned certificate
  SHA-256 that updates must match. These are the Info.plist's `LBRuntime`, `LBVersion` and `LBSignerSHA256` on the
  Mac.
- **Downloads in each release:**
  - `LoupedeckBridge-v<ver>-windows-x64.zip`
  - its `.sha256`
  - its signature, `.p7s`
  These sit next to the Mac zip and its `.sha256`.
- **Signing:**
  - The publish job, after the user approves the run, makes a **detached CMS signature over the Windows zip's exact
    bytes**, with the same `.p12`, in the same step that signs the Mac app. The key exists in that step only.
  - The secrets keep their names (`MAC_SIGNING_P12`, `MAC_SIGNING_P12_PASSWORD`). Renaming them would mean handling
    the key. *(My call.)*
  - No Authenticode on the program: a self-signed certificate doesn't satisfy SmartScreen, and Authenticode wouldn't
    cover the Python files. *(My call.)*
- **The checks, in the tray app and in `install.ps1`:** before anything is replaced, all of these must pass:
  - the zip's SHA-256 matches its `.sha256`
  - the signature verifies over the zip's bytes (signature only: the certificate is self-signed, so there's no chain
    to check)
  - the signing certificate's SHA-256 (DER) equals the pinned one, the same fingerprint as the Mac:
    `4927ccbb…0faa2cf4`
  - the zip holds exactly one `LoupedeckBridge\` folder with `LoupedeckBridge.exe`, of the version asked for
  - updates only: that version is newer than the running one
- **Workflows:**
  - **release.yml:**
    - A **Windows build job** on a GitHub-hosted Windows runner, alongside the Mac build. It checks the version and
      changelog, builds the zip, and saves it before any test code runs. It then runs the suite (with the C#
      checks) using the bundled Python, and checks the tests left the build unchanged.
    - **The publish job** (macOS, the `release` environment):
      - checks the Windows zip is byte for byte the one the Windows job saved
      - signs both builds in the key step
      - checks the Mac build as today
    - Before anything is published, **the tray app's own check and `install.ps1` accept the signed Windows zip**, on
      a Windows runner. The builder picks the job split.
    - **Publishing refuses to run unless both platforms' downloads are present.**
  - **ci.yml** adds Windows jobs:
    - the suite on Python 3.9
    - the C# build and its checks
    - a release-build rehearsal with a throwaway key: build, sign, then check with the app's own check and
      `install.ps1`, including that a changed byte and another key are both refused
  - `tools/check_release.py` stays as it is: one version, one changelog. `tools/release.sh` changes in two ways
    *(my calls)*:
    - it also runs from Git Bash on Windows (it finds `.venv\Scripts\python.exe`), so the user can release from
      either computer
    - it checks that `install.ps1` pins the same key as `install.sh`, which a test also keeps in step
- **`tools/install.ps1`:**
  - Runs on Windows PowerShell 5.1, which every Windows 10/11 has. It needs neither admin rights nor `gh`.
  - A friend runs:
    ```powershell
    irm https://raw.githubusercontent.com/MegaMattMiller/LoupedeckBridge/main/tools/install.ps1 -OutFile install.ps1
    powershell -ExecutionPolicy Bypass -File install.ps1
    ```
    The second line relaxes the script policy for that one run only; nothing system-wide changes. The download is
    saved and run in two steps, so friends can read it first, as with `install.sh`.
  - It prints the release key's fingerprint, then:
    1. downloads the release with `Invoke-WebRequest`, which adds no "from the internet" mark, so there's no
       SmartScreen step
    2. runs the checks above
    3. stops a running LoupedeckBridge (`--quit`)
    4. keeps the old copy as the previous version, puts the new one in place and starts it
    5. adds the Start menu entry
  - Options: `-Version v0.6.0`, `-AllowOlder`, `-Uninstall`.
- **Uninstall** *(my call: Windows users expect it)*:
  - an entry in Settings → Apps → Installed apps, registered per user under `HKCU`, so no admin is needed
  - it quits the app and removes the program, the Start menu entry, Start at login and the Apps entry
  - it keeps the user's mapping, presets cache, client ID and logs, and says where they are
- **Updating from the tray** *(my call on the mechanism)*. A running program can't be moved or deleted on Windows
  (unlike the Mac app, which moves itself to the Trash), so the swap happens after the old app exits:
  1. Download the zip, `.sha256` and `.p7s` to a temporary folder. Downloads are streamed, hashed as they arrive,
     and stopped past 200 MB.
  2. Run the checks, then unzip to `LoupedeckBridge.new\` next to the install folder.
  3. Stop the bridge (cleanly, keys released).
  4. Start the new copy from `LoupedeckBridge.new\`, told to finish the update and given the old app's process id.
     Then exit.
  5. The new copy waits for the old one to exit, then:
     - renames the install folder to `LoupedeckBridge.previous\`, replacing any older one
     - copies itself into the install folder
     - starts the installed copy and exits
     The installed copy then removes `LoupedeckBridge.new\`.
  - **If anything fails:** up to step 4, the current version keeps running and an alert names the step. After that,
    the new copy puts `LoupedeckBridge.previous\` back and starts it, with an alert.
  - **Go back to the previous version** reverses the swap from `LoupedeckBridge.previous\`.
    - It doesn't re-check a signature: the signature covers the zip, and the zip is gone by then. Anything that could
      tamper with the previous copy in the user's folder could tamper with the installed one too. It checks the copy
      is a complete LoupedeckBridge of the recorded version. *(My call.)*
  - The install path never changes, so Start at login and the Start menu entry keep working across updates.
- **Proving the update:** publish **v0.6.0** (both platforms), then a small real **v0.6.1**, and install v0.6.1 from
  v0.6.0's tray menu on this PC. The Mac updates from its menu too (v0.5.1 → v0.6.0 → v0.6.1), which proves the Mac
  side still finds its zip. Each publish waits for the user's go-ahead.

### Development on Windows
- **`tools/bridgectl.ps1`**, the Windows twin of `tools/bridgectl` *(my call: the bash one drives `launchctl` and
  `open`)*. It covers `build`, `start`, `stop`, `restart`, `status` (each with `-Dev`), `logs`, `login`, `install`
  and `settings`.
- **The dev build**, "LoupedeckBridge Dev", in `build\`:
  - runs the repo's code with `.venv\Scripts\python.exe`, so Python edits never need a rebuild
  - never checks for updates
  - has its own mutex, Start-at-login value and notification name
  - `start -Dev` pauses the installed release and `stop -Dev` brings it back, as on the Mac
- **The commands**, added to the README and CLAUDE.md:
  ```powershell
  py -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt
  .venv\Scripts\python -m pytest -q
  ```
- **Tests:**
  - Mac-only tests skip on Windows, and the new Windows-only tests skip on the Mac.
  - On Windows, pytest builds and runs the C# checks, as it does the Swift checks on the Mac.
  - The existing suite keeps passing on Python 3.9 on both systems.

## Goals, non-goals, anti-goals
- **Goals:**
  - the Mac's features on Windows
  - friends install with one command and no admin
  - updates from the tray that keep working
  - the Mac release behaves exactly as before
- **Non-goals:**
  - a native build for Windows on ARM (the x64 build may run there under emulation; untested)
  - Windows 7 or 8
  - a paid code-signing certificate, or the Microsoft Store
  - an MSI or another installer framework
  - updating without a click
  - Lightroom Classic
- **Anti-goals:**
  - installing anything not signed with the user's own key
  - an update that leaves no working app
  - an admin prompt to install or update
  - a stuck Shift, Ctrl or Alt after a crash, a kill, an unplug or an update
  - a GitHub "latest release" without the Mac zip, which the Mac apps' update check would quietly miss
  - anything that looks like malware to antivirus: hidden PowerShell at login, or scripts downloaded and run in the
    background
  - the bridge talking to the internet, or anything listening beyond 127.0.0.1
  - losing the mapping, presets or client ID on an update

## Constraints
- Windows 10 (22H2) and 11, x64. Install, update and uninstall without admin.
- The tray app uses only .NET Framework 4.8 (WinForms, `System.Security` for `SignedCms`), with no NuGet packages.
- No new runtime dependencies for the bridge. The repo's Python stays 3.9-compatible; the release bundles 3.12.
- **New build-time downloads** (approving this design approves them): the python-build-standalone Windows build and
  the four Windows wheels, all pinned by SHA-256.
- The signing key stays in the GitHub `release` environment, usable only in the signing step of a run the user
  approved. `tools/make_signing_identity.sh` is never run, and the key is never replaced.
- Each release needs the user's go-ahead: the assistant asks before pushing a tag, and GitHub asks the user to approve
  the run.
- `install.ps1` runs on Windows PowerShell 5.1.
- Lightroom: only `connections.json` is read. Live edits happen only on a test photo, after the user says go.

## To verify first (may change the how, not the what)
1. The bundled Python (python-build-standalone 3.12, Windows x64) runs the whole suite. python-rtmidi 1.5.8 and
   websockets 15.0.1 have `cp312-win_amd64` wheels. The bridge opens the Loupedeck+ from the bundled Python.
2. **MIDI on Windows:**
   - the port's name
   - that polling the port list notices an unplug and a replug, and that reopening works
   - what opening does while another program holds the port
3. **`SendInput`:** a held Loupedeck Shift, Ctrl or Alt combines with the real mouse and keyboard (Shift-click,
   Ctrl-click, Alt-drag) with no help.
   - Also: whether Alt pressed and released alone focuses Lightroom's menu bar. If it does, the bridge masks it the
     way Windows tools usually stop the Windows key from opening Start.
4. **Lightroom on Windows:**
   - registering, the Allow dialog, and the saved client ID
   - the `\` and `f` shortcuts
   - that dials, tracking and presets behave as on the Mac
5. Files downloaded by `Invoke-WebRequest` (Windows PowerShell 5.1) and by the tray app carry no Mark of the Web, so
   SmartScreen doesn't step in. Defender lets the unsigned program run.
6. **The signature:**
   - one made by the publish runner's openssl over the zip verifies with .NET Framework's `SignedCms`
   - its signer certificate's SHA-256 is the pinned fingerprint
   - a changed byte, and another key, are both refused
7. The tray app's alerts appear as Windows notifications named LoupedeckBridge. The settings page on 127.0.0.1 brings
   up no firewall prompt.
8. Replacing the install folder after the old app exits works without admin. Start at login and the Start menu entry
   still work after an update.

## Live checks with the user (on this PC)
The Mac's milestone 1, 2, 5 and 6 checks, on Windows:
- dials, buttons, presets, Fn and the --/Col modes
- keys and shortcuts, including modifier + mouse
- unplug and replug alerts, the Loupedeck held by another program, and a killed bridge (restart) and a killed tray
  app (no bridge left, no stuck key)
- Start at login after a sign-out
- the install command
- the tray update from v0.6.0 to v0.6.1, and Go back
- uninstall

The results go in `docs/FINDINGS.md`.

## Left to the builder
- How the stop request and the status pipe reach the bridge (for example a handle number in an environment variable,
  opened with `msvcrt.open_osfhandle`, or the standard streams).
- The C# file split, how it compiles (MSBuild or `dotnet build` against the 4.8 targeting pack, with no NuGet
  packages), and how pytest runs its checks.
- Where the build records runtime, version and fingerprint (a file next to the program, or compiled in), and where
  the update preferences are stored.
- The icons (drawn in code, or small `.ico` files in the repo).
- The exact menu and alert wording where Windows differs, the README's Windows section, and the install text for
  friends.
- The workflow job split, as long as the requirements above hold.
- The bundled Python's strip list.
- How uninstall removes the running program's own folder.
