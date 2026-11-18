# Milestone 7: Windows, with a Tray App and Releases for Friends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The bridge on Windows with everything the Mac has, a C# tray app just like the Mac's menu-bar app, and
signed Windows releases that friends install with one PowerShell command, with no admin rights, and update from the tray.

**Architecture:**
- **The shared Python** gains:
  - a `SendInput` keyboard (`bridge/platform/windows_keys.py`)
  - pipe-based stop and status for Windows (`bridge/instance.py`, `bridge/status.py`)
  - a "Loupedeck busy" state (`bridge/midi_input.py`)
  - UTF-8 everywhere
- **The tray app** (`windows/launcher/`, C# on .NET Framework 4.8) mirrors `macos/launcher/`:
  - pure, tested `Policies.cs` (ported from `Policies.swift`), and `Signature.cs`
  - the I/O: `BridgeProcess.cs`, `TrayApp.cs`, `Updater.cs`, `Swap.cs`
- **The release** is a folder (`LoupedeckBridge.exe` + `LoupedeckBridge.json` + `python\` + `app\`), zipped:
  - built and tested on a GitHub Windows runner
  - signed on the existing macOS signing job with a detached CMS signature (`.p7s`) from the same release key
  - checked by the tray app and `tools/install.ps1` against the pinned certificate SHA-256

**Tech Stack:**
- Python ≥3.9 (repo) / 3.12 (release, python-build-standalone `x86_64-pc-windows-msvc`), `ctypes`/`msvcrt`
- C# (`LangVersion` latest) on .NET Framework 4.8: WinForms, `System.Security` (`SignedCms`), `System.Net.Http`,
  `System.Web.Extensions` (`JavaScriptSerializer`); built with `dotnet build` and no NuGet packages
- PowerShell 7 (build scripts, `bridgectl.ps1`) and Windows PowerShell 5.1 (`install.ps1`)
- `openssl smime` (LibreSSL on macOS, OpenSSL 3 from Git for Windows), GitHub Actions (`windows-2025`, `macos-15`),
  pytest

**Spec:** [docs/superpowers/specs/2026-11-17-m7-windows-design.md](../specs/2026-11-17-m7-windows-design.md), within
[the bridge design](../specs/2026-11-16-loupedeck-bridge-design.md) and after
[milestone 6](../specs/2026-11-17-m6-mac-releases-design.md).

## Global Constraints

- Windows 10 (22H2) and 11, x64. Install, update and uninstall without admin.
- The tray app uses only .NET Framework 4.8 (WinForms, `System.Security` for `SignedCms`), with no NuGet packages.
- No new runtime dependencies for the bridge. The repo's Python stays 3.9-compatible; the release bundles 3.12.
- The bridge connects and serves on 127.0.0.1 only.
- Only the tray app talks to the internet: `api.github.com` and GitHub's release downloads. It sends
  `User-Agent: LoupedeckBridge/<version>`. Dev builds never check for updates.
- The version sent to Lightroom on register stays `"0.1"` (`bridge/app.py` `APP_VERSION`).
- **Cmd sends Ctrl on Windows.**
- Names: the release is "LoupedeckBridge" and the dev build "LoupedeckBridge Dev". The install folder is
  `%LOCALAPPDATA%\Programs\LoupedeckBridge\`, with siblings `LoupedeckBridge.new\` and `LoupedeckBridge.previous\`.
- **The downloads in each release**, all under one version tag:
  - `LoupedeckBridge-v<ver>-windows-x64.zip`, `<same>.sha256`, `<same>.p7s`
  - the Mac's `LoupedeckBridge-v<ver>-macos-arm64.zip` and `<same>.sha256`
- The pinned release certificate SHA-256 is `4927ccbb8cc8c7e3c32afa79d58f11f2129b84b3c7638cb530cb2ced0faa2cf4`, in both
  `tools/install.sh` and `tools/install.ps1`.
- **An install or update is accepted only if every check passes,** and nothing is replaced until they all do:
  - the SHA-256 matches its `.sha256`
  - the `.p7s` verifies over the zip's exact bytes (signature only), and its signer certificate's SHA-256 (DER) equals
    the pinned one
  - the zip holds exactly one `LoupedeckBridge\` folder, with `LoupedeckBridge.exe` and a bundled, non-dev
    `LoupedeckBridge.json`, and no unsafe paths
  - the version is the one asked for, and newer unless `-AllowOlder`
- **New build-time downloads** (the approved design covers them): the python-build-standalone Windows build and the
  four Windows wheels, pinned by SHA-256.
- **The signing key** stays in the GitHub `release` environment, usable only in the signing step of a run the user
  approved. Never run `tools/make_signing_identity.sh` locally (CI's `--out` throwaway runs are the existing
  practice), never handle the key, never replace it.
- `install.ps1` runs on Windows PowerShell 5.1.
- **Lightroom:** read only `connections.json`. Try live edits only on a test photo, after the user says go.
- **Commits:** Conventional Commits, local only, after each task.
  - Commits are GPG-signed: tell the user when a Pinentry passphrase prompt is waiting.
  - Ask before every push and tag. Before pushing, check the outgoing commits for the client ID, Adobe's docs, build
    output, personal paths and email addresses.
- Commands on this PC: `.venv\Scripts\python -m pytest -q` (the venv exists: Python 3.11). Build scripts run in `pwsh`.
- **Order:** Tasks 1–10 on branch `milestone-7-windows`, then the whole-branch review, then Tasks 11–12 (merge and
  release, with the user). Tasks 4 and 6 are live checks with the user on the real device and Lightroom.

## Review Focus

1. **Non-ASCII text and paths on Windows:** a user folder like `C:\Users\Zoë Ünal`, a `mapping.json` hand-edited in
   Notepad (UTF-8, maybe with a BOM), preset names with emoji. All are read and written as UTF-8, with no crash, and
   paths with spaces survive the command lines the tray app builds. Tests:
   - Task 1: `test_text_io_names_utf8`, `test_mapping_reads_utf8_with_bom`
   - Task 9: `command_line_quotes_paths`
2. **A key stuck after the bridge or the tray app is killed mid-hold** (Task Manager → End task): every key is let
   go. Tests:
   - Task 3: `test_closed_control_pipe_stops_cleanly`
   - Task 5: `quit_after_forced_kill_releases_keys`
   - Task 6: `test_tray_releases_every_holdable_key`
3. **The Loupedeck held by the Loupedeck or Logi software** (e.g. it starts at login): the menu says "in use by
   another program", the bridge keeps retrying, and there's no crash-restart loop. Tests:
   - Task 3: `test_busy_port_is_retried_and_reported`, `test_busy_clears_when_unplugged`
   - Task 5: `problem_text_names_busy`
4. **A crafted or tampered download:** another key, a changed byte, `..\` or absolute entry names, an extra folder,
   no exe. It's refused and nothing is replaced. Tests:
   - Task 8: `zip_layout_refuses_unsafe_paths`, `signature_refuses_*`
   - Task 9: `test_install_refuses_unsafe_zip_paths`, `test_install_refuses_wrong_signature`
5. **An update interrupted midway** (the download fails, the copy fails, the new copy doesn't start): the old version
   keeps running or is put back, and the user is told which step failed. Tests:
   - Task 9: `swap_failure_puts_the_old_back`, `test_failed_copy_puts_back_and_restarts_the_old_app`

---

### Task 1: The suite on Windows (UTF-8, line endings, Mac-only tests)

**Files:**
- Create: `.gitattributes`, `tests/test_text_io.py`
- Modify: every text read/write found by the new test, in:
  - `bridge/`: `commands.py`, `hardware.py`, `instance.py`, `lightroom.py`, `mapping.py`, `presets.py`,
    `settings/server.py`, `status.py`, `__main__.py`
  - `tools/`: `check_release.py`, `find_unknown.py`, `lr_dump_params.py`, `midi_dump.py`, `summarize_capture.py`
- Modify also:
  - `bridge/platform/macos_ax.py`: load ApplicationServices on first use, so importing `macos_keys` works on Windows
  - `tests/test_bridgectl.py`, `tests/test_install_script.py`: `pytestmark = skipif(sys.platform != "darwin")`
  - `tests/test_platform.py`: set `USERPROFILE` as well as `HOME`; `Path.home()` reads `USERPROFILE` on Windows
  - `.gitignore`: `windows/**/bin/`, `windows/**/obj/`
  - `.github/workflows/ci.yml`: a new job, `suite-windows`
  - `CLAUDE.md`: the Windows setup and test commands
- Test: `tests/test_text_io.py`, `tests/test_mapping.py`, and the existing tests that fail on Windows today:
  - `test_settings_server.py::test_serves_page_with_token`, `::test_page_assets_are_local` (HTTP 500: cp1252)
  - `test_layout.py::test_five_section_rows` (★ misread)
  - `test_platform.py::test_macos_paths`
  - the `test_macos_keys.py` collection error

**Interfaces:**
- Produces:
  - **The text I/O rule:** every text read or write in `bridge/` and `tools/` names its encoding:
    - JSON reads use `encoding="utf-8-sig"` (a BOM from Notepad is accepted)
    - everything else uses `"utf-8"`
    - this covers `RotatingFileHandler(..., encoding="utf-8")` and `os.fdopen(..., encoding="utf-8")`
  - **`.gitattributes`:**
    ```
    * text=auto eol=lf
    *.zip binary
    *.ico binary
    *.png binary
    ```

- [ ] **Step 1: Line endings.** Add `.gitattributes` and commit it alone (`chore: keep LF line endings on Windows
  checkouts`). With `git status` clean, run `git rm -rq --cached . && git reset -q --hard`; the tree is clean, so
  nothing is lost. Expected: Git Bash's `file tools/release.sh` no longer says "CRLF".
- [ ] **Step 2: Write the failing tests:**
  - `test_text_io_names_utf8`: walk the AST of `bridge/**/*.py` and `tools/*.py`. It fails, listing `file:line`, for
    any of these called without an `encoding=` keyword and without a mode string containing `"b"`:
    - `open(...)`, and `<x>.open(...)` where `x` isn't `os` or `webbrowser`
    - `.read_text()`, `.write_text()`
    - `os.fdopen(...)`, `RotatingFileHandler(...)`
  - `test_mapping_reads_utf8_with_bom` (Review Focus 1), in `tests/test_mapping.py`:
    - the setup: a temp folder named `Zoë Ünal x`, holding a user `mapping.json` written as `"\ufeff" + json` with a
      literal preset name `"Café ☕ ★"` on `p1`
    - `Mapping.load(path)` keeps that name, and has no warnings
- [ ] **Step 3: Run to verify they fail:** `.venv\Scripts\python -m pytest -q`. Expected: the two new tests and the
  four existing ones above fail, and `test_macos_keys.py` errors at collection.
- [ ] **Step 4: Implement** the rule, the lazy `macos_ax` load, the skip marks, `USERPROFILE`, and `.gitignore`.
- [ ] **Step 5: Run the whole suite** → all pass on Windows (the Mac-only ones skip).
- [ ] **Step 6: CI.** Add job `suite-windows` to `ci.yml`:
  - `runs-on: windows-2025`, the same pinned `checkout`/`setup-python` SHAs, and `python-version: "3.9.13"`
  - steps: `python -m venv .venv`, `.venv\Scripts\python -m pip install -r requirements-dev.txt`,
    `.venv\Scripts\python -m pytest -q`
  CLAUDE.md "Commands" gains:
  `py -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt` and `.venv\Scripts\python -m pytest -q`.
- [ ] **Step 7: Commit:** `fix: read and write text as UTF-8, and run the suite on Windows`.

---

### Task 2: Keyboard keys on Windows (SendInput; Cmd sends Ctrl)

**Files:**
- Create: `bridge/platform/windows_keys.py`, `tests/test_windows_keys.py`
- Modify:
  - `bridge/platform/windows.py`: `keyboard()` returns `WindowsKeyboard()`
  - `bridge/commands.py`: the Cmd label on Windows
  - `tests/test_commands.py`

**Interfaces:**
- Produces:
  - **`windows_keys.VK: Dict[str, int]`:** the same names as `macos_keys.KEYCODES`, with US-layout virtual-key
    codes:
    - modifiers: `shift` 0x10, `ctrl` 0x11, `alt` 0x12, **`cmd` 0x11**
    - `tab` 0x09, `space` 0x20, `return` 0x0D, `escape` 0x1B, `delete` 0x08
    - arrows: `left` 0x25, `up` 0x26, `right` 0x27, `down` 0x28
    - `f1`–`f12` 0x70–0x7B; letters and digits are their ASCII capitals
    - punctuation: `=` 0xBB, `-` 0xBD, `]` 0xDD, `[` 0xDB, `'` 0xDE, `;` 0xBA, `\` 0xDC, `,` 0xBC, `/` 0xBF,
      `.` 0xBE, `` ` `` 0xC0
  - **`HOLDABLE_VKS = (0x10, 0x11, 0x12, 0x09, 0x25, 0x26, 0x27, 0x28)`:** every key the bridge can hold. Task 6's
    tray app lets go of exactly these.
  - **`MENU_MASK_VK = 0xE8`** (unassigned).
  - **`class WindowsKeyboard`:**
    - `__init__(self, send: Optional[Callable[[int, bool], None]] = None)`; the default sender is `_send_input(vk,
      down)`
    - methods `key_down(name)`, `key_up(name)`, `key_repeat(name)`, `tap(keys: List[str])`, `is_trusted() -> True`,
      `close()`
    - unknown names raise `ValueError`, like `MacKeyboard`
    - **reference counts per code:** Ctrl and Cmd share 0x11, which goes down on the first press and up on the last
      release
    - **Alt's release is masked:** `MENU_MASK_VK` down and up just before Alt up, so an Alt tap never focuses
      Lightroom's menu bar
  - **`_input_for(vk: int, down: bool)`** returns the `INPUT` struct: the scan code from `MapVirtualKeyW`,
    `KEYEVENTF_EXTENDEDKEY` for the arrows, `KEYEVENTF_KEYUP` on up. `_send_input` passes it to `SendInput`.
  - **`commands.key_labels(platform: str = sys.platform) -> Dict[str, str]`:** `KEY_LABELS`, with `cmd` →
    `"Cmd (sends Ctrl)"` on `win32`. The action label (`commands.py:140`) uses it.

- [ ] **Step 1: Write the failing tests**, which run on every OS with a recording sender:
  - `test_names_match_the_mac`: `set(VK) == set(macos_keys.KEYCODES)`
  - `test_codes`: the values above for `shift ctrl alt cmd tab left up right down f \ return escape delete space f1`
  - `test_cmd_sends_ctrl_and_ctrl_stays_until_both_released`: `key_down("ctrl")`, `key_down("cmd")` → sent
    `[(0x11, True)]`; `key_up("ctrl")` → nothing more; `key_up("cmd")` → `(0x11, False)`
  - `test_alt_release_is_masked`: `key_down("alt"); key_up("alt")` →
    `[(0x12, True), (0xE8, True), (0xE8, False), (0x12, False)]`
  - `test_tap_keeps_held_modifiers`: with Shift held, `tap(["shift", "f"])` sends only `f` down and up
  - `test_tap_validates_before_sending`: `tap(["ctrl", "nope"])` raises `ValueError`, and nothing is sent
  - `test_repeat_sends_down_again`: `key_repeat("left")` → `(0x25, True)`
  - `test_inputs_for_arrows_are_extended` (Windows only): `_input_for(0x25, True)` has the extended flag and a
    non-zero scan code; `_input_for(0x46, False)` has `KEYEVENTF_KEYUP` and no extended flag
  - `test_cmd_label_on_windows` (in `test_commands.py`): `key_labels("win32")["cmd"] == "Cmd (sends Ctrl)"` and
    `key_labels("darwin")["cmd"] == "Cmd"`
- [ ] **Step 2: Run to verify they fail:** `.venv\Scripts\python -m pytest -q tests/test_windows_keys.py
  tests/test_commands.py` → FAIL (no module).
- [ ] **Step 3: Implement** per the interfaces (ctypes `user32.SendInput` and `MapVirtualKeyW`; the `INPUT` /
  `KEYBDINPUT` structures sized for 64-bit).
- [ ] **Step 4: Run the whole suite** → all pass.
- [ ] **Step 5: Commit:** `feat: keyboard keys on Windows with SendInput (Cmd sends Ctrl)`.

---

### Task 3: Stop, status and a busy Loupedeck, without signals

**Files:**
- Modify: `bridge/instance.py`, `bridge/status.py`, `bridge/__main__.py`, `bridge/midi_input.py`, `bridge/app.py`,
  `macos/launcher/tests/PolicyTests.swift` + `tests/test_launcher_policies.py`
- Create: `tests/test_main_windows.py`
- Test: `tests/test_instance.py`, `tests/test_status.py`, `tests/test_midi_input.py`, `tests/test_main.py`
  (`log_handlers`)

**Interfaces:**
- Produces (what the tray app relies on):
  - **`instance.CONTROL_HANDLE_ENV = "LB_CONTROL_HANDLE"`**
  - **`instance.open_control(environ=os.environ) -> Optional[IO[str]]`:** on Windows, the inheritable pipe handle
    named there, opened read-only (`msvcrt.open_osfhandle`, then `os.fdopen(..., "r", encoding="utf-8")`). It returns
    None without the variable, with a bad value, or off Windows.
  - **`instance.watch_control(stream: IO[str], on_stop: Callable[[], None]) -> threading.Thread`:** a daemon thread
    reading lines. On a line `stop`, or end of file (the tray app has gone), it calls `on_stop()` once and ends.
    Other lines are ignored.
  - **`status.STATUS_HANDLE_ENV = "LB_STATUS_HANDLE"`:** `StatusReporter.from_env` takes it on Windows
    (`msvcrt.open_osfhandle(h, os.O_WRONLY)`, then a line-buffered UTF-8 file). `LB_STATUS_FD` stays for the Mac.
  - **The new status field:** `StatusReporter.state` gains `"loupedeck_busy": False`.
  - **`__main__.STDERR_IS_LOG_ENV = "LB_STDERR_IS_LOG"`:** `log_handlers(log_path, stderr=None, environ=os.environ)`
    leaves out the console copy when it's `"1"`. The tray app sends stderr into `bridge.log`, so a copy would double
    every line.
  - **`__main__._run`:**
    - on `win32`: `watch_control(open_control(), lambda: loop.call_soon_threadsafe(main_task.cancel))` when
      `open_control()` returns a stream
    - on `darwin`: the existing `parent_gone` watch, unchanged
  - **`MidiInput(..., busy_retry: float = 3.0)`** and **`on_busy: Optional[Callable[[bool], None]]`:**
    - when `open_port` raises, it logs once per busy spell ("the Loupedeck is in use by another program (…): quit the
      Loupedeck or Logi software; retrying"), calls `on_busy(True)`, waits `busy_retry`, and looks again
    - `on_busy(False)` comes after the next successful open, or once the port is gone from the list
  - **`app.build`** wires `midi.on_busy = lambda busy: status.set(loupedeck_busy=busy)`.

- [ ] **Step 1: Write the failing tests:**
  - `test_control_stop_line_stops`, `test_control_eof_stops`, `test_control_other_lines_ignored`: use `os.pipe()`
    wrapped with `os.fdopen`. `on_stop` is called exactly once (for a stop line and for EOF), and never for `hello\n`.
  - `test_status_starts_not_busy`: `StatusReporter(None).state["loupedeck_busy"] is False`.
  - `test_log_handlers_skip_console_when_stderr_is_the_log`: with `{"LB_STDERR_IS_LOG": "1"}`, only the file handler.
  - `test_busy_port_is_retried_and_reported` (Review Focus 3): `open_port` raises `OSError("in use")` twice, then
    succeeds (`busy_retry=0.01`). Then:
    - the `on_busy` calls are `[True, False]`
    - an event still arrives after the open
    - the "in use" log line appears once
  - `test_busy_clears_when_unplugged`: busy, then the port name leaves the list → `on_busy(False)`.
  - **`tests/test_main_windows.py`** (Windows only). It starts the real `python -m bridge` with `LOCALAPPDATA` and
    `APPDATA` in a temp dir, a `connections.json` naming an unused port, `--midi-port NoSuchDevice`, and the pipes
    passed with `subprocess.STARTUPINFO(lpAttributeList={"handle_list": [...]})`. Every process it starts is killed
    in teardown, as in `test_main.py`. Tests:
    - `test_stop_line_stops_cleanly`: write `stop\n` → exit 0 within 10 s, and the log ends with "bridge stopped"
    - `test_closed_control_pipe_stops_cleanly` (Review Focus 2): close the write end → the same
    - `test_status_lines_arrive`: the first line on the status pipe parses as JSON with `"loupedeck_busy": false`
    - `test_second_instance_exits_3`
  - **Swift `parse_ignores_new_fields`:** `BridgeStatus.parse` of a line with `"loupedeck_busy":true` is non-nil.
    Add it to `CHECKS`; it runs on macOS CI.
- [ ] **Step 2: Run to verify they fail:** `.venv\Scripts\python -m pytest -q tests/test_instance.py
  tests/test_status.py tests/test_midi_input.py tests/test_main.py tests/test_main_windows.py` → FAIL.
- [ ] **Step 3: Implement** per the interfaces.
- [ ] **Step 4: Run the whole suite** → all pass.
- [ ] **Step 5: Commit:** `feat: stop and status pipes on Windows, and a busy Loupedeck state`.

---

### Task 4: First live check on this PC (with the user)

**Files:**
- Modify: `docs/FINDINGS.md`, a new section "Milestone 7: Windows". Any fix found here gets its test first.

This answers spec "To verify first" 2, 3 and 4, before the tray app is built on top.

- [ ] **Step 1: Ask the user** to pick a test photo in Lightroom and say go. Run `.venv\Scripts\python -m bridge
  --debug` in a terminal. Lightroom shows its Allow dialog once, and the user clicks Allow. Expected log lines:
  - "Loupedeck connected (Loupedeck+ …)"; record the exact port name
  - Lightroom registered, with `client.json` written to `%LOCALAPPDATA%\loupedeck-lr-bridge\`
- [ ] **Step 2: With the user,** check and record each of these:
  - dials, dial clicks, C1/C2, undo/redo, copy/paste, presets on P1–P8, Fn + Export, clr/bw
  - the --/Col modes
  - the arrows (repeat while held), Tab, `\` (Before/After), `f` (screen mode)
  - Loupedeck Shift-click and Ctrl-click in the grid, Alt-drag on a slider, and Cmd+Z (sends Ctrl)
  - whether an Alt tap alone does anything visible (it's masked)
  - real Shift + a Loupedeck arrow
- [ ] **Step 3: Unplug and replug** the Loupedeck: "disconnected", then reconnected, and how long it took.
- [ ] **Step 4: Busy.** Stop the bridge. Run `.venv\Scripts\python tools\midi_dump.py` (it holds the port), then start
  the bridge. Expected: the "in use" line once. Quit `midi_dump`; the bridge opens the device within about 3 s.
- [ ] **Step 5: Ctrl-C** stops it with no stuck key (hold Shift on the device while pressing Ctrl-C).
- [ ] **Step 6: Record** the results, including anything that differs from the Mac, in FINDINGS.md. Commit:
  `docs: record the first Windows live check`.

---

### Task 5: The tray app's rules (pure C#, tested)

**Files:**
- Create:
  - `windows/launcher/LoupedeckBridge.csproj`: `net48`, `OutputType` WinExe, `LangVersion` latest,
    `AutomaticallyUseReferenceAssemblyPackages=false`, `Product`/`AssemblyTitle` "LoupedeckBridge"; references
    `System.Windows.Forms`, `System.Drawing`, `System.Security`, `System.Net.Http`, `System.Web.Extensions`
  - `windows/launcher/Policies.cs`, `windows/launcher/BuildInfo.cs`
  - `windows/launcher/tests/PolicyTests.csproj` (`net48` Exe; it compiles `..\Policies.cs`, `..\BuildInfo.cs` and
    later `..\Signature.cs`, `..\Download.cs`, `..\Swap.cs`, plus `PolicyTests.cs`)
  - `windows/launcher/tests/PolicyTests.cs`
  - `tests/test_windows_launcher.py`
- No C# 9+ features that need runtime support (records, `init`, ranges).

**Interfaces:**
- Produces (namespace `LoupedeckBridge`):
  - **`BuildInfo`** (`Runtime`, `Repo`, `Version`, `IsDev`, `SignerSha256`):
    - `static BuildInfo Parse(string json)` and `static BuildInfo Load(string jsonPath)` return null when the JSON is
      unreadable. The updater parses the JSON straight from a downloaded zip.
    - `string Name => IsDev ? "LoupedeckBridge Dev" : "LoupedeckBridge"`
    - `MutexName => @"Local\" + Name`, `QuitEventName => MutexName + ".quit"`
    - the JSON file `LoupedeckBridge.json` sits next to the exe:
      `{"runtime": "bundled"|"repo", "repo": "C:\\…", "version": "0.6.0", "is_dev": false, "signer_sha256": "…"}`
  - **`RuntimePaths`** (`Python`, `Workdir`), from `static RuntimePaths Resolve(BuildInfo info, string appDir)`:
    - `bundled` → `<appDir>\python\python.exe`, `<appDir>\app`
    - `repo` → `<repo>\.venv\Scripts\python.exe`, `<repo>`
    - anything else → null
  - **`BridgeCommand.Arguments(IEnumerable<string> extra)`** → `-E -s -B -X utf8 -m bridge …`
  - **`BridgeStatus`** (`Loupedeck`, `Lightroom`, `Keys`, `FiveMode`, `SettingsUrl`, `LoupedeckBusy`, which defaults
    to false), from `static BridgeStatus Parse(string line)`:
    - `JavaScriptSerializer`; null for anything that isn't a status line
  - **`AlertPolicy`, `RestartPolicy`, `SupervisorAction`, `BridgeSupervisor`:** ported from `Policies.swift`, with the
    same numbers (3 s, 15 s, 60 s, a 5 s restart, 3 restarts in 600 s, exit code 3 = already running) and the same
    states. The `keysMissing` alert is dropped (keys are always allowed on Windows).
  - **`Version`:** `static Version Parse(string)` (null if invalid), `IComparable<Version>`, `ToString()`.
  - **`TrayText.Problem(BridgeSupervisor.State state, bool isStopped, BridgeStatus status) -> string`**, in this
    order:
    1. "updating…"
    2. "the bridge has stopped"
    3. "starting…"
    4. "the Loupedeck is in use by another program"
    5. "the Loupedeck isn't connected"
    6. "Lightroom isn't connected"
    7. "all good"
  - **`TrayText.Tooltip(string name, string problem)`** → `name + ": " + problem`, which must fit `NotifyIcon.Text`'s
    63 characters.
- **The test exe** prints one line per check: `ok <name>` or `FAIL <name>: <why>`. It takes an optional first
  argument, a fixtures folder (used from Task 8).
- **`tests/test_windows_launcher.py`** mirrors `tests/test_launcher_policies.py`:
  - it's skipped unless `win32` and `dotnet` is on PATH
  - a module fixture runs `dotnet build windows\launcher\tests\PolicyTests.csproj -c Release -nologo -o <tmp>`, then
    runs the exe
  - `CHECKS` holds the names below, and each must be `ok`

- [ ] **Step 1: Write the failing checks.** First, the Swift checks of the same names, ported:
  - `never_connected_never_alerts`, `drop_alerts_after_debounce`, `quick_replug_is_silent`, `wake_grace`,
    `flapping_is_rate_limited`, `rate_limited_alert_fires_later`
  - `restart_disarms`, `restart_budget`, `already_running_is_not_a_crash`
  - `parse_rejects_garbage`, `bridge_exit_drops_pending_disconnect`
  - `quit_after_forced_kill_releases_keys` (Review Focus 2), `quit_after_clean_stop_just_exits`
  - `crash_releases_alerts_and_schedules_once`, `manual_restart_during_wait_spawns_once`,
    `stale_restart_click_does_nothing`
  - `status_ignored_once_the_bridge_is_gone`, `already_running_quits_the_app`
  - `version_compare`
  - `update_stops_the_bridge_without_quitting`, `update_after_a_forced_stop_releases_keys`,
    `update_when_stopped_swaps_at_once`, `update_cancels_a_pending_restart`, `failed_update_restarts_the_bridge`,
    `second_update_request_is_ignored`, `quit_during_an_update_just_quits`

  Then the new ones:
  - `parse_reads_busy`: `"loupedeck_busy":true` → `LoupedeckBusy`; a line without the field → false
  - `runtime_paths_bundled_and_repo`: both shapes as above; `runtime: "weird"` → null; `repo` without a path → null
  - `bridge_arguments`: starts `-E -s -B -X utf8 -m bridge`
  - `build_info_names`: dev → `Local\LoupedeckBridge Dev` and `Local\LoupedeckBridge Dev.quit`
  - `problem_text_names_busy` (Review Focus 3): a busy status gives item 4 even though `Loupedeck` is false
  - `tooltips_fit`: every `Problem` text, with both names, is ≤ 63 characters
- [ ] **Step 2: Run to verify they fail:** `.venv\Scripts\python -m pytest -q tests/test_windows_launcher.py` → FAIL
  (doesn't compile).
- [ ] **Step 3: Implement** `Policies.cs` and `BuildInfo.cs`, with no WinForms in them.
- [ ] **Step 4: Run the whole suite** → all pass.
- [ ] **Step 5: Commit:** `feat: the Windows tray app's rules, ported from the Mac app, with checks`.

---

### Task 6: The tray app, the dev build and `bridgectl.ps1` (with a live check)

**Files:**
- Create in `windows/launcher/`:
  - `Program.cs`: the entry point and command line
  - `BridgeProcess.cs`, `KeyRelease.cs`, `TrayApp.cs`, `Icons.cs`, `LoginItem.cs`, `Log.cs`
- Create in `windows/launcher/tests/FakeApp/`: `FakeApp.csproj`, `Program.cs`
- Create in `tools/`: `build_windows_app.ps1`, `bridgectl.ps1`
- Create tests: `tests/test_bridgectl_ps1.py`, `tests/test_windows_tray_keys.py`

**Interfaces:**
- **`LoupedeckBridge.exe` command line:**
  - no arguments: the tray app
  - `--quit`: sets the running copy's quit event, waits up to 10 s for it to exit. Exit 0 when it's gone (or wasn't
    running), 1 if it's still there.
  - `--login on|off|status`: prints `on` or `off`
  - `--check-signature`: comes in Task 8; `--finish-update` in Task 9
- **`BridgeProcess`:**
  - starts `RuntimePaths.Python` with `BridgeCommand.Arguments`, in `Workdir`, with `CreateNoWindow`
  - two `AnonymousPipeServerStream`s with inheritable client handles: status (bridge → app), and control
    (app → bridge)
  - the env gets `LB_STATUS_HANDLE`, `LB_CONTROL_HANDLE` and `LB_STDERR_IS_LOG=1`; then
    `DisposeLocalCopyOfClientHandle`
  - stdout and stderr are read as UTF-8 and appended to `bridge.log`
  - **`Stop()`:** writes `stop\n` to the control pipe; after 5 s, `Kill()`, then `KeyRelease.ReleaseAll()`
- **`KeyRelease.HoldableKeys = { 0x10, 0x11, 0x12, 0x09, 0x25, 0x26, 0x27, 0x28 }`:** `ReleaseAll()` sends a key-up
  for each with `SendInput`.
- **`Log.Write(string message, string level = "INFO")`:**
  - appends `yyyy-MM-dd HH:mm:ss,fff LEVEL   launcher: message` to `%LOCALAPPDATA%\loupedeck-lr-bridge\logs\bridge.log`
  - opens with `FileShare.ReadWrite | FileShare.Delete` for each line, so the bridge's log rotation can rename the file
- **`TrayApp`:**
  - a `NotifyIcon` with a `ContextMenuStrip` rebuilt on `Opening`, laid out as the spec's sketch, plus the
    "Loupedeck: in use by another program" line
  - icons drawn in code: sliders, and a warning triangle; `Tooltip` text
  - alerts as `ShowBalloonTip`, worded as the Mac's with "tray icon" for "menu-bar icon", and no keys alert
  - a 1 s timer for `AlertPolicy.Tick`; `SystemEvents.PowerModeChanged` Resume → `DidWake`
  - the restart timer; **Restart bridge** and **Open log** when stopped; **Open settings…**
  - `SessionEnding` → a clean stop
  - a named mutex (a second copy exits 0 at once), and a quit event waited on with `RegisteredWaitHandle`
- **`LoginItem`:** the value `<BuildInfo.Name>` = `"<exe path>"` under
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, with methods `IsOn`, `Set(bool)`.
- **`tools/build_windows_app.ps1 [-Dev] [-Release OUT_DIR]`.** `-Dev` is the default, and `-Release` comes in Task 7.
  The dev build:
  - `dotnet build windows\launcher\LoupedeckBridge.csproj -c Release -nologo -p:Version=<__version__>
    -p:AssemblyTitle="LoupedeckBridge Dev" -o "build\LoupedeckBridge Dev"`
  - plus `LoupedeckBridge.json` with `{"runtime":"repo","repo":<repo>,"version":<ver>,"is_dev":true,"signer_sha256":""}`
- **`tools/bridgectl.ps1 <command> [-Dev] [args]`,** run as `pwsh -File tools\bridgectl.ps1 …`. Commands:
  `build | start | stop | restart | status | login on|off|status | install [args] | logs | settings`.
  - the release is `$env:LB_BRIDGECTL_RELEASE_APP` or `%LOCALAPPDATA%\Programs\LoupedeckBridge\LoupedeckBridge.exe`
  - the dev build is `$env:LB_BRIDGECTL_DEV_APP` or `<repo>\build\LoupedeckBridge Dev\LoupedeckBridge.exe`
  - "running" means a process whose `Path` equals that exe (case-insensitive)
  - `stop` = `<exe> --quit`; `start` = `Start-Process <exe>`, then after 1.5 s it's running, or the last 8 log lines
  - `start -Dev` stops a running release and writes `%LOCALAPPDATA%\loupedeck-lr-bridge\release-paused`
  - `stop -Dev` starts the release again if that marker exists, then deletes it
  - `start` (release) refuses while the dev build runs
  - `install` runs `powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\install.ps1 @args`
- **FakeApp** (test-only, stands in for `LoupedeckBridge.exe`):
  - it appends its arguments to `$env:LB_FAKE_LOG`
  - with no arguments, it stays running only if `LB_FAKE_STAY=1`
  - `--quit` kills the other running copies with its own path and exits 0, unless `LB_FAKE_WONT_QUIT=1` (exit 1)

- [ ] **Step 1: Write the failing tests:**
  - `test_tray_releases_every_holdable_key` (Review Focus 2): the numbers in `KeyRelease.cs`'s `HoldableKeys` (read as
    text) equal `windows_keys.HOLDABLE_VKS`.
  - **`tests/test_bridgectl_ps1.py`** (Windows, `pwsh` and `dotnet`). It builds FakeApp into two temp folders, the
    "release" and the "dev", sets the two override variables and `LOCALAPPDATA` to temp dirs, and kills leftovers in
    teardown. Tests:
    - `test_status_targets`: `status` → "not running"; with the release FakeApp running (`LB_FAKE_STAY=1`) →
      "running"; `status -Dev` → "not running"
    - `test_start_dev_pauses_the_release`: the release FakeApp is running. `start -Dev` → the release's log has
      `--quit`, the marker exists, and the dev FakeApp's log has a start.
    - `test_stop_dev_resumes_the_release`: the marker exists. `stop -Dev` → the release started, the marker is gone.
    - `test_stop_dev_without_marker_leaves_release_alone`
- [ ] **Step 2: Run to verify they fail** → FAIL.
- [ ] **Step 3: Implement** the tray app, the dev build script and `bridgectl.ps1`. Build with
  `pwsh -File tools\bridgectl.ps1 build`.
- [ ] **Step 4: Run the whole suite** → all pass.
- [ ] **Step 5: Live check with the user** (spec "To verify first" 7), using `pwsh -File tools\bridgectl.ps1 start
  -Dev`:
  1. The icon appears; note whether it's behind ^.
  2. The menu shows the version, Loupedeck, Lightroom and the five buttons.
  3. Unplug: "Loupedeck disconnected" after about 3 s, and a warning icon. Replug: "Loupedeck is back". A quick
     replug: no alert.
  4. `midi_dump.py` holding the port: "Loupedeck: in use by another program".
  5. End task on `python.exe` in Task Manager: an alert, and a restart after 5 s.
  6. End task on the tray app while holding Shift on the device: the bridge exits within about 1 s, and Shift isn't
     stuck.
  7. Quit: the icon goes and the bridge stops.
  8. Start at login: on, sign out and in, and it's running; then off.
  9. Open settings… opens the page, with no firewall prompt.
  10. The notifications are named "LoupedeckBridge Dev".
  Record the results in FINDINGS.md.
- [ ] **Step 6: Commit:** `feat: the Windows tray app, the dev build, and bridgectl.ps1`.

---

### Task 7: The Windows release folder with bundled Python

**Files:**
- Create:
  - `tools/python-standalone-windows.lock`
  - `tools/release-requirements-windows.txt`
  - `tools/package_windows_release.ps1`
  - `tests/test_windows_release_bundle.py`
- Modify: `tools/build_windows_app.ps1` (`-Release OUT_DIR`), `tests/test_release_lock.py`

**Interfaces:**
- **The lock** (the same format as the Mac's). The newest 3.12 build, from the same release as the Mac:
  ```
  url=https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-x86_64-pc-windows-msvc-install_only.tar.gz
  sha256=590dfcbe3a34c07301e6332e13e2188b98655cd072b08afa45a7998dc4c22bc5
  ```
- **`tools/release-requirements-windows.txt`**, the `cp312-win_amd64` / `py3-none-any` wheels at
  `requirements.txt`'s versions:
  ```
  mido==1.3.3 --hash=sha256:01033c9b10b049e4436fca2762194ca839b09a4334091dd3c34e7f4ae674fd8a
  packaging==26.3 --hash=sha256:d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c
  python-rtmidi==1.5.8 --hash=sha256:052c89933cae4fca354012d8ca7248f4f9e1e3f062471409d48415a7f7d7e59e
  websockets==15.0.1 --hash=sha256:fcd5cf9e305d7b8338754470cf69cf81f420459dbae8a3b40cee57417f4614a7
  ```
- **`build_windows_app.ps1 -Release OUT_DIR`** makes `OUT_DIR\LoupedeckBridge\`:
  1. Download the tarball into `.cache\` if it's missing, and refuse it (deleting it) if its SHA-256 differs. Unpack
     it to `python\`.
  2. `python\python.exe -E -m pip install --no-cache-dir --only-binary=:all: --no-deps --require-hashes -r
     tools\release-requirements-windows.txt`.
  3. Copy `bridge\`, `config\` and `docs\lr_parameters_10.0.json` into `app\`. Copy `tools\install.ps1` next to the
     exe; it's used by the uninstall entry, from Task 9.
  4. Strip `Lib\test`, `idlelib`, `tkinter`, `turtledemo`, `ensurepip`, `tcl\`, `DLLs\_tkinter.pyd`, `DLLs\tcl86t.dll`,
     `DLLs\tk86t.dll`, `include\`, every `__pycache__` / `test` / `tests` folder and every `.pyc`. Keep pip, which
     CI's venv uses.
  5. `compileall --invalidation-mode unchecked-hash` over `python\Lib` and `app\`.
  6. Build the exe with `AssemblyTitle` "LoupedeckBridge". Write `LoupedeckBridge.json`:
     `{"runtime":"bundled","version":<ver>,"is_dev":false,"signer_sha256":<LB_SIGNER_SHA256 or install.sh's pin>}`.
- **`tools/package_windows_release.ps1 APP_DIR OUT_DIR`** makes `LoupedeckBridge-v<ver>-windows-x64.zip`:
  - with `[IO.Compression.ZipFile]::CreateFromDirectory(APP_DIR, zip, Optimal, $true)`, so the entries are under
    `LoupedeckBridge/`
  - plus `<zip>.sha256`, written as `<hex>  <name>\n` like `shasum`

- [ ] **Step 1: Write the failing tests:**
  - **`tests/test_release_lock.py`** gains:
    - `test_windows_python_lock`: the URL matches
      `/cpython-3\.12\.\d+%2B\d{8}-x86_64-pc-windows-msvc-install_only\.tar\.gz$`
    - `test_windows_release_requirements_pin_what_requirements_pins`
  - **`tests/test_windows_release_bundle.py`** is skipped unless `LB_WINDOWS_RELEASE_DIR` names a built
    `LoupedeckBridge\` folder. Python runs as the app runs it: `-E -s -B -X utf8`, in `app\`. Tests:
    - `test_layout`, including the JSON fields, and the exe's `FileVersion` equal to `bridge.__version__`
    - `test_bundled_python_is_its_own_3_12`
    - `test_code_and_packages_load_from_the_bundle`
    - `test_winmm_opens`: `rtmidi.MidiIn().get_ports()` runs
    - `test_bridge_command_line`: `--help`
    - `test_no_dev_leftovers`, `test_everything_is_precompiled`
    - `test_user_site_packages_are_ignored`: a `.pth` planted in `%APPDATA%\Python\Python312\site-packages`, with
      `APPDATA` in a temp dir, doesn't run
- [ ] **Step 2: Run to verify they fail** → FAIL.
- [ ] **Step 3: Implement.** Build into the scratchpad, then run the bundle tests against it. Spec "To verify first" 1
  is done when the whole suite also passes with the bundled Python:
  - `<dir>\python\python.exe -m venv --system-site-packages --without-pip <scratch>\venv`
  - in that venv, `python -m pip install --require-hashes --only-binary=:all: --no-deps -r
    tools\release-test-requirements.txt`
  - in that venv, `python -m pytest -q`
- [ ] **Step 4: Run the whole suite** (the repo `.venv`) → all pass.
- [ ] **Step 5: Commit:** `build: the Windows release folder with bundled Python 3.12`.

---

### Task 8: Signatures and update decisions (C#, tested)

**Files:**
- Create: `windows/launcher/Signature.cs`, `windows/launcher/Download.cs`, `tools/sign_windows_zip.sh`,
  `tests/test_sign_windows_zip.py`
- Modify: `windows/launcher/Policies.cs`, `windows/launcher/Program.cs` (`--check-signature`), `PolicyTests.cs`,
  `tests/test_windows_launcher.py` (fixtures, checks)

**Interfaces:**
- **`tools/sign_windows_zip.sh FILE P12 PASSWORD_FILE`** writes `FILE.p7s`. It runs with `${OPENSSL:-openssl}`:
  1. `pkcs12 -in P12 -passin file:PASSWORD_FILE -nodes` → a PEM in a `mktemp -d` folder (`umask 077`, removed by a
     `trap … EXIT`)
  2. `smime -sign -binary -noattr -md sha256 -outform DER -signer <pem> -in FILE -out FILE.p7s`
  3. a check: `smime -verify -binary -noverify -inform DER -in FILE.p7s -content FILE -out /dev/null`
  It's run in the release's key step (Task 10), with macOS's LibreSSL there and Git for Windows' OpenSSL 3 here.
- **`Signature.Problem(byte[] content, byte[] p7s, string pinnedSha256) -> string`** returns null if it's OK.
  Otherwise, in this order:
  1. "no release key is pinned in this build" (pinned isn't 64 hex characters)
  2. "the signature is unreadable" (decoding failed)
  3. "the signature should have exactly one signer"
  4. "the signature doesn't match the download" (`new SignedCms(new ContentInfo(content), detached: true)`, `Decode`,
     `CheckSignature(verifySignatureOnly: true)` throws)
  5. "it's signed with another key" (the SHA-256 of the signer certificate's `RawData` isn't the pinned one,
     compared case-insensitively)
- **`Download.CopyCapped(Stream from, Stream to, long limit) -> string`** returns the SHA-256 in lowercase hex. It
  throws `DownloadTooLargeException` past `limit`; the updater passes `209_715_200`.
- **In `Policies.cs`:**
  - **`ReleaseInfo`** (`Version`, `Zip`, `Sha256`, `Signature`, all `Uri`):
    - `static string AssetName(Version v) => $"LoupedeckBridge-v{v}-windows-x64.zip"`
    - `static ReleaseInfo Parse(string json)`: from `tag_name` and `assets[].name/browser_download_url`; https only;
      no `draft` or `prerelease`; it needs the zip, `.sha256` and `.p7s`
    - `string Saved()` and `static ReleaseInfo Restore(string saved, Version newerThan)`
  - **`UpdateSchedule.ShouldCheck(DateTime nowUtc, DateTime? lastCheckUtc, bool enabled, bool isDev, TimeSpan
    sinceLaunch)`:** 24 h; the first check at 30 s.
  - **`UpdateNotice`** (`LastAnnounced`, `Announce(Version v, Version current) -> bool`), as on the Mac.
  - **`enum InstallStep { Download, Verify, Unzip, StopBridge, HandOver, MoveOldAside, CopyNewIn, LaunchNew }`**, with
    `static readonly InstallStep[] InstallOrder` in that order.
  - **`static string ZipLayoutProblem(IEnumerable<string> entryNames)`** returns null when:
    - every entry is under `LoupedeckBridge/`
    - no entry has a `..` segment, a drive letter, or a leading `/` or `\`
    - both `LoupedeckBridge/LoupedeckBridge.exe` and `LoupedeckBridge/LoupedeckBridge.json` are there
  - **`static string InstallProblem(BuildInfo found, Version current, bool shaOK, bool signatureOK, bool
    allowOlder)`**, the first failure in this order:
    1. "the download is damaged (its SHA-256 doesn't match)"
    2. "it isn't signed with your LoupedeckBridge release key"
    3. "it isn't a LoupedeckBridge release" (not bundled, or dev)
    4. "it has no readable version"
    5. "it isn't newer than the installed v…"
- **`LoupedeckBridge.exe --check-signature FILE [--pinned SHA256]`:** checks `FILE.p7s` over `FILE` against the
  build's `SignerSha256` (or `--pinned`). Exit 0 prints `ok: …`; exit 1 prints `refused: <problem>`.
- **Test fixtures:** `tests/test_windows_launcher.py` makes them with `openssl` (Git for Windows': `C:\Program
  Files\Git\usr\bin\openssl.exe` if it's not on PATH) and passes the folder to the test exe:
  - two throwaway identities, A and B, each a self-signed RSA-3072 certificate with `extendedKeyUsage =
    critical, codeSigning` (the same `req` config as `make_signing_identity.sh`), packed as `.p12`
  - `content.bin` (random bytes), with `content.bin.p7s` from A via `bash tools/sign_windows_zip.sh`
  - `other.p7s` from B
  - `a.sha256`: A's certificate DER SHA-256

- [ ] **Step 1: Write the failing tests.** In C#:
  - `signature_accepts_the_pinned_certificate`
  - `signature_refuses_another_certificate` (Review Focus 4)
  - `signature_refuses_a_changed_byte`
  - `signature_needs_a_pinned_key`
  - `signature_refuses_garbage`
  - `release_parse_accepts_a_real_shape`, `release_parse_rejects_garbage` (each a rate-limit body, no `.p7s`, the
    Mac-only assets, a draft, a pre-release, an `http:` URL)
  - `check_schedule`, `notice_once_per_version`, `found_update_survives_a_relaunch`
  - `install_plan_order`: `Verify` comes before `StopBridge` and `MoveOldAside`
  - `install_plan_refuses_*`, one for each `InstallProblem` reason, plus `install_plan_accepts_valid`
  - `zip_layout_refuses_unsafe_paths` (Review Focus 4): each of `LoupedeckBridge/../x`, `C:/x`, `/x`,
    `\LoupedeckBridge\x`, `Other/x`, and a missing exe is refused; a good list is accepted
  - `download_is_capped_and_hashed`: a known SHA-256 for 1 KiB of MemoryStream; it throws when longer than the limit

  In `tests/test_sign_windows_zip.py` (needs `bash` and `openssl`; runs on macOS CI and here):
  - `test_signature_verifies_and_a_change_does_not`
  - `test_no_key_left_behind`: `TMPDIR` is a temp folder, and it's empty afterwards
- [ ] **Step 2: Run to verify they fail** → FAIL.
- [ ] **Step 3: Implement** per the interfaces. The checks also prove spec "To verify first" 6 for OpenSSL 3; LibreSSL
  is covered in Task 10.
- [ ] **Step 4: Run the whole suite** → all pass.
- [ ] **Step 5: Commit:** `feat: signature and update checks for Windows releases`.

---

### Task 9: The updater, `install.ps1`, uninstall and "go back"

**Files:**
- Create: `windows/launcher/Updater.cs`, `windows/launcher/Swap.cs`, `windows/launcher/Registration.cs`,
  `tools/install.ps1`, `tests/test_install_ps1.py`
- Modify: `windows/launcher/TrayApp.cs` (the menu items), `Program.cs` (`--finish-update`), `Policies.cs`
  (`CommandLine`), `PolicyTests.cs`, `tests/test_windows_launcher.py`

**Interfaces:**
- **`CommandLine.Quote(string arg)`** and **`CommandLine.Join(IEnumerable<string> args)`:** the Windows argv rules
  (quotes for spaces and tabs, backslashes doubled before a quote and at the end).
- **`Swap`:**
  - **`static string Run(string installDir, string newDir, Action<string, string> copyTree)`** returns null on
    success. Otherwise it returns `"<step>: <reason>"`, after putting the old version back.
    1. rename `installDir` → `installDir + ".previous"`, after deleting an older `.previous`
    2. `copyTree(newDir, installDir)`
    3. on a failure in step 2: delete the partial `installDir`, then rename `.previous` back
  - **`static string GoBack(string installDir, Action<string, string> copyTree)`:** the same, from `.previous` into
    place, keeping the current version as the new `.previous`.
  - **`static string GoBackProblem(string previousDir)`:** null when it has `LoupedeckBridge.exe` and a bundled, non-dev
    `LoupedeckBridge.json` with a readable version.
  - **`static void CleanUp(string installDir)`:** at startup, deletes `installDir + ".new"`, ignoring failures.
- **`LoupedeckBridge.exe --finish-update OLDPID INSTALLDIR`**, run from `LoupedeckBridge.new\`:
  1. wait up to 30 s for OLDPID to exit
  2. `Swap.Run(INSTALLDIR, <own folder>, CopyTree)`
  3. update the Apps entry's `DisplayVersion`, if the entry exists
  4. start `INSTALLDIR\LoupedeckBridge.exe` and exit
  On a failure, it writes `UpdateFailed` = `"<step>: <reason>"` under `HKCU\Software\LoupedeckBridge` and starts
  whichever version is in place. The tray app shows that value as an alert on its next start, then deletes it.
- **`Updater`** (release builds only):
  - like the Mac's `Updater.swift`: `CheckIfDue`, `CheckNow`, `Available`, `Automatic`
  - `HttpClient` with a 15 s timeout, `User-Agent: LoupedeckBridge/<ver>` and `Accept: application/vnd.github+json`,
    against `https://api.github.com/repos/MegaMattMiller/LoupedeckBridge/releases/latest`
  - **preferences** under `HKCU\Software\LoupedeckBridge`: `AutoUpdateCheck` (DWORD, default 1), `LastUpdateCheck`
    (ISO 8601 UTC), `AvailableRelease`, `AnnouncedVersion`
  - **Install** follows `InstallOrder`:
    1. download the zip, `.sha256` and `.p7s` to `%TEMP%\LoupedeckBridge-update-<ver>\` (`CopyCapped`)
    2. Verify: SHA-256, `Signature.Problem`, `ZipLayoutProblem`, then the zip's JSON, then `InstallProblem`
    3. Unzip to `<installDir>.new` (deleting an old one first)
    4. stop the bridge (`BridgeSupervisor.StopForUpdate`)
    5. HandOver: start `<installDir>.new\LoupedeckBridge.exe --finish-update <own pid> <installDir>`, then exit
  - a failure before HandOver: an alert naming the step, and `UpdateAbandoned` restarts the bridge
  - **Go back to the previous version (v…)…** appears when the restart budget is used up and `GoBackProblem(…)` is
    null. It stops, runs `Swap.GoBack`, then starts the restored copy.
- **`Registration`:** constructed with `(string uninstallKey)`, defaulting to
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\LoupedeckBridge`. `SetDisplayVersion(string)` does nothing
  when the key doesn't exist (a dev build, or a copy not installed by `install.ps1`).
- **`tools/install.ps1 [-Version latest|vX.Y.Z] [-AllowOlder] [-Uninstall]`** (Windows PowerShell 5.1,
  `Set-StrictMode -Version 2`, `$ErrorActionPreference = 'Stop'`):
  - `$PinnedSignerSha256Default = "4927ccbb8cc8c7e3c32afa79d58f11f2129b84b3c7638cb530cb2ced0faa2cf4"`
  - **environment overrides, for tests and CI:** `LB_PINNED_SIGNER_SHA256`, `LB_RELEASES_API`, `LB_DOWNLOAD_BASE`,
    `LB_INSTALL_DIR`, `LB_START_MENU_DIR`, `LB_RUN_KEY`, `LB_UNINSTALL_KEY`, `LB_INSTALL_NO_START=1`
  - **install, in order:**
    1. print the fingerprint
    2. resolve the version: `Invoke-RestMethod "$api/latest"` with the user agent, or the one given
    3. download the three files with `Invoke-WebRequest -UseBasicParsing -OutFile`, refusing over 200 MB
    4. check the SHA-256 (`Get-FileHash`) and the signature: `Add-Type -AssemblyName System.Security`, then
       `SignedCms`, the same checks and wording as `Signature.Problem`
    5. check the zip's layout (the same rules as `ZipLayoutProblem`), then `ExtractToDirectory` into a temp folder,
       then the JSON (bundled, non-dev, the version asked for, newer unless `-AllowOlder`)
    6. `<installed exe> --quit`; if it exits 1, stop with "LoupedeckBridge won't quit; nothing was changed"
    7. move the old folder to `.previous`, then copy the new one in. On a failure, put `.previous` back and start it.
    8. create the Start menu shortcut, `LoupedeckBridge.lnk`, with `WScript.Shell`
    9. register the Apps entry: `DisplayName` "LoupedeckBridge", `DisplayVersion`, `Publisher` "LoupedeckBridge",
       `InstallLocation`, `DisplayIcon` (the exe), `NoModify`=1, `NoRepair`=1, and `UninstallString` =
       `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<installDir>\install.ps1" -Uninstall`
    10. start the app, unless `LB_INSTALL_NO_START`
  - **exit codes:** 0 ok, 1 refused (nothing replaced), 2 usage
  - **`-Uninstall`:** `Set-Location $env:TEMP`; `--quit`; remove the Run value, the shortcut, the Apps entry, the
    install folder and `.previous`. Then print where the settings and logs are kept (`%APPDATA%\loupedeck-lr-bridge`,
    `%LOCALAPPDATA%\loupedeck-lr-bridge`); they aren't removed.

- [ ] **Step 1: Write the failing tests.** C# checks:
  - `command_line_quotes_paths` (Review Focus 1): `C:\Users\Zoë Ünal\AppData\Local\Programs\LoupedeckBridge`, a path
    ending in `\`, and an argument with a quote, each round-trip through `CommandLineToArgvW` (P/Invoke in the test)
  - `swap_moves_old_aside_and_copies_new`, `swap_replaces_an_older_previous`
  - `swap_failure_puts_the_old_back` (Review Focus 5): `copyTree` throws after copying one file → the original folder
    is back, byte for byte, and the result names `CopyNewIn`
  - `go_back_swaps_previous_in`, `go_back_needs_a_complete_previous`

  **`tests/test_install_ps1.py`** (Windows, `powershell.exe`, `dotnet`, `openssl`, `bash`):
  - **the setup:**
    - a release built from a fake `LoupedeckBridge\` folder (FakeApp as the exe, plus a JSON file), zipped and signed
      with identity A
    - served by a `http.server` thread on 127.0.0.1, with `LB_RELEASES_API` / `LB_DOWNLOAD_BASE` pointing at it
    - the install folder, Start menu and registry keys in temp locations: `HKCU\Software\LoupedeckBridgeTests\<uuid>\…`,
      deleted in teardown
    - `LB_PINNED_SIGNER_SHA256` = A
  - **the tests:**
    - `test_install_into_empty_dir`
    - `test_install_a_named_version`
    - `test_install_refuses_wrong_signature` (signed with B)
    - `test_install_refuses_bad_sha256`, `test_install_refuses_a_changed_byte`
    - `test_install_refuses_unsafe_zip_paths` (an entry `LoupedeckBridge/../evil.txt`, and nothing written outside)
    - `test_install_failure_leaves_app_in_place` (a 404; a corrupt zip)
    - `test_older_needs_flag`, `test_old_app_kept_as_previous`
    - `test_no_pinned_key_refuses`, `test_install_prints_the_release_key`
    - `test_running_app_is_stopped_before_the_swap`, `test_app_that_wont_quit_is_left_alone`
    - `test_failed_copy_puts_back_and_restarts_the_old_app` (Review Focus 5): a file in the new tree made unreadable
      with a deny ACL for the test
    - `test_downloads_are_size_capped`
    - `test_start_menu_and_apps_entry`, `test_uninstall_keeps_user_settings`

  In `tests/test_release_lock.py`: `test_both_installers_pin_the_same_key` (text).
- [ ] **Step 2: Run to verify they fail** → FAIL.
- [ ] **Step 3: Implement** per the interfaces.
- [ ] **Step 4: Run the whole suite** → all pass.
- [ ] **Step 5: Commit:** `feat: tray updates, install.ps1, uninstall and go back on Windows`.

---

### Task 10: CI, the release workflow and release tooling

**Files:**
- Modify: `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `tests/test_release_workflow.py`,
  `tools/release.sh`

**Interfaces:**
- **`ci.yml`:**
  - **`release-build` (macOS)** gains a step after its throwaway identity exists. It signs a sample file with `bash
    tools/sign_windows_zip.sh` (LibreSSL), then uploads artifact `libressl-sample`: the sample, its `.p7s` and
    `signer.sha256`.
  - **The new `release-build-windows`** (`windows-2025`, needs `release-build`, no secrets):
    1. A throwaway identity: `bash tools/make_signing_identity.sh --out "$RUNNER_TEMP/id"`, then `LB_SIGNER_SHA256`.
    2. `pwsh -File tools/build_windows_app.ps1 -Release dist`.
    3. The suite with the bundled Python, with the test tools pinned by hash as on macOS. Then
       `test_windows_release_bundle.py` with `LB_WINDOWS_RELEASE_DIR`.
    4. Package. Sign with `sign_windows_zip.sh` and the throwaway `.p12`.
    5. The app checks it: `dist\LoupedeckBridge\LoupedeckBridge.exe --check-signature <zip>` passes.
    6. A tampered copy is refused: `if …; then exit 1`.
    7. The LibreSSL sample passes `--check-signature <sample> --pinned <its sha>`.
    8. `install.ps1` against a local HTTP server: refused with `LB_PINNED_SIGNER_SHA256` set to 64 zeros, then
       installed into `$RUNNER_TEMP` with the right pin and `LB_INSTALL_NO_START=1`. The installed exe's
       `--check-signature` on the zip passes.
- **`release.yml`** jobs:
  - **`build`:** macOS, unchanged.
  - **`build-windows`** (`windows-2025`):
    - checks the tag and version as `build` does
    - builds with install.sh's pin
    - packages `unsigned-windows.zip` and records `zip_sha256` (an output), then uploads the artifact before any test
      code runs
    - runs the suite with the bundled Python and the bundle tests
    - checks the tests left the folder unchanged (a SHA-256 manifest)
  - **`sign`** (macOS, `environment: release`; the current `publish`, renamed). It:
    - checks both artifacts byte for byte against `build` / `build-windows` outputs
    - in the one key step: imports the identity, signs the Mac app, runs `tools/sign_windows_zip.sh` on the Windows
      zip, and deletes the key files and keychain (trap)
    - checks the Mac build as today, and packages it
    - uploads artifact `signed-release` with all five files
  - **`verify-windows`** (`windows-2025`, no secrets): downloads `signed-release`, unzips the Windows zip to a temp
    folder, then runs its exe's `--check-signature`, and `install.ps1` against a local server
    (`LB_INSTALL_NO_START=1`, the pinned key from install.sh).
  - **`publish`** (`ubuntu-24.04`, needs `build`, `sign` and `verify-windows`; `permissions: contents: write`; no
    environment):
    - refuses unless all five files for the version exist
    - then `gh release create` with the changelog notes, as today
- **`tests/test_release_workflow.py`:**
  - the existing checks move from `publish` to `sign`, where the key lives
  - new: `test_windows_build_is_saved_before_any_test_code_runs`
  - new: `test_sign_signs_exactly_the_saved_windows_build`
  - new: `test_windows_zip_is_signed_in_the_key_step`, which also checks that no `LoupedeckBridge.exe` runs in that
    step
  - new: `test_verify_windows_runs_the_app_check_and_install_ps1`
  - new: `test_publish_needs_both_platforms`: the five names, and `needs` covering `verify-windows`
  - new: `test_only_sign_uses_the_release_environment`
  - new: `test_windows_rehearsal_proves_tampering_and_another_key_are_refused`
- **`tools/release.sh`:**
  - `python` falls back to `.venv/Scripts/python.exe` (Git Bash on Windows)
  - it fails unless `tools/install.ps1`'s `$PinnedSignerSha256Default` equals install.sh's pin

- [ ] **Step 1: Write the failing workflow tests** above.
- [ ] **Step 2: Run to verify they fail** → FAIL.
- [ ] **Step 3: Implement** the workflows and `release.sh`. Use only the already-pinned action SHAs (`checkout`,
  `setup-python`, `upload-artifact`, `download-artifact`), with no `pull_request` triggers in `release.yml`.
- [ ] **Step 4: Run the whole suite** → all pass. Run `bash -n tools/*.sh`.
- [ ] **Step 5: Ask the user, then push the branch** (the pre-push checks in Global Constraints). CI must pass on
  GitHub; fix it if not. LibreSSL → `SignedCms` is proven when `release-build-windows` passes.
- [ ] **Step 6: Commit** the fixes from CI: `ci: build, test, sign and verify Windows releases`.

**→ The whole-branch review happens here,** before Task 11.

---

### Task 11: v0.6.0, the first release with Windows (with the user)

**Files:**
- Modify: `bridge/__init__.py` (`0.6.0`), `CHANGELOG.md` (`## v0.6.0`), `docs/FINDINGS.md`, `CLAUDE.md`, and
  `README.md`:
  - **Windows install for friends:** Lightroom's "Enable external controllers", quitting the Loupedeck or Logi
    software, the two commands, the fingerprint, the Allow dialog
  - the tray icon behind ^, and how to pin it
  - updates, Go back, uninstall (Settings → Apps)
  - what talks to the internet
  - development on Windows (`bridgectl.ps1`, the dev build)
  - the roadmap: 7 = Windows ✅ once done
  - the layout table: `windows/launcher/`, the new tools

- [ ] **Step 1:** Version, changelog and docs. Commit: `docs: v0.6.0 with Windows`. Ask, then push. CI passes.
- [ ] **Step 2:** The user merges to `main` (their decision), then runs `tools/release.sh 0.6.0`, from Git Bash here or
  on the Mac. It asks before pushing the tag. The user approves the `sign` run on GitHub, and the release appears
  with all five files.
- [ ] **Step 3: Install it the friends' way on this PC,** after `pwsh -File tools\bridgectl.ps1 stop -Dev`: the
  `irm …/install.ps1 -OutFile install.ps1` and `powershell -ExecutionPolicy Bypass -File install.ps1` lines from the
  README. Check:
  - **spec "To verify first" 5:** `Get-Item <downloaded zip> -Stream Zone.Identifier` finds nothing, there's no
    SmartScreen step, and Defender stays quiet
  - the Start menu entry, and the Apps entry with version 0.6.0
  - the tray shows v0.6.0, the bridge works, and Lightroom asks no new Allow (the same `client.json`)
  - an unplug alert is named "LoupedeckBridge" (spec "To verify first" 7, for the release)
- [ ] **Step 4: On the Mac** (the user): "Check for updates now" finds v0.6.0, and Install works. This proves the Mac
  still finds its zip.
- [ ] **Step 5:** Record it in FINDINGS. Commit: `docs: record the v0.6.0 release on Windows and the Mac`.

---

### Task 12: v0.6.1 through the tray (proves updates, go back and uninstall)

**Files:**
- Modify: the review's deferred minors (each with its test first), `bridge/__init__.py` (`0.6.1`), `CHANGELOG.md`,
  `docs/FINDINGS.md`

- [ ] **Step 1:** TDD each small fix. Then merge, and `tools/release.sh 0.6.1`; the user approves the run.
- [ ] **Step 2: With the user,** on this PC:
  - "Check for updates now" in v0.6.0's tray finds v0.6.1; Install
  - the tray restarts as v0.6.1, `LoupedeckBridge.previous\` holds v0.6.0, and the Apps entry says 0.6.1
  - spec "To verify first" 8: Start at login and the Start menu entry still start v0.6.1
- [ ] **Step 3: Go back.** Rename the installed `app\bridge\__main__.py`, so the bridge fails 3 times. The menu offers
  "Go back to the previous version (v0.6.0)…"; v0.6.0 runs. Then update to v0.6.1 again from the menu.
- [ ] **Step 4: Uninstall** from Settings → Apps. The app, the shortcut, the Apps entry and the login item are gone;
  `%APPDATA%\loupedeck-lr-bridge\mapping.json` and the logs remain. Reinstall with `install.ps1`.
- [ ] **Step 5:** Record it in FINDINGS. Commit: `docs: record the first Windows tray update, go back and uninstall`.
