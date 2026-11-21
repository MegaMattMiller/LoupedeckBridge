# LoupedeckBridge

Use a **Loupedeck+** with **Adobe Lightroom** (the cloud-based desktop app, *not* Lightroom Classic) on macOS and
Windows.

Loupedeck's own software only supports Lightroom Classic. Lightroom 10 has an external-controller
WebSocket API, so this is a small local Python bridge: Loupedeck+ MIDI in → Lightroom API calls out,
over `127.0.0.1` only.

**Status:** releases for Macs on macOS 14 or later — Apple Silicon since v0.5.0, Intel since v0.7.0 — and for
Windows 10 and 11, 64-bit (since v0.6.1; checked on Windows 11): dials, dial clicks, Lightroom buttons and presets, real keyboard keys and
shortcuts, a settings page for presets and for remapping any control (with an Fn layer), and a menu-bar or tray
app with alerts, Start at login and updates. See the
[design](docs/superpowers/specs/2026-11-16-loupedeck-bridge-design.md), the
[Windows design](docs/superpowers/specs/2026-11-17-m7-windows-design.md), the
[Intel Mac design](docs/superpowers/specs/2026-11-21-m8-intel-macs-design.md), [CHANGELOG.md](CHANGELOG.md) and
[docs/FINDINGS.md](docs/FINDINGS.md) for everything verified so far.

## Install on a Mac

Apple Silicon or Intel, macOS 14 or later. The installer works out which Mac you're on and fetches that
Mac's download.

1. In Lightroom: **Preferences → Interface → Enable external controllers**, then restart Lightroom.
2. Quit the Loupedeck / Logi software so it doesn't grab the device.
3. In Terminal, on any Mac (no GitHub account or developer tools needed):
   ```bash
   curl -fsSLo install.sh https://raw.githubusercontent.com/MegaMattMiller/LoupedeckBridge/main/tools/install.sh
   ```
   ```bash
   bash install.sh
   ```
   You can read `install.sh` first; it's short. It downloads the newest release, checks it, puts
   **LoupedeckBridge.app** in `/Applications` and starts it. In a copy of this repo,
   `tools/bridgectl install` does the same.

   If you run it from a Rosetta terminal on an Apple Silicon Mac, it still installs the Apple Silicon build.
   `LB_ARCH=arm64` or `LB_ARCH=x86_64` forces one.
4. On the first start, allow:
   - **Notifications**, for the alerts.
   - **Accessibility:** click *Open System Settings* and turn on **LoupedeckBridge** (keyboard keys need it).
   - In Lightroom, the **Allow** dialog. The client ID it hands back is saved to
     `~/Library/Application Support/loupedeck-lr-bridge/client.json`, so it only appears once.

Before it replaces anything, `install.sh` checks:
- the download's SHA-256
- that it holds exactly one LoupedeckBridge.app, with the release's bundle id, the version asked for, and
  the architecture of the Mac it's installing on
- that it's validly signed with the **LoupedeckBridge release key** (the certificate's SHA-256 is pinned
  in the script)

It prints that key's fingerprint first. On a new Mac, check it against one you've noted somewhere other than
GitHub:
```
4927ccbb8cc8c7e3c32afa79d58f11f2129b84b3c7638cb530cb2ced0faa2cf4
```

If a check fails, nothing is replaced. The app it replaces goes to the Trash. For one version:
`bash install.sh v0.5.0`. Going back to an older version than the installed one also needs `--allow-older`.

## Install on Windows

For Windows 10 or 11, 64-bit. No admin rights, GitHub account or developer tools needed.

1. In Lightroom: **Edit → Preferences → Interface → Enable external controllers**, then restart Lightroom.
2. Quit the Loupedeck / Logi software, and turn off its start at login. Windows 11 lets both programs read the
   Loupedeck at once, so it would act on every control too.
3. In **PowerShell** (Start → type "PowerShell"):
   ```powershell
   irm https://raw.githubusercontent.com/MegaMattMiller/LoupedeckBridge/main/tools/install.ps1 -OutFile install.ps1
   ```
   ```powershell
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```
   The second line relaxes PowerShell's script policy for that one run only. You can read `install.ps1` first. It
   downloads the newest release, checks it, installs it to `%LOCALAPPDATA%\Programs\LoupedeckBridge`, adds a Start
   menu entry and an entry in Settings → Apps, and starts it. In a copy of this repo,
   `pwsh -File tools\bridgectl.ps1 install` does the same.
4. **Find the tray icon:** Windows puts a new tray icon behind the **^** next to the clock. Drag it from there onto
   the taskbar, or turn LoupedeckBridge on in Settings → Personalization → Taskbar → Other system tray icons.
5. In Lightroom, the **Allow** dialog. The client ID it hands back is saved to
   `%LOCALAPPDATA%\loupedeck-lr-bridge\client.json`, so it only appears once.

Keyboard keys need no permission on Windows. The Loupedeck's **Cmd sends Ctrl**, so Cmd + Z undoes, as on the Mac.

Before it replaces anything, `install.ps1` checks the download's SHA-256, its signature (the `.p7s` next to it, made
with the same **LoupedeckBridge release key** as the Mac app), and that the zip holds exactly one LoupedeckBridge
release of the version asked for. It prints the key's fingerprint first, the same one as above.

If a check fails, nothing is replaced. The version it replaces is kept as `LoupedeckBridge.previous` next to the
installed one. For one version: `powershell -ExecutionPolicy Bypass -File install.ps1 -Version v0.6.1`. Going back to
an older version than the installed one also needs `-AllowOlder`.

**Uninstall:** Settings → Apps → LoupedeckBridge → Uninstall (or `install.ps1 -Uninstall`). Your layout, presets and
client ID stay in `%APPDATA%\loupedeck-lr-bridge` and `%LOCALAPPDATA%\loupedeck-lr-bridge` (with the logs); delete
those folders to remove them too.

## Updates

The same on both systems, from the menu-bar or tray icon's menu:
- Once a day, the app asks GitHub for the newest release. A new one shows in the menu, just above Quit, as
  **Update available: v… – Install…**, with one alert per version.
  - **Check for updates now** checks straight away.
  - Untick **Check for updates automatically** to stop the daily check.
- **Install…** checks the download exactly as `install.sh` / `install.ps1` do, signature included. Only then does
  it stop the bridge, put this version aside (the Trash on a Mac, `LoupedeckBridge.previous` on Windows), put the
  new one in its place and start it. If any step fails, the current version keeps running (or is put back) and an
  alert says which step.
- Settings and permissions carry over: every release is signed with the same key, and installed in the same place.
- If the new version's bridge keeps failing (the menu says it has stopped), **Go back to the previous
  version (v…)…** puts the previous copy back (on the Mac after the same checks).

## What talks to the internet

Only the menu-bar or tray app (and the installers, when you run them), and only GitHub:
- `api.github.com`, for the daily check (and **Check for updates now**). It sends `LoupedeckBridge/<version>`
  as its user agent, and no account or ID.
- GitHub's download servers, when you install an update.

The bridge itself only connects to Lightroom on `127.0.0.1`, and its settings page only answers on
`127.0.0.1`. Dev builds never check for updates.

## Using it

- **Your layout:** `mapping.json` in `~/Library/Application Support/loupedeck-lr-bridge/`
  (Windows: `%APPDATA%\loupedeck-lr-bridge\`). It's created from `config/default_mapping.json` on
  first run. The settings page edits it; you can also edit it by hand and restart.
  - A broken file falls back to the default and is left untouched (the settings page won't save over it).
  - It follows improvements to the default layout **control by control**. Controls you changed (e.g.
    presets on P1–P8) stay as you set them; the log mentions when a newer default exists for one of those.
- **Logs:** `~/Library/Logs/loupedeck-lr-bridge/bridge.log` (Windows:
  `%LOCALAPPDATA%\loupedeck-lr-bridge\logs\bridge.log`).
- **Behaviour:** dials and Lightroom buttons work even when Lightroom is in the background.
  Input is dropped while Lightroom is closed, and the bridge reconnects when it's back. Turning a
  colour dial in the device's B&W mode does nothing unless the photo is already black & white.

## Settings page: presets on P1–P8

While the bridge runs, open **http://127.0.0.1:7690/** with **Open settings…** in the menu, the
Loupedeck's **custom mode** button, `tools/bridgectl settings`, or a bookmark.
1. Pick a slot (P1–P8) on the left.
2. Search your Lightroom presets on the right, and click one to put it on that slot.
3. ✕ clears a slot.

Changes save to your `mapping.json` straight away and work without a restart. Pressing a P button on
the Loupedeck lights up its slot on the page. A slot whose preset was deleted, or whose name now
matches several presets, is marked so you can assign it again.

The page is local only:
- It only answers on 127.0.0.1, and only to requests addressed to it.
- Changes need a secret that only the page itself has, so other websites open in your browser can't
  change your buttons. (It doesn't stop other programs on your Mac, which can read the page too.)
- The first time, loading the names of ~1,500 presets takes about half a minute; after that they're
  remembered. If you rename a preset in Lightroom, click **Refresh list** to see the new name.
- If the bridge restarts while the page is open, the page reloads itself.
- It loads nothing from the internet.
- `--settings-port N` moves it to another port, and `--settings-port 0` turns it off.
- To work on the page without Lightroom or the device, run `.venv/bin/python tools/preview_settings.py`.
  It serves the page on port 7691 with fake presets and a throwaway mapping.

## Settings page: buttons & dials (and the Fn layer)

The **Buttons & dials** tab changes what any control does. Changes save and work at once.
- Each control has two columns: **Normal**, and **With Fn held**. Holding the Loupedeck's **Fn** button
  switches every control to its Fn action; a control with none ("Same as normal") does its normal job.
  Fn itself does nothing else. If you let go of Fn before a button, that button still finishes its Fn action.
- L1–L3 and C1–C6 come first. Other buttons, the dials and the colour dials (per Hue/Sat/Lum/B&W bank)
  are folded below.
- Click a cell, or **use the control on the Loupedeck**: it's selected on the page (and still does its
  action). Holding Fn switches the page to the Fn column.
- Buttons and dial clicks take a Lightroom command (ratings, flags, colour labels, next/previous photo,
  views and zoom, tools, auto tone, white balance, Upright, Export…), **Nothing**, or **Open this
  settings page**. Dial turns take any Lightroom slider, a **command pair** (one per direction, e.g.
  previous/next photo), or Nothing.
- A dial click **resets whatever that dial adjusts** in the layer in use ("Reset this dial's slider").
- **Fn + Export exports with your previous export settings**, with no dialog. It's fixed, and it's the
  only way to export without the dialog; plain Export always opens it. If Lightroom has no previous
  settings yet, nothing happens.
- **clr/bw** is fixed: it always keeps the photo's black & white in step with the device's lights.
- **--/Col modes:** the five buttons next to --/Col have three modes. The page header shows the current one;
  the device has no light for it.
  - **Ratings:** ★ to ★★★★★. The bridge always starts in Ratings.
  - **Colours:** red, yellow, green, blue, purple. --/Col swaps Ratings and Colours.
  - **Keys:** Shift, Ctrl, Cmd, Alt, Tab as real keys. **Fn + --/Col** turns Keys on and off.
  --/Col is fixed. Each mode's five buttons can be remapped in the "Five buttons (--/Col)" section.
- P1–P8 keep their presets (set on the Presets tab); their Fn actions are set here.
- **Reset** returns one control to its default; **Restore default layout** (two clicks) resets all of
  them but keeps your P1–P8 presets.
- The page can't create keyboard keys or shortcuts; keys you already have (e.g. Shift) can be replaced,
  and Reset brings them back.
- `tools/lr_check_commands.py` checks the command list against Lightroom (on a test photo).

## The menu-bar app

The Loupedeck's arrow buttons, the Before/After and screen-mode shortcuts, and Shift/Ctrl/Cmd/Alt/Tab
in Keys mode (Fn + --/Col) send real key presses. macOS only allows that with the **Accessibility**
permission, which it grants to the *app* that started the bridge. So the bridge always runs inside
**LoupedeckBridge.app**, and the permission covers only it, not your terminal.

While the bridge runs, LoupedeckBridge shows an icon in the menu bar: sliders when all is well, a warning
triangle when the Loupedeck or Lightroom isn't connected, keyboard keys need permission, or the bridge
has stopped. Its menu shows the version, the Loupedeck, Lightroom, keyboard keys and the five buttons'
mode, plus **Open settings…**, **Start at login**, the update items and **Quit LoupedeckBridge**.

**Alerts** (macOS notifications):
- **"Loupedeck disconnected"** when a Loupedeck that was working drops and is still gone after about
  3 seconds. A quick replug, a Loupedeck that was never plugged in this session, and the first 15 seconds
  after the Mac wakes don't alert. At most one a minute.
- **"Loupedeck is back"** after a "disconnected" alert.
- **"Keyboard keys need permission"**, once per run, if Accessibility is missing.
- **"LoupedeckBridge stopped"** if the bridge crashes. The app restarts it after 5 seconds, at most 3 times
  in 10 minutes. After that, the menu offers **Restart bridge** and **Open log**. If the bridge ever dies
  abruptly, the app lets go of any key it was holding.
- **"LoupedeckBridge v… is available"**, once per new version.
- No alert when Lightroom quits; the icon shows it.

**One limit:** a Loupedeck that goes quiet while still plugged in (it happened once on 2026-11-16) can't
be detected, because the device sends nothing when idle. Replug its dongle if the controls stop responding.

**Start at login** is off until you tick it in the menu (or `tools/bridgectl login on`; `off` and
`status` too). It appears in System Settings → General → Login Items.

**What these permissions cover, plainly:**
- Accessibility lets LoupedeckBridge send key presses, and watch and adjust real mouse and keyboard
  input. It uses that in two ways only:
  - it sends the keys you map to Loupedeck buttons;
  - **while a Loupedeck Shift/Ctrl/Alt/Cmd is held**, an input tap adds that modifier to your real
    mouse and keyboard events, so Alt-drag and Shift-click work.
- The tap is switched off whenever no Loupedeck modifier is held. It only ever reads and changes
  modifier flags, and logs nothing about your input.
- The permission belongs to the app. A release runs only the code inside it, and updates are checked
  against the release key; the dev build runs whatever is in this repo and its `.venv`.

Keys go to whichever app is in front, like a second keyboard.
- Before/After sends `\` (Lightroom's Show Original).
- Screen mode sends `f` (Full Screen Loupe).
- Tab shows and hides the right panel.
- Tab and the arrows repeat while held.
- A held Loupedeck Shift/Ctrl/Alt/Cmd also applies to your real mouse and keyboard, e.g. Alt-drag a slider or Shift-click photos.

In a copy of this repo, `tools/bridgectl start | stop | restart | status | logs` control the installed
release. `stop` (like Quit in the menu) releases any held keys first. Only one bridge runs at a time: a
second one, e.g. from a terminal, refuses to start.

## The tray app (Windows)

On Windows, LoupedeckBridge lives in the notification area by the clock (see *Find the tray icon* above). It works
like the Mac's menu-bar app:
- **The icon** shows sliders when all is well, and a warning when the Loupedeck or Lightroom isn't connected or the
  bridge has stopped. Hover over it for the same in words.
- **Its menu** (click or right-click): the version, the Loupedeck, Lightroom and the five buttons' mode, then
  **Open settings…**, **Start at login**, the update items and **Quit LoupedeckBridge**. If another program holds
  the Loupedeck (possible on PCs where only one program can read it), it says "Loupedeck: in use by another program",
  and the bridge keeps trying.
- **Alerts** are Windows notifications named LoupedeckBridge, with the same rules as on the Mac: "Loupedeck
  disconnected", "Loupedeck is back", "LoupedeckBridge stopped" (restarted after 5 seconds, at most 3 times in 10
  minutes, then **Restart bridge** and **Open log** in the menu), and one per new version.
- **Keys:** the bridge sends key presses with Windows' `SendInput`, which needs no permission. A held Loupedeck
  Shift/Ctrl/Alt/Cmd applies to your real mouse and keyboard too (Windows keeps one key state for all input), so
  Alt-drag and Shift-click work. If the tray app or the bridge is ended (even from Task Manager), held keys are let
  go.
- **Start at login** is off until you tick it. It appears in Task Manager → Startup apps.

In a copy of this repo, `pwsh -File tools\bridgectl.ps1 start | stop | restart | status | logs | settings` control
the installed release, as `tools/bridgectl` does on the Mac.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

- **Run from the terminal:** `.venv/bin/python -m bridge` (Ctrl-C stops it; `--debug` adds a verbose log
  and a Lightroom frame log, client GUID redacted). Keyboard keys don't work this way (see above).
- **The dev app**, "LoupedeckBridge Dev", runs this repo's code with its `.venv`, so editing the Python never
  needs a rebuild (only changes to `macos/launcher/` do). It has its own bundle id, so it never mixes with
  the release in Login Items, notifications or Accessibility, and it never updates itself.
  ```bash
  tools/bridgectl build          # builds build/LoupedeckBridge Dev.app (needs Xcode's command-line tools)
  tools/bridgectl start --dev    # pauses the installed release while it runs
  tools/bridgectl stop --dev     # stops it and brings the release back
  ```
  `restart`, `status` and `login` take `--dev` too (`logs` shows the one log both write). On its first start macOS asks for Documents access
  (the code lives in this repo under `~/Documents`), notifications and Accessibility.
- **After rebuilding the dev app**, macOS treats it as a new app (it's signed ad hoc), so its permissions may
  not carry over:
  - **Keyboard keys stop working,** and the menu says "Keyboard keys: need permission". In System Settings →
    Privacy & Security → Accessibility, remove LoupedeckBridge Dev with "−", add `build/LoupedeckBridge Dev.app`
    again with "+", and switch it on. The menu updates within seconds.
  - **No alerts,** and the log says "alerts are off". In System Settings → Notifications → LoupedeckBridge Dev,
    turn "Allow notifications" on, then `tools/bridgectl restart --dev`.
  - Check Accessibility any time with `open -n "build/LoupedeckBridge Dev.app" --args --check-permission`
    (the result goes to the log).
- **Dial feel:** the four constants at the top of `bridge/dial_feel.py`.
- **The release app** locally: `tools/build_release_app.sh OUT_DIR` (it downloads the pinned Python into
  `.cache/` the first time), then `LB_RELEASE_APP=OUT_DIR/LoupedeckBridge.app .venv/bin/python -m pytest -q
  tests/test_release_bundle.py`.
- **CI** (`.github/workflows/ci.yml`) runs on every push: the suite on Python 3.9 on both kinds of Mac and on
  Windows; then each release built and tested with its own Python, on its own kind of machine, and a signing rehearsal with a throwaway key (sign, check, package,
  install, and a changed byte refused). It also checks that a signature made by macOS's LibreSSL, as the release
  signs the Windows zip, passes the tray app's check.

**On Windows**, in PowerShell 7 (`pwsh`), with Python 3.9 or later and, for the tray app, the .NET SDK (it builds for
the .NET Framework 4.8 that comes with Windows):
```powershell
py -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
```
- **Run from the terminal:** `.venv\Scripts\python -m bridge --debug`. Keyboard keys work this way too.
- **The dev build**, "LoupedeckBridge Dev", runs this repo's code with its `.venv` (so Python changes need no
  rebuild), with its own name for notifications and Start at login, and never updates itself:
  ```powershell
  pwsh -File tools\bridgectl.ps1 build          # builds build\LoupedeckBridge Dev\ (dotnet, telemetry off)
  pwsh -File tools\bridgectl.ps1 start -Dev     # pauses the installed release while it runs
  pwsh -File tools\bridgectl.ps1 stop -Dev      # stops it and brings the release back
  ```
- **The release folder** locally: `pwsh -File tools\build_windows_app.ps1 -Release OUT_DIR` (it downloads the pinned
  Python into `.cache\` the first time), then set `LB_WINDOWS_RELEASE_DIR=OUT_DIR\LoupedeckBridge` and run
  `tests\test_windows_release_bundle.py`.

## Releasing

1. Set the version in `bridge/__init__.py`, and add a `## vX.Y.Z` section to `CHANGELOG.md` (it becomes the
   release notes). Merge to `main` and push.
2. `tools/release.sh X.Y.Z` (on the Mac, or in Git Bash on Windows). It checks that you're on an up-to-date, clean
   `main`, that the version and changelog match, that `install.sh` and `install.ps1` pin the same release key, and
   that the tests pass. Then it tags `vX.Y.Z` and asks before pushing the tag.
3. GitHub builds and tests that tag on each kind of Mac and on Windows (`.github/workflows/release.yml`), then
   waits. In the run on
   GitHub's Actions page, **Review deployments** → approve `release`.
4. In one step it signs both tested Mac apps and the tested Windows zip (a detached `.p7s`) with the release key.
   It checks that the Mac updater and `install.sh` will accept them, then, on an Intel Mac that the Intel app
   accepts its own download, and on Windows that the tray app and `install.ps1` accept the Windows zip. It
   publishes the release only with all seven downloads (each of the three zips and its `.sha256`, and the Windows
   `.p7s`): each Mac app's update check looks for its own Mac's zip by name in the newest release. Installed apps
   see it within a day.

**The release key** lives only in this repo's GitHub `release` environment (secrets `MAC_SIGNING_P12` and
`MAC_SIGNING_P12_PASSWORD`). Only `v*` tags can use that environment, and only after you approve the run.
`tools/make_signing_identity.sh` made it (2026-11-17), and its certificate's SHA-256 is pinned in
`tools/install.sh` and `tools/install.ps1`. **Don't replace it:** installed apps only accept updates signed with
the key they were signed with, so a new key means reinstalling everywhere with `install.sh` / `install.ps1`.

## Roadmap

1. ✅ Core bridge on macOS: dials, dial clicks, Lightroom buttons, presets, reconnects
2. ✅ Keyboard keys and shortcuts on macOS: Shift/Ctrl/Cmd/Alt/Tab and arrows, Before/After, screen mode (sent to whichever app is in front)
3. ✅ Settings page: search presets and assign them to P1–P8
4. ✅ Settings page: remap any control, with an Fn layer
5. ✅ Start at login, plus a menu-bar status icon and alerts
6. ✅ Mac releases: a self-contained app built and signed on GitHub, installed with one command, updated from the menu
7. ✅ Windows: the bridge, a tray app, and releases for friends installed with one PowerShell command
8. ✅ Intel Macs: a second Mac download in every release, built and tested on an Intel Mac, installed and updated the same way

## Layout

| Path | What |
|---|---|
| `bridge/__main__.py`, `bridge/app.py` | Entry point and wiring |
| `bridge/__init__.py` | The version (`__version__`) |
| `bridge/midi_input.py`, `bridge/hardware.py` | Loupedeck+ MIDI → control events (survives unplugging) |
| `bridge/mapping.py`, `config/default_mapping.json` | Control → action layout |
| `bridge/actions.py` | Runs actions: Lightroom calls, presets, dial adjustments, the Fn layer |
| `bridge/commands.py`, `config/commands.json` | What the settings page may assign, in plain words |
| `bridge/settings/` | The settings page: server, layout list, static page |
| `bridge/status.py` | Status lines for the menu-bar app |
| `bridge/dials.py`, `bridge/dial_feel.py` | Detent coalescing, tracking, the dial-feel curve |
| `bridge/session.py` | Keeps a registered Lightroom connection alive |
| `bridge/platform/` | Per-OS paths and keyboard keys (macOS, Windows) |
| `bridge/lightroom.py` | Async Lightroom Controller API client (register, requests, observers) |
| `config/loupedeck_plus.json` | Loupedeck+ MIDI map: every dial, colour-dial mode bank and button |
| `docs/lr_parameters_10.0.json` | Type, label, default and range of all 170 Lightroom edit parameters |
| `macos/launcher/` | The menu-bar app (Swift): the bridge process, menu and alerts, updates, signature check |
| `windows/launcher/` | The tray app (C#, .NET Framework 4.8): the same for Windows, with its checks in `tests/` |
| `tools/bridgectl`, `tools/bridgectl.ps1` | Start, stop, build and install from the terminal (Mac, Windows) |
| `tools/install.sh`, `tools/install.ps1` | The standalone installers (any Mac; any Windows PC), and the Windows uninstall |
| `tools/build_windows_app.ps1`, `tools/package_windows_release.ps1` | The Windows dev build and release folder; its zip |
| `tools/sign_windows_zip.sh`, `tools/check_windows_release.ps1` | Signing the Windows zip (`.p7s`); checking it on Windows |
| `tools/python-standalone-windows.lock`, `tools/release-requirements-windows.txt` | The Windows release's pinned Python and packages |
| `tools/build_mac_app.sh`, `tools/build_release_app.sh` | The dev app; the release app with its own Python |
| `tools/sign_release_app.sh`, `tools/package_release.sh` | Signing and zipping a release |
| `tools/python-standalone.lock`, `tools/release-requirements.txt` | The Apple Silicon release's pinned Python and packages |
| `tools/python-standalone-intel.lock`, `tools/release-requirements-intel.txt` | The Intel release's pinned Python and packages |
| `tools/release.sh`, `tools/check_release.py` | Tagging a release; version and changelog checks |
| `tools/make_signing_identity.sh`, `tools/import_signing_identity.sh` | The release key; its temporary keychain on GitHub |
| `.github/workflows/` | CI, and the release build |
| `tools/midi_dump.py` | Labelled raw MIDI capture |
| `tools/summarize_capture.py` | Turn a capture into a per-control table |
| `tools/find_unknown.py` | Chime on the first control not in the map yet |
| `tools/lr_probe.py` | Read-only Lightroom smoke test (shows reply shapes) |
| `tools/lr_dump_params.py` | Regenerate `docs/lr_parameters_<version>.json` (read-only) |
| `tools/lr_check_commands.py` | Check `config/commands.json` against Lightroom (test photo) |
| `tools/preview_settings.py` | The settings page with a fake Lightroom (no device needed) |
| `captures/` | Raw MIDI / Lightroom frame logs the map and notes are based on |

Not affiliated with Adobe, Loupedeck or Logitech.
