# Verified findings (2026-11-16)

Companion to [HANDOFF.md](HANDOFF.md). Everything here was checked on this Mac, not assumed.

## Files in this project
- `docs/HANDOFF.md`: the original handoff/plan.
- `docs/adobe/` (**local only, gitignored**: Adobe's copyrighted pages). Lightroom writes `LrControllerAPI_10.0_Setup.html` (connection/protocol) and `LrControllerAPI_10.0.html` (~150 commands) to the macOS temp folder; copy them here to keep them, since macOS clears that folder. Find them with `find /private/var/folders -name 'LrControllerAPI*' 2>/dev/null`.

## Loupedeck+ hardware: resolved
The "unknown" in the handoff is answered: **it is a USB-MIDI device.**

| Item | Value |
|---|---|
| USB VID / PID | `0x2ec2` / `0x0002` (product string `Loupedeck_`) |
| Interface 0–1 | CDC-ACM serial → `/dev/cu.usbmodem2101` (the path follows the USB port; it changes if you move the cable to another port) |
| Interface 2–3 | USB Audio Control + **MIDI Streaming** (class 1, subclass 3) |
| CoreMIDI | source **`Loupedeck+`** and destination **`Loupedeck+`** |

The serial port's purpose is unknown (likely firmware/config); we can ignore it for now.

### MIDI protocol: Step 1 done
Full map: [`config/loupedeck_plus.json`](../config/loupedeck_plus.json) (14 tone/custom dials, 8 colour dials × 4 modes, 40 buttons). Checked against all 6 captures: every number the device sent is mapped, and every mapped number has been seen.
- Everything is on **channel 0**.
- **Dial turn** = CC on the dial's number. Value **1 = one detent clockwise**, **127 = one detent counter-clockwise** (two's complement −1). No other value ever appeared in ~620 dial messages, fast spins included, so there's **no hardware acceleration**. Messages arrive as fast as every ~6 ms, so the bridge has to do any acceleration itself, based on timing.
- **Dial click** = note with the **same number** as the dial's CC. Every dial clicks, including the tone dials.
- **Button** = `note_on` vel 64 on press, `note_off` vel 64 on release. Since release is reported, held keys can act as modifiers (shift/ctrl/alt/command → layers) and long-press is possible.
- **The colour dials depend on the mode.** The colour mode changes their numbers: **HUE 1–8, SAT 9–16, LUM 17–24, B&W 25–32** (red → magenta, in Lightroom's HSL order; physical "light blue" = aqua, "dark red" = magenta). B&W mode comes from the clr/bw button (note 101) and turns off all three HUE/SAT/LUM lights; it matches Lightroom's B&W colour-mix panel. Untested: whether pressing clr/bw again returns to colour. The device tracks the mode, so the number alone gives mode + colour and the bridge needs no mode state. The HUE/SAT/LUM buttons (notes 98/99/100) are still reported, so the bridge can also see which mode was picked. Re-pressing the lit mode button keeps the same bank (radio-style, no "off"). All 24 turns and clicks have been seen.
- The CC 25–32 seen in the unlabelled first run was this B&W bank: the device was already in B&W mode then.
- CC 43 and 47 (gaps in the tone-dial range) never appeared; probably unused. CC 43 and 47 (gaps in the tone-dial range) have never been seen.
- Capture convention: under a label, the **last** source of each kind (cc / note) is the real one. `tools/summarize_capture.py` applies that rule.

Loupedeck / Logi plugin service: **not running** ✓

## Lightroom
- Lightroom (cloud) **10.0** at `/Applications/Adobe Lightroom CC`, same version as the docs. Lightroom Classic is also installed; don't confuse the two.
- `connections.json` = `{"port":7682}`.
- With Lightroom open, it listens on **`*:7682` (all interfaces, IPv6 dual-stack)**, not only 127.0.0.1 as the doc implies. The Allow dialog is the only gate against other machines on the network, so the bridge connects to 127.0.0.1 only.

## Lightroom protocol: Step 2 done (2026-11-16 10:17)
Verified with [`tools/lr_probe.py`](../tools/lr_probe.py) against Lightroom 10.0 (build `20261029-1525-df1be3b`). Raw frames are in `captures/lr-frames-*.jsonl` (client GUID redacted).
- **Register** reply: `["<clientGUID>", "10.0"]`. The GUID is saved to `~/Library/Application Support/loupedeck-lr-bridge/client.json` (mode 600, outside iCloud). Re-registering with it skips the Allow dialog, and Lightroom returns the same GUID.
- **`response` is an array of the function's return values** (Lua-style multiple returns). Functions that return nothing (`increment`, `undo`, `applyPreset`, …) reply with an **empty object `{}`** instead:
  - `getRange("Exposure2012")` → `[-5, 5, 2, 0.1, 0.33]` = min, max, decimal places, small step, large step
  - `getValue` → `[0]`, `getLabel` → `["Exposure"]`, `getParameterType` → `["number"]`
  - A single list return is wrapped twice: `getParameterNames` → `[[…170 names…]]`, `getPanelNames` → `[["lightPanel","colorPanel","effectsPanel","detailPanel","opticsPanel","lensBlurPanel"]]`
  - `appVersionTable` → `[{"major":10,"minor":0,"revision":0,"build":"20261029-1525-df1be3b"}]`. `build` is a **string**, not the number the doc claims.
  - Some booleans carry a 2nd value with menu-item state: `isBlackAndWhiteOn` → `[false, {"enabled":true,"title":"Convert to Black ＆ White","checked":false}]`
  - `getColorLabel` → `["no_label_color"]` (the doc says `'none'`), `getFlag` → `["unflagged"]`, `getSelectedTool` → `["loupe"]`
- **Errors:** `{"success": false, "response": ["invalid_request"]}` for an unknown message.
- **Parameter names for the dials** (all present in the 170-name list):
  - Tone: `Exposure2012 Contrast2012 Highlights2012 Shadows2012 Whites2012 Blacks2012 Clarity2012 Texture Dehaze Vibrance Saturation Temperature Tint`
  - Colour dials, by device mode: HUE → `HueAdjustment<Colour>`, SAT → `SaturationAdjustment<Colour>`, LUM → `LuminanceAdjustment<Colour>`, B&W → `GrayMixer<Colour>` (Colour = Red Orange Yellow Green Aqua Blue Purple Magenta)
  - Don't confuse these with `RedHue`/`RedSaturation`/`GreenHue`/`BlueHue`/`ShadowTint`, which belong to the **Calibration** panel.

## Parameter reference: Step 3 done
[`docs/lr_parameters_10.0.json`](lr_parameters_10.0.json) (from [`tools/lr_dump_params.py`](../tools/lr_dump_params.py), read-only) has the type, label, default and range of all **170** parameters: 149 number, 19 boolean, 2 string (`CameraProfile` default "Adobe Standard", `WhiteBalance` default "As Shot").
- `getRange` usually returns 5 values but **4 (no large step)** for 8 parameters: `EnhanceDenoiseAmount HDREditMode PerspectiveUpright crop* straightenAngle`.
- A default of **`{}`** is Lua `nil` = no fixed default (65 parameters, e.g. all `GrayMixer*`, which are computed per photo).
- **Ranges can depend on the photo:** `Temperature`/`Tint` came back as 0–100 (default 50) for the photo open at the time, not Kelvin. The bridge should read `getRange` live and not hard-code ranges.
- Dial targets: ±100 sliders (Contrast, Highlights, Shadows, Whites, Blacks, Clarity, Texture, Dehaze, Vibrance, Saturation, all 32 colour params) step **10 / 20**. Exposure −5..5, 2 decimals, step **0.1 / 0.33**. Temp/Tint step **1 / 10**. These steps are coarse for one dial detent (10 detents from 0 to +100), so how much one detent moves is a mapping decision.

## Write behaviour (milestone 1 checks, 2026-11-16)
From [`tools/lr_verify_writes.py`](../tools/lr_verify_writes.py) on a test photo in Loupe view. Originals were restored afterwards.
- **`increment`/`decrement` amounts are in the parameter's own units**: `increment("Exposure2012", 0.1)` moved 0 → 0.1 EV.
- **Lightroom clamps at the range ends**: `increment("Contrast2012", 500)` stopped at 100.
- **`straightenAngle` works outside the crop tool** (tool was `loupe`): `increment(…, 1)` moved 0 → 1°. `resetToDefault` put it back to 0.
- **Tracking makes a burst one undo step:** `startTracking`, 5× `increment(0.05)` → +0.25 EV, then a single `undo()` returned Exposure to its starting value. This held both with an explicit `stopTracking` and when tracking ended by itself after the 2 s tracking delay (what the dial engine relies on). Lightroom (cloud) has no step-by-step History panel like Classic, so this was checked through `undo`.
- **`applyPreset` applies to the photo in Loupe view**, and `undo()` reverts it completely (8 sampled settings matched the pre-preset values).
- So the dial engine uses `increment`/`decrement` for every parameter, and no `setValue` fallback is needed.

## Milestone 1 live check (2026-11-16, Mac, Lightroom 10.0)
`python -m bridge --debug` with the default layout on a test photo; ~1,000 Lightroom calls, **none failed**.
- ✅ All tone dials, D1/D2 (Texture/Dehaze), the control dial (straighten), and the colour dials in HUE/SAT/LUM. Each dial click resets its slider.
- ✅ C1/C2 pick/reject toggles, undo/redo, copy/paste settings, export (opens the dialog), clr/bw.
- ✅ The B&W guard: in the device's B&W mode on a colour photo, the colour dials logged "GrayMixerRed ignored…" and changed nothing.
- ✅ Lightroom quit and reopen: the bridge waited and reconnected about 10 s later with no Allow dialog. Loupedeck unplug/replug: detected, then resumed about 9 s later.
- **Device behaviour learned:** clr/bw flips the device between B&W mode (all lights off, colour dials send 25–32) and colour mode (back to HUE lit), on its own. A blind `toggleBlackAndWhite` could therefore leave the lights and the photo opposite each other. **Fixed:** the bridge tracks the device's mode and makes the photo match it. The re-test confirmed they stay in step.
- Fast spins hit the slider ends (Lightroom clamps). Dial-feel tuning is up to the user (`bridge/dial_feel.py`).
- Ctrl-C shutdown takes a few seconds (websocket close / MIDI port close); it isn't a hang.

## LoupedeckBridge.app and macOS permissions (milestone 2, 2026-11-16)
- `tools/build_mac_app.sh` builds `build/LoupedeckBridge.app` (bundle id `io.github.megamattmiller.loupedeckbridge`, ad-hoc signed). It spawns `<repo>/.venv/bin/python -m bridge` as a **child process**, so macOS treats the app as responsible for it.
- **Accessibility is scoped to the app:** launched through the app, `--check-permission` reports *granted*. The same check from a terminal-launched Python reports *not trusted*. The terminal and the Claude app gained nothing.
- **The first launch also needs Documents access:** the repo, and so the venv, lives in `~/Documents`, which macOS protects per app. Python blocks during startup until "LoupedeckBridge would like to access files in your Documents folder" is answered, with no log output until then. A packaged release (code inside the app bundle) won't need this.
- An ad-hoc signature changes when the launcher is rebuilt, so macOS may ask again after `tools/build_mac_app.sh`. Editing the Python code never needs a rebuild.

## API notes the handoff didn't capture
- **How object handles come about:** `addAdjustmentChangeObserver(param?)` and `addHapticsObserver()` return a GUID/object. Later notifications arrive as extra responses for that same original `requestId` (this is the "one request, many responses" case). Call `close` on the handle when done.
- **Tracking:** `startTracking(param)` turns itself off **2 s** after the last change, or as soon as a *different* parameter is adjusted. `stopTracking()` commits **one** history state. `setMultipleAdjustmentThreshold` defaults to **0.5 s** and has no effect if it's larger than the tracking delay.
- **Useful for encoders/buttons:** `ratingIncrease()`/`ratingDecrease()`, `flagIncrease()`/`flagDecrease()`, `flagPickToggle()`, `zoomInSome()`/`zoomOutSome()`, `setTrackingModifiers("option")` (Option-drag clipping view), `showClipping()`, `selectTool("crop"|"heal"|"masking"|…)`, `getParameterType`, `getPanelNames`, `getDefault`.
- **Haptics observer** reports slider `hit` min/max/`default` crossings. The Loupedeck+ has no motor, but this could drive a "snapped to default" cue.
- **Doc gaps, check against real responses:**
  - The docs use Lua wording ("table", "nil", multiple return values), and `getRange` returns 5 values. The JSON shape of `response` for these isn't specified (array? keyed object?), so log the raw frames first.
  - `revealPanel()` has no description or arguments.
  - The argument format of `setImageSettingsXMP` isn't documented.
  - There's no documented error format for `success: false`.

## Environment
- `/usr/bin/python3` = **3.9.6** (Apple's Command Line Tools build). It works for `mido`, `python-rtmidi` and `websockets` in a venv, but 3.9 is past end-of-life, so a newer Python is worth considering.
- `swift` is available. A CoreMIDI listing script works with nothing extra installed.
