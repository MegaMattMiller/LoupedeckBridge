# Milestone 9: Reload the Layout from Its File — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A **Reload from file** button in the settings page, and saves that re-read `mapping.json` first, so a layout
synced from another machine can be picked up without a restart and is never undone by a later edit.

**Architecture:** `Mapping` gains `reload()`, and `_edit()` re-reads the file before applying a change; both share one
file reader. The settings server gets a `reload` request that calls it, looks the P1–P8 presets up again and refreshes
every open tab; saves that brought in outside changes do the same. The page gets one button and two result lines.

**Tech Stack:** Python 3.9+ (`bridge/mapping.py`, `bridge/settings/server.py`), the settings page's plain JS/HTML/CSS
(`bridge/settings/static/`), pytest with a real websockets client.

**Spec:** `docs/superpowers/specs/2026-11-22-m9-layout-reload-design.md`

## Global Constraints
- The repo's Python stays compatible with Python 3.9. No new dependencies.
- Name UTF-8 in every text read and write; reads accept a BOM (`utf-8-sig`). `tests/test_text_io.py` checks.
- The settings page stays local: no inline script (the CSP forbids it), no `innerHTML`, no outside URLs
  (`test_page_assets_are_local`).
- A file that can't be read is never overwritten.
- Copy, exactly:
  - button: `Reload from file`
  - changed: `Reloaded the layout from <file>.`
  - unchanged: `<file> hasn't changed since it was read.`
  - unreadable on reload: `<file> couldn't be read (<error>); the layout in use was kept`
  - refused save (MappingNotWritable): `<file> couldn't be read, so it won't be overwritten; fix or delete it, then
    click Reload from file in the settings page`
  - the page's not-writable notice: `Your mapping.json couldn't be read, so changes can't be saved. Fix or delete it,
    then click Reload from file.`
- Version: v0.8.0.
- Tests on Windows: `.venv\Scripts\python -m pytest -q <files>`; the whole suite takes about 4 minutes (run it in the
  background). On the Mac: `.venv/bin/python -m pytest -q`.
- Commits: Conventional Commits, one or more per task, local. Ask before every push.

## Review Focus
1. **A key held through a reload:** a Loupedeck button holding Shift while a reload changes that button's action must
   still let Shift go when released (held keys are remembered by physical control). Test in Task 1.
2. **A file fixed after an unreadable start:** the bridge started with a broken `mapping.json` (layout = default, not
   writable). After a fix, Reload must make it the layout and writable, and the page's warning must go. Tests in
   Tasks 1 and 2.
3. **A file deleted after start, then a save:** the save is refused, and nothing is created; Reload then recreates it
   from the default. Test in Task 1.
4. **Reload while Lightroom is closed:** the layout still reloads, and the presets are looked up when Lightroom comes
   back. Test in Task 2.
5. **A hand edit saved by Notepad (with a BOM):** Reload and saves read it like the start does. Test in Task 1.

---

### Task 1: `Mapping.reload()` and saves that re-read the file

**Files:**
- Modify: `bridge/mapping.py` (`load`, `_edit`, the four public save methods, `MappingNotWritable`'s message)
- Test: `tests/test_mapping.py`, `tests/test_actions.py`

**Interfaces:**
- Produces:
  - `class MappingUnreadable(Exception)`: str() is `"<file> couldn't be read (<error>); the layout in use was kept"`.
  - `Mapping.reload(self) -> bool`: what a start does with the file (recreate it from the default if missing, follow
    a new default, read it), in place. Returns True when the file's contents differ from the layout in use (always
    True when the layout in use was the fallback for an unreadable file). Raises `MappingUnreadable` and changes
    nothing when the file can't be read. Updates `self.warnings` and logs them, as `load()` does.
  - `set_action(...) -> bool`, `set_press_action(...) -> bool`, `reset_control(...) -> bool`,
    `restore_defaults(...) -> bool`: True when the file had changed on disk since it was last read (the save brought
    those changes in). Each still raises `MappingNotWritable` when the file can't be read now, and `ValueError` /
    `OSError` as today.
  - `Mapping.writable` is True once a read succeeds (load, reload or save).

- [ ] **Step 1: Write the failing tests** in `tests/test_mapping.py` (use its `write()` helper and `PRESET`):
  - `test_reload_picks_up_a_changed_file`: load; rewrite the file with `p1`'s press = `PRESET`; `reload()` is True,
    and `press_action("p1") == PRESET`.
  - `test_reload_of_an_unchanged_file_says_so`: `reload()` right after `load()` is False.
  - `test_reload_keeps_the_layout_when_the_file_is_unreadable`: load a good file; write `"{not json"`; `reload()`
    raises `MappingUnreadable` whose message contains `"couldn't be read ("` and `"the layout in use was kept"`; the
    old `press_action("p1")` is still returned, `writable` is still True, and the file is still `"{not json"`.
  - `test_reload_after_a_fix_makes_the_file_writable`: load `"{not json"` (`writable` False); write a good file;
    `reload()` is True and `writable` is True.
  - `test_reload_recreates_a_missing_file_from_the_default`: load; delete the file; `reload()` recreates it, and its
    controls equal the default's.
  - `test_reload_reads_a_file_saved_with_a_bom`: write the file as `utf-8-sig` with `p1` = `PRESET`; `reload()`
    gives `press_action("p1") == PRESET`.
  - `test_save_applies_the_change_to_the_file_on_disk`: `a = Mapping.load(path)`; another writer saves `p2` =
    `PRESET`; `a.set_press_action("p3", {**PRESET, "id": "B"})` returns True; the file holds both, and
    `a.press_action("p2") == PRESET`.
  - `test_save_without_outside_changes_returns_false`: a save straight after load returns False.
  - `test_save_refused_when_the_file_became_unreadable`: load; write `"{not json"`; `set_press_action` raises
    `MappingNotWritable` (message contains `"then click Reload from file"`); the file is still `"{not json"`.
  - `test_save_refused_when_the_file_was_deleted`: load; delete; `set_press_action` raises `MappingNotWritable`, and
    the file still doesn't exist.

  And in `tests/test_actions.py`:
  - `test_key_held_through_a_reload_is_released`: use `setup(tmp_path, controls=..., keyboard=FakeKeyboard())` with
    a control whose press is `{"type": "key", "key": "shift"}`. Press it. Rewrite the file with that control's press
    = `{"type": "none"}`, then `reload()` the dispatcher's mapping. Release it: `FakeKeyboard` saw Shift go up.

- [ ] **Step 2: Run them and watch them fail**

  Run: `.venv\Scripts\python -m pytest -q tests/test_mapping.py tests/test_actions.py`
  Expected: FAIL. `reload` / `MappingUnreadable` don't exist, and the saves return None and write the old copy.

- [ ] **Step 3: Implement in `bridge/mapping.py`**
  - **One reader:** `_read_doc(path: Path) -> dict` reads `utf-8-sig`, parses, and checks that `controls` is an
    object. It raises what `load()` catches today: `OSError`, `ValueError`, `KeyError` and `TypeError`. `load()`,
    `reload()` and `_edit()` all use it.
  - **`reload()`:** runs `load()`'s file steps (create if missing, `_follow_new_default`), then `_read_doc`, then
    swaps in `_doc`, `_controls` and `warnings`. Compare the new doc with the old `_doc` for the return value.
  - **`_edit()`:** re-reads with `_read_doc`. On failure it raises `MappingNotWritable` with the new message, before
    writing anything. It applies `change` to the fresh doc, writes it atomically, and only then swaps `_doc` and
    `_controls`. It returns whether the fresh doc differed from the old `_doc`. The four public methods return
    `_edit`'s result.

- [ ] **Step 4: Run the tests**

  Run: `.venv\Scripts\python -m pytest -q tests/test_mapping.py tests/test_actions.py tests/test_text_io.py`
  Expected: PASS, including the existing `test_failed_save_leaves_no_phantom_change` and
  `test_unreadable_file_is_never_overwritten`.

- [ ] **Step 5: Commit**: `feat(mapping): reload the layout from its file, and re-read it before each save`

---

### Task 2: The settings page's Reload from file

**Files:**
- Modify: `bridge/settings/server.py` (`_handle`, the assign/clear path, `_remap`), `bridge/settings/static/index.html`,
  `bridge/settings/static/app.js`, `bridge/settings/static/app.css`
- Test: `tests/test_settings_server.py`

**Interfaces:**
- Consumes: Task 1's `Mapping.reload() -> bool`, `MappingUnreadable`, and the save methods' `-> bool`.
- Produces:
  - **The request:** `{"op": "reload"}`. It runs `mapping.reload()`, then `await dispatcher.reload_presets()`, then
    sends `state` and `layout` to every tab. Last, it sends `{"type": "reloaded", "changed": bool, "file": "<name>"}`
    to the tab that asked, after the broadcasts, since `onState` clears the notice line.
  - **If the file can't be read:** `{"type": "error", "message": str(MappingUnreadable)}` to that tab, with nothing
    broadcast.
  - **The log:** `reloaded <file> (changed)` or `reloaded <file> (unchanged)`.
  - **Saves** (assign/clear and the three `_remap` requests): when the save method returns True, the server also runs
    `reload_presets()` and broadcasts `state` and `layout`.

- [ ] **Step 1: Write the failing tests** in `tests/test_settings_server.py` (with its `Rig`, which writes the file
  at `rig.path`):
  - `test_reload_sends_the_new_layout_to_every_tab`: tabs a and b. Rewrite the file with p2 =
    `{"type":"preset","id":"ID-WARM","name":"Warm"}`. Tab a sends `reload`. Tab b gets a `state` whose p2 id is
    `"ID-WARM"`, and a `layout`. Tab a gets `{"type": "reloaded", "changed": True, "file": "m.json"}`.
  - `test_reload_of_an_unchanged_file_says_so`: `reloaded` with `changed` False.
  - `test_reload_of_an_unreadable_file_keeps_the_layout`: write `"{not json"`, then `reload` gives an `error`
    containing `"the layout in use was kept"`. A following `assign` still fails with `"couldn't be read"`. The file
    is unchanged.
  - `test_reload_after_fixing_the_file_makes_it_writable`: `Rig(mapping_text="{not json")`, so the state says
    `writable` False. Write a good file and send `reload`: the next `state` says `writable` True, and an `assign` to
    p1 is saved.
  - `test_reload_works_while_lightroom_is_closed`: `Rig(connected=False)`, then rewrite and `reload`: `reloaded`
    says `changed` True.
  - `test_a_save_brings_in_outside_changes`: an outside writer sets p3 = Warm, then the tab sends a `set` for another
    control. The broadcast `state` shows p3 `"ID-WARM"`, so the presets were looked up again.
  - `test_page_has_a_reload_button`: `/` holds `id="reload"` with text `Reload from file`, after `</nav>` (outside
    the tablist). `/app.js` holds `op: "reload"`, `"reloaded"`, `Reloaded the layout from`, `hasn't changed since it
    was read` and `then click Reload from file.`.

- [ ] **Step 2: Run them and watch them fail**

  Run: `.venv\Scripts\python -m pytest -q tests/test_settings_server.py`
  Expected: FAIL. `reload` is an "unknown request", and the page has no button.

- [ ] **Step 3: Implement**
  - **`server.py`:** the `reload` request as in Interfaces, and the extra refresh after saves that brought changes.
  - **`index.html`:** put the tabs in a `div class="tabbar"` with the `nav` and a
    `<button id="reload" type="button" class="link" title="Read mapping.json again, e.g. after Syncthing brought a
    change from another machine">Reload from file</button>`.
  - **`app.css`:** `.tabbar` is a wrapping flex row: the tabs on the left, the button on the right. It carries the
    border line the `.tabs` has now.
  - **`app.js`:** the button sends `{op: "reload"}`. A `reloaded` message shows the changed or unchanged line in the
    notice. The not-writable notice gets its new copy.

- [ ] **Step 4: Run the tests**

  Run: `.venv\Scripts\python -m pytest -q tests/test_settings_server.py tests/test_layout.py`
  Expected: PASS.

- [ ] **Step 5: See it in a browser.** Run `.venv\Scripts\python -m bridge --debug` and open the settings page. Check
  that the button sits at the right of the tab row, and wraps below the tabs at phone width. Click it: "mapping.json
  hasn't changed since it was read." Edit the file, then click it: "Reloaded the layout from mapping.json.", and the
  change shows.

- [ ] **Step 6: Commit**: `feat(settings): a Reload from file button`

---

### Task 3: Docs and v0.8.0

**Files:**
- Modify: `README.md` (the settings page section; a new "Syncing a layout between machines" section; roadmap item 9),
  `docs/FINDINGS.md`, `CHANGELOG.md` (`## v0.8.0`), `bridge/__init__.py` (`0.8.0`), `CLAUDE.md` (only if a trap
  came up)

- [ ] **Step 1: The README:**
  - **Reload from file:** what it does, and when to use it (after a sync, or after a hand edit).
  - **Syncing a layout between machines:**
    - share the layout folder, giving each OS's path
    - the ignore patterns `!/mapping.json` then `*`, set on each machine (Syncthing never syncs them)
    - why `mapping.base.json` stays out of the sync
    - before a machine joins: quit LoupedeckBridge and move its `mapping.json` aside
    - after a change arrives: click Reload from file
  - **Roadmap:** `9. ✅ Layout sync: reload the layout from its file, and saves that never undo a synced change`.
- [ ] **Step 2: FINDINGS**, a "Milestone 9" section:
  - Lightroom gives a synced preset the same id on every machine. Checked 2026-11-22 on a Mac (Apple Silicon) and the
    Windows PC, Lightroom 10.0 on both: the same 1,572 ids and names, in the same order.
  - Syncing `mapping.base.json` makes an older version reset untouched controls; syncing only `mapping.json` doesn't.
- [ ] **Step 3: The version and changelog:** `0.8.0`, and a `## v0.8.0 — <date>` section in the CHANGELOG's style.
- [ ] **Step 4: Run the whole suite**

  Run: `.venv\Scripts\python -m pytest -q` (in the background)
  Expected: all pass, including `tests/test_check_release.py` (the version and changelog agree).

- [ ] **Step 5: Commit**: `docs: layout sync, Reload from file, and v0.8.0`

---

### Task 4: Live check on two machines (with the user)

- [ ] **Step 1: Get the branch onto the Mac.** Ask, then push `milestone-9-layout-reload`. The user pulls it on the
  Mac.
- [ ] **Step 2: Run the dev builds.**
  - **Windows:** `pwsh -File tools\bridgectl.ps1 build`, then `pwsh -File tools\bridgectl.ps1 start -Dev`.
  - **Mac:** `tools/bridgectl build`, then `tools/bridgectl start --dev`.
  - Both use the real layout folder, synced by Syncthing with the ignore patterns.
- [ ] **Step 3: The spec's live check:**
  1. Change a dial on the Mac; once it has synced, click Reload from file on the PC. The Loupedeck follows, and the
     page shows the change.
  2. Change P1 on the Mac. Before reloading on the PC, change a button there. The Mac's P1 survives on both machines.
  3. Break `mapping.json` by hand: Reload keeps the layout and says why. Fix it: Reload brings it back, with no
     restart.
- [ ] **Step 4: Record** what it proved in FINDINGS. Commit: `docs: record the two-machine layout sync check`.

---

### Task 5: v0.8.0 (after the review and the merge, the user's decisions)

- [ ] **Step 1:** The user merges to `main`, runs `tools/release.sh 0.8.0` and approves the signing run. CI must pass
  first.
- [ ] **Step 2:** "Check for updates now" on each machine finds v0.8.0, and Install works. Reload from file works in
  the release.
- [ ] **Step 3:** Record it in FINDINGS. Commit: `docs: record v0.8.0 on both machines`. Ask, then push.
