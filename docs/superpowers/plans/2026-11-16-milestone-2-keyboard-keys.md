# Milestone 2: Keyboard Keys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Loupedeck+'s Shift, Ctrl, Cmd, Alt, Tab and arrow buttons act as real keys (held while held), Before/After and screen mode send Lightroom's shortcuts, and on macOS the bridge runs inside a small LoupedeckBridge.app that holds the Accessibility permission.

**Architecture:** A per-OS keyboard backend (macOS: CoreGraphics events through `ctypes`) sits behind the dispatcher, which tracks held keys and releases them on button release, device disconnect and shutdown. Key actions don't depend on Lightroom being connected. A tiny Swift launcher app spawns the repo's venv Python as a child, so macOS attributes the permission to the app rather than the terminal.

**Tech Stack:** Python ≥3.9 + `ctypes` (CoreGraphics, ApplicationServices), Swift (`swiftc`, ad-hoc `codesign`) for the launcher only, `pytest`.

**Spec:** [docs/superpowers/specs/2026-11-16-loupedeck-bridge-design.md](../specs/2026-11-16-loupedeck-bridge-design.md) (updated 2026-11-16: keys go to the front app; Mac permission via LoupedeckBridge.app). Facts: [docs/FINDINGS.md](../../FINDINGS.md).

## Global Constraints

- Everything from milestone 1 still holds: Python 3.9-compatible, runtime deps exactly `mido`, `python-rtmidi`, `websockets` (no new Python packages; `ctypes` only), 127.0.0.1 only, GUID never logged or committed, live edits only on a test photo.
- **Keys go to whichever app is in front.** No front-app check.
- **Never leave a key held.** Release on button release, device disconnect, and bridge shutdown (Ctrl-C, SIGTERM, crash path).
- **Keys don't need Lightroom:** key and shortcut actions work while Lightroom is closed or disconnected.
- **The Accessibility permission is granted by the user**, never by a script. The bridge only detects, prompts, and explains.
- The launcher is the only non-Python code. Its build output goes in `build/` (gitignored). The Python code is read from the repo at run time, so editing Python never needs a launcher rebuild. Rebuilding the launcher may need the permission granted again (ad-hoc signature).
- Windows keyboard backend: milestone 6. On Windows, key actions log once and do nothing for now.
- Commit after each task (local only; pushing is the user's call).

## Review Focus

1. **Bridge stops while Shift/Cmd is held** (Ctrl-C, `bridgectl stop`, crash): every held key is released. Test: Task 3 `test_held_keys_released_on_shutdown`, Task 4 `test_sigterm_exits_cleanly`.
2. **Device unplugged while a key is held:** it's released. Test: Task 3 `test_held_keys_released_on_device_disconnect`.
3. **Permission not granted:** key buttons don't throw, one clear log line says how to grant it, and dials and buttons keep working. Test: Task 3 `test_keys_without_permission_log_once`.
4. **Two bridges at once** (terminal + app): the second refuses with a clear message, and the first is unaffected. Test: Task 4 `test_second_instance_refuses`.
5. **A lost note-off or a doubled note-on:** no double key-down and no stray key-up. Test: Task 3 `test_press_twice_single_down`, `test_release_without_press_noop`.

---

### Task 1: LoupedeckBridge.app launcher + permission check (user-involved)

**Files:**
- Create: `macos/launcher/main.swift`, `tools/build_mac_app.sh`, `bridge/platform/macos_ax.py`
- Modify: `bridge/__main__.py` (add `--check-permission` and `--midi-port`), `.gitignore` (`build/`), `docs/FINDINGS.md`
- Test: `tests/test_macos_ax.py`

**Interfaces:**
- Produces: `bridge.platform.macos_ax.is_trusted() -> bool` (`AXIsProcessTrusted`) and `request_permission() -> bool` (`AXIsProcessTrustedWithOptions` with `kAXTrustedCheckOptionPrompt=True`, which shows macOS's own prompt).
- Produces: `python -m bridge --check-permission`, which logs `Accessibility permission: granted|missing`, prompts if missing, and exits 0. Also `python -m bridge --midi-port NAME` (default `Loupedeck`).
- Launcher (`main.swift`): reads `LBRepoPath` from its Info.plist and spawns `<repo>/.venv/bin/python -m bridge <own argv[1:]>` with the working directory set to the repo, as a **child process** (`posix_spawn`, not exec, so macOS keeps the app responsible). It forwards SIGTERM/SIGINT/SIGHUP to the child and exits with the child's status.
- `tools/build_mac_app.sh`: builds `build/LoupedeckBridge.app` with `swiftc -O`. Info.plist: `CFBundleIdentifier=io.github.megamattmiller.loupedeckbridge`, `CFBundleName=LoupedeckBridge`, `LSUIElement=true`, `LBRepoPath=<absolute repo path>`. Signed with `codesign --force --sign -`.

- [ ] **Step 1: Write `tests/test_macos_ax.py`** (skipped off macOS): `is_trusted()` returns a `bool`. `request_permission` is exposed but not called in tests, because it would pop a dialog.
- [ ] **Step 2: Run it to see it fail** (module missing).
- [ ] **Step 3: Implement** `macos_ax.py`, the CLI flags, the Swift launcher and the build script. Add `build/` to `.gitignore`.
- [ ] **Step 4: Build and verify.** Run `tools/build_mac_app.sh`. Expected: `codesign -dv build/LoupedeckBridge.app` shows `Identifier=io.github.megamattmiller.loupedeckbridge`.
- [ ] **Step 5: Permission check with the user.** Run `open build/LoupedeckBridge.app --args --check-permission`. macOS should prompt for **LoupedeckBridge** (not Claude). After the user grants it, run it again: the log shows `granted`. Also confirm that running `python -m bridge --check-permission` from the terminal still shows `missing`, which proves the grant is scoped to the app. Record both in FINDINGS.
- [ ] **Step 6: Commit.** "Add LoupedeckBridge.app launcher and permission check"

---

### Task 2: macOS keyboard backend

**Files:**
- Create: `bridge/platform/macos_keys.py`
- Modify: `bridge/platform/macos.py`, `bridge/platform/windows.py` (add `keyboard()`)
- Test: `tests/test_macos_keys.py`

**Interfaces:**
- Produces: `MacKeyboard(post: Callable[[int, bool, int, bool], None] = <CoreGraphics poster>, trusted: Callable[[], bool] = macos_ax.is_trusted)` with:
  - `key_down(name)`, `key_up(name)`, `key_repeat(name)` (an auto-repeat key-down)
  - `tap(keys: List[str])`
  - `is_trusted() -> bool`
  - Arguments to `post`: `(keycode, down, flags, autorepeat)`.
- Produces: `bridge.platform.macos.keyboard() -> MacKeyboard` and `bridge.platform.windows.keyboard() -> None` (milestone 6).
- Key names: modifiers `shift ctrl alt cmd`, plus `tab left right up down space return escape delete`, `f1`–`f12`, `a`–`z`, `0`–`9`, and the characters `` \ / , . ; ' [ ] - = ` ``. Keycodes are the `kVK_*` values from Carbon's `Events.h`, for example shift 56, ctrl 59, alt 58, cmd 55, tab 48, left 123, right 124, down 125, up 126, `\` 42, `f` 3, `e` 14. An unknown name raises `ValueError`.
- Flags: shift `0x20000`, ctrl `0x40000`, alt `0x80000`, cmd `0x100000`. Every posted event carries the flags of the modifiers currently held. Modifier keys are posted as `kCGEventFlagsChanged` events, other keys as key down/up. Posting uses `CGEventCreateKeyboardEvent` → `CGEventSetType`/`CGEventSetFlags`/`CGEventSetIntegerValueField(kCGKeyboardEventAutorepeat=8)` → `CGEventPost(kCGHIDEventTap)` → `CFRelease`.
- `tap(keys)`: the modifiers in `keys` go down in order, then the last key goes down and up, then those modifiers go up in reverse. Modifiers the user is already holding stay down.

- [ ] **Step 1: Write failing tests** (recording `post`, all values literal):
  - `test_modifier_down_up_flags`: `key_down("shift")` → `(56, True, 0x20000, False)`; `key_up("shift")` → `(56, False, 0, False)`.
  - `test_key_carries_held_modifiers`: `cmd` down, then `left` down → `(123, True, 0x100000, False)`.
  - `test_tap_shortcut_order`: `tap(["cmd","shift","e"])` gives exactly cmd↓ (cmd), shift↓ (cmd|shift), e↓, e↑ (cmd|shift), shift↑ (cmd), cmd↑ (0).
  - `test_tap_backslash`: `tap(["\\"])` → `(42, True, 0, False), (42, False, 0, False)`.
  - `test_tap_keeps_users_held_modifier`: `alt` down, then `tap(["f"])` → the f events carry alt, and alt is still held afterwards (no alt↑).
  - `test_key_repeat_sets_autorepeat`: `key_repeat("right")` → `(124, True, 0, True)`.
  - `test_unknown_key_raises`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** `macos_keys.py` and the `keyboard()` functions.
- [ ] **Step 4: Run the tests to see them pass.**
- [ ] **Step 5: Commit.** "Add macOS keyboard backend"

---

### Task 3: Key and shortcut actions

**Files:**
- Modify: `bridge/actions.py`, `bridge/midi_input.py` (add the `on_close` hook), `bridge/app.py` (wire the keyboard; release keys on device close and shutdown), `config/default_mapping.json`
- Test: `tests/test_actions.py`, `tests/test_midi_input.py`, `tests/test_mapping.py`, `tests/test_app.py`

**Interfaces:**
- Consumes: the keyboard object from Task 2 (`key_down/key_up/key_repeat/tap/is_trusted`, or `None`).
- Produces:
  - `Dispatcher(mapping, session, dials, keyboard=None, repeat_delay=0.4, repeat_interval=0.05)`
  - `Dispatcher.release_all_keys() -> None`
  - `MidiInput.on_close: Optional[Callable[[], None]]`, called when the port closes (unplug or stream closed)
  - `app.build(..., keyboard=None)`, where `app.run` passes `platform.current().keyboard()`
- Rules:
  - `key` and `shortcut` presses and releases are handled **before** the Lightroom-connected check.
  - `key` press:
    - permission missing → one warning ("Keyboard keys need Accessibility permission: System Settings → Privacy & Security → Accessibility → LoupedeckBridge"), then nothing
    - control already held → nothing
    - otherwise `key_down`
    - non-modifier keys (`tab` and the arrows) also start a repeat: after `repeat_delay`, `key_repeat` every `repeat_interval` until release. This is a design call: synthetic key-downs don't auto-repeat on macOS. Task 5 confirms it.
  - `Release` of a held control → cancel its repeat, then `key_up`.
  - `shortcut` press → `tap(action["mac"])` on macOS, `tap(action["windows"])` on Windows.
  - A keyboard of `None` (Windows for now) → one info log, then nothing.
  - An unknown key name in a `key`/`shortcut` action (`ValueError` from the backend) → a warning naming the control, nothing sent, never raised.
- Default layout: `before_after` → `{"type":"shortcut","mac":["\\"],"windows":["\\"]}` (Show Original); `screen_mode` → `{"type":"shortcut","mac":["f"],"windows":["f"]}` (Full Screen Loupe).

- [ ] **Step 1: Write failing tests:**
  - `test_key_press_release_holds_key`
  - `test_press_twice_single_down`
  - `test_release_without_press_noop`
  - `test_shortcut_taps_os_keys` (Before/After → `tap(["\\"])` on darwin)
  - `test_keys_without_permission_log_once`
  - `test_keys_work_while_lightroom_disconnected`
  - `test_arrow_repeats_while_held` (`repeat_delay=0.02`, `repeat_interval=0.01`: at least 2 `key_repeat("right")` before release, none after)
  - `test_modifier_does_not_repeat`
  - `test_release_all_keys`
  - `test_held_keys_released_on_device_disconnect` (the app wiring: `on_close` → `release_all_keys`)
  - `test_held_keys_released_on_shutdown` (`App.run` cancelled → `key_up` for held keys)
  - `test_on_close_called_on_unplug` (MIDI)
  - `test_unknown_shortcut_key_logged` (a shortcut `["hyper"]` → warning, no raise)
  - a mapping spot check for `before_after` and `screen_mode`
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole suite.**
- [ ] **Step 5: Commit.** "Send real keys and shortcuts from the Loupedeck"

---

### Task 4: Run as an app: clean stop, one instance, bridgectl

**Files:**
- Create: `bridge/instance.py`, `tools/bridgectl`
- Modify: `bridge/__main__.py` (SIGTERM/SIGHUP cancel the main task, so cleanup runs and "bridge stopped" is logged), `bridge/app.py` (take the instance lock first), `README.md` (a "Run as an app (macOS)" section: build, grant the permission, start/stop/status/logs)
- Test: `tests/test_instance.py`, `tests/test_main.py`

**Interfaces:**
- Produces: `bridge.instance.acquire(path: Path) -> Optional[IO]`. It returns an open, locked file (an exclusive, non-blocking `fcntl.flock`; `msvcrt.locking` on Windows), or `None` if another bridge holds the lock. The lock lives at `state_dir()/bridge.lock`. When it's held, `python -m bridge` logs "Another LoupedeckBridge is already running; not starting a second one" and exits with code 3.
- `tools/bridgectl {build|start|stop|status|logs}`:
  - `build` runs the build script
  - `start` runs `open -g build/LoupedeckBridge.app`
  - `stop` runs `pkill -TERM -f 'LoupedeckBridge.app/Contents/MacOS/LoupedeckBridge'`
  - `status` uses `pgrep`
  - `logs` runs `tail -f ~/Library/Logs/loupedeck-lr-bridge/bridge.log`

- [ ] **Step 1: Write failing tests:**
  - `test_second_instance_refuses`: two `acquire()` calls on the same path → the second returns `None`; after the first file is closed, `acquire` succeeds again.
  - `test_sigterm_exits_cleanly` (`tests/test_main.py`, macOS): start `python -m bridge --midi-port NoSuchDevice` as a subprocess with `HOME` set to a temp dir. That temp `HOME` contains `Library/Application Support/Adobe/Lightroom CC/Connections/connections.json` pointing at an unused port, so the user's real Lightroom is never contacted. Send SIGTERM. Expected: exit code 0 within 3 s, and `bridge.log` contains "bridge stopped".
  - `test_second_process_exits_3`: two such subprocesses with the same `HOME` → the second exits with code 3.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole suite.**
- [ ] **Step 5: Commit.** "Run as an app: clean SIGTERM stop, single instance, bridgectl"

---

### Task 5: Live check with the user

- [ ] **Step 1:** Stop any terminal bridge. Run `tools/bridgectl build` and `tools/bridgectl start`. The permission is granted from Task 1, so expect no prompt; if the launcher was rebuilt, grant it again.
- [ ] **Step 2:** Walk through with the user:
  - hold Loupedeck-Alt and drag a slider with the mouse (Lightroom's clipping view should appear)
  - Shift/Cmd held while clicking photos in the grid (multi-select)
  - Tab
  - a single arrow press, and an arrow **held** (repeats)
  - Before/After (`\` shows the original)
  - screen mode (`f` full screen)
  - a key press while another app is in front (goes to that app)
  - unplugging while holding Shift (no stuck Shift)
  - `bridgectl stop` while holding Cmd (no stuck Cmd)
  - dials and buttons still working inside the app
- [ ] **Step 3:** Record the results in FINDINGS and fix any issue test-first. Commit.
- [ ] **Step 4:** Run the final whole-branch review (a fresh reviewer), then a fix pass, then finish the branch.
