# Changelog

Each release's section here becomes its GitHub release notes (`tools/check_release.py`). Versions are
`bridge/__init__.py`'s `__version__`.

## v0.6.0 — 2026-11-18

Windows: the bridge, a tray app, and releases installed with one PowerShell command. One release now carries both
platforms' downloads.

- **Windows 10 and 11 (64-bit):** everything the Mac version does: dials, buttons, presets, keyboard keys and
  shortcuts, and the settings page. Cmd sends Ctrl. Keyboard keys need no permission.
- **A tray app,** in the notification area (Windows may first hide it behind **^**): the status at a glance, alerts
  when the Loupedeck drops out, restarts after errors, Start at login, and updates from its menu, with Go back.
- **`tools/install.ps1`** installs a release for the current user, with no admin rights: a Start menu entry, and an
  entry in Settings → Apps that uninstalls it. It checks every download against the same release key as the Mac's
  before it replaces anything, and keeps the previous version for Go back.
- **Releases:** the Windows zip is signed (a detached `.p7s`) in the same approved step as the Mac app, checked on
  Windows, and published only together with the Mac download.
- **The bridge** reads and writes its files as UTF-8 on every system (a `mapping.json` saved by Notepad works), and
  carries on when the Loupedeck is unplugged on Windows.
- `tools/release.sh` also runs from Git Bash on Windows, and checks that `install.sh` and `install.ps1` pin the same
  release key.

## v0.5.1 — 2026-11-17

Safer installs and releases (from the review of v0.5.0), and the first update installed from the menu.

- **Updates:** downloads are streamed to disk, hashed as they arrive, and stopped past 200 MB. A failed unzip
  says why (e.g. a full disk). A found update stays in the menu, and its one alert isn't repeated, after the
  app restarts.
- **`install.sh`:** checks the signing identifier the way the app does, and says why an unzip fails. If it put
  the old app back after a failure, it starts it again, and it stops if the running app won't quit.
- **Releases:** the signing job signs the commit the build job built, after checking the tag hasn't moved,
  and "Run workflow" must be started from the version's tag. CI also proves that a changed byte and another
  key are both refused.
- `tools/bridgectl`'s app-path overrides are now `LB_BRIDGECTL_RELEASE_APP` and `LB_BRIDGECTL_DEV_APP`.

## v0.5.0 — 2026-11-17

The first release: everything from milestones 1–6, for Apple Silicon Macs (macOS 14 or later).

- **Loupedeck+ → Lightroom** (the cloud-based desktop app, not Classic), over Lightroom's local
  controller API on `127.0.0.1` only: dials, dial clicks, Lightroom buttons and presets, and reconnecting
  after either side goes away.
- **Keyboard keys and shortcuts:** Shift, Ctrl, Cmd, Alt, Tab and the arrows; Before/After and screen mode.
  The `--/Col` button switches the five buttons between star ratings, colour labels and (with Fn) keys.
- **A settings page** on `127.0.0.1`: search presets and put them on P1–P8, and remap any button or dial,
  with an Fn layer.
- **A menu-bar app:** status at a glance (Loupedeck, Lightroom, keyboard permission, button mode), alerts
  when the Loupedeck drops out, restarts after errors, and Start at login.
- **Releases and updates:** a self-contained app with its own Python, signed with the LoupedeckBridge
  release key. It checks GitHub for a new version once a day and installs it from the menu, only if the
  download is signed with the same key. `tools/install.sh` installs it on any Mac.
