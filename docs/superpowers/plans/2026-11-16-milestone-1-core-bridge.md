# Milestone 1: Core Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turning dials and pressing Lightroom-API buttons on the Loupedeck+ controls Lightroom per the default layout, with good dial feel, tracking, and automatic reconnects. Keyboard keys and the settings page come in later milestones.

**Architecture:** An asyncio app. `MidiInput` turns Loupedeck+ MIDI into `Turn`/`Press`/`Release` events using the hardware map. The `Dispatcher` looks up each control's action in the user mapping: dial adjustments go to the `DialEngine` (coalesces detents, applies the user's dial-feel curve, tracking), and everything else becomes direct Lightroom API calls through a self-reconnecting `LightroomSession`.

**Tech Stack:** Python ≥3.9, asyncio, `mido` + `python-rtmidi`, `websockets` 15, `pytest` (dev only).

**Spec:** [docs/superpowers/specs/2026-11-16-loupedeck-bridge-design.md](../specs/2026-11-16-loupedeck-bridge-design.md). Facts about the device and API: [docs/FINDINGS.md](../../FINDINGS.md).

## Global Constraints

- Must run on Apple's system Python **3.9** and current Windows Python (3.12+). Every module starts with `from __future__ import annotations`. No 3.10+ syntax at runtime (`match`, `X | Y` outside annotations).
- Runtime dependencies stay exactly `mido`, `python-rtmidi`, `websockets`. Add `pytest` to a new `requirements-dev.txt` only.
- Network: connect to `127.0.0.1` only.
- Never modify Lightroom's files. Only read `connections.json`.
- Never commit Adobe's docs or the client GUID. The GUID lives in the per-user state dir (mode 600 on Mac).
- Live tests that change edits run **only on a photo the user picks for testing**. Ask before every live write session.
- **Input while Lightroom is disconnected is dropped**, not queued.
- **B&W-bank dials do nothing unless `isBlackAndWhiteOn()` is true.** They never silently convert the photo.
- Lightroom replies: `response` is always an **array of return values** (`getRange` → `[min, max, decimals, small_step, large_step?]`, 4 or 5 values).
- Tests run with `.venv/bin/python -m pytest -q`. Async tests use `asyncio.run(...)` inside plain test functions (no pytest-asyncio).
- Commit after each task (local only; the user decides about pushing).

## Review Focus

1. **Lightroom not running at start, or quit mid-session:** the bridge keeps running, retries quietly, drops input meanwhile, and old detents never replay. Tested in Task 5 (`test_session_waits_while_lightroom_down`, `test_session_reconnects_after_drop`) and Task 8 (`test_dropped_while_disconnected`).
2. **Device unplugged and replugged:** the bridge notices the port vanished and reopens it when it's back, without restarting. Tested in Task 9 (`test_reopens_after_unplug`).
3. **Very fast spins** (~150 detents/s for seconds): at most one Lightroom call per parameter per flush interval, total movement preserved, no backlog. Tested in Task 7 (`test_flood_is_bounded`).
4. **No usable photo** (Lightroom answers `success:false` to `getRange`/`increment`): a warning is logged, that turn is skipped, nothing crashes, and the next turn tries again. Tested in Task 7 (`test_lightroom_error_drops_turn`).
5. **Broken user mapping** (invalid JSON or a bad entry): invalid JSON → use the default layout without overwriting the user's file; a bad entry → that control does nothing, plus a warning naming it. Tested in Task 4 (`test_corrupt_user_file_falls_back`, `test_invalid_entry_becomes_none`).

---

### Task 1: Verify Lightroom write behaviour on a test photo

Findings here can change details in Tasks 7–8 (e.g. `increment` vs `setValue`). **User-involved:** before running, ask the user to open a photo they're happy to edit (ideally a duplicate) in Lightroom's Edit view, and wait for their go-ahead.

**Files:**
- Create: `tools/lr_verify_writes.py`
- Modify: `docs/FINDINGS.md` (new section "Write behaviour (milestone 1 checks)")

- [ ] **Step 1: Write `tools/lr_verify_writes.py`.** It registers via `bridge.lightroom.Lightroom`, records the original values of `Exposure2012`, `Contrast2012`, `straightenAngle`, and runs these checks, printing each raw reply:
  1. `increment("Exposure2012", 0.1)` → `getValue` (expect +0.1 in EV units).
  2. `increment("Contrast2012", 500)` → `getValue` (does it clamp at 100?).
  3. `increment("straightenAngle", 1)` with the crop tool **not** active (`getSelectedTool` ≠ `"crop"`) → `getValue`.
  4. `resetToDefault("straightenAngle")` → `getValue` (expect 0).
  5. `startTracking("Exposure2012")`, then 5× `increment("Exposure2012", 0.05)`, then `stopTracking()`.
  6. `applyPreset(<first id from getPresetIDs>)` in Loupe view, then `undo()`.

  Finally it restores every recorded original with `setValue`.
- [ ] **Step 2: Run it (after the user's go-ahead).** Run: `.venv/bin/python tools/lr_verify_writes.py`. Expected: every check prints a reply. Ask the user to confirm on screen that the photo is back as it was, and that step 5 left one history entry.
- [ ] **Step 3: Record the results** in `docs/FINDINGS.md`. If `increment` doesn't move `straightenAngle` outside the crop tool, or doesn't clamp, note the fallback chosen for Task 7: `getValue` at turn start + `setValue` with local clamping.
- [ ] **Step 4: Commit.** `git add tools/lr_verify_writes.py docs/FINDINGS.md && git commit -m "Verify Lightroom write behaviour for dials and presets"`

---

### Task 2: Test setup and per-OS paths

**Files:**
- Create: `requirements-dev.txt` (`pytest==8.3.5`), `tests/__init__.py` (empty), `bridge/platform/__init__.py`, `bridge/platform/macos.py`, `bridge/platform/windows.py`
- Modify: `bridge/lightroom.py` (drop the hard-coded `CONNECTIONS_JSON` / `STATE_FILE`)
- Test: `tests/test_platform.py`

**Interfaces:**
- Produces: `bridge.platform.current() -> module` (macOS or Windows module; on any other `sys.platform` raises `RuntimeError("Linux/other systems aren't supported: Lightroom doesn't run there")`).
  Each module has `lightroom_connections_json() -> Path`, `state_dir() -> Path`, `config_dir() -> Path`, `log_dir() -> Path`.
  - macOS: `~/Library/Application Support/Adobe/Lightroom CC/Connections/connections.json`; state and config `~/Library/Application Support/loupedeck-lr-bridge`; logs `~/Library/Logs/loupedeck-lr-bridge`.
  - Windows: `%LOCALAPPDATA%\Adobe\Lightroom CC\Connections\connections.json`; state `%LOCALAPPDATA%\loupedeck-lr-bridge`; config `%APPDATA%\loupedeck-lr-bridge`; logs `%LOCALAPPDATA%\loupedeck-lr-bridge\logs`.
- Produces: `bridge.lightroom.lightroom_port(path: Optional[Path] = None) -> int` (default path from `platform.current()`, fallback 7682), and `Lightroom(app_name, app_version, frame_log=None, state_file: Optional[Path] = None)` (default `platform.current().state_dir() / "client.json"`). Also `Lightroom.connect(port: Optional[int] = None)`.

- [ ] **Step 1: Write failing tests** in `tests/test_platform.py`:
  - `test_macos_paths(monkeypatch, tmp_path)`: with `HOME=tmp_path`, `macos.lightroom_connections_json() == tmp_path / "Library/Application Support/Adobe/Lightroom CC/Connections/connections.json"`, and `macos.log_dir() == tmp_path / "Library/Logs/loupedeck-lr-bridge"`.
  - `test_windows_paths(monkeypatch, tmp_path)`: with `LOCALAPPDATA=tmp_path/"L"` and `APPDATA=tmp_path/"R"`, `windows.lightroom_connections_json().parts[-4:] == ("Adobe", "Lightroom CC", "Connections", "connections.json")` under `tmp_path/"L"`, and `windows.config_dir() == tmp_path/"R"/"loupedeck-lr-bridge"`.
  - `test_current_rejects_linux(monkeypatch)`: `sys.platform = "linux"` → `pytest.raises(RuntimeError, match="Lightroom doesn't run there")`.
  - `test_port_from_file(tmp_path)`: a file containing `{"port": 7700}` → `7700`. Missing file or `"garbage"` → `7682`.
- [ ] **Step 2: Run them to see them fail.** `.venv/bin/python -m pip install -q -r requirements-dev.txt && .venv/bin/python -m pytest -q tests/test_platform.py`. Expected: import errors.
- [ ] **Step 3: Implement** the platform modules and the `lightroom.py` changes. Windows paths read `os.environ` at call time, so tests can run on a Mac.
- [ ] **Step 4: Run the tests and check the probe still works.** `.venv/bin/python -m pytest -q` → all pass; `.venv/bin/python tools/lr_probe.py | head -3` → registers with no dialog.
- [ ] **Step 5: Commit.** `git add requirements-dev.txt tests bridge && git commit -m "Add per-OS paths and test setup"`

---

### Task 3: Hardware decoding

**Files:**
- Create: `bridge/hardware.py`
- Test: `tests/test_hardware.py`

**Interfaces:**
- Produces (in `bridge/hardware.py`):
  - frozen dataclasses `Turn(control: str, detents: int)`, `Press(control: str)`, `Release(control: str)`; `Event = Union[Turn, Press, Release]`.
  - `HardwareMap.load(path: Path = <repo>/config/loupedeck_plus.json) -> HardwareMap`.
  - `HardwareMap.decode(msg_type: str, number: int, value: int) -> Optional[Event]`, where `msg_type` is mido's `"control_change" | "note_on" | "note_off"`.
  - `HardwareMap.controls: Dict[str, str]`, mapping control id → `"dial"` or `"button"`.
  - Control ids: keys of `dials` and `buttons`. Colour dials are `f"{bank}_{colour}"`, e.g. `hue_red`, `sat_magenta`, `bw_aqua`.
- Decoding rules: CC value → `v - 128 if v > 63 else v`. `note_on` → `Press`, `note_off` or `note_on` with value 0 → `Release`. Unknown numbers → `None`.

- [ ] **Step 1: Write failing tests:**
  - `test_turn_directions`: `decode("control_change", 33, 1) == Turn("exposure", 1)`; `(…, 33, 127) == Turn("exposure", -1)`.
  - `test_colour_banks`: CC 1 → `hue_red`, 16 → `sat_magenta`, 21 → `lum_aqua`, 25 → `bw_red`, 32 → `bw_magenta`.
  - `test_clicks_and_buttons`: `decode("note_on", 33, 64) == Press("exposure")`, `decode("note_off", 33, 64) == Release("exposure")`, `decode("note_on", 66, 64) == Press("shift")`, `decode("note_on", 66, 0) == Release("shift")`.
  - `test_unknown_numbers`: CC 43 → `None`; note 127 → `None`.
  - `test_every_captured_message_decodes`: every non-marker record in all `captures/raw-*.jsonl` (fields `type`, `control`/`note`, `value`/`velocity`) decodes to a non-`None` event.
  - `test_controls_catalogue`: `len(controls) == 14 + 32 + 40`; `controls["exposure"] == "dial"`, `controls["bw_red"] == "dial"`, `controls["c1"] == "button"`.
- [ ] **Step 2: Run them to see them fail.** `.venv/bin/python -m pytest -q tests/test_hardware.py`.
- [ ] **Step 3: Implement `bridge/hardware.py`.** Build two lookup dicts at load (cc number → dial id, note number → control id), skipping keys that start with `_`.
- [ ] **Step 4: Run the tests to see them pass.**
- [ ] **Step 5: Commit.** "Decode Loupedeck+ MIDI into control events"

---

### Task 4: Default layout and user mapping

**Files:**
- Create: `config/default_mapping.json`, `bridge/mapping.py`
- Test: `tests/test_mapping.py`

**Interfaces:**
- Consumes: `HardwareMap.controls` (Task 3).
- Produces: `Mapping.load(user_path: Path, default_path: Path = <repo>/config/default_mapping.json) -> Mapping`; `Mapping.turn_action(control: str) -> dict`; `Mapping.press_action(control: str) -> dict`; `Mapping.warnings: List[str]`. A missing control means `{"type": "none"}`.
- File format: `{"version": 1, "controls": {"<id>": {"turn": <action>, "press": <action>}}}`. Action shapes:
  - turn only: `{"type": "adjust", "param": str}`, `{"type": "step", "cw": {"message": str, "args": list}, "ccw": {...}}`
  - press only: `{"type": "call", "message": str, "args": list}`, `{"type": "preset", "id": str|null, "name": str|null}` (at least one set), `{"type": "key", "key": one of shift ctrl cmd alt tab left right up down}`, `{"type": "shortcut", "mac": [str], "windows": [str]}`
  - either: `{"type": "none"}`.
- Default layout content (spec table):
  - Tone dials: `exposure→Exposure2012`, `contrast→Contrast2012`, `highlights→Highlights2012`, `shadows→Shadows2012`, `whites→Whites2012`, `blacks→Blacks2012`, `clarity→Clarity2012`, `vibrance→Vibrance`, `saturation→Saturation`, `temperature→Temperature`, `tint→Tint`, `d1→Texture`, `d2→Dehaze`, `control→straightenAngle`.
  - Colour dials: `hue_X→HueAdjustmentX`, `sat_X→SaturationAdjustmentX`, `lum_X→LuminanceAdjustmentX`, `bw_X→GrayMixerX` (X capitalised: Red … Magenta).
  - Every dial's press: `call resetToDefault [<its param>]`.
  - Buttons: `c1 flagPickToggle`, `c2 flagRejectToggle`, `undo undo`, `redo redo`, `copy copyEditSettings`, `paste pasteEditSettings`, `export openExport`, `clr_bw toggleBlackAndWhite` (all `call`, `args: []`).
  - `p1`–`p8`: `{"type": "preset", "id": null, "name": null}` (unassigned).
  - `shift ctrl command alt tab` → `key` with names `shift ctrl cmd alt tab`; `up down left right` → `key`.
  - `before_after` and `screen_mode` → `none` until milestone 2 verifies Lightroom's shortcuts.
  - Everything else → `none`.
- Behaviour: no user file → copy the default there (create parent dirs). Invalid JSON → log an error, use the default, **leave the file untouched**. Invalid entry → that slot becomes `none`, plus a warning containing the control id.

- [ ] **Step 1: Write failing tests:**
  - `test_default_covers_every_control`: every id in `HardwareMap.controls` has an entry. Dials have `turn` and `press`; buttons have `press`.
  - `test_default_params_exist`: every `adjust` param and every `resetToDefault` arg is a key in `docs/lr_parameters_10.0.json`.
  - `test_first_run_copies_default(tmp_path)`: after `Mapping.load(tmp_path/"m.json")`, the file exists and equals the default.
  - `test_corrupt_user_file_falls_back(tmp_path)`: the file holds `"{not json"` → `turn_action("exposure") == {"type": "adjust", "param": "Exposure2012"}` and the file text is still `"{not json"`.
  - `test_invalid_entry_becomes_none(tmp_path)`: user file `{"version":1,"controls":{"exposure":{"turn":{"type":"adjust"}}}}` → `turn_action("exposure") == {"type": "none"}` and some warning contains `"exposure"`.
  - `test_press_type_rejected_for_turn(tmp_path)`: `exposure.turn = {"type":"call","message":"undo","args":[]}` → `none`, plus a warning.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Write `config/default_mapping.json` and implement `bridge/mapping.py`.** A user file *replaces* the default entirely (no merging), so what the user sees is what runs.
- [ ] **Step 4: Run the tests to see them pass.**
- [ ] **Step 5: Commit.** "Add default layout and user mapping loader"

---

### Task 5: Self-reconnecting Lightroom session

**Files:**
- Create: `bridge/session.py`, `tests/fake_lightroom.py`
- Modify: `bridge/lightroom.py` (add the `connected` property and `async wait_closed()`)
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `Lightroom(..., state_file=...)`, `Lightroom.connect(port=...)` (Task 2).
- Produces:
  - `LightroomSession(app_name: str, app_version: str, port: Optional[int] = None, state_file: Optional[Path] = None, retry_delay: float = 2.0, on_connect: Optional[Callable[[], Awaitable[None]]] = None, on_disconnect: Optional[Callable[[], None]] = None)`
  - `async LightroomSession.run_forever() -> None`
  - `LightroomSession.connected -> bool`
  - `LightroomSession.lr -> Optional[Lightroom]`
  - `async LightroomSession.call(message: str, *params) -> list`, which raises `ConnectionError` when disconnected.
  - `SETUP_CALLS = [("revealAdjustedControls", [True]), ("setTrackingDelay", [2.0]), ("setMultipleAdjustmentThreshold", [1.0])]`, sent after every successful register.
- Produces: `tests/fake_lightroom.py`:
  - `FakeLightroom()` with `async start() -> int` (binds `127.0.0.1` port 0, returns the port), `async stop()`, `async drop_clients()`.
  - `calls: List[Tuple[str, list]]`.
  - `responses: Dict[str, list]` (default reply `[]`; `register` → `["FAKE-GUID", "10.0"]`).
  - `failing: Set[str]` (those messages get `{"success": false, "response": ["invalid_request"]}`).
- Loop: connect → register (timeout 120 s, for the first-run Allow dialog) → `SETUP_CALLS` → `await on_connect()` → wait for close → `on_disconnect()` → sleep `retry_delay` → repeat. A refused connection or an error → log at INFO once per outage, sleep, repeat.

- [ ] **Step 1: Write failing tests** (each uses `tmp_path/"client.json"` as `state_file`, and `retry_delay=0.05`):
  - `test_session_registers_and_runs_setup`: the fake's `calls` begin with `register`, followed by exactly `SETUP_CALLS`; `on_connect` was awaited once, after them; `connected` is `True`.
  - `test_session_reconnects_after_drop`: after `drop_clients()`, `connected` becomes `False`, `on_disconnect` fires once, and within 1 s `connected` is `True` again with `register` called twice. The second register passes `"FAKE-GUID"` as the third param.
  - `test_session_waits_while_lightroom_down`: start the session pointing at an unused port; `connected` stays `False` for 0.3 s; start a fake on that port; `connected` becomes `True` within 1 s.
  - `test_call_while_disconnected_raises`: `pytest.raises(ConnectionError)`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** the fake server (with `websockets.asyncio.server.serve`) and `bridge/session.py`.
- [ ] **Step 4: Run the tests to see them pass.**
- [ ] **Step 5: Commit.** "Add self-reconnecting Lightroom session"

---

### Task 6: Dial feel (**written by the user**)

The user writes the body of `detent_amount`; it decides how the bridge feels. The implementer prepares the file, the dataclass and the tests, then **pauses and hands this to the user**, explaining the trade-offs: per-detent size at slow speed, how fast acceleration kicks in, and the ceiling.

**Files:**
- Create: `bridge/dial_feel.py`
- Test: `tests/test_dial_feel.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) ParamRange(min: float, max: float, decimals: int, small_step: float, large_step: Optional[float])`
  - `ParamRange.from_reply(values: list) -> ParamRange`, accepting 4 or 5 values.
  - `detent_amount(rng: ParamRange, detents_per_sec: float) -> float`, the amount for **one** detent. The engine multiplies by the detent count and rounds to `rng.decimals`.

- [ ] **Step 1: Write the tests.** Sample ranges: Exposure `(-5,5,2,0.1,0.33)`, Contrast `(-100,100,0,10,20)`, Temperature `(0,100,0,1,10)`, straighten `(-45,45,1,10,None)`. Speeds `[0, 1, 5, 20, 60, 150]`.
  - `test_from_reply_five_and_four`.
  - `test_amount_is_visible`: for every range and speed, `detent_amount ≥ 10 ** -decimals`, so one detent never rounds to 0.
  - `test_slow_is_fine`: for speeds ≤ 5, `amount ≤ (max - min) / 100`.
  - `test_monotonic`: the amount never decreases as speed increases.
  - `test_fast_accelerates`: `detent_amount(r, 150) ≥ 2 * detent_amount(r, 1)`.
- [ ] **Step 2: Implement `ParamRange`; leave `detent_amount` raising `NotImplementedError("written by the user")`.** Run the tests: the `from_reply` test passes, the rest fail.
- [ ] **Step 3: User writes `detent_amount` (5–10 lines).**
- [ ] **Step 4: Run the tests to see them pass.** `.venv/bin/python -m pytest -q tests/test_dial_feel.py`.
- [ ] **Step 5: Commit** (the user's authorship credited in the message). "Add dial feel curve"

---

### Task 7: Dial engine

**Files:**
- Create: `bridge/dials.py`
- Test: `tests/test_dials.py`

**Interfaces:**
- Consumes: `ParamRange`, `detent_amount` (Task 6); a client with `async call(message, *params) -> list` (`LightroomSession`, Task 5).
- Produces:
  - `DialEngine(client, feel=detent_amount, clock=time.monotonic, flush_interval=0.025, turn_gap=0.5, speed_window=0.2)`
  - `DialEngine.add(param: str, detents: int) -> None` (sync; records `clock()`)
  - `async DialEngine.flush() -> None`
  - `async DialEngine.run() -> None` (flushes every `flush_interval` forever)
  - `DialEngine.reset() -> None` (drops all pending and turn state)
- Per-parameter flush, for each param with pending ≠ 0:
  1. **New turn** (first `add` after ≥ `turn_gap` without one): `getRange(param)` → `ParamRange.from_reply`. For `GrayMixer*` params, `isBlackAndWhiteOn()`: if the first value is `False`, mark this turn **blocked** (drop pending until the next turn, log once). Then `startTracking(param)`.
  2. Speed = number of `add` timestamps in the last `speed_window`, divided by `speed_window`.
  3. `amount = round(abs(pending) * feel(rng, speed), rng.decimals)`. If 0, skip. Otherwise send `increment(param, amount)` if pending > 0, else `decrement(param, amount)`. Reset pending to 0.
  4. A `LightroomError`, `ConnectionError` or timeout → log a warning, drop pending, mark the turn failed (it retries on the next turn). Never raise.
  - (If Task 1 found `increment` unusable for a param, use the fallback recorded in FINDINGS for it.)

- [ ] **Step 1: Write failing tests** with a recording fake client, a fake clock, and `feel=lambda r, s: 1.0` unless stated:
  - `test_first_detent_starts_tracking_and_increments`: `add("Contrast2012", 1)`; `flush()` → calls `[("getRange",["Contrast2012"]), ("startTracking",["Contrast2012"]), ("increment",["Contrast2012", 1])]`.
  - `test_negative_uses_decrement`: `add(…, -1)` → `("decrement", ["Contrast2012", 1])`.
  - `test_detents_coalesce`: 10 adds, then one flush → a single `increment` of 10.
  - `test_flood_is_bounded`: 150 adds/s for 2 s, flushing every 0.025 s of fake time → at most 81 `increment` calls, total amount == 300, and `getRange` called once.
  - `test_new_turn_after_gap`: two bursts 0.6 s apart → `getRange` and `startTracking` each called twice.
  - `test_feel_gets_speed`: a spy `feel` sees a speed of about 50 when adds come 0.02 s apart.
  - `test_rounding_to_decimals`: `getRange` reply `[-5,5,2,0.1,0.33]`, `feel=lambda r,s: 0.033` → `increment ["Exposure2012", 0.03]`.
  - `test_bw_dial_blocked_when_not_bw`: `isBlackAndWhiteOn` → `[False, {}]` → no `increment` for `GrayMixerRed`; with `[True, {}]` on the next turn → incremented.
  - `test_lightroom_error_drops_turn`: `getRange` fails → no increment, no exception; the next turn after the gap succeeds.
  - `test_two_dials_independent`: Exposure and Contrast in the same interval → one increment each.
  - `test_reset_drops_pending`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement `bridge/dials.py`.**
- [ ] **Step 4: Run the tests to see them pass.**
- [ ] **Step 5: Commit.** "Add dial engine with coalescing, tracking and B&W guard"

---

### Task 8: Dispatcher (events → actions)

**Files:**
- Create: `bridge/actions.py`
- Test: `tests/test_actions.py`

**Interfaces:**
- Consumes: `Event` types (Task 3), `Mapping` (Task 4), `LightroomSession.call` and `.connected` (Task 5), `DialEngine.add` (Task 7).
- Produces:
  - `Dispatcher(mapping: Mapping, session, dials: DialEngine)`
  - `async Dispatcher.handle(event: Event) -> None`
  - `async Dispatcher.resolve_presets() -> None` (called after each connect)
  - `Dispatcher.preset_warnings: List[str]`
- Rules:
  - Not `session.connected` → drop the event (debug log).
  - `Turn`:
    - `adjust` → `dials.add(param, detents)`.
    - `step` → one call of `cw`/`ccw` per detent, sent in order.
    - `none` → nothing.
  - `Press`:
    - `call` → `session.call(message, *args)`.
    - `preset` → `applyPreset(resolved_id)`. Unresolved → warning, nothing sent.
    - `key`/`shortcut` → log once "keyboard actions arrive in milestone 2".
    - `none` → nothing.
  - `Release` → nothing (milestone 2 adds key-up).
  - Every Lightroom error is logged, never raised.
- Preset resolution:
  - `getPresetIDs` once. A configured id in that list → use it.
  - Otherwise, if a name is set, fetch `getPresetName` for all ids once (cache until the next connect) and require exactly one exact match.
  - 0 or >1 matches → unresolved, with a warning naming the slot (e.g. `"p3: 2 presets named 'Heavy'"`).

- [ ] **Step 1: Write failing tests** (fake session recording calls with a settable `connected`, a spy dial engine, a `Mapping` from a temp user file):
  - `test_turn_adjust_goes_to_dials`: `Turn("exposure", -1)` → `dials.add("Exposure2012", -1)`.
  - `test_step_calls_per_detent`: control mapped to `step` nextPhoto/previousPhoto; `Turn(c, -2)` → two `previousPhoto` calls.
  - `test_press_call`: `Press("c1")` → `("flagPickToggle", [])`.
  - `test_dial_click_resets`: `Press("exposure")` → `("resetToDefault", ["Exposure2012"])`.
  - `test_dropped_while_disconnected`: `connected=False` → no calls, no dial adds.
  - `test_preset_by_id`, `test_preset_by_name_when_id_missing`, `test_preset_ambiguous_name_unresolved` (`p3` set to name `"Heavy"`, two presets with that name → no `applyPreset` on `Press("p3")`; a warning contains `"p3"` and `"Heavy"`).
  - `test_lightroom_error_does_not_raise`.
  - `test_key_action_is_noop`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement `bridge/actions.py`.**
- [ ] **Step 4: Run the tests to see them pass.**
- [ ] **Step 5: Commit.** "Add dispatcher for dials, buttons and presets"

---

### Task 9: MIDI input, app wiring, `python -m bridge`, live check

**Files:**
- Create: `bridge/midi_input.py`, `bridge/app.py`, `bridge/__main__.py`
- Modify: `README.md` (a "Run" section), `docs/FINDINGS.md` (live-check results)
- Test: `tests/test_midi_input.py`, `tests/test_integration.py`

**Interfaces:**
- Consumes: everything above. `bridge.platform.current().config_dir()` and `.log_dir()`.
- Produces:
  - `MidiInput(hardware: HardwareMap, port_hint="Loupedeck", list_ports=mido.get_input_names, open_port=mido.open_input, poll=1.0)`
  - `MidiInput.events() -> AsyncIterator[Event]`. It waits until a port name containing `port_hint` exists and opens it with a callback that forwards decoded events through `loop.call_soon_threadsafe` into an `asyncio.Queue`. Every `poll` seconds it checks `list_ports()`; if the port vanished it closes it and waits again. Unknown messages are skipped with a debug log.
  - `app.build(config_dir: Path, midi, port: Optional[int] = None, state_file: Optional[Path] = None, feel=detent_amount, frame_log: Optional[Path] = None) -> App`, where `midi` is anything with `events() -> AsyncIterator[Event]`. `async App.run() -> None` wires it all together:
    - session `on_disconnect` → `dials.reset()`
    - session `on_connect` → `dispatcher.resolve_presets()`
    - `Mapping.warnings` and `preset_warnings` are logged at start
  - `async app.run(debug: bool = False) -> None` calls `build` with the real `MidiInput` and the platform's config dir, then `App.run()`.
  - `python -m bridge [--debug]` logs:
    - always: INFO to stderr, plus `RotatingFileHandler(log_dir/"bridge.log", maxBytes=1_000_000, backupCount=3)`
    - with `--debug`: DEBUG level, plus the Lightroom frame log at `log_dir/"frames.jsonl"` (GUID redacted, as today)

- [ ] **Step 1: Write failing tests:**
  - `test_waits_for_device`: `list_ports` returns `[]` then `["Loupedeck+"]` → `open_port` called once, after it appears.
  - `test_reopens_after_unplug`: the port is listed, then missing, then back → `open_port` called twice; the first port is closed; events after the replug come through.
  - `test_unknown_messages_skipped`: CC 43, then CC 33 v1 → only `Turn("exposure", 1)` is yielded.
  - `test_integration_exposure_capture` (`tests/test_integration.py`): replay the `"exposure dial"` and `"exposure click"` records of `captures/raw-20261116-001458.jsonl` through a fake `midi` into `app.build(config_dir=tmp_path, midi=fake, port=<FakeLightroom port>, state_file=tmp_path/"client.json", feel=lambda r, s: 0.1)`. The fake's calls include `startTracking ["Exposure2012"]`, at least one `increment`, at least one `decrement` on `Exposure2012`, and `resetToDefault ["Exposure2012"]`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** `midi_input.py`, `app.py`, `__main__.py`, and the README "Run" section.
- [ ] **Step 4: Run the whole suite.** `.venv/bin/python -m pytest -q` → all pass.
- [ ] **Step 5: Live check on the Mac (user-involved).** First ask the user to quit the Loupedeck software and open a test photo, then run `.venv/bin/python -m bridge`. Walk through with the user:
  - each tone dial and its click
  - the colour dials in HUE/SAT/LUM, and B&W both with B&W off (nothing happens; log says why) and on
  - D1/D2, and the control dial (straighten + click reset)
  - C1/C2 toggles, undo/redo, copy/paste, export (dialog opens), clr/bw
  - quit Lightroom (the bridge waits) → reopen (reconnects, no dialog)
  - unplug/replug the Loupedeck (resumes)
  - a fast spin (no lag, one history step per turn)

  Record the results in `docs/FINDINGS.md`.
- [ ] **Step 6: Commit.** "Wire up the bridge: python -m bridge"
