# LoupedeckBridge: design

Date: 2026-11-16 · Status: draft for approval · Builds on: [HANDOFF.md](../../HANDOFF.md), [FINDINGS.md](../../FINDINGS.md)

## Intent

Drive **Adobe Lightroom (the cloud-based desktop app, not Classic)** from a **Loupedeck+** with no Logi or
Loupedeck software involved. Logi's own Lightroom plugin exists, but it can be pulled or broken at any
time. This bridge is a **full replacement** that depends only on Lightroom's public controller API, the
device's plain USB-MIDI, and a small amount of our own code.

## Goals

1. Every Loupedeck+ control does something useful in Lightroom out of the box (default layout below).
2. A **settings page** to (a) search Lightroom presets and assign them to P1–P8, and (b) remap **any**
   control to any supported action. Changes apply immediately.
3. Some Loupedeck buttons act as **real keyboard keys** (modifiers, Tab, arrows), held for as long as the
   button is held.
4. Dials feel good: fine control at slow speed, fast travel when spun, no lag, and Lightroom's history
   isn't flooded.
5. Runs in the background from login and recovers by itself when Lightroom restarts or the device is replugged.
6. **macOS first**, then **Windows** (the user will test on a Windows PC with Lightroom). The code is split
   so each OS has one small module of its own.

## Non-goals

- Linux. Lightroom doesn't run there, and controlling it over the network conflicts with the local-only
  constraint. Keep the per-OS split clean so it *could* be added; don't build it.
- Lightroom Classic.
- Layers, pages or profiles (holding a key to swap what other controls do). A single layout for v1.
- Feedback to the device. The Loupedeck+ has no screens, and its HUE/SAT/LUM lights are managed by the device.

## Anti-goals (failure even if it "works")

- Any runtime dependence on Logi/Loupedeck software.
- Anything reachable from the network, or remappable by a web page you happen to visit.
- Surprise destructive actions (e.g. exporting without a dialog, converting a photo to B&W unexpectedly).
- A heavy or fragile dependency stack. Today: `mido`, `python-rtmidi`, `websockets`. Add nothing without a strong reason.
- Lightroom lagging behind the dials, or a history entry for every detent.

## Constraints

- Python, in a project venv. Must run on Apple's system Python **3.9** and on current Windows Python (3.12+).
  No system-wide installs without asking.
- Network: connect to `127.0.0.1` only, and serve the settings page on `127.0.0.1` only.
- Never modify Lightroom's files. Only read `connections.json` (Mac
  `~/Library/Application Support/Adobe/Lightroom CC/Connections/`, Windows `%LOCALAPPDATA%\Adobe\Lightroom CC\Connections\`).
- Never commit Adobe's docs or the client GUID. The GUID lives in the per-user state dir (mode 600 on Mac).
- macOS: sending keyboard events needs **Accessibility** permission, which **the user grants**. The bridge
  can only detect it's missing and say so.
- Windows: a MIDI input usually can't be opened by two programs at once. The Loupedeck software and our
  capture tools must not be running alongside the bridge.
- Live tests that change edits only run on a photo the user picks for testing.

## Approaches considered

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| **A** | Python bridge + settings page in the browser, served by the bridge | Builds on existing code, few dependencies, easy to search 1,572 presets; but it's a browser tab, not an app window, and on Mac the keyboard permission goes to Python | **Chosen** |
| B | Native Swift menu-bar app | Most self-contained, own permission entry; but a rewrite in a new language, Mac-only, bigger build | Possible later; config/map carry over |
| C | Python + Qt window | Real window; but a very large dependency and A's permission issue | Dropped |

## Decided by the user

| Control | Action |
|---|---|
| Tone dials (exposure, contrast, highlights, shadows, whites, blacks, clarity, vibrance, saturation, temperature, tint) | Adjust their Lightroom slider (`Exposure2012`, `Contrast2012`, …, `Temperature`, `Tint`) |
| D1 / D2 | `Texture` / `Dehaze` |
| Control dial | `straightenAngle` (photo angle); click resets it |
| Colour dials | Bank by device mode: HUE → `HueAdjustment<Colour>`, SAT → `SaturationAdjustment<Colour>`, LUM → `LuminanceAdjustment<Colour>`, B&W → `GrayMixer<Colour>` |
| Any dial click | Reset that dial's parameter to default |
| C1 / C2 | Pick / reject, as toggles (`flagPickToggle` / `flagRejectToggle`) |
| P1–P8 | Apply a preset chosen in the settings page (`applyPreset`) |
| Shift, Ctrl, Cmd, Alt, Tab | Real keyboard keys, held while the button is held. Cmd = ⌘ on Mac, Windows key on Windows |
| ← → ↑ ↓ | Real arrow keys |
| Undo / Redo, Copy / Paste | `undo` / `redo`, `copyEditSettings` / `pasteEditSettings` |
| Export | `openExport` (dialog, never a direct export) |
| clr/bw | `toggleBlackAndWhite`, kept in step with the device: the bridge tracks the device's colour/B&W mode (from colour-dial numbers, HUE/SAT/LUM presses and clr/bw presses) and makes the photo match the device's new mode. It falls back to a plain toggle while the mode is unknown. *(Live-check fix: a blind toggle left the lights and the photo opposite each other.)* |
| Before/After, screen mode | Lightroom's keyboard shortcut for each, per OS (see "To verify") |
| C3–C6, L1–L3, custom mode, fn, --/col, HUE/SAT/LUM | Nothing by default; assignable in the remapper (HUE/SAT/LUM still switch the device's bank) |
| **When Lightroom isn't the front app** | Dials and Lightroom-API buttons still control Lightroom (it may be in the background, e.g. on another screen). **Keyboard-key and shortcut buttons only work while Lightroom is in front.** |

Settings page: **presets and full remapper**. Platforms: **Mac first, then Windows** (user tests).

## Design

### Pieces

```
Loupedeck+ ─MIDI─▶ input ─▶ events ─▶ mapper ─▶ actions ─┬─▶ Lightroom client (WebSocket, existing bridge/lightroom.py)
                     ▲                    ▲               └─▶ keyboard backend (per OS)
            hardware map           user mapping  ◀──── settings page (HTTP + live WebSocket, 127.0.0.1)
   config/loupedeck_plus.json   (per-user config dir)
```

- **Input:** opens the `Loupedeck+` MIDI port and turns raw messages into events using the hardware map:
  `Turn(control, detents=±1, t)`, `Press(control)`, `Release(control)`. A colour-dial number resolves to
  `(bank, colour)`. The CC value decodes as `v - 128 if v > 63 else v`.
- **Mapper:** looks up the control's action in the user mapping.
- **Actions** (the remapper offers the same set):
  - `adjust(param)` for dials: amount per detent comes from the **dial-feel function** (below), sent with
    `increment`/`decrement`. Click → `resetToDefault(param)`.
  - `call(message, args…)` for buttons: one Lightroom API call from a curated catalog (zero-argument
    commands plus fixed-argument ones like `showView("compare")`, `rating3`, `selectTool("crop")`,
    `setWhiteBalance("auto")`). The builder curates it from the Adobe reference and
    `docs/lr_parameters_10.0.json`.
  - `step(cw: call, ccw: call)` for dials: a different `call` per turn direction, e.g. next/previous photo,
    rating up/down, zoom in/out. *(Design call: without this, a dial could only be remapped to another slider.)*
  - `preset(name, id)`: apply a Lightroom preset.
  - `key(name)`: a real key held from press to release.
  - `shortcut(keys, per-OS)`: a key combination tapped on press.
  - `none`.
- **Lightroom client:** the existing one, plus reconnect logic (re-read the port file on every attempt,
  re-register with the saved GUID) and a status flag the settings page can show.
- **Keyboard backend (per OS):** key down/up for named keys, "is Lightroom in front?", and a permission
  check. Mac: CoreGraphics keyboard events and `AXIsProcessTrusted` through `ctypes`. Windows: `SendInput`
  and `GetForegroundWindow` through `ctypes`. No new libraries.
- **Settings page:** served by the bridge on `127.0.0.1`.
  - *Presets* tab: a search box over all presets and eight P-slots; assign or clear.
  - *Remapper* tab: every control. Select one by clicking it on screen **or pressing it on the device**
    (live highlight). Pick an action type and its details, then save. "Restore default layout" is available.
  - *Status* strip: Lightroom connected? Device connected? Mac keyboard permission granted?

### Dials (the user writes the key part)

- On the first detent of a turn: `startTracking(param)`. Lightroom ends tracking on its own after the
  tracking delay, or when another parameter is touched. At connect, set `setMultipleAdjustmentThreshold` so
  several dials turned together become one history step.
- Detents arrive up to ~150/s. Group them per parameter so Lightroom gets at most one `increment` per
  parameter every ~20–30 ms, with no backlog and no lag. The exact window is the builder's call.
- **Dial-feel function, written by the user (~5–10 lines):** given the parameter's range info
  (`min, max, decimals, small_step, large_step` from `getRange`, read live per photo) and the turn speed,
  return the amount per detent. The builder provides the surrounding code, speed measurement and tests.
  This decides how the bridge *feels*, so it's the user's call.

### Config

- **Hardware map:** `config/loupedeck_plus.json` (exists, read-only at runtime).
- **Default layout:** `config/default_mapping.json` in the repo.
- **User mapping:** `mapping.json` in the per-user config dir (Mac `~/Library/Application Support/loupedeck-lr-bridge/`,
  Windows `%APPDATA%\loupedeck-lr-bridge\`), created from the default on first run. This keeps it safe from
  code updates and out of the public repo.
- Presets are stored as **name + ID**. ID first, then name if the ID is gone. A missing or ambiguous preset
  shows a warning in the settings page, and the button does nothing.

### Behaviour rules

- **Input while Lightroom is disconnected is dropped**, not queued, so old turns never replay.
- **B&W bank vs Lightroom state:** the device can be in its B&W bank even when the photo isn't B&W (it
  powered up that way in our captures). B&W-bank dials do nothing unless `isBlackAndWhiteOn()` is true, and
  the status strip says why. They never silently convert the photo.
- At connect: `revealAdjustedControls(true)`, so Lightroom opens the panel of whatever is being adjusted.
- **Keys only in Lightroom (user's decision):** `key` and `shortcut` actions fire only while Lightroom is
  the frontmost app. Otherwise the press is ignored. `adjust`, `step`, `call` and `preset` work regardless of focus.
- **No stuck keys:** every held key is released when its button is released, *and* when Lightroom stops
  being the front app, the device disconnects, the bridge stops or crashes (exit handler), or its mapping
  changes while the key is down.
  *(Design call: a stuck Shift or Cmd would break the whole computer until the key is pressed again.)*
- **Mac keyboard permission, v1:** Accessibility is granted to the Python that runs the bridge, which means
  any script run by that Python can send keystrokes. The README must say so plainly. A tiny wrapper app with
  its own permission entry is a possible later step. *(Design call.)*

### Security (settings page)

Any web page open in your browser can send requests to `127.0.0.1`. Without protection, a malicious site
could remap a button to type keystrokes. So:
- Bind to `127.0.0.1` only.
- Reject requests whose `Host` isn't `127.0.0.1`/`localhost` on our port (guards against DNS rebinding).
- Changes require the page's own `Origin` **and** a random per-run token embedded in the page.

### Per-OS module

`bridge/platform/macos.py`, `bridge/platform/windows.py`, each providing: paths (Lightroom port file, state,
config, logs), keyboard backend, "Lightroom in front?", and autostart install/remove (Mac: launchd agent;
Windows: logon task or Startup-folder entry). Everything else is shared.

### Running

- `python -m bridge` runs it in the foreground and prints the settings URL. An autostart command installs
  it to start at login.
- Logs go to a rotating file in the per-user log dir. Frame logging is off by default (debug flag), and the
  GUID is always redacted.

## Testing

- **Unit:** MIDI decoding (replay the real `captures/raw-*.jsonl`), mapping lookups, preset resolution,
  config load/save, request checks for the settings page.
- **Integration:** a fake Lightroom WebSocket server records the calls the bridge makes for a captured
  input sequence.
- **Manual on Mac:** a checklist per control against real Lightroom, on a test photo the user chooses.
- **Windows:** a written checklist the user runs on the Windows PC, covering install, MIDI open, register,
  dials, keys, autostart.

## Milestones (Mac first)

1. Core: MIDI → mapping → Lightroom for all dials and API buttons in the default layout; dial feel; tracking; reconnects.
2. Keyboard keys and shortcuts (Mac backend, permission check).
3. Settings page: presets.
4. Settings page: full remapper.
5. Autostart on login (Mac) and the status strip.
6. Windows backend, plus the user's Windows test run.

## To verify early (may adjust the layout, not the architecture)

- Does `straightenAngle` respond to `increment`/`setValue` outside the crop tool?
- Is `increment`'s amount in the parameter's own units, and does Lightroom clamp at the range ends?
- Does `applyPreset` hit the photo in Loupe view (it says "selected photos")?
- Lightroom's keyboard shortcuts for **Before/After** and the **screen-mode** equivalent, on Mac and on Windows.
- Lightroom's process name on Windows, for the "in front?" check.

## Left to the builder

The library-level choices within the constraints (how to serve HTTP alongside WebSockets without new
dependencies, test runner, file layout under `bridge/`), the exact grouping window for detents, whether
arrow keys auto-repeat while held, the remapper's visual layout, and the curated action catalog.
