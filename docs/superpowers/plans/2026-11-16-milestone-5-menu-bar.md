# Milestone 5: Menu-bar Status, Alerts, Start at Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LoupedeckBridge.app becomes a menu-bar app: it shows the bridge's status, alerts when a working Loupedeck drops, starts at login when ticked, restarts a crashed bridge, and carries the launcher fixes deferred from milestone 2.

**Architecture:** The Python bridge writes one JSON status line per change to a pipe the app passes as fd 3 (`LB_STATUS_FD`). The Swift app (AppKit, UserNotifications, ServiceManagement, CoreGraphics) reads the lines, draws the icon and menu, and decides alerts and restarts with two pure policy types. The policies have a Swift test harness that pytest compiles and runs.

**Tech Stack:** Python ≥3.9 (asyncio), Swift via `swiftc` (no Xcode project), system frameworks only, `pytest`.

**Spec:** [docs/superpowers/specs/2026-11-16-m5-menu-bar-login-design.md](../specs/2026-11-16-m5-menu-bar-login-design.md), within [the bridge design](../specs/2026-11-16-loupedeck-bridge-design.md).

## Global Constraints

- Milestones 1–4 still hold: Python 3.9-compatible, no new Python dependencies, 127.0.0.1 only, GUID never logged, single instance (exit code 3 = already running).
- System frameworks only in Swift: AppKit, UserNotifications, ServiceManagement, CoreGraphics. No image files (SF Symbols as template images).
- The bridge must run unchanged under `python -m bridge` (no launcher, no pipe, no status output).
- A failed status write is never fatal.
- Alerts:
  - "Loupedeck disconnected" only when a Loupedeck connected during this run drops, still gone after 3 s, not within 15 s of a wake, at most one per kind per minute
  - "Loupedeck is back" only after a "disconnected" was shown
  - "Keyboard keys need permission" once per run
  - none for Lightroom
- Start at login is off until ticked (menu or `tools/bridgectl login on`). Nothing registers itself.
- Quit: SIGTERM, wait up to 5 s, then SIGKILL; exit 0. After any non-clean bridge exit, the app sends key-ups for Shift, Ctrl, Cmd, Alt, Tab and the four arrows.
- Restarts: 5 s after an unexpected exit, at most 3 in 10 minutes, then stay stopped with "Restart bridge" and "Open log".
- Launcher fixes:
  - the bridge's stdout/stderr and the launcher's own messages are appended to `~/Library/Logs/loupedeck-lr-bridge/bridge.log`
  - Python runs with `-E`
  - signal handlers are installed before spawning
- Rebuilding the app or registering a login item changes the user's system. Ask before each first time (Task 1, Task 5), and test on the user's Mac only with their go-ahead.
- Commit after each task (local only).

## Review Focus

1. **Login (or a bridge restart) without the Loupedeck plugged in:** no alert, the icon warns, plugging it in clears the warning and still doesn't alert. Tests: Task 3 `never_connected_never_alerts`, `restart_disarms`.
2. **A USB blip, a quick replug, or waking from sleep:** no alert. A cable that keeps flapping alerts at most once a minute. Tests: Task 3 `quick_replug_is_silent`, `wake_grace`, `flapping_is_rate_limited`.
3. **The pipe goes away** (the app is force-quit, or the bridge runs in a terminal): the bridge keeps working and logs nothing alarming. Test: Task 2 `test_write_failure_disables_quietly`, `test_no_fd_means_no_output`.
4. **The keyboard permission is granted while the bridge runs:** the menu shows "allowed" within seconds, with no restart. Test: Task 2 `test_keys_polled_until_allowed`.
5. **A crash loop:** at most 3 restarts in 10 minutes, then it stays stopped and says so. Exit code 3 is never treated as a crash. Test: Task 3 `restart_budget`, `already_running_is_not_a_crash`.

---

### Task 1: Verify the platform assumptions (throwaway app)

**Files:**
- Create (scratchpad only, never committed): a throwaway `LBSpike.app`, bundle id `io.github.megamattmiller.loupedeckbridge.spike`, ad-hoc signed like the real app.
- Modify: `docs/FINDINGS.md` (the results)

**Interfaces:**
- Produces: a FINDINGS section, "Milestone 5 platform checks", answering spec "To verify first" items 1–2:
  - item 1: does `SMAppService.mainApp.register()` succeed for an ad-hoc app, and does `status` read back `.enabled`?
  - item 2: does UserNotifications ask once and then show a notification titled with the app's name?
  - Item 3 (Accessibility in the menu-bar app) is checked in Task 5.

- [ ] **Step 1: Ask the user's go-ahead.** The spike briefly registers a login item and asks for notification permission, both for the throwaway app; both are undone at the end.
- [ ] **Step 2: Build and run the spike** in the scratchpad. It should:
  - request notification authorization and post "LoupedeckBridge spike: hello"
  - call `SMAppService.mainApp.register()`, print `status`, then `unregister()` and print `status` again
  - print each result to stdout
- [ ] **Step 3: Record the results** in FINDINGS, with the user confirming what they saw.
  - If `register()` fails: the plan's Task 4 uses a per-user LaunchAgent (`~/Library/LaunchAgents/io.github.megamattmiller.loupedeckbridge.plist`, `RunAtLoad`, `ProgramArguments` = the app binary) instead. Ledger it as a ruling.
  - If notifications are refused for an ad-hoc app: stop and ask the user. The spec forbids alerts that carry another app's name.
- [ ] **Step 4: Clean up:** unregister, delete the spike app, and ask the user to remove its notification entry if macOS kept one.
- [ ] **Step 5: Commit** `docs/FINDINGS.md` ("Milestone 5: platform checks").

---

### Task 2: Bridge status reporter

**Files:**
- Create: `bridge/status.py`
- Modify: `bridge/app.py` (`App`, `build`, `run`)
- Test: `tests/test_status.py`, `tests/test_app.py`

**Interfaces:**
- Produces in `bridge/status.py`:
  - `STATUS_FD_ENV = "LB_STATUS_FD"`
  - `class StatusReporter`
    - `__init__(self, write: Optional[Callable[[str], None]], keyboard=None)`; `write(None)` disables it.
    - `state: dict`: `{"loupedeck": False, "lightroom": False, "keys": "allowed"|"missing"|"unavailable", "five_mode": "ratings", "settings_url": None}`. `keys` comes from `keyboard` (`None` → `"unavailable"`, else `is_trusted()`).
    - `@classmethod from_env(cls, environ=os.environ, keyboard=None) -> "StatusReporter"`: opens the fd in `LB_STATUS_FD` (`os.fdopen(fd, "w", buffering=1)`); missing or invalid → disabled.
    - `set(self, **changes) -> None`: updates `state` and writes `json.dumps(state) + "\n"` only if something changed.
    - `async run(self, interval: float = 3.0) -> None`: writes the state once, then re-checks `keys` every `interval` while it's `"missing"`. Never raises.
    - A write raising `OSError` (e.g. `BrokenPipeError`) disables the reporter, logged once at info.
  - `build(..., status: Optional[StatusReporter] = None)` wires (all keep their current behaviour too):
    - `midi.on_open` → `loupedeck=True`
    - `midi.on_close` → `loupedeck=False`
    - session connect → `lightroom=True`; session disconnect → `lightroom=False`
    - `dispatcher.on_mode_change` → `five_mode=dispatcher.five_mode`
    - `settings_url` is set at build time
  - `App(..., status=None)`: `run()` adds `status.run()` as a task.
  - `run()` creates `StatusReporter.from_env(keyboard=keyboard)`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_status.py`:

```python
def test_writes_only_changes():
    lines = []
    s = StatusReporter(lines.append)
    s.set(loupedeck=True)
    s.set(loupedeck=True)
    s.set(lightroom=True)
    assert [json.loads(l)["loupedeck"] for l in lines] == [True, True]
    assert json.loads(lines[-1]) == {**s.state, "loupedeck": True, "lightroom": True}
```

Plus, with assertions named:
- `test_no_fd_means_no_output` (Review Focus 3): `StatusReporter.from_env(environ={})` and `environ={"LB_STATUS_FD": "nope"}` → `set(...)` writes nothing and raises nothing.
- `test_from_env_writes_lines_to_the_fd`: `r, w = os.pipe()`, `from_env({"LB_STATUS_FD": str(w)})`, `set(loupedeck=True)` → `os.read(r, …)` decodes to one JSON line ending in `"\n"`.
- `test_write_failure_disables_quietly` (Review Focus 3): close the read end, then `set(...)` twice → no exception; the reporter is disabled after the first failure; one info record.
- `test_keys_polled_until_allowed` (Review Focus 4): a fake keyboard with `trusted=False`; `run(interval=0.01)` in a task; flip to `True` → within 0.2 s a line with `"keys": "allowed"`, and polling stops (no further lines).
- `test_keys_unavailable_without_keyboard`: `StatusReporter(lines.append, keyboard=None).state["keys"] == "unavailable"`.

In `tests/test_app.py`, `test_status_wired`: `build(..., settings_port=7699, status=StatusReporter(lines.append))` with a midi stub that has `on_open`/`on_close` →
- `midi.on_open()` gives `loupedeck` true, and `midi.on_close()` false
- `session.on_disconnect()` gives `lightroom` false, and `await session.on_connect()` true
- `dispatcher.on_mode_change()` after `col` gives `five_mode` `"colours"`
- `settings_url` is `"http://127.0.0.1:7699/"`
- held keys are still released on `on_close` (the existing test keeps passing)

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_status.py tests/test_app.py -q`
Expected: FAIL (`ModuleNotFoundError: bridge.status`).

- [ ] **Step 3: Implement** `bridge/status.py` and the wiring in `bridge/app.py`.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bridge/status.py bridge/app.py tests/test_status.py tests/test_app.py
git commit -m "Bridge status reporter: one JSON line per change on LB_STATUS_FD"
```

---

### Task 3: Alert and restart policies (Swift, tested)

**Files:**
- Create: `macos/launcher/Policies.swift`, `macos/launcher/tests/PolicyTests.swift`, `tests/test_launcher_policies.py`

**Interfaces:**
- Produces in `Policies.swift` (Foundation only, no AppKit, so it compiles in a plain test binary):
  - `struct BridgeStatus: Decodable, Equatable { var loupedeck: Bool; var lightroom: Bool; var keys: String; var five_mode: String; var settings_url: String? }`
    - `static func parse(_ line: String) -> BridgeStatus?`: nil for anything that isn't a valid status line
  - `enum Alert: Equatable { case disconnected, back, keysMissing, bridgeStopped(willRestart: Bool) }`
  - `struct AlertPolicy`
    - `debounce = 3.0`, `wakeGrace = 15.0`, `minInterval = 60.0`
    - `mutating func status(_ s: BridgeStatus, at now: Double) -> [Alert]`
    - `mutating func tick(at now: Double) -> [Alert]`: called about once a second; sends a pending "disconnected"
    - `mutating func didWake(at now: Double)`
    - `mutating func bridgeRestarted()`: disarms until the next connect; resets the per-run "keys missing" alert
    - Rules:
      - armed by the first `loupedeck == true`
      - a drop while armed starts a pending timer
      - the alert is sent when the timer reaches `debounce`, `now >= wakeUntil`, and the rate limit allows it; a pending alert held back by the limit fires once allowed, if the Loupedeck is still gone
      - reconnecting clears any pending alert, and sends `.back` only if `.disconnected` was shown
      - `.keysMissing` is sent at most once per run
  - `struct RestartPolicy`
    - `delay = 5.0`, `window = 600.0`, `maxRestarts = 3`
    - `mutating func shouldRestart(exitCode: Int32, at now: Double) -> Bool`: false for exit code 0 (clean stop) and 3 (already running); otherwise true while fewer than 3 restarts happened in the last 10 minutes
- `tests/PolicyTests.swift`: a `main` that runs named checks, prints `ok <name>` or `FAIL <name>: …`, and exits non-zero on any failure.
- `tests/test_launcher_policies.py`:
  - skips unless `sys.platform == "darwin"` and `swiftc` exists
  - compiles `Policies.swift` and `PolicyTests.swift` into a temp binary and runs it
  - one pytest test per Swift check name, parametrized from the binary's output

- [ ] **Step 1: Write the failing Swift checks** in `PolicyTests.swift` (time is a plain `Double`):
  - `never_connected_never_alerts` (Review Focus 1): status lines with `loupedeck: false` for 60 s plus ticks → `[]`.
  - `drop_alerts_after_debounce`: connect at 0, drop at 10 → nothing at ticks 11 and 12; `.disconnected` at 13; reconnect at 20 → `[.back]`.
  - `quick_replug_is_silent` (Review Focus 2): drop at 10, back at 12 → no alerts at any tick to 30.
  - `wake_grace` (Review Focus 2): connected, `didWake(at: 100)`, drop at 101 → nothing until 115; `.disconnected` at the first tick ≥ 115 if still gone.
  - `flapping_is_rate_limited` (Review Focus 2): drop/back every 5 s for 120 s → at most 2 `.disconnected` and 2 `.back`.
  - `keys_missing_once_per_run`: three status lines with `keys: "missing"` → one `.keysMissing`; after `bridgeRestarted()`, one more.
  - `restart_disarms` (Review Focus 1): connected, `bridgeRestarted()`, then `loupedeck: false` for 30 s → no alert.
  - `restart_budget` (Review Focus 5): exit code 1 at 0, 10 and 20 → true, true, true; at 30 → false; at 700 → true.
  - `already_running_is_not_a_crash` (Review Focus 5): exit codes 0 and 3 → false.
  - `parse_rejects_garbage`: `""`, `"{}"`, `"not json"` and `"{\"loupedeck\": 1}"` → nil; a full line → the struct.
- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_launcher_policies.py -q`
Expected: FAIL (compile error: the types don't exist).

- [ ] **Step 3: Implement `Policies.swift`.**
- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (the policy checks show up as individual tests).

- [ ] **Step 5: Commit**

```bash
git add macos/launcher/Policies.swift macos/launcher/tests/PolicyTests.swift tests/test_launcher_policies.py
git commit -m "Launcher: alert and restart policies, with Swift checks run by pytest"
```

---

### Task 4: The menu-bar app

**Files:**
- Create: `macos/launcher/BridgeProcess.swift`, `macos/launcher/StatusMenu.swift`
- Modify: `macos/launcher/main.swift`, `tools/build_mac_app.sh` (compile every `macos/launcher/*.swift`, not `tests/`; an optional first argument = output folder, default `build/`), `tools/bridgectl` (`login on|off|status`)
- Test: `tests/test_launcher_policies.py` stays green. The app itself is checked by hand in Task 5.

**Interfaces:**
- Consumes: Task 2's status lines, Task 3's `BridgeStatus`, `AlertPolicy`, `RestartPolicy`, `Alert`.
- `main.swift`:
  - `--login on|off|status`: uses `SMAppService.mainApp` (or the Task 1 fallback), prints the state, exits 0/1, and never starts the bridge.
  - `--check-permission`: today's one-shot behaviour, with no menu-bar icon.
  - Anything else: run as a menu-bar app.
- `BridgeProcess`:
  - spawns `.venv/bin/python -E -m bridge` with the extra arguments, the repo as working directory, and fd 3 = the pipe's write end with `LB_STATUS_FD=3`
  - stdout and stderr are appended to `~/Library/Logs/loupedeck-lr-bridge/bridge.log` (directory created if missing); the launcher's own messages go there too
  - signal handlers (TERM/INT/HUP → stop the bridge, then exit) are installed before spawning
  - reads status lines on a background queue and delivers `BridgeStatus` on the main queue
  - on exit:
    - code 3 → quit quietly
    - a clean stop (Quit or a signal) → exit 0
    - anything else → post key-ups for Shift, Ctrl, Cmd, Alt, Tab and the four arrows (CGEvent, the same key codes as `bridge/platform/macos_keys.py`), then let `RestartPolicy` decide
  - `stop()`: SIGTERM, wait up to 5 s, then SIGKILL
- `StatusMenu`:
  - an `NSStatusItem` with an SF Symbol template image, normal or warning (warning if `!loupedeck || !lightroom || keys == "missing"`, or the bridge is stopped)
  - the menu exactly as the spec shows it, plus "Restart bridge" and "Open log" when stopped
  - the "Start at login" checkmark reads `SMAppService.mainApp.status` each time the menu opens and toggles register/unregister; errors are shown in an alert
  - "Open settings…" opens `settings_url`
  - notifications through `UNUserNotificationCenter` (authorization requested at launch); wording per the spec
  - a 1 s timer calls `AlertPolicy.tick`
  - `NSWorkspace.didWakeNotification` → `didWake`
- `tools/bridgectl login on|off|status` runs `"$APP/Contents/MacOS/LoupedeckBridge" --login …`.

- [ ] **Step 1:** `tools/build_mac_app.sh [OUT_DIR]` compiles all launcher sources into `OUT_DIR/LoupedeckBridge.app` (default `build/`). Check with `swiftc -typecheck` on every file first.
- [ ] **Step 2: Implement** `main.swift`, `BridgeProcess.swift` and `StatusMenu.swift` per the interfaces.
- [ ] **Step 3: Build into the scratchpad** (`tools/build_mac_app.sh <scratchpad>/m5-build`), **not** the user's `build/` app. Run it with `--login status` and `--check-permission` to confirm the one-shot paths exit without an icon.
- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add macos/launcher tools/build_mac_app.sh tools/bridgectl
git commit -m "LoupedeckBridge.app: menu-bar status, alerts, start at login, restarts, launcher fixes"
```

---

### Task 5: Rebuild, permissions, docs, live check

**Files:**
- Modify: `README.md` ("Run as an app": the menu, alerts, Start at login, re-granting permissions; the roadmap ticks item 5), `docs/FINDINGS.md` (the live check)

- [ ] **Step 1: Ask the user's go-ahead** to rebuild their app (`tools/bridgectl build`). macOS may ask again for Accessibility and Documents, and once for notifications.
- [ ] **Step 2: Rebuild and start it with the user:**
  - grant the permissions again if macOS asks
  - the icon appears; the menu shows Loupedeck, Lightroom, Keyboard keys and Five buttons correctly
  - spec item 3: keyboard keys still work (Keys mode, arrows)
- [ ] **Step 3: Live checklist with the user:**
  1. Unplug the dongle: an alert after about 3 s, and the icon warns. Replug: "is back".
  2. A quick replug (under 2 s): no alert.
  3. Quit Lightroom: the icon warns, no alert.
  4. --Col / Fn + --Col: the menu's "Five buttons" follows.
  5. Open settings… opens the page.
  6. Tick Start at login, log out and back in (or check System Settings → Login Items): the bridge starts. Untick it.
  7. `kill -9` the Python bridge: an alert says it stopped and is restarting; it comes back; no key stuck.
  8. Quit LoupedeckBridge: the icon goes away, the bridge stops, no key stuck.
  9. Start with the Loupedeck unplugged: no alert, the icon warns.
- [ ] **Step 4: Docs.** README: the menu, the alerts and their rules, Start at login (off until ticked), re-granting permissions after a rebuild, and the known limit (a Loupedeck that goes quiet while still plugged in can't be detected). FINDINGS: the live check.
- [ ] **Step 5: Commit**

```bash
git add README.md docs/FINDINGS.md
git commit -m "Milestone 5: docs and live-check results"
```
