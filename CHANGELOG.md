# Changelog

Each release's section here becomes its GitHub release notes (`tools/check_release.py`). Versions are
`bridge/__init__.py`'s `__version__`.

## v0.8.0 — 2026-11-22

One layout on several machines: the settings page reloads it from its file, and a save never undoes a change
synced in from another machine.

- **Reload from file** in the settings page reads `mapping.json` again, without a restart. The Loupedeck and every
  open page switch to it at once. A file that can't be read leaves the layout in use as it is. Once it's fixed,
  Reload brings it back, with no restart needed any more.
- **Saves apply to the file as it is on disk,** never to the copy read at start. So a change synced in from
  another machine, or made by hand, survives your next edit.
- **The README explains syncing a layout with Syncthing:** which file, the ignore patterns, and the one step for a
  machine joining.

## v0.7.0 — 2026-11-21

Intel Macs. One release now carries a download for each kind of Mac, and each one installs and updates itself
from its own.

- **Intel Macs (macOS 14 or later):** everything the Apple Silicon version does, from the same `install.sh`
  command and the same signed releases, with updates from the menu bar. `install.sh` works out which Mac it's on
  and fetches that Mac's download; run from a Rosetta terminal on an Apple Silicon Mac, it still installs the
  Apple Silicon build.
- **Apple Silicon Macs are unaffected.** Their download keeps its name, so every app already installed keeps
  updating exactly as before, with nothing to do.
- **Releases** carry seven downloads: each Mac's zip and `.sha256`, and the Windows zip, its `.sha256` and its
  `.p7s`. Both Mac apps are built and tested on their own kind of Mac, then signed with the one release key in
  the one step you approve. Nothing is published unless every download is there, because an app looks for its
  own Mac's zip by name and would otherwise quietly find no update.

## v0.6.2 — 2026-11-18

The review's smaller fixes for Windows, and the first update to install from the tray.

- **Updates from the tray:** an unexpected error while checking or installing ends with its reason, not a crash
  dialog. Alerts name the step that failed in plain words. Before it quits, the tray app checks that the new version
  really started. After a failed swap it starts whichever copy is still whole. TLS is left to Windows (1.2 and 1.3).
- **The tray app** is built for 64-bit Windows only, which its key release relies on.
- **Uninstall** keeps the Settings → Apps entry until the app is really gone, so it can be tried again from there. It
  removes the update preferences too (your layout, presets and client ID stay), and it works when started from inside
  the install folder.
- **`install.ps1`** is plain ASCII, because Windows PowerShell reads it in the PC's own code page.
- **The settings page** names the keys a shortcut sends on this system (Ctrl on Windows).

## v0.6.1 — 2026-11-18

Windows: the bridge, a tray app, and releases installed with one PowerShell command. One release now carries both
platforms' downloads. (v0.6.0 was tagged but never published: its release run stopped before signing, because the
signing job downloaded the Windows zip into the repo's own `windows/` folder. That's fixed here.)

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
