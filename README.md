# LoupedeckBridge

Use a **Loupedeck+** with **Adobe Lightroom** (the cloud-based desktop app, *not* Lightroom Classic) on macOS.

Loupedeck's own software only supports Lightroom Classic. Lightroom 10 has an external-controller
WebSocket API, so this is a small local Python bridge: Loupedeck+ MIDI in → Lightroom API calls out,
over `127.0.0.1` only.

**Status:** milestone 1 (the core bridge) works on macOS: dials, dial clicks, and the Lightroom
buttons in the default layout. Keyboard keys and the settings page come next. See the
[design](docs/superpowers/specs/2026-11-16-loupedeck-bridge-design.md) and
[docs/FINDINGS.md](docs/FINDINGS.md) for everything verified so far.

## Setup

1. Lightroom: **Preferences → Interface → Enable external controllers**, then restart Lightroom.
2. Quit the Loupedeck / Logi software so it doesn't grab the device.
3. Python environment:
   ```bash
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   ```
4. The first connection shows an **Allow** dialog in Lightroom. The client ID it hands back is
   saved to `~/Library/Application Support/loupedeck-lr-bridge/client.json`, so the dialog
   only appears once.

## Run

```bash
.venv/bin/python -m bridge
```

Stop it with Ctrl-C. Add `--debug` for a verbose log plus a Lightroom frame log (client GUID redacted).

- **Your layout:** `mapping.json` in `~/Library/Application Support/loupedeck-lr-bridge/`
  (Windows: `%APPDATA%\loupedeck-lr-bridge\`). It's created from `config/default_mapping.json` on
  first run. Edit it and restart. A broken file falls back to the default and is left untouched.
- **Logs:** `~/Library/Logs/loupedeck-lr-bridge/bridge.log`.
- **Dial feel:** the four constants at the top of `bridge/dial_feel.py`.
- **Behaviour:** dials and Lightroom buttons work even when Lightroom is in the background.
  Input is dropped while Lightroom is closed, and the bridge reconnects when it's back. Turning a
  colour dial in the device's B&W mode does nothing unless the photo is already black & white.

Tests: `.venv/bin/python -m pip install -r requirements-dev.txt && .venv/bin/python -m pytest -q`

## Run as an app (macOS, needed for keyboard keys)

The Loupedeck's Shift/Ctrl/Cmd/Alt/Tab/arrow buttons and the Before/After and screen-mode shortcuts
send real key presses. macOS only allows that with the **Accessibility** permission, which it grants
to the *app* that started the bridge. Run the bridge from the small **LoupedeckBridge.app** so the
permission covers only the bridge, not your terminal:

```bash
tools/bridgectl build    # builds build/LoupedeckBridge.app (needs Xcode's command-line tools)
tools/bridgectl start
```

On the first start, macOS asks twice. Allow both:
1. **Documents access**, because the bridge's code lives in this repo under `~/Documents`.
2. **Accessibility:** click *Open System Settings* and turn on **LoupedeckBridge**. Check it any
   time with `open build/LoupedeckBridge.app --args --check-permission` (the result goes to the log).

`tools/bridgectl stop | restart | status | logs` do what they say. `stop` releases any held keys first.
Editing the Python code never needs a rebuild. Rebuilding the app may make macOS ask again.
Only one bridge runs at a time: a second one, e.g. from a terminal, refuses to start.

Keys go to whichever app is in front, like a second keyboard.
- Before/After sends `\` (Lightroom's Show Original).
- Screen mode sends `f` (Full Screen Loupe).
- Tab shows and hides the right panel.
- Tab and the arrows repeat while held.
- A held Loupedeck Shift/Ctrl/Alt/Cmd also applies to your real mouse and keyboard, e.g. Alt-drag a slider or Shift-click photos.

## Roadmap

1. ✅ Core bridge on macOS: dials, dial clicks, Lightroom buttons, presets, reconnects
2. Keyboard keys and shortcuts: Shift/Ctrl/Cmd/Alt/Tab and arrows (only while Lightroom is in front), Before/After, screen mode
3. Settings page: search presets and assign them to P1–P8
4. Settings page: remap any control
5. Start at login, plus a status display
6. Windows (macOS-tested code first, then a Windows test run)
7. **GitHub Releases** once it's shippable: versioned downloads and a changelog

## Layout

| Path | What |
|---|---|
| `bridge/__main__.py`, `bridge/app.py` | Entry point and wiring |
| `bridge/midi_input.py`, `bridge/hardware.py` | Loupedeck+ MIDI → control events (survives unplugging) |
| `bridge/mapping.py`, `config/default_mapping.json` | Control → action layout |
| `bridge/actions.py` | Runs actions: Lightroom calls, presets, dial adjustments |
| `bridge/dials.py`, `bridge/dial_feel.py` | Detent coalescing, tracking, the dial-feel curve |
| `bridge/session.py` | Keeps a registered Lightroom connection alive |
| `bridge/platform/` | Per-OS paths (macOS, Windows) |
| `bridge/lightroom.py` | Async Lightroom Controller API client (register, requests, observers) |
| `config/loupedeck_plus.json` | Loupedeck+ MIDI map: every dial, colour-dial mode bank and button |
| `docs/lr_parameters_10.0.json` | Type, label, default and range of all 170 Lightroom edit parameters |
| `tools/midi_dump.py` | Labelled raw MIDI capture |
| `tools/summarize_capture.py` | Turn a capture into a per-control table |
| `tools/find_unknown.py` | Chime on the first control not in the map yet |
| `tools/lr_probe.py` | Read-only Lightroom smoke test (shows reply shapes) |
| `tools/lr_dump_params.py` | Regenerate `docs/lr_parameters_<version>.json` (read-only) |
| `captures/` | Raw MIDI / Lightroom frame logs the map and notes are based on |

Not affiliated with Adobe, Loupedeck or Logitech.
