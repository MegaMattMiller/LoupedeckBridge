# LoupedeckBridge

Use a **Loupedeck+** with **Adobe Lightroom** (the cloud-based desktop app, *not* Lightroom Classic) on macOS.

Loupedeck's own software only supports Lightroom Classic. Lightroom 10 has an external-controller
WebSocket API, so this is a small local Python bridge: Loupedeck+ MIDI in → Lightroom API calls out,
over `127.0.0.1` only.

**Status:** on macOS, milestones 1–4 work: dials, dial clicks, Lightroom buttons and presets, real
keyboard keys and shortcuts (run as LoupedeckBridge.app), and a settings page for presets and for
remapping any control, with an Fn layer. Start at login and a status display come next. See the
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
  first run. Edit it and restart.
  - A broken file falls back to the default and is left untouched (the settings page won't save over it).
  - It follows improvements to the default layout **control by control**. Controls you changed (e.g.
    presets on P1–P8) stay as you set them; the log mentions when a newer default exists for one of those.
- **Logs:** `~/Library/Logs/loupedeck-lr-bridge/bridge.log`.
- **Dial feel:** the four constants at the top of `bridge/dial_feel.py`.
- **Behaviour:** dials and Lightroom buttons work even when Lightroom is in the background.
  Input is dropped while Lightroom is closed, and the bridge reconnects when it's back. Turning a
  colour dial in the device's B&W mode does nothing unless the photo is already black & white.

Tests: `.venv/bin/python -m pip install -r requirements-dev.txt && .venv/bin/python -m pytest -q`

## Settings page: presets on P1–P8

While the bridge runs, open **http://127.0.0.1:7690/** with `tools/bridgectl settings`, the
Loupedeck's **custom mode** button, or a bookmark.
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

## Run as an app (macOS, needed for keyboard keys)

The Loupedeck's arrow buttons, the Before/After and screen-mode shortcuts, and Shift/Ctrl/Cmd/Alt/Tab
in Keys mode (Fn + --/Col; the bridge starts in Ratings) send real key presses. macOS only allows that with the **Accessibility** permission, which it grants
to the *app* that started the bridge. Run the bridge from the small **LoupedeckBridge.app** so the
permission covers only the bridge, not your terminal:

```bash
tools/bridgectl build    # builds build/LoupedeckBridge.app (needs Xcode's command-line tools)
tools/bridgectl start
```

On the first start, macOS asks twice. Allow both:
1. **Documents access**, because the bridge's code lives in this repo under `~/Documents`.
2. **Accessibility:** click *Open System Settings* and turn on **LoupedeckBridge**. Check it any
   time with `open -n build/LoupedeckBridge.app --args --check-permission` (the result goes to the log).

**What these permissions cover, plainly:**
- Accessibility lets LoupedeckBridge send key presses, and watch and adjust real mouse and keyboard
  input. It uses that in two ways only:
  - it sends the keys you map to Loupedeck buttons;
  - **while a Loupedeck Shift/Ctrl/Alt/Cmd is held**, an input tap adds that modifier to your real
    mouse and keyboard events, so Alt-drag and Shift-click work.
- The tap is switched off whenever no Loupedeck modifier is held. It only ever reads and changes
  modifier flags, and logs nothing about your input.
- The permission belongs to the app, and the app runs whatever code is in this repo and its `.venv`.
  Treat changes to those like changes to any app you've given Accessibility.

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
2. ✅ Keyboard keys and shortcuts on macOS: Shift/Ctrl/Cmd/Alt/Tab and arrows, Before/After, screen mode (sent to whichever app is in front)
3. ✅ Settings page: search presets and assign them to P1–P8
4. ✅ Settings page: remap any control, with an Fn layer
5. Start at login, plus a status display
6. Windows (macOS-tested code first, then a Windows test run)
7. **GitHub Releases** once it's shippable: versioned downloads and a changelog

## Layout

| Path | What |
|---|---|
| `bridge/__main__.py`, `bridge/app.py` | Entry point and wiring |
| `bridge/midi_input.py`, `bridge/hardware.py` | Loupedeck+ MIDI → control events (survives unplugging) |
| `bridge/mapping.py`, `config/default_mapping.json` | Control → action layout |
| `bridge/actions.py` | Runs actions: Lightroom calls, presets, dial adjustments, the Fn layer |
| `bridge/commands.py`, `config/commands.json` | What the settings page may assign, in plain words |
| `bridge/settings/` | The settings page: server, layout list, static page |
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
| `tools/lr_check_commands.py` | Check `config/commands.json` against Lightroom (test photo) |
| `tools/preview_settings.py` | The settings page with a fake Lightroom (no device needed) |
| `captures/` | Raw MIDI / Lightroom frame logs the map and notes are based on |

Not affiliated with Adobe, Loupedeck or Logitech.
