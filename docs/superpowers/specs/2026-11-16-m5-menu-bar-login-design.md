# Milestone 5: menu-bar status, alerts, start at login (design)

Date: 2026-11-16 · Status: approved by the user · Part of: [the bridge design](2026-11-16-loupedeck-bridge-design.md)

## Intent
Make the bridge's state visible without opening anything, and tell the user when something goes wrong.
On 2026-11-16 the Loupedeck stopped responding twice with no sign except a line in the log: once the
USB-C dongle dropped, and once the device went quiet while still plugged in. The user wants **an alert**
when something goes wrong and **a status icon** they can always see (their words: "a status tray icon").
The bridge should also **start by itself at login**. This milestone includes the launcher fixes deferred
from milestone 2, so the app is rebuilt only once.

## What the user gets (agreed in conversation)
- **A menu-bar icon** while the bridge runs. It looks normal when all is well, and shows a warning when the
  Loupedeck or Lightroom isn't connected or the keyboard permission is missing.
- **Clicking it opens a menu:**
  ```
  ● Loupedeck: connected
  ● Lightroom: connected
  ● Keyboard keys: allowed
    Five buttons: Ratings
  ─────────────────────
    Open settings…
  ✓ Start at login
  ─────────────────────
    Quit LoupedeckBridge
  ```
- **Alerts** are macOS notifications from LoupedeckBridge:
  - "Loupedeck disconnected", with a hint to check the cable or dongle
  - "Loupedeck is back"
  - "Keyboard keys need permission", once at start, if Accessibility isn't granted
  - **no alert when Lightroom quits** (usually deliberate); the icon and menu show it
- **Start at login** is a checkmark in the menu, **off until ticked**.
- **Quit** stops the bridge cleanly, letting go of any held keys first.
- **A known limit, said plainly:** a Loupedeck that goes quiet while still plugged in can't be detected,
  because the device sends nothing when idle. Only a disconnect is detected.

## Approaches (the user picked A)
- **A. The menu-bar icon lives in LoupedeckBridge.app (chosen).** The small Swift launcher, which already
  starts the Python bridge as a child process, becomes a menu-bar app. The bridge reports status over a
  private pipe; the app draws the icon and menu, posts the alerts, and handles Start at login and Quit.
  - For: native look, and alerts carry the LoupedeckBridge name. No new Python dependencies. The app must
    be rebuilt this milestone anyway for the deferred launcher fixes.
  - Against: more Swift that the Python test suite can't cover, so the menu gets a hands-on check. Mac only;
    Windows (milestone 6) gets its own tray icon.
- B. The icon in Python with a menu-bar library (pystray / PyObjC). Rejected:
  - a large new dependency, against the design's "nothing heavy" rule
  - AppKit must own the main thread, so the bridge's asyncio core would move to a background thread, a
    risky change to the part that works
  - alerts would come from "Python" or "Script Editor"
- C. Alerts only, no icon. Rejected: no always-visible status, which is half of what the user asked for.

## Decided (how it's built)
- **Status pipe.**
  - The launcher creates a pipe and gives its write end to the bridge as file descriptor 3, with
    `LB_STATUS_FD=3` in the environment.
  - The bridge writes one JSON object per line: once at start, then on every change.
    `{"loupedeck": bool, "lightroom": bool, "keys": "allowed"|"missing"|"unavailable", "five_mode": "ratings"|"colours"|"keys", "settings_url": str|null}`
  - Without `LB_STATUS_FD` (e.g. `python -m bridge` in a terminal) nothing is written.
  - A write that fails (the launcher is gone) is ignored, never fatal.
- **Where the status comes from (all in the bridge, one source of truth):**
  - Loupedeck: the MIDI input's `on_open` / `on_close` hooks.
  - Lightroom: the session's connect and disconnect hooks.
  - Keys: the keyboard backend's `is_trusted()`, re-checked every few seconds while missing, so granting the
    permission turns the item green without a restart. `"unavailable"` where there's no keyboard backend.
  - Five buttons: `Dispatcher.on_mode_change`.
- **Alerts.**
  - Sent by the app with the system notification framework. macOS asks once for permission to show
    LoupedeckBridge's notifications.
  - **"Disconnected" alerts only when a Loupedeck that was connected during this run drops** (the user's
    choice). At login, after the app restarts a crashed bridge, or whenever the Loupedeck simply isn't
    there yet, a missing Loupedeck shows only on the icon. The alert is armed by the first connect.
  - It's sent only if the Loupedeck is still gone after about **3 seconds**, so a quick replug or a USB blip
    doesn't alert. "Is back" is sent only after a "disconnected" alert was shown.
  - **After the Mac wakes from sleep**, disconnect alerts wait about **15 seconds**, since USB devices
    re-enumerate on wake. *(Builder check; my call.)*
  - At most one alert per kind per minute, so a flapping cable can't flood the screen.
  - The keyboard alert is sent once per run.
- **Start at login is off until the user ticks it** (the user's choice), in the menu or with
  `tools/bridgectl login on`. Nothing registers itself on first launch.
- **Start at login** uses macOS's own login-item service for the main app (ServiceManagement,
  `SMAppService.mainApp`). It appears in System Settings → General → Login Items as LoupedeckBridge, and the
  checkmark reflects its real state. *(My call: the native, user-visible mechanism, with no plist to manage.
  If it refuses an ad-hoc-signed app, fall back to a per-user LaunchAgent that starts the same app; this is
  checked first, see "To verify".)*
- **Quit** sends the bridge SIGTERM (it releases held keys and closes cleanly), waits up to **5 seconds**
  for it to exit (then SIGKILL), and the app exits with status 0.
- **Keys after a hard death:** if the bridge ends any way other than a clean exit (killed, native crash,
  or the SIGKILL above), the app itself sends key-ups for every key the bridge can hold (Shift, Ctrl, Cmd,
  Alt, Tab, the arrows), using CoreGraphics. It's harmless when nothing was held.
  *(Builder check; my call. FINDINGS suggests a stuck synthetic modifier clears on the next real input,
  but the anti-goal is "never".)*
- **Exit code 3** ("already running", from the single-instance lock) isn't a crash: the app shows nothing
  and quits quietly, since another LoupedeckBridge is already in the menu bar.
- **If the bridge exits unexpectedly** (it crashed, or stopped itself after an error):
  - the icon shows "Bridge stopped" and an alert says so
  - the app restarts it automatically after 5 seconds, at most 3 times in 10 minutes
  - after that it stays stopped, and the menu offers **Restart bridge** and **Open log**
  *(My call: recovery without a babysitter, but no restart loop.)*
- **Deferred launcher fixes (from milestone 2), in the same rebuild:**
  - the bridge's stdout and stderr, and the launcher's own messages, are appended to the bridge log
    (`~/Library/Logs/loupedeck-lr-bridge/bridge.log`), so a crash before logging starts is still recorded
  - Python is started with `-E`, so stray `PYTHON*` environment variables can't change it
  - signal handlers are installed before the child is spawned, so an early SIGTERM can't orphan it
- **Icon:** an SF Symbol drawn as a template image, so it follows light and dark menu bars, with a warning
  variant. No image files.
- `tools/bridgectl` keeps working: `start` opens the app, `stop` sends SIGTERM to the launcher, which passes
  it on. It gains `login on|off|status`, a command-line twin of the menu checkmark.
- **Permissions after the rebuild:** the new app is signed again (ad hoc), so macOS may ask once more for
  Accessibility and Documents access, plus the new notification permission. The README says so.
- The settings page is unchanged: its Lightroom status and five-button chip stay. The original plan's page
  "status strip" is replaced by the menu.

## Goals, non-goals, anti-goals
- **Goals:**
  - the state is visible at a glance
  - a disconnect alerts within seconds
  - the bridge starts at login with no terminal
  - Quit and the crash path never leave a key held
  - no new Python dependencies
- **Non-goals:**
  - Windows tray (milestone 6)
  - detecting a silent-but-plugged-in Loupedeck
  - alerts for Lightroom quitting
  - a full preferences window (the settings page covers settings)
  - GitHub Releases or notarized signing (milestone 7)
- **Anti-goals:**
  - an alert storm from a flapping cable
  - an icon that says "connected" when the bridge has stopped
  - losing the keyboard permission for good, or a stuck key after Quit or a crash
  - two bridges running after login
  - a login item that silently fails

## Constraints
- macOS 27 (the user's Mac). Swift via the command-line tools (`swiftc`, as `tools/build_mac_app.sh` does
  today). No Xcode project. Ad-hoc code signing.
- System frameworks only: AppKit, UserNotifications, ServiceManagement, CoreGraphics (key-ups after a hard death).
- Python stays 3.9-compatible. The Python side of the status pipe is unit-tested; the Swift side gets a
  checklist run by the user.
- The bridge must keep running unchanged under `python -m bridge` (no launcher, no pipe).
- Single instance stays: the existing lock prevents a second bridge.

## To verify first (may change the how, not the what)
1. `SMAppService.mainApp.register()` works for the ad-hoc-signed app built in `build/`. If not, use a
   LaunchAgent.
2. An ad-hoc-signed app can post notifications through UserNotifications (macOS asks once). If not, find
   the nearest native alternative before falling back to anything that shows another app's name.
3. The Accessibility permission still applies to keys sent by the child after the launcher becomes a
   menu-bar app.

## Left to the builder
- The exact SF Symbols and the wording of menu items and alerts, within the agreed menu.
- How often to re-check the keyboard permission while it's missing (a few seconds).
- The Swift code's structure (one file or a few), and how it reads the pipe.
- The `bridgectl login` implementation.
