# Milestone 3: Settings Page for Presets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local page at http://127.0.0.1:7690 to search Lightroom presets and assign them to P1–P8, applied immediately.

**Architecture:** The bridge's existing `websockets` server serves the static page over GET and runs a token-protected WebSocket for every change. A `PresetCatalog` caches preset names from Lightroom. `Mapping` becomes editable (atomic saves) and follows new defaults control by control. The dispatcher re-resolves presets after each change, and device presses are broadcast to the page.

**Tech Stack:** Python ≥3.9, `websockets` 15 (server + `process_request`), stdlib `webbrowser`, plain HTML/CSS/JS (no framework, no CDN), `pytest`.

**Spec:** [docs/superpowers/specs/2026-11-16-m3-settings-presets-design.md](../specs/2026-11-16-m3-settings-presets-design.md), within [the bridge design](../specs/2026-11-16-loupedeck-bridge-design.md).

## Global Constraints

- Milestones 1–2 still hold: Python 3.9-compatible, no new runtime dependencies, Lightroom on 127.0.0.1 only, GUID never logged, live edits only on a test photo.
- Settings server: binds **127.0.0.1** only. Requests whose `Host` isn't `127.0.0.1:<port>` or `localhost:<port>` are refused. The WebSocket needs the page's own `Origin` **and** the per-run token.
- The page loads nothing from the internet.
- `mapping.json` saves are atomic (temp file + `os.replace`). An unreadable `mapping.json` is never overwritten.
- Changes apply without a restart.
- Commit after each task (local only).

## Review Focus

1. **Another website open in the browser** tries to change the mapping (cross-origin WebSocket, DNS rebinding): refused. Tests: Task 3 `test_wrong_host_refused`, `test_foreign_origin_refused`, `test_bad_token_closed`.
2. **Lightroom closed while the page is open:** the page is told "Lightroom isn't connected", nothing crashes, and slots still show. Test: Task 3 `test_presets_while_lightroom_down`.
3. **An unreadable `mapping.json`** when assigning: nothing is saved, the reason is shown, and the file is untouched. Tests: Task 1 `test_unreadable_file_is_never_overwritten`, Task 3 `test_assign_refused_when_mapping_unreadable`.
4. **Two tabs open:** both see a change made in either. Test: Task 3 `test_change_broadcast_to_all_tabs`.
5. **A preset deleted or duplicated in Lightroom after assignment:** the slot shows missing/ambiguous. Assigning from the list uses the ID, so it's never ambiguous. Tests: Task 2 `test_slot_status`, Task 3 `test_assign_by_id`.

---

### Task 1: Editable mapping, per-control default following, open_settings

**Files:**
- Modify: `bridge/mapping.py`, `config/default_mapping.json` (`custom_mode` → `{"type": "open_settings"}`)
- Test: `tests/test_mapping.py`

**Interfaces:**
- Produces:
  - `Mapping.path: Path`
  - `Mapping.set_press_action(control: str, action: dict) -> None`: validates via `_check` (raises `ValueError` on an invalid action), updates memory, and saves atomically. Raises `MappingNotWritable` if the file couldn't be read at load.
  - `class MappingNotWritable(Exception)`
  - press action `{"type": "open_settings"}`
- Default following: for each control, if `user[c] == base[c]`, then the user gets `default[c]`. A control the default dropped, and the user never changed, is removed. Controls the user changed are kept, and when the default also changed them, a notice names them. `base` becomes the new default. A file that can't be read is left alone.

- [ ] **Step 1: Write failing tests:**
  - `test_unedited_controls_follow_new_default_even_if_others_edited`: the user edited `c3`, and the default changed `before_after` → the user gets the new `before_after` and keeps `c3`.
  - `test_user_change_wins_and_is_mentioned`: the user and the new default both changed `before_after` → the user's value is kept, and a warning names `before_after`.
  - `test_set_press_action_saves_atomically`: after `set_press_action("p3", {"type":"preset","id":"A","name":"Warm"})`, a new `Mapping.load` shows it, and no temp file is left behind.
  - `test_set_press_action_rejects_invalid`: `{"type":"adjust"}` on a press raises `ValueError`, and the file is unchanged.
  - `test_unreadable_file_is_never_overwritten`: `{not json` → `set_press_action` raises `MappingNotWritable`, and the file text is unchanged.
  - `test_open_settings_action`: `custom_mode` in the default → `{"type":"open_settings"}`. `open_settings` is accepted as a press type and rejected as a turn type.
  - Replace `test_edited_mapping_is_kept_when_default_changes` (whole-file semantics) with the per-control tests above.
- [ ] **Step 2: Run them to see them fail. Step 3: Implement. Step 4: Run the whole suite. Step 5: Commit.** "Editable mapping, per-control default following, open_settings"

---

### Task 2: Preset catalog, slot status, open_settings action

**Files:**
- Create: `bridge/presets.py`
- Modify: `bridge/actions.py`
- Test: `tests/test_presets.py`, `tests/test_actions.py`

**Interfaces:**
- Produces:
  - `PresetCatalog(session, chunk=50)`:
    - `async items() -> List[Tuple[str, str]]` gives (id, name) for every preset. It calls `getPresetIDs`, then `getPresetName` concurrently in chunks of `chunk`. The result is cached.
    - `invalidate() -> None`.
  - `Dispatcher(..., catalog=None, opener=webbrowser.open, settings_url=None)`:
    - `Dispatcher.resolve_presets()` uses the catalog for names, and invalidates it first (Lightroom may have new presets).
    - `Dispatcher.slot_status(control) -> dict` returns `{"slot", "id", "name", "status": "empty"|"ok"|"missing"|"ambiguous"|"unknown"}`. It's `"unknown"` before any resolve.
    - `Dispatcher.reload_presets() -> None` (async): re-resolves after a mapping change.
  - An `open_settings` press calls `opener(settings_url)` (one info log if `settings_url` is None). It works without Lightroom, like keys.

- [ ] **Step 1: Write failing tests:**
  - `test_catalog_fetches_names_in_chunks_and_caches`: 120 ids, `chunk=50` → 1 + 120 calls the first time, 0 the second time; after `invalidate`, it fetches again.
  - `test_catalog_raises_when_disconnected` (`ConnectionError` passes through).
  - `test_slot_status`: covers `empty` / `ok` / `missing` / `ambiguous`.
  - `test_open_settings_opens_url` (fake opener; works while disconnected).
  - The existing preset tests still pass using the catalog.
- [ ] **Step 2: Run them to see them fail. Step 3: Implement. Step 4: Run the whole suite. Step 5: Commit.** "Preset catalog, slot status and open_settings"

---

### Task 3: Settings server

**Files:**
- Create: `bridge/settings/__init__.py`, `bridge/settings/server.py`
- Modify: `bridge/app.py` (`build(..., settings_port=None)`; `App.run` runs the server and passes every event to it), `bridge/__main__.py` (`--settings-port`, default 7690), `tools/bridgectl` (`settings`)
- Test: `tests/test_settings_server.py`

**Interfaces:**
- Produces:
  - `SettingsServer(port, mapping, dispatcher, catalog, token=None)` with:
    - `async serve()` (runs forever; if the port is busy, logs an error and returns without stopping the bridge)
    - `url: str` (e.g. `http://127.0.0.1:7690/`)
    - `on_event(event)`, which broadcasts presses of `p1`–`p8`
  - The token is `secrets.token_urlsafe(24)` unless one is given.
- HTTP (via `process_request`): `GET /` → `static/index.html` with `__TOKEN__` replaced. `GET /app.js` and `GET /app.css` → static files. `/ws` → the WebSocket. Anything else → 404. A wrong `Host` → 403 for every path. The WebSocket uses `origins=[f"http://127.0.0.1:{port}", f"http://localhost:{port}"]`.
- WebSocket messages (JSON):
  - The client's first message must be `{"op":"hello","token":…}`, otherwise the server closes with 1008.
  - Server → client:
    - `{"type":"state","slots":[slot_status…],"writable":bool,"settings_url":…}` after hello and after every change, broadcast to all clients
    - `{"type":"presets","items":[[id,name]…]}` or `{"type":"error","message":…}` in answer to `{"op":"presets"}`
    - `{"type":"pressed","slot":"p3"}` on a device press
  - Client → server:
    - `{"op":"assign","slot":"p3","id":…,"name":…}`
    - `{"op":"clear","slot":"p3"}`
    - Both are validated (slot in p1–p8; `id`/`name` are strings). Either answers `state`, or `error` with a message.

- [ ] **Step 1: Write failing tests** (real `websockets` client against the server on a free port; real `Mapping` in `tmp_path`; real `Dispatcher` with a fake session):
  - `test_serves_page_with_token`
  - `test_wrong_host_refused` (`Host: evil.example:PORT` → 403)
  - `test_foreign_origin_refused`
  - `test_bad_token_closed`
  - `test_presets_list`
  - `test_presets_while_lightroom_down`
  - `test_assign_by_id` (an assignment saves `mapping.json`, and pressing `p3` then sends `applyPreset` with that id)
  - `test_clear_slot`
  - `test_assign_refused_when_mapping_unreadable`
  - `test_change_broadcast_to_all_tabs`
  - `test_device_press_highlights_slot`
  - `test_port_busy_does_not_stop_bridge`
- [ ] **Step 2: Run them to see them fail. Step 3: Implement. Step 4: Run the whole suite. Step 5: Commit.** "Settings server: page, token-protected WebSocket, live updates"

---

### Task 4: The page

**Files:**
- Create: `bridge/settings/static/index.html`, `app.js`, `app.css`
- Modify: `README.md` (a "Settings page" section)
- Test: `tests/test_settings_server.py` (`test_page_assets_are_local`)

**Interfaces:**
- Consumes: Task 3's WebSocket messages.
- The page:
  - **Slot column:** P1–P8, each with a name or "empty" and a warning badge for missing/ambiguous. Click a slot to select it; ✕ clears it.
  - **Preset column:** a search box filtering by case-insensitive substring, with up to 200 results shown. Click a result to assign it to the selected slot.
  - **Status line:** connected or reconnecting; "Lightroom isn't connected"; "can't save: mapping.json unreadable". Device presses flash their slot.
  - The WebSocket reconnects every 2 s if dropped.
  - Theme-aware light/dark CSS, and it works at phone width.

- [ ] **Step 1: Write the failing test** `test_page_assets_are_local`: the served HTML/JS/CSS contain no `http://` or `https://` URL except `127.0.0.1`/`localhost`, and the HTML references `/app.js` and `/app.css`.
- [ ] **Step 2: Run it to see it fail. Step 3: Implement the page. Step 4: Run the whole suite. Step 5: Commit.** "Settings page UI"

---

### Task 5: Live check, review, finish

- [ ] **Step 1:** Restart the app (`tools/bridgectl restart`). Open the page with `tools/bridgectl settings` **and** with the custom mode button.
- [ ] **Step 2:** With the user:
  - search, assign 2–3 presets, then press those P buttons (on the test photo; undo afterwards)
  - clear a slot
  - two tabs: a change in one shows in the other
  - quit Lightroom: the page says so; reopen it: the presets load again
  - press a P button: its slot flashes
- [ ] **Step 3:** Record the results in FINDINGS; fix any issues test-first.
- [ ] **Step 4:** Final whole-branch review (fresh reviewer), then a fix pass, then finish the branch.
