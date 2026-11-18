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

## Milestone 2 live check (keyboard keys, 2026-11-16)
All passed after two fixes, running as LoupedeckBridge.app:
- Alt-drag shows the clipping view. Shift/Cmd-click selects in the grid. Loupedeck Shift + a real key types uppercase.
- Arrows work, and repeat when held. **Tab shows/hides the right panel**, the same as the real keyboard's Tab (not "keyboard focus", as the shortcut file suggested).
- Before/After (`\`) shows the original, and screen mode (`f`) goes full screen. Both also go to whichever app is in front.
- No stuck keys after unplugging while holding Shift, or `bridgectl stop` while holding Cmd.
- Dials and buttons all work from the app. No extra Input Monitoring prompt appeared.

**Fix 1: synthetic modifiers vanish under real input.** Every real mouse or keyboard event carries the *physical* keyboard's modifier flags, and macOS resets its modifier state to match. Recording `CGEventSourceFlagsState` showed a Loupedeck Alt held in both the session and HID state, then dropped from both 1.1 s in, as soon as the mouse moved. **Fixed** with an active event tap (`bridge/platform/macos_tap.py`) that adds the held Loupedeck modifiers to real mouse and keyboard events.

**Fix 2: stale personal mapping.** A `mapping.json` created from an older default never picked up new defaults (Before/After and screen mode stayed "none"). **Fixed:** `mapping.base.json` records the default a mapping started from. Unedited mappings follow new defaults; edited ones are kept, with a notice.

**After the review fixes** (tap enabled only while a Loupedeck modifier is held, real modifiers
joining Loupedeck keys), a live re-check passed:
- Alt-drag and Shift-click still work.
- Real Shift + Loupedeck → selects text.
- `bridgectl stop` mid-dial-spin stops promptly.

**Lightroom blocks every client while an Allow dialog is open:** WebSocket handshakes time out until it's answered. A stray test bridge triggered one; the tests now pin `--lightroom-port` and kill every process they start.

## Milestone 3 live check (settings page, 2026-11-16)
All passed with the real bridge, Lightroom and Loupedeck:
- The custom mode button opens the page.
- Presets assigned to P-slots apply when pressed, and their slots flash on the page.
- Clearing a slot works, and changes show live in two tabs.
- Quitting Lightroom shows "Lightroom isn't connected". The list comes back after reopening.
- An unedited mapping picked up the new `custom_mode → open_settings` default by itself (per-control following).

**Lightroom lists preset names slowly:** `getPresetIDs` returns 1,572 ids in ~64 ms, but each
`getPresetName` takes ~26 ms (~17 ms when 50 are in flight). So the full list takes ~27 s; the design
had estimated 1–2 s. **Fixed:**
- Names are cached in `preset_names.json` (state dir), so only new presets are looked up and later loads are instant.
- The first load shows progress, and "Refresh list" re-reads every name (a renamed preset keeps its id).

**Re-check after the review fixes (same day), all passed:**
- Restarting the bridge with the page open: the page reloaded itself (new token) and assigning still worked.
- Quitting Lightroom turned the status amber ("waiting for Lightroom"). Reopening it turned it green;
  the bridge reconnected ~7 s after Lightroom launched.
- "Refresh list" in one of two tabs showed progress in both. Turning a dial during the ~27 s load felt
  normal (by feel; not measured).
- P1–P3 applied their presets.

**Dead controls with a healthy bridge = the device is gone from USB.** The Loupedeck+ (on a USB-C to
USB-A dongle) dropped off USB; the page and Lightroom connection looked fine, but the log said
"Loupedeck disconnected; waiting for it to come back" and macOS listed no MIDI inputs. Replugging
the dongle fixed it; the bridge reopened the device by itself. A visible device status is for milestone 5.

## Fn button (milestone 4 capture, 2026-11-16)
With the bridge paused, holding Fn and pressing L1, C3 and C1, then the same without Fn, then turning
and clicking Exposure with and without Fn: **every control sent exactly the same MIDI either way**.
Fn itself sends note 110 on when pressed and off when released. So Fn layers are entirely the
bridge's job: it tracks Fn and picks each press's layer when the press starts.

## --/Col and the five buttons (capture, 2026-11-16)
With the bridge paused: the five buttons next to --/Col (Shift, Ctrl, Cmd, Alt, Tab; notes 66–70) sent
**the same notes before --/Col, after it, after pressing it again, and after Fn + --/Col**. --/Col itself
is note 65, and **no lights change**. So the Ratings / Colours / Keys modes are entirely the bridge's job.

**The device can go quiet while still on USB.** During this check it stopped sending any MIDI (not even
C3) while macOS still listed it and its MIDI interface. Replugging the dongle fixed it. Fn + --/Col
was ruled out as the cause: a controlled capture with it pressed last kept sending. The USB descriptors
also show a CDC serial interface besides MIDI (Loupedeck's own software may use it); the bridge
doesn't use it.

## Milestone 4 live check (remapper and Fn layer, 2026-11-16)
**Commands:** `tools/lr_check_commands.py` sent all 72 checkable commands in `config/commands.json`
to Lightroom on a test photo: **all accepted**. 8 were left for checking by hand: the dialogs (Export,
Preferences, the merges, Copy settings…), Edit in Photoshop, and Duplicate photo. **Not yet checked by hand:** Duplicate photo, Edit in Photoshop, Preferences, the three merge dialogs and Copy settings (choose…); only the Export dialog is known to work (milestone 1).

**With the user, all passed:**
- The mapping upgraded by itself: P1–P3 presets kept, dial clicks became "reset this dial's slider", Export gained Fn + Export, no warnings.
- Presets and dial-click resets work as before.
- Fn actions on L1–L3 and C1–C6, set on the page, work with Fn held and leave the normal actions alone.
- Letting go of Fn before the button gives exactly one Fn action.
- Using a control on the device selects it on the page; Fn + C3 selects C3's Fn cell.
- Fn + Export exports with the previous settings; plain Export still opens the dialog.
- clr/bw keeps the lights and the photo in step, with and without Fn.
- Reset and Restore default layout keep the P1–P3 presets.
- **--/Col modes (Task 7), all passed:**
  - starts in Ratings (★ to ★★★★★)
  - --/Col gives Colours (red to purple) and back, with the page's chip following
  - Fn + --/Col gives Keys (Tab toggles the side panels)
  - a Shift held through a mode switch is let go properly
  - from Keys, --/Col returns to the last of Ratings/Colours
  - a per-mode remap on the page works

## Milestone 5 platform checks (2026-11-16)
A throwaway, ad-hoc-signed app (bundle id `…loupedeckbridge.spike`) answered the design's two open questions:
- **Login item:** `SMAppService.mainApp.register()` works for an ad-hoc-signed app. The status went
  notFound → enabled, and `unregister()` returned it to notRegistered. The plan's main route stands; no
  LaunchAgent fallback is needed.
- **Notifications:** they work from the repo's `build/` folder (authorized, posted). From a temporary
  folder (`/private/tmp`), UserNotifications refused at once with "Notifications are not allowed for this
  application" (UNErrorDomain 1), without asking. The real app lives in `build/`, so alerts carry the
  LoupedeckBridge name as designed. Don't run the app from a temp folder.

## Milestone 5 live check (menu-bar app, 2026-11-16)
**Two bugs found on the first real run, both fixed with a test first:**
- **The status pipe was dead** ("status reporting off: [Errno 9] Bad file descriptor"). The app's
  posix_spawn file actions put the pipe's write end on fd 3, *then* closed the read end, which was also fd 3.
  Now the read end is closed first (`status_pipe_reaches_the_app`).
- **Every log line appeared twice.** The app routes the bridge's stderr into bridge.log, and the bridge also
  logged to stderr. The console copy is now skipped when stderr is the log file.

**Permissions after a rebuild:** each rebuild is signed ad hoc, so macOS treats it as a new app.
- Accessibility had to be removed and re-added in System Settings.
- Notifications were refused at once, with no prompt, until "Allow notifications" was turned back on for
  LoupedeckBridge in System Settings → Notifications.
- The first build after the change prompted for both, plus Documents access.
- A fixed signing identity avoids this: milestone 6's releases are all signed with one key.

**With the user, all passed:**
1. Unplugging the dongle: "disconnected" after about 3 s and a warning icon; replugging: "is back".
2. A quick replug: no alert.
3. Lightroom quitting: a warning icon, no alert.
4. --/Col and Fn + --/Col: the menu's "Five buttons" follows.
5. Open settings… opens the page.
6. Start at login appears in Login Items and can be unticked.
7. The bridge killed with SIGKILL (exit 137): an alert, restarted after exactly 5 s, everything reconnected.
8. Quit: the icon goes away, and the bridge stops cleanly.
9. Starting with the Loupedeck unplugged: no alert, a warning icon; plugging it in: a normal icon, no alert.

Also checked:
- a second copy of the app quits quietly ("already running")
- `--check-permission` reports and exits without an icon
- granting Accessibility while it runs turns the menu's "Keyboard keys" to allowed within seconds

**Re-check after the review fixes (2026-11-17), all passed:**
- A normal stop (SIGTERM to the bridge, exit 0): no "disconnected" alert. The menu said "stopped", and
  "Restart bridge" brought it back.
- A hard kill (exit 137), then "Restart bridge" clicked during the 5 s wait: exactly one new bridge, the
  automatic restart was cancelled, and the app stayed up.
- Notifications survived this rebuild; Accessibility again had to be removed and re-added.

## Milestone 6: releases, signing and updates (2026-11-17)
**Signatures:**
- codesign's requirement `certificate leaf = H"…"` compares a **SHA-1** hash. So both the installer and the
  app compare the **SHA-256 of the signing certificate (DER)** with the pinned value, after a strict
  signature check. In the app, the Security framework's first certificate (`SecCodeCopySigningInformation`)
  is the same one `codesign -d --extract-certificates` writes as `…0`; a check on Calculator.app proves it.
- A **self-signed** identity shows as "0 valid identities found" (`CSSMERR_TP_NOT_TRUSTED`) in
  `security find-identity`, but codesign signs with it, and `codesign --verify --strict` passes.
- A `.p12` from macOS's LibreSSL with `-keypbe PBE-SHA1-3DES -certpbe PBE-SHA1-3DES -macalg sha1` imports
  into a temporary keychain on GitHub's `macos-15` (Apple Silicon) runner. An ad hoc signature has no
  certificate at all.
- Signed Mach-O files inside `Contents/Resources` (the bundled Python) pass strict verification, ad hoc and
  self-signed.

**The bundled Python** (python-build-standalone CPython 3.12.16, `install_only`):
- The whole suite passes with it (310 tests, locally and on GitHub), with the bundle's own packages.
  CoreMIDI opens from it. python-rtmidi 1.5.8 has a cp312 arm64 wheel; mido needs `packaging` too.
- Python would write `__pycache__` into the app, which breaks its signature. So the build precompiles
  everything with `--invalidation-mode unchecked-hash`, and the app runs Python with `-B`. Running the suite
  against a built app leaves its signature valid.
- python-build-standalone isn't a framework build, so it reads the user's `~/.local/lib/python3.12/site-packages`.
  A `.pth` file planted there ran inside the app (which holds the Accessibility permission). The app now runs
  Python with `-E -s -B`; with `-s` the planted file doesn't run.
- Size: a 76 MB app and a 30 MB zip, after removing tests, Tcl/Tk, headers and static libraries. Most of
  CPython's extension modules are built in; only 6 Mach-O files need signing.

**GitHub Actions:**
- The newest Python 3.9 GitHub has for Apple Silicon runners is 3.9.13.
- `upload-artifact` keeps neither symlinks nor permissions, so the tested build travels as a `ditto` zip.
- CI's signing rehearsal (a throwaway identity: sign, check, package, `install.sh`) passed on the first
  push.

**The final review (before the first release) found two holes in the release workflow,** both fixed:
test tools from PyPI weren't pinned and ran before the tested build was saved, and the build's own binary
ran while the signing key was usable. Now the build is saved first, the test tools are pinned by hash, the
publish job checks it signs the saved bytes, and the key exists during the signing step only
(`tests/test_release_workflow.py`).

**Found by a live run of `install.sh`:** it refused an ad hoc build correctly but silently (`pipefail` ended
the script when there was no certificate to hash). It now says why (a test covers it).

**The first release, v0.5.0 (2026-11-17):** tagged with `tools/release.sh`, built and tested on GitHub,
signed after the user's approval, and published (a 28.7 MB zip). Installed on the user's Mac with
`tools/bridgectl install` (`install.sh`):
- `codesign --verify --strict` and the app's own check pass on the user's Mac (TeamIdentifier "not set", as
  expected for a self-signed key), and the app has no quarantine flag, so macOS showed no "downloaded from the
  internet" step.
- It runs its bundled Python (`…/Resources/python/bin/python3 -E -s -B -m bridge`); the Loupedeck and
  Lightroom connected, and keyboard keys work after the first-run permission grants.
- **Lightroom accepted the saved client ID with no new Allow dialog** (the registration version stays "0.1").
- The first update check ran 32 s after launch against GitHub's real answer: "up to date (v0.5.0)". A relaunch
  two minutes later didn't check again (once a day).
- Before installing, the old ad hoc `build/LoupedeckBridge.app` (the same bundle id) had its Start at login
  turned off and went to the Trash; the dev app is rebuilt later as "LoupedeckBridge Dev".

**The first menu update, v0.5.0 → v0.5.1 (2026-11-17):** v0.5.1 (the review's deferred fixes) was released
the same way, then installed from v0.5.0's menu: "Check for updates now" found it, Install downloaded and
checked it in about 3 s, the bridge stopped cleanly, v0.5.0 moved itself to the Trash, and v0.5.1 started in
its place.
- **Moving the running app to the Trash and starting the new copy works from inside the app**, with no
  "prevented from modifying apps" prompt (the self-signed key has no Team ID).
- **Accessibility and notifications survived the update:** keyboard keys work in v0.5.1 with no new grant,
  because both versions are signed with the same key at the same path.
- The new bridge had the Loupedeck and Lightroom connected within half a second, with no Allow dialog.
- The saved "update available" entry was cleared on the new version's first start, and the Trash copy is
  recorded for "Go back to the previous version".

All five of the design's "To verify first" items are confirmed.

## Milestone 7: Windows (2026-11-17)
Checked on the user's Windows PC: Windows 11 (10.0.26200), x64.

**The PC:**
- **Lightroom 10.0**, the same build as the Mac (`20261029-1525-df1be3b`), at `C:\Program Files\Adobe\Adobe
  Lightroom CC\lightroom.exe`.
  - `%LOCALAPPDATA%\Adobe\Lightroom CC\Connections\connections.json` = `{"port":7682}`.
  - It listens on **127.0.0.1:7682 only**; the Mac listened on every interface.
- **The Loupedeck+:** USB `VID_2EC2&PID_0002`, with a MIDI interface ("Loupedeck+") and a serial port (COM11), as on
  the Mac.
  - WinMM names the input **`Loupedeck+ 0`** and the output `Loupedeck+ 1`: Windows adds a number. The bridge's
    "Loupedeck" hint still matches.

**Text encoding:**
- Python's default text encoding on Windows is cp1252, which misread the ★ in `config/commands.json`. The settings
  page's `app.js` answered 500.
- Every text read and write now names UTF-8, and JSON reads accept Notepad's BOM. `tests/test_text_io.py` keeps it
  that way.

**First live check** (the repo's `python -m bridge --debug`, through a helper holding the tray app's control pipe):
- Registering saved a new client ID within 3 s. Later runs reconnected with it, with no Allow dialog, in under
  10 ms.
- **With the user, all worked:**
  - dials and dial-click resets, the colour dials, C1/C2, undo/redo, copy/paste, Export and Fn + Export, clr/bw
  - the --/Col modes
  - the arrows (repeating) and Tab; `\` (Before/After) and `f` (screen mode), the same shortcuts as on the Mac
- **The five buttons send keys only in Keys mode** (Fn + --/Col), as designed. Holding Fn while pressing them gives
  their Fn action, which by default is the rating or colour.
- **`SendInput` modifiers combine with the real mouse and keyboard with no help.** Windows keeps one key state for
  all input, so there's no equivalent of the Mac's modifier tap. All of these worked:
  - Loupedeck Shift-click and Ctrl-click in the grid
  - Alt-drag on a slider (the clipping view)
  - Cmd + Z, which undoes (Cmd sends Ctrl)
  - real Shift + a Loupedeck arrow
  - Alt pressed and released alone did nothing visible (its release is masked)
- **Unplugging stopped the bridge** (bug, fixed test-first):
  - RtMidi's WinMM `closePort` fails in `midiInUnprepareHeader` once the device has gone, and raised
    `rtmidi.SystemError`.
  - Its source shows that on this path it has already closed the handle and freed the buffers, yet leaves the port
    marked open. Destroying the port later (mido's `__del__`, or rtmidi's destructor) would free them a second time.
  - The bridge now carries on, and keeps that one port alive and marked closed. After the fix, an unplug and replug
    reconnected (8 s, mostly the user's wait), and the dials worked.
- **Stopping through the control pipe while the Loupedeck held Shift:** exit 0, "bridge stopped", and Shift was let
  go (letters typed afterwards were lowercase).
- **MIDI inputs are shared on this PC.** While another program held `Loupedeck+ 0` open, the bridge opened it too,
  with no error (Windows 11's multi-client MIDI). So the "in use by another program" state can't happen here; it's
  for PCs where an input still opens for one program at a time. The flip side: the Loupedeck or Logi software
  running at the same time would also act on every control, so it must still be quit.

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
