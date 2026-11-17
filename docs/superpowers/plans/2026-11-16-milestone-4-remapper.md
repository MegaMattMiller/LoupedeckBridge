# Milestone 4: Remapper with an Fn Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A **Buttons & dials** tab on the settings page that changes what any control does, in a normal layer and an Fn layer, live.

**Architecture:** `mapping.json` entries gain an optional `fn` sub-entry; `Mapping` answers per layer and gains edit/reset operations. The dispatcher tracks Fn and picks the layer at press time. A hand-made `config/commands.json` (with the slider list) is the only source of what the page may assign; the settings server validates every change against it and broadcasts a per-control layout to all tabs.

**Tech Stack:** Python ≥3.9, `websockets` 15, plain HTML/CSS/JS (no framework, no CDN), `pytest`.

**Spec:** [docs/superpowers/specs/2026-11-16-m4-remapper-design.md](../specs/2026-11-16-m4-remapper-design.md), building on [milestone 3](../specs/2026-11-16-m3-settings-presets-design.md) and [the bridge design](../specs/2026-11-16-loupedeck-bridge-design.md).

## Global Constraints

- Milestones 1–3 still hold: Python 3.9-compatible, no new runtime dependencies, Lightroom and the page on 127.0.0.1 only, GUID never logged, live edits only on a test photo with the user's go-ahead.
- `mapping.json` saves are atomic and copy-then-swap (a failed save changes nothing in memory). An unreadable `mapping.json` is never overwritten.
- The page can never create a `key` or `shortcut` action, and never changes Fn, clr/bw, Export's Fn slot (fixed to export with previous), or P1–P8's normal layer.
- `exportWithPrevious` runs only from Export's Fn slot, and only after `canExportWithPrevious` says yes.
- `config/commands.json` holds our own labels and Lightroom message names only; nothing is copied from Adobe's reference (docs/adobe stays uncommitted).
- Python only: no launcher rebuild in this milestone.
- Commit after each task (local only).

## Review Focus

1. **The user's existing mapping** (presets on P1–P3, everything else unedited) after upgrading: presets kept, dial clicks become "reset this dial's slider", Export gains Fn + Export, no warnings. Test: Task 2 `test_milestone3_mapping_upgrades_cleanly`.
2. **Unplugging (or a reconnect) while Fn is held:** the layer doesn't stick. Test: Task 2 `test_fn_cleared_on_unplug_and_reconnect`.
3. **Hand-edited odd Fn entries** (`"fn": 5`, `"fn": {"press": "x"}`, a preset in `fn`, `exportWithPrevious` on C1): load with warnings, never crash, never run. Test: Task 1 `test_odd_fn_entries_load_with_warnings`.
4. **A stale or hostile page message** (Fn itself, clr/bw, Export's Fn slot, P1 normal, a key choice, an unknown id, a slider on a button): refused with an error, file untouched, connection still usable. Test: Task 4 `test_set_refuses_what_the_page_cannot_change`.
5. **A dial spun fast with the page open:** the page gets at most one "used" message per control every 0.25 s. Test: Task 4 `test_turns_are_throttled_for_the_page`.

---

### Task 1: Mapping: Fn layer, edit/reset operations, rules

**Files:**
- Modify: `bridge/mapping.py`, `config/default_mapping.json`
- Test: `tests/test_mapping.py`

**Interfaces:**
- Produces (all in `bridge/mapping.py`):
  - `FN_KEY = "fn"` (the layer key's control id)
  - `Mapping.default_path: Path` (stored by `load`)
  - `Mapping.turn_action(control: str, fn: bool = False) -> dict` and `press_action(control: str, fn: bool = False) -> dict`: with `fn=True`, the Fn slot if set, else the normal one.
  - `Mapping.fn_action(control: str, slot: str) -> Optional[dict]`: the Fn slot's own action; `None` = same as normal.
  - `Mapping.set_action(control: str, slot: str, action: Optional[dict], layer: str = "normal") -> None`: `slot` in `("turn", "press")`, `layer` in `("normal", "fn")`. `action=None` only with `layer="fn"` (removes that Fn slot; an empty `fn` is dropped). Raises `ValueError` (invalid action or rule), `MappingNotWritable`, `OSError` (save failed; memory unchanged). `set_press_action(control, action)` stays as `set_action(control, "press", action)`.
  - `Mapping.reset_control(control: str, keep_normal_press: bool = False) -> None`: the control's entry becomes the default's (both layers); with the flag, its current normal press is kept.
  - `Mapping.restore_defaults(keep_normal_press: Iterable[str] = ()) -> None`: every entry becomes the default's, except the normal press of the listed controls.
  - New press action `{"type": "reset_dial"}`.
- Rules, applied at load (invalid → warning, becomes `none` or is dropped) and in `set_action` (→ `ValueError`):
  - `fn` must be an object with only `turn`/`press`; each slot is validated like a normal one.
  - no `preset` in `fn`.
  - a `call` to `exportWithPrevious` is valid only at `export` → `fn` → `press`.
- Default layout change: `export` gains `"fn": {"press": {"type": "call", "message": "exportWithPrevious", "args": []}}` (the dispatcher ignores Fn slots until Task 2, so nothing changes in use yet). Dial clicks change in Task 2, together with the dispatcher code that runs them.

- [ ] **Step 1: Write the failing tests** in `tests/test_mapping.py`:

```python
RATING3 = {"type": "call", "message": "rating3", "args": []}

def test_fn_layer_falls_back_to_normal(tmp_path):
    m = Mapping.load(write(tmp_path / "m.json", {
        "c3": {"press": NONE, "fn": {"press": RATING3}},
        "c4": {"press": RATING3},
        "c5": {"press": RATING3, "fn": {"press": NONE}}}))
    assert m.press_action("c3", fn=True) == RATING3 and m.press_action("c3") == NONE
    assert m.press_action("c4", fn=True) == RATING3          # no Fn slot: same as normal
    assert m.press_action("c5", fn=True) == NONE             # Fn slot set to Nothing
    assert m.fn_action("c4", "press") is None and m.fn_action("c3", "press") == RATING3

def test_set_action_fn_layer_saves_and_clears(tmp_path):
    user = tmp_path / "m.json"
    m = Mapping.load(user)
    m.set_action("c3", "press", RATING3, layer="fn")
    assert json.loads(user.read_text())["controls"]["c3"]["fn"] == {"press": RATING3}
    m.set_action("c3", "press", None, layer="fn")
    assert "fn" not in json.loads(user.read_text())["controls"]["c3"]
    assert m.press_action("c3", fn=True) == NONE
```

Plus, each with the assertions named:
- `test_set_action_validates`: a `call` as a `turn` → `ValueError`; `None` with `layer="normal"` → `ValueError`; a preset in `fn` → `ValueError`; `exportWithPrevious` on `c1` → `ValueError`; the file is unchanged after each.
- `test_reset_control_restores_both_layers`: after setting `c3` normal and Fn, `reset_control("c3")` → entry equals the default's; `reset_control("p1", keep_normal_press=True)` keeps P1's preset and drops its Fn slot.
- `test_restore_defaults_keeps_listed_presses`: with presets on p1/p2 and an Fn action on c3, `restore_defaults(keep_normal_press=["p1", "p2"])` → p1/p2 presets kept, c3 back to default, file saved.
- `test_export_fn_default`: `press_action("export", fn=True)` is the `exportWithPrevious` call and `press_action("export")` is still `openExport`.
- `test_odd_fn_entries_load_with_warnings` (Review Focus 3): `"c1": {"press": NONE, "fn": 5}`, `"c2": {"press": NONE, "fn": {"press": "x"}}`, `"c3": {"press": NONE, "fn": {"press": {"type": "preset", "id": "A", "name": "W"}}}`, `"c4": {"press": {"type": "call", "message": "exportWithPrevious", "args": []}}` → loads; each control named in a warning; `press_action(c, fn=True) == NONE` for c1–c4 (c1/c2 fall back to their NONE normal press).

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mapping.py -q`
Expected: the new tests FAIL (`TypeError: press_action() got an unexpected keyword argument 'fn'`, missing methods, no Export Fn slot yet).

- [ ] **Step 3: Implement** the interfaces above in `bridge/mapping.py`, and edit `config/default_mapping.json`. One private `_save(doc)` does copy-then-swap for every edit. Validate `fn` entries in `load` the same way as normal slots, then the two rules, with a helper `_rule_problem(control, layer, slot, action) -> Optional[str]` shared by `load` and `set_action`. `_dumps` stays one line per control.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bridge/mapping.py config/default_mapping.json tests/test_mapping.py
git commit -m "Mapping: Fn layer, edit/reset operations, reset_dial action, Fn + Export default"
```

---

### Task 2: Dispatcher: Fn layer, reset_dial, clr/bw tied to the button

**Files:**
- Modify: `bridge/actions.py`, `config/default_mapping.json` (every dial and colour-dial `press` → `{"type": "reset_dial"}`)
- Create: `tests/data/default_mapping_m3.json` (`git show 4bff1bf:config/default_mapping.json`, the milestone 3 default)
- Test: `tests/test_actions.py`, `tests/test_mapping.py`

**Interfaces:**
- Consumes: Task 1's `FN_KEY`, `turn_action(c, fn=)`, `press_action(c, fn=)`.
- Produces: `Dispatcher.fn_held: bool` (read-only property).
- Behaviour:
  - `Press("fn")`/`Release("fn")` set/clear Fn and do nothing else (whatever `fn` maps to).
  - A press uses `press_action(control, fn=self.fn_held)` at press time. Held keys and repeats already remember what they pressed, so a release ends them whatever Fn does in between.
  - A turn uses `turn_action(control, fn=self.fn_held)` per message.
  - `reset_dial`: `resetToDefault(param)` for the `adjust` turn of the layer used by this press, else nothing.
  - Every `clr_bw` press, in any layer and whatever it maps to, runs the sync: if the device mode is known, toggle only when the photo differs; if unknown, a plain `toggleBlackAndWhite`.
  - The B&W guard (photo must be B&W) applies to press actions that reset a `GrayMixer…` slider (`reset_dial` resolving to one, or `resetToDefault` with a `GrayMixer…` argument), not to other actions on `bw_` controls.
  - A `call` to `exportWithPrevious` first calls `canExportWithPrevious`; if the first reply value is falsy, log at info and send nothing.
  - `release_all_keys()` and `device_reconnected()` also clear Fn.

- [ ] **Step 1: Write the failing tests.** Extend `FakeSession.call` with `self.can_export = True` answering `canExportWithPrevious` → `[self.can_export]`. Tests:

```python
def test_key_released_even_if_fn_let_go_first(tmp_path):
    kb = FakeKeyboard()
    d, _, _ = setup(tmp_path, {"c3": {"press": NONE, "fn": {"press": {"type": "key", "key": "shift"}}}}, keyboard=kb)
    async def main():
        for e in (Press("fn"), Press("c3"), Release("fn"), Release("c3")):
            await d.handle(e)
    run(main())
    assert kb.events == [("down", "shift"), ("up", "shift")]

def test_reset_dial_follows_the_layers_turn(tmp_path):
    d, s, _ = setup(tmp_path, {"exposure": {"turn": {"type": "adjust", "param": "Exposure2012"},
                                            "press": {"type": "reset_dial"},
                                            "fn": {"turn": {"type": "adjust", "param": "Contrast2012"}}},
                               "d1": {"turn": NONE, "press": {"type": "reset_dial"}}})
    async def main():
        await d.handle(Press("exposure")); await d.handle(Release("exposure"))
        await d.handle(Press("fn")); await d.handle(Press("exposure"))
        await d.handle(Release("exposure")); await d.handle(Release("fn"))
        await d.handle(Press("d1"))
    run(main())
    assert s.calls == [("resetToDefault", ["Exposure2012"]), ("resetToDefault", ["Contrast2012"])]
```

Plus, with assertions named:
- `test_fn_layer_press_and_turn`: c3 Fn press `rating3` → with Fn held, `rating3` is called, without it nothing; exposure Fn turn `adjust Contrast2012` → `dials.added` gets `Contrast2012` while Fn is held and `Exposure2012` after release.
- `test_fn_presses_do_nothing_else`: `fn` hand-mapped to a `call` → pressing Fn makes no Lightroom calls; `d.fn_held` is True between Press and Release.
- `test_fn_cleared_on_unplug_and_reconnect` (Review Focus 2): Press(fn) then `release_all_keys()` → `fn_held` False; Press(fn) then `device_reconnected()` → False.
- `test_clr_bw_syncs_whatever_it_maps_to`: `clr_bw` mapped to `none` with an Fn slot `rating3`; device mode known B&W (turn `bw_red` first), photo colour → Fn + clr/bw calls `toggleBlackAndWhite` once and never `rating3`.
- `test_bw_guard_only_for_gray_mixer_resets`: photo colour; `bw_red` press mapped to `rating3` → called; `bw_red` press `reset_dial` with turn `adjust GrayMixerRed` → no `resetToDefault`.
- `test_export_with_previous_checks_first`: Fn + Export with `can_export = False` → calls are only `canExportWithPrevious`; with True → `exportWithPrevious` follows.
- In `tests/test_mapping.py`, `test_default_dial_clicks_reset_dial`: every dial and colour-dial press in the default is `{"type": "reset_dial"}`. Update `test_default_params_exist` to count only turn params (`len(params) == 14 + 32`) and `test_default_layout_spot_checks` (`exposure` press → `reset_dial`).
- In `tests/test_mapping.py`, `test_milestone3_mapping_upgrades_cleanly` (Review Focus 1): `tests/data/default_mapping_m3.json` as both base and user file, presets on p1–p3 in the user file, then `Mapping.load(user)` with the new default → p1–p3 presets kept, `exposure` press is `reset_dial`, Export has its Fn action, `m.warnings == []`.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_actions.py -q`
Expected: the new tests FAIL (no `fn_held`, `reset_dial` not handled, clr/bw still tied to the command, dial clicks still `resetToDefault`).

- [ ] **Step 3: Implement** the behaviour above in `bridge/actions.py`, and change the dial clicks in `config/default_mapping.json`. Handle Fn first in `handle`, before keys. Pass the layer into `_press` (`fn: bool`) so `reset_dial` and the guard use the press-time layer. `_sync_bw()` replaces the clr/bw branch in `_press` and runs for every `clr_bw` press; like other Lightroom calls it's skipped while Lightroom isn't connected (the device mode is still tracked).

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bridge/actions.py config/default_mapping.json tests/test_actions.py tests/test_mapping.py tests/data/default_mapping_m3.json
git commit -m "Dispatcher: Fn layer, dial clicks reset the dial's slider, clr/bw sync on the button, export check"
```

---

### Task 3: Command catalog

**Files:**
- Create: `config/commands.json`, `bridge/commands.py`
- Test: `tests/test_commands.py`

**Interfaces:**
- Produces (`bridge/commands.py`):
  - `COMMANDS_PATH` (`config/commands.json`), `PARAMS_PATH` (`docs/lr_parameters_10.0.json`)
  - `CommandCatalog.load(commands_path=COMMANDS_PATH, params_path=PARAMS_PATH) -> CommandCatalog` with:
    - `commands: Dict[str, dict]`: id → `{"id", "label", "group", "message", "args"}`
    - `pairs: Dict[str, dict]`: id → `{"id", "label", "cw", "ccw"}` (command ids)
    - `sliders: Dict[str, str]`: param → label, for `"type": "number"` parameters only
  - `action_for(choice: dict, slot: str) -> Optional[dict]`. `choice["kind"]` is one of:
    - `command` + `id` (press) → `call`
    - `slider` + `param` (turn) → `adjust`
    - `pair` + `id` (turn) → `step`
    - `reset_dial` (press)
    - `open_settings` (press)
    - `none` (either slot)
    - `same` → `None`
    Anything else, an unknown id, or the wrong slot → `ValueError`.
  - `describe(action: dict) -> dict`: `{"label": str, "choice": Optional[dict]}` for any mapping action:
    - catalog commands, sliders and pairs by their labels
    - `resetToDefault(p)` → "Reset <slider label>"
    - `reset_dial` → "Reset this dial's slider"
    - `toggleBlackAndWhite` → "Black & white (kept in step with the device)"
    - `exportWithPrevious` → "Export with previous settings"
    - `key` → "Key: Shift"
    - `shortcut` → "Shortcut: " + the Mac keys joined with " + "
    - `preset` → "Preset: <name>"
    - `open_settings` → "Open this settings page"
    - `none` → "Nothing"
    - any other call → "Lightroom: <message>"
    `choice` is the `action_for` choice that would produce it, or `None` when the page can't produce it.
  - `to_page() -> dict`: `{"type": "catalog", "commands": [{"id", "label", "group"}…], "pairs": [{"id", "label"}…], "sliders": [[param, label]…]}`, in file order and sliders sorted by label.
- `config/commands.json`: `{"version": 1, "commands": [...], "pairs": [...]}`. Curate groups and labels from the local reference (Flag, Rating, Colour label, Photos, View, Tools, Edit, App). Each `selectTool`, `showView` and `setWhiteBalance` argument must be one the reference lists.

- [ ] **Step 1: Write the failing tests** in `tests/test_commands.py`:

```python
REQUIRED = {  # id: (message, args) — the defaults and the design's examples
    "flag_pick_toggle": ("flagPickToggle", []), "flag_reject_toggle": ("flagRejectToggle", []),
    "rating_3": ("rating3", []), "rating_up": ("ratingIncrease", []), "rating_down": ("ratingDecrease", []),
    "label_red": ("colorLabelRed", []), "next_photo": ("nextPhoto", []), "previous_photo": ("previousPhoto", []),
    "zoom_to_fit": ("zoomToFit", []), "crop_tool": ("selectTool", ["crop"]), "auto_tone": ("setAutoTone", []),
    "undo": ("undo", []), "redo": ("redo", []), "copy_settings": ("copyEditSettings", []),
    "paste_settings": ("pasteEditSettings", []), "open_export": ("openExport", []),
}
EXCLUDED = {"exportWithPrevious", "toggleBlackAndWhite", "applyPreset", "setTrackingDelay",
            "setMultipleAdjustmentThreshold", "startTracking", "stopTracking", "increment", "decrement"}

def test_required_and_excluded():
    c = CommandCatalog.load()
    for cid, (msg, args) in REQUIRED.items():
        assert (c.commands[cid]["message"], c.commands[cid]["args"]) == (msg, args), cid
    messages = {x["message"] for x in c.commands.values()}
    assert not messages & EXCLUDED
    assert not [m for m in messages if m.startswith(("get", "is", "can", "add")) or m.endswith("WithName")]
```

Plus, with assertions named:
- `test_ids_unique_and_pairs_reference_commands`: no duplicate ids in the file; every pair's `cw`/`ccw` is a command id; pairs include previous/next photo, rating down/up, zoom out/in.
- `test_sliders_are_number_params`: `c.sliders["Exposure2012"] == "Exposure"`; `"AutoGrayscaleMix" not in c.sliders`.
- `test_action_for_each_kind_and_refusals`:
  - `command rating_3` on press → `{"type": "call", "message": "rating3", "args": []}`
  - `slider Exposure2012` on turn → `adjust`
  - `pair` on turn → `step` with both calls
  - `same` → `None`
  - `ValueError` for a slider on press, a command on turn, an unknown id, kind `key`, and `reset_dial` on turn
- `test_describe_round_trips_every_choice`: for every command, slider and pair, `describe(action_for(choice, slot))["choice"] == choice`.
- `test_describe_labels`:
  - `resetToDefault("Exposure2012")` → "Reset Exposure"
  - key shift → "Key: Shift"
  - `{"type": "call", "message": "fooBar", "args": []}` → "Lightroom: fooBar", with `choice` None
  - every action in `config/default_mapping.json` describes to a label not starting with "Lightroom:"

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_commands.py -q`
Expected: FAIL (`ModuleNotFoundError: bridge.commands`).

- [ ] **Step 3: Write `config/commands.json`** (curated from the local Adobe reference, our own labels) **and implement `bridge/commands.py`.**

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add config/commands.json bridge/commands.py tests/test_commands.py
git commit -m "Command catalog: curated Lightroom commands, dial pairs, sliders"
```

---

### Task 4: Settings server: layout, remapper changes, device use

**Files:**
- Create: `bridge/settings/layout.py`
- Modify: `bridge/settings/server.py` (`bridge/app.py` and the preview tool need no change: the new constructor arguments default)
- Test: `tests/test_settings_server.py`, `tests/test_layout.py`

**Interfaces:**
- Consumes: Task 1 mapping operations, Task 2 `Dispatcher.fn_held`, Task 3 `CommandCatalog`.
- Produces:
  - `bridge/settings/layout.py`:
    - `YOUR_BUTTONS = ["l1", "l2", "l3", "c1", "c2", "c3", "c4", "c5", "c6"]`
    - `fixed_reason(control: str, layer: str, slot: str) -> Optional[str]`. Fixed:
      - `clr_bw` press, both layers: "Keeps the photo's black & white in step with the device"
      - `export` Fn press: "Fixed: export with previous settings"
      - `p1`–`p8` normal press: "Set on the Presets tab"
    - `rows(mapping, commands: CommandCatalog, controls: Dict[str, str]) -> List[dict]`, one row per control except `fn`:
      `{"control", "name", "group": "your"|"buttons"|"dials"|"colour", "bank" (colour only: "hue"|"sat"|"lum"|"bw"), "slots": ["turn", "press"] or ["press"], "normal": {slot: describe(...)}, "fn": {slot: describe(...) or None}, "fixed": {"normal.press": reason, ...}, "note": str or None}`
      - order: your buttons, then other buttons in hardware-map order, then dials, then colour dials by bank
      - notes: `custom_mode` → "This button opens this page"; `hue`/`sat`/`lum` → "Also switches the colour dials' bank"
  - `SettingsServer(port, mapping, dispatcher, catalog, token=None, commands=None, controls=None)`: `commands` defaults to `CommandCatalog.load()`, `controls` to `HardwareMap.load().controls`.
  - After hello, the server sends `state`, then `catalog` (`commands.to_page()`), then `{"type": "layout", "rows": [...]}`.
  - New ops; each answers an `error` on refusal and otherwise broadcasts `layout`, plus `state` for `restore_defaults`:
    - `{"op": "set", "control", "layer": "normal"|"fn", "slot": "turn"|"press", "choice": {...}}`
    - `{"op": "reset", "control"}`: P buttons reset with `keep_normal_press=True`
    - `{"op": "restore_defaults"}`: keeps P1–P8 normal presses
  - Refusals: unknown control or `fn`; a slot the control doesn't have; a fixed slot; `same` in the normal layer; anything `action_for` refuses; `MappingNotWritable`; `ValueError`; `OSError` ("couldn't save …").
  - `state` slots: a P button whose normal press isn't a preset → `"status": "other"` and `"label"` from `describe`.
  - Device use replaces `pressed`:
    - a press or turn of any control except `fn` broadcasts `{"type": "used", "control", "layer": "fn"|"normal"}` (layer from `dispatcher.fn_held`); turns at most once per control per `USED_INTERVAL = 0.25` s
    - Fn press/release broadcasts `{"type": "fn", "held": bool}`

- [ ] **Step 1: Write the failing tests.** In `tests/test_layout.py`:
  - `test_rows_order_groups_and_fn`: the first nine rows are `YOUR_BUTTONS`; no `fn` row; `exposure` has slots `["turn", "press"]`, group `dials`, normal press label "Reset this dial's slider"; `export` `fixed` has `"fn.press"`; `p1` `fixed` has `"normal.press"`; `hue_red` group `colour`, bank `hue`.
  - `test_fn_column_same_as_normal_is_none`: `c3` without an Fn slot → `row["fn"]["press"] is None`.

In `tests/test_settings_server.py` (use the existing `Rig`; update the old `pressed` test to `used`):

```python
def test_set_fn_command_saves_and_broadcasts(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as a, rig.connect() as b:
                await rig.hello(a); await rig.hello(b)
                await a.send(json.dumps({"op": "set", "control": "c3", "layer": "fn", "slot": "press",
                                         "choice": {"kind": "command", "id": "rating_3"}}))
                row = next(r for r in (await rig.next(b, "layout"))["rows"] if r["control"] == "c3")
                assert row["fn"]["press"]["choice"] == {"kind": "command", "id": "rating_3"}
                assert rig.mapping.press_action("c3", fn=True)["message"] == "rating3"
    asyncio.run(main())
```

Plus, with assertions named:
- `test_connect_sends_catalog_and_layout`: after `hello` the next messages are `catalog` (contains `rating_3`) and `layout`.
- `test_set_same_clears_fn_and_slider_pair_on_dials`:
  - `same` → `press_action("c3", fn=True)` back to normal
  - exposure Fn turn `slider Contrast2012` → saved
  - d1 normal turn `pair` previous/next → a `step` action
- `test_set_refuses_what_the_page_cannot_change` (Review Focus 4): each of these → `error`, file bytes unchanged, then a valid `set` still works:
  - control `fn`
  - `clr_bw` press, either layer
  - `export` Fn press
  - `p1` normal press
  - `{"kind": "key", "key": "shift"}`
  - an unknown command id
  - a slider on `c3` press
  - `same` in the normal layer
  - an unknown control
- `test_reset_and_restore_defaults_keep_presets`: with a preset on p1 and Fn actions on p1 and c3:
  - `reset` p1 → preset kept, its Fn slot gone
  - `restore_defaults` → c3 default, p1 preset kept
  - the clients receive `layout` and `state`
- `test_restore_refused_when_mapping_unreadable`: unreadable file → `error`, file untouched.
- `test_device_use_and_fn_are_broadcast`:
  - `server.on_event(Press("fn"))` with `dispatcher` Fn held → `{"type": "fn", "held": True}`
  - `on_event(Press("c3"))` → `used` with layer `fn`
- `test_turns_are_throttled_for_the_page` (Review Focus 5): three `Turn("exposure", 1)` events within 0.1 s → exactly one `used` message (read with a short timeout).
- `test_other_action_on_a_p_button_shows_its_label`: p8 hand-mapped to `rating3` → state slot `{"status": "other", "label": "Rating: ★★★"}` (or whatever label the catalog gives `rating_3`; compare against `describe`).

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_layout.py tests/test_settings_server.py -q`
Expected: FAIL (no `bridge.settings.layout`, unknown ops, `pressed` still sent).

- [ ] **Step 3: Implement** `layout.py` and the server changes. Keep the milestone 3 security checks unchanged. Track the last `used` time per control in a dict for the throttle.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bridge/settings/layout.py bridge/settings/server.py tests/test_layout.py tests/test_settings_server.py
git commit -m "Settings server: remapper layout and changes, device use and Fn broadcast"
```

---

### Task 5: The Buttons & dials tab

**Files:**
- Create: `bridge/settings/static/remap.js`
- Modify: `bridge/settings/static/index.html`, `app.js`, `app.css`, `bridge/settings/server.py` (`FILES` gains `/remap.js`), `tools/preview_settings.py` (`--demo-device`)
- Test: `tests/test_settings_server.py` (`test_page_assets_are_local` covers `/remap.js`; add `test_serves_remap_js`)

**Interfaces:**
- Consumes: Task 4 messages (`catalog`, `layout`, `used`, `fn`) and ops (`set`, `reset`, `restore_defaults`).
- `app.js` keeps the connection and Presets tab. It routes `catalog`/`layout`/`used`/`fn` to `Remap.onMessage(msg)`, defined in `remap.js` (loaded after `app.js`, using its `send`, `el`, `$`, `notice`). It flashes P rows on `used` for `p1`–`p8`. Presets-tab slots with `status: "other"` show their `label` and no ✕.
- The tab, as chosen in the mockup (layout A):
  - Tabs **Presets** | **Buttons & dials**, the choice kept in `localStorage` (try/catch).
  - A table with columns Normal and With Fn held, for "Your buttons" first. "Other buttons", "Dials" and "Colour dials" (sub-headed by bank) are collapsible sections, closed by default.
  - Dials show Turn and Click in each cell. An Fn cell that's `null` shows "Same as normal" dimmed.
  - Clicking a cell selects that control, layer and slot. A `used` message selects the control (layer from the message) only while this tab is showing. An `fn` message switches the selected layer.
  - The editor shows:
    - the control name and a layer toggle
    - for dials, a slot toggle
    - a search box and a grouped list of choices for the slot: commands, or sliders and pairs, plus Reset this dial's slider for dial clicks, Nothing, Same as normal in the Fn layer, and Open this settings page for presses
    The current choice is marked. Clicking a choice sends `set`.
  - Fixed slots show their reason instead of choices. A row's `note` shows in the editor. Custom mode needs a second click ("Click again to change the button that opens this page").
  - **Reset** sends `reset`. **Restore default layout** needs a second click whose text says P1–P8 presets are kept.
  - When not `writable`, choices are disabled and the existing notice shows.
  - Built with DOM APIs and `textContent` only, as `app.js` is.
- `tools/preview_settings.py --demo-device`: every 4 s, it simulates holding Fn, using `c3`, then releasing Fn, by calling `server.on_event` with a fake `fn_held`. This lets the browser check exercise selection.

- [ ] **Step 1: Write the failing test** `test_serves_remap_js` (GET `/remap.js` → 200, `text/javascript`), and extend `test_page_assets_are_local` to fetch it.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings_server.py -q -k "remap or assets"`
Expected: FAIL (404).

- [ ] **Step 3: Implement** the files above. `node --check` both scripts.

- [ ] **Step 4: Verify in the built-in browser** with `.venv/bin/python tools/preview_settings.py --demo-device` (http://127.0.0.1:7691/). Checks:
  - the tab shows, and the choice survives a reload
  - set C3's Fn action to Rating ★★★ and see it in a second tab
  - Same as normal clears it
  - a slider and a pair on a dial
  - fixed slots can't be changed
  - Reset and Restore default (presets kept)
  - the demo's Fn + C3 selects C3's Fn cell
  - the custom mode warning
  - the Presets tab still works
  Then run the suite: `.venv/bin/python -m pytest -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add bridge/settings/static bridge/settings/server.py tools/preview_settings.py tests/test_settings_server.py
git commit -m "Settings page: Buttons & dials tab with Fn layer"
```

---

### Task 6: Check the commands against Lightroom; docs; live check

**Files:**
- Create: `tools/lr_check_commands.py`
- Modify: `README.md` (Buttons & dials, Fn layers, Fn + Export, clr/bw fixed), `docs/FINDINGS.md` (the Fn capture; command check results; live check), `config/commands.json` (fixes the check finds)

**Interfaces:**
- `tools/lr_check_commands.py [--group NAME] [--port N]`: registers with the saved client ID like the bridge does, so there's no new Allow dialog. It sends each catalog command in the chosen groups once, 0.5 s apart, and prints `ok` / `refused (<reply>)` per id. It never sends `exportWithPrevious`.

- [ ] **Step 1: Write the tool.** No unit test: it's a manual live tool, like `tools/lr_verify_writes.py`. It reuses `bridge.lightroom` and `bridge.commands`.

- [ ] **Step 2: Run it on the user's test photo, with their go-ahead,** one group at a time. The user watches Lightroom and tells you anything that did something unexpected. Remove or fix any refused or surprising command in `commands.json`, and rerun the suite.

- [ ] **Step 3: Docs.** The README gets a "Buttons & dials" section covering:
  - selecting a control, including from the device
  - Fn layers and "same as normal"
  - Fn + Export
  - clr/bw being fixed
  - dial clicks resetting what the dial adjusts
  - Reset and Restore default
  - the page can't create keyboard keys
  Tick roadmap item 4. FINDINGS gets the Fn capture result and the command check.

- [ ] **Step 4: Restart the user's bridge (`tools/bridgectl restart`) and run the live check with them:**
  1. Their existing presets still work, and dial clicks still reset.
  2. Assign Fn actions to L1–L3 and C1–C6 from the page and use them.
  3. Release Fn before the button.
  4. Use a control on the device to select it.
  5. Fn + Export exports with the previous settings (on the test photo).
  6. clr/bw still keeps the lights and photo in step, with and without Fn.
  7. Reset and Restore default keep the presets.

  Record the results in FINDINGS.

- [ ] **Step 5: Commit**

```bash
git add tools/lr_check_commands.py README.md docs/FINDINGS.md config/commands.json
git commit -m "Milestone 4: command check tool, docs, live-check results"
```
