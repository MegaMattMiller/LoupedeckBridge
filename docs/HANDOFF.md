# Handoff: Loupedeck+ → Lightroom (cloud) bridge

## Goal
Make my **Loupedeck+** control **Adobe Lightroom** (the cloud/desktop app, NOT Lightroom Classic) on my Mac. Loupedeck's own software only supports Classic. Lightroom now has an **external controller API**, so the plan is a small local bridge: read the Loupedeck+ input → send Lightroom API commands over WebSocket.

## Current state
- Lightroom: Preferences > Interface > "Enable external controllers" is ON, Lightroom restarted.
- Lightroom saved two doc pages to my temp folder: `LrControllerAPI_10.0_Setup.html` (connection) and the API reference (command list, version 10.0). Find them with:
  `find /private/var/folders -name 'LrControllerAPI*' 2>/dev/null`
- Loupedeck+ is plugged in via USB, Loupedeck software is **quit** (it must stay quit so it doesn't grab the device).
- **Unknown:** how the Loupedeck+ shows up on macOS. I believe it's a USB MIDI device (like the original Loupedeck) but that is NOT confirmed.

## Step 1: identify the device
1. Audio MIDI Setup > Window > Show MIDI Studio: is there a Loupedeck entry?
2. `system_profiler SPUSBDataType | grep -i -B2 -A8 loupedeck`
3. If MIDI: write a tiny `mido` (python-rtmidi) listener that prints every message, then I'll turn each dial and press each button so we can build a map (CC/note numbers, relative vs absolute encoder values).
4. If not MIDI (e.g. HID or serial), work out the protocol from there (hidapi / pyserial), or check whether MIDI2LR-style projects already document it.

## Step 2: Lightroom connection (from the Setup page)
- WebSocket server: `ws://127.0.0.1:7682` by default. If that port is busy Lightroom uses another and writes it to `connections.json` in `~/Library/Application Support/Adobe/Lightroom CC/Connections` — read that file rather than hardcoding.
- Request format:
  ```json
  {"requestId": "<new guid>", "object": null, "message": "<operation>", "params": [ ... ]}
  ```
  `object` can be omitted for the root object.
- Response: `{"requestId": "<same guid>", "success": true, "response": {...}}`. One request can get several responses.
- First call must be register:
  ```json
  {"requestId": "<guid>", "object": null, "message": "register", "params": ["<appName>", "<appVersion>", "<optional_clientGUID>"]}
  ```
  Lightroom shows an allow dialog; reply contains a clientGUID + Lightroom version. **Save the clientGUID** and pass it on later connects so the dialog doesn't reappear.
- `close` message on an object handle when done with it.

## Useful API commands (from the API reference)
- Sliders: `increment(param, amount?)`, `decrement(param, amount?)`, `setValue(param, value)`, `getValue(param)`, `getRange(param)` → min, max, precision, small/large increment, `getParameterNames()`, `getLabel(param)`, `resetToDefault(param)`. Param names are like `"Exposure2012"` — dump the real list with `getParameterNames()`.
- Smooth dragging: `startTracking(param)` / `stopTracking()`, `setTrackingDelay(sec)`, `setMultipleAdjustmentThreshold(sec)` (important if several dials move at once, to avoid flooding history).
- Navigation/view: `nextPhoto()`, `previousPhoto()`, `showView("loupe"|"square_grid"|"compare"|"dynamic_grid")`, zoom functions, `undo()`, `redo()`.
- Culling: `flagPick()`, `flagReject()`, `flagUnflag()`, `rating0()`…`rating5()`, `colorLabelRed()` etc.
- Edit helpers: `setAutoTone()`, `setWhiteBalance(...)`, `toggleBlackAndWhite()`, `copyEditSettings()`, `pasteEditSettings()`, `resetAllDevelopAdjustments()`, presets/profiles (`getPresetIDs`, `applyPreset`, `getProfileIDs`, `applyProfile`), crop/rotate, masks.
- `revealAdjustedControls(true)` makes Lightroom open the panel of whatever slider is being adjusted.
- `addAdjustmentChangeObserver(param?)` for feedback.
- Check the reference page for exact argument formats before relying on them.

## Plan
1. Device discovery + raw input dump (Step 1).
2. Minimal WebSocket client: register, store GUID, call `appVersionString()` to prove it works.
3. Dump `getParameterNames()` + `getRange()` for each to a JSON file.
4. Mapping config (YAML/JSON): Loupedeck control → Lightroom command, roughly mirroring the default Loupedeck+ Lightroom Classic layout (exposure, contrast, highlights, shadows, whites, blacks, temp, tint, vibrance, saturation, HSL dials, pick/reject, ratings, undo, next/prev photo, before/after).
5. Bridge loop: async (asyncio + `websockets` + MIDI callback), use tracking for dial turns, reconnect if Lightroom restarts.
6. Optionally run it as a launchd agent at login.

## Constraints
- Python 3 preferred. Keep it local only (127.0.0.1).
- Don't modify Lightroom files beyond reading `connections.json`.
- Ask me before installing anything system-wide; a venv is fine.
