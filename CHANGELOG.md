# Changelog

Each release's section here becomes its GitHub release notes (`tools/check_release.py`). Versions are
`bridge/__init__.py`'s `__version__`.

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
