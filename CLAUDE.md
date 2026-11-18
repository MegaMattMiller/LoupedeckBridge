# Working on LoupedeckBridge

A local bridge so a Loupedeck+ controls Adobe Lightroom (the cloud-based desktop app, **not** Lightroom
Classic, though both may be installed). Python bridge (Loupedeck+ MIDI in, Lightroom's controller WebSocket
API out), plus a menu-bar app on macOS. Mac releases since v0.5.0; Windows is milestone 7. See README.md.

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
  (`client.json` in the bridge's config folder: `~/Library/Application Support/loupedeck-lr-bridge/` on macOS,
  `%APPDATA%\loupedeck-lr-bridge\` on Windows). The bridge never logs the ID either.
- **Local only:** the bridge connects and serves on 127.0.0.1 only. Only the menu-bar app talks to the
  internet, and only to GitHub (the update check and downloads). No telemetry.
- **Lightroom:** read only its `connections.json`; never change Lightroom's files. Try live edits only on a
  test photo, after the user says go.
- **Installs:** a project venv (`.venv`) is fine. Ask before anything system-wide (Homebrew, a global pip,
  a Python installer), and before new build-time downloads. New runtime dependencies need the user's OK.
- **Permissions** (macOS Accessibility, notifications) are granted by the user, never scripted.
- **Releases:** the user runs `tools/release.sh X.Y.Z` (it asks before pushing the tag) and approves the
  signing run on GitHub. CI must pass first.
- **The signing key** lives only in the GitHub `release` environment. The user made it with
  `tools/make_signing_identity.sh`; never run that script, handle the key or its password, or replace it.
  Its fingerprint is pinned in `tools/install.sh`, and installed apps accept updates signed only with it.
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

## Known traps
- **Controls dead but the bridge looks healthy:** the Loupedeck's USB dongle can drop silently. Check the log
  for "Loupedeck connected" and ask the user to replug the dongle before suspecting the code.
- **Rebuilding the dev app** (ad hoc signature) can lose its Accessibility grant: remove and re-add it in
  System Settings. Releases keep their grants, because every one is signed with the same key.
- While a Lightroom Allow dialog is open, Lightroom answers no client.
- **Milestone 7:** GitHub's "latest release" must still include the Mac download
  (`LoupedeckBridge-v<ver>-macos-arm64.zip`), or the Mac apps' update check quietly finds nothing.
