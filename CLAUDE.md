# Working on LoupedeckBridge

A local bridge so a Loupedeck+ controls Adobe Lightroom (the cloud-based desktop app, **not** Lightroom
Classic, though both may be installed). Python bridge (Loupedeck+ MIDI in, Lightroom's controller WebSocket
API out), plus a menu-bar app on macOS and a tray app on Windows. Mac releases since v0.5.0, Windows since v0.6.1
(milestone 7). See README.md.

## Start here, not with new probes
- `docs/FINDINGS.md`: everything verified so far: the device's MIDI, Lightroom's API, macOS permissions,
  signing, releases. Read it before probing hardware or Lightroom again.
- `docs/superpowers/specs/` (designs) and `docs/superpowers/plans/` (plans), one pair per milestone.
- `config/loupedeck_plus.json` (the MIDI map), `docs/lr_parameters_10.0.json` (all Lightroom parameters).
- `CHANGELOG.md`, one section per release.

## Rules
- **The repo is public.** Ask before every push, tag and release. Before pushing, check the outgoing
  commits for: the Lightroom client ID, Adobe's docs, build output, personal paths and email addresses.
- **Never commit** `docs/adobe/` (Adobe's copyrighted API pages; gitignored) or the Lightroom client ID
  (`client.json` in the bridge's state folder: `~/Library/Application Support/loupedeck-lr-bridge/` on macOS,
  `%LOCALAPPDATA%\loupedeck-lr-bridge\` on Windows). The bridge never logs the ID either.
- **Local only:** the bridge connects and serves on 127.0.0.1 only. Only the menu-bar / tray app (and the
  installers) talk to the internet, and only to GitHub (the update check and downloads). No telemetry: build the
  tray app with `DOTNET_CLI_TELEMETRY_OPTOUT=1` (the scripts and tests do).
- **Lightroom:** read only its `connections.json`; never change Lightroom's files. Try live edits only on a
  test photo, after the user says go.
- **Installs:** a project venv (`.venv`) is fine. Ask before anything system-wide (Homebrew, a global pip,
  a Python installer), and before new build-time downloads. New runtime dependencies need the user's OK.
- **Permissions** (macOS Accessibility, notifications) are granted by the user, never scripted.
- **Releases:** the user runs `tools/release.sh X.Y.Z` (it asks before pushing the tag) and approves the
  signing run on GitHub. CI must pass first.
- **The signing key** lives only in the GitHub `release` environment. The user made it with
  `tools/make_signing_identity.sh`; never run that script, handle the key or its password, or replace it.
  Its fingerprint is pinned in `tools/install.sh` and `tools/install.ps1`, and installed apps accept updates signed
  only with it. The script is macOS-only (CI's Windows job makes throwaway keys with `tests/signing_fixtures.py`).
- The repo's Python code stays compatible with Python 3.9. The release app bundles Python 3.12.

## How the work goes
Each milestone: talk it through → a design doc → a plan → test-first implementation (watch each test fail
first) → one fresh review of the whole branch → a live check with the user on the real device and
Lightroom → merge (the user decides; ask before pushing). Record what a live check proves in
`docs/FINDINGS.md`.

## Commands
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # setup
.venv/bin/python -m pytest -q                                             # tests (macOS: Swift checks too)
.venv/bin/python -m bridge --debug                                        # run in a terminal (no keyboard keys)
tools/bridgectl build                                                     # the dev app, "LoupedeckBridge Dev"
tools/bridgectl start --dev                                               # pauses the installed release
tools/bridgectl logs
```
The installed release is `/Applications/LoupedeckBridge.app`; `tools/bridgectl start|stop|status` act on it.

On Windows, in PowerShell 7 (the tray app needs the .NET SDK; tests build it):
```powershell
py -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt   # setup
.venv\Scripts\python -m pytest -q                                      # tests (C# checks too)
.venv\Scripts\python -m bridge --debug                                 # run in a terminal (keys work)
pwsh -File tools\bridgectl.ps1 build                                   # the dev build, "LoupedeckBridge Dev"
pwsh -File tools\bridgectl.ps1 start -Dev                              # pauses the installed release
```
The installed release is `%LOCALAPPDATA%\Programs\LoupedeckBridge\`; `bridgectl.ps1 start|stop|status` act on it.
Its log (the tray app's and the bridge's): `%LOCALAPPDATA%\loupedeck-lr-bridge\logs\bridge.log`. The full suite takes
about 4 minutes here, mostly `tests/test_install_ps1.py`: run it in the background.

## Known traps
- **Controls dead but the bridge looks healthy:** the Loupedeck's USB dongle can drop silently. Check the log
  for "Loupedeck connected" and ask the user to replug the dongle before suspecting the code.
- **Rebuilding the dev app** (ad hoc signature) can lose its Accessibility grant: remove and re-add it in
  System Settings. Releases keep their grants, because every one is signed with the same key.
- While a Lightroom Allow dialog is open, Lightroom answers no client.
- GitHub's "latest release" must always include the Mac download (`LoupedeckBridge-v<ver>-macos-arm64.zip`), or
  the Mac apps' update check quietly finds nothing (release.yml's publish job refuses without all five files).
- A release run's Sign job shows "queued" while it waits for the user's approval. After a flaky failure,
  `gh run rerun <id> --failed` (ask first) reruns only the failed jobs.
- **Windows:**
  - Name UTF-8 in every text read and write (the default is cp1252); `tests/test_text_io.py` checks.
  - Windows won't rename a folder that a process stands in (its current folder): the tray app and the bridge step
    out at start, or updates fail.
  - In PowerShell, rename folders with `[IO.Directory]::Move`: when a rename fails, `Move-Item` moves the files
    one by one and splits the folder.
  - A venv's `python.exe` is a launcher with the real Python as its child (two processes); releases have one.
  - Windows PowerShell 5.1 started from PowerShell 7 inherits its `PSModulePath` and can't load its own modules.
  - `build\LoupedeckBridge Dev\` may predate the C# code: rebuild it (`bridgectl.ps1 build`) before checking with it.
  - The tests run beside the real install: every `install.ps1` `LB_*` setting must point somewhere temporary in
    them (`test_rig_keeps_every_install_ps1_place_away_from_this_pc`). One left out once wiped the real update prefs.
  - Checking Start at login takes a sign-out, which also ends the Claude session: record progress first; the user
    resumes with `claude --continue`.
