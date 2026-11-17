# Milestone 6: Mac Releases with In-app Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Versioned, self-contained Mac releases built and signed on GitHub, installed with one command on any of the user's Macs, and updated from the menu bar after a signature check against the user's own key.

**Architecture:**
- One version in `bridge/__init__.py`.
- A build script makes either the dev app (repo Python, "LoupedeckBridge Dev") or the release app (bundled python-build-standalone 3.12 plus the code, "LoupedeckBridge").
- Pure Swift types in `Policies.swift` decide runtime paths, version order, when to check and what to install; `Updater.swift` does the I/O.
- `tools/install.sh` is the standalone installer.
- GitHub Actions run the tests on every push, and build, test, wait for approval, sign and publish on a version tag.

**Tech Stack:** Python ≥3.9 (repo) / 3.12 (release), Swift via `swiftc`, bash, `openssl`, `codesign`, `ditto`, `gh`, GitHub Actions (GitHub-hosted Apple Silicon runners), `pytest`.

**Spec:** [docs/superpowers/specs/2026-11-17-m6-mac-releases-design.md](../specs/2026-11-17-m6-mac-releases-design.md), within [the bridge design](../specs/2026-11-16-loupedeck-bridge-design.md).

## Global Constraints

- Milestones 1–5 hold:
  - the Python bridge is 127.0.0.1-only and Python 3.9-compatible in the repo
  - no new runtime dependencies
  - single instance (exit 3)
  - GUID never logged
  - the repo is public
- Only the Swift app talks to the internet: `api.github.com`, and GitHub's release asset hosts.
- Dev builds never check for or install updates.
- The release bundle id is `io.github.megamattmiller.loupedeckbridge` ("LoupedeckBridge"). The dev bundle id is `io.github.megamattmiller.loupedeckbridge.dev` ("LoupedeckBridge Dev").
- The version sent to Lightroom on register stays `"0.1"`.
- An update or install is accepted only if every check passes:
  - `codesign --verify --strict` with `identifier "io.github.megamattmiller.loupedeckbridge" and certificate leaf = H"<sha256>"`
  - one app in the zip, with the release bundle id
  - a newer version, unless `--allow-older` on the command line
  - nothing is replaced until all of the above pass
- Asset name: `LoupedeckBridge-v<version>-macos-arm64.zip`, plus `<same>.sha256`.
- Python: python-build-standalone CPython 3.12, `aarch64-apple-darwin`, `install_only`, pinned with its SHA-256 in `tools/python-standalone.lock`.
- **Ask the user first:**
  - the first build-time downloads (the Python tarball, wheels)
  - every push and tag
  - creating the GitHub `release` environment and its required reviewer
  - each publish
  - The user runs `tools/make_signing_identity.sh` themselves; the assistant never handles the key or its password.
- Commit after each task (local only).

## Review Focus

1. **A tampered update, or one signed with another key:** refused with an alert, nothing replaced, the current version keeps running. Tests: Task 3 `install_plan_refuses_*`, Task 4 `test_install_refuses_wrong_signature`.
2. **An update that fails midway** (download error, bad zip, full disk): the current version keeps running and the user is told which step failed. Tests: Task 4 `test_install_failure_leaves_app_in_place`; Task 3 `install_plan_order`.
3. **The dev build and the release both installed:** never two bridges; `bridgectl` acts on the release unless `--dev`; `start --dev` pauses the release and `stop --dev` resumes it. Test: Task 1 `test_bridgectl_targets`.
4. **A release tag whose version or changelog doesn't match:** CI fails before signing. Test: Task 5 `test_check_release_*`.
5. **GitHub unreachable, rate-limited, or answering with unexpected JSON:** a quiet log line, retried the next day, no alert. Test: Task 3 `release_parse_rejects_garbage`, `check_schedule`.

---

### Task 1: One version; dev and release apps kept apart

**Files:**
- Modify: `bridge/__init__.py` (`__version__ = "0.5.0"`), `bridge/settings/server.py` + `static/index.html` (footer shows `v0.5.0`), `macos/launcher/Policies.swift` (`RuntimePaths`), `macos/launcher/main.swift`, `macos/launcher/BridgeProcess.swift` (use `RuntimePaths`), `tools/build_mac_app.sh` (`--dev` / `--release` variants), `tools/bridgectl` (release by default, `--dev`)
- Test: `tests/test_settings_server.py`, `macos/launcher/tests/PolicyTests.swift` + `tests/test_launcher_policies.py`, `tests/test_bridgectl.py`

**Interfaces:**
- `bridge.__version__ = "0.5.0"`. `bridge/app.py` keeps `APP_VERSION = "0.1"` for Lightroom, with a comment saying why.
- `struct RuntimePaths { let python: String; let workdir: String; static func resolve(info: [String: Any], bundle: String) -> RuntimePaths? }`:
  - `LBRuntime == "bundled"` → `python = <bundle>/Contents/Resources/python/bin/python3`, `workdir = <bundle>/Contents/Resources/app`
  - `"repo"` (or missing, for old builds) with `LBRepoPath` → `<repo>/.venv/bin/python`, workdir `<repo>`
  - anything else → nil (the app logs and exits 2)
- `BridgeProcess(python:workdir:arguments:)` replaces `(repo:arguments:)`. The spawn is unchanged otherwise. Update the `status_pipe_reaches_the_app` check to the new initializer.
- Info.plist keys:
  - `LBRuntime`
  - `LBVersion`
  - `LBSignerSHA256` (release only; empty for dev)
  - `LBIsDev` (true for dev)
- `tools/build_mac_app.sh [--release OUT_DIR] [--dev]` (default `--dev` into `build/`). Dev: bundle id `….dev`, name "LoupedeckBridge Dev", `LBRuntime=repo`. `--release` is filled in by Task 2.
- `tools/bridgectl`:
  - `RELEASE_APP=/Applications/LoupedeckBridge.app`, `DEV_APP=$REPO/build/LoupedeckBridge Dev.app`
  - `start|stop|restart|status|login` act on the release; `--dev` (first argument after the command) on the dev app
  - process matching uses each app's full executable path
  - `start --dev` stops the release first, and remembers that in `~/Library/Application Support/loupedeck-lr-bridge/release-paused`
  - `stop --dev` starts the release again if that marker exists, then removes it
  - `build` builds the dev app
  - `install` comes in Task 4
  - the app menu shows "LoupedeckBridge v<LBVersion>" (dev: "LoupedeckBridge Dev (repo)")

- [ ] **Step 1: Write the failing tests:**
  - `test_page_shows_version` (server): GET `/` contains `v0.5.0`.
  - Swift `runtime_paths_bundled_and_repo`: both shapes resolve as above; `{"LBRuntime": "weird"}` → nil.
  - `test_bridgectl_targets` (Review Focus 3), in `tests/test_bridgectl.py`. It runs `tools/bridgectl` with `PATH` and `HOME` pointing at a temp dir, whose fake `pgrep`, `pkill` and `open` record their arguments in a log file. Asserts:
    - `status` checks the `/Applications/LoupedeckBridge.app/...` path
    - `status --dev` checks the `build/LoupedeckBridge Dev.app/...` path
    - `start --dev` while the release "runs" (the fake `pgrep` succeeds for the release path) sends TERM to the release, writes the `release-paused` marker, then opens the dev app
    - `stop --dev` with the marker present opens the release and removes the marker
- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest -q tests/test_settings_server.py tests/test_launcher_policies.py tests/test_bridgectl.py` → FAIL.
- [ ] **Step 3: Implement** per the interfaces. In the build script, keep the `rm -rf` of only the app being built.
- [ ] **Step 4: Run the whole suite** → all pass. Run `bash -n tools/*.sh tools/bridgectl`.
- [ ] **Step 5: Ask the user** before rebuilding their dev app. The rename to "LoupedeckBridge Dev" makes macOS ask for Accessibility and notifications once more for the dev app. Then `tools/bridgectl build && tools/bridgectl start --dev`, and check the bridge runs. Commit: "One version; dev and release apps kept apart".

---

### Task 2: The release app with bundled Python

**Files:**
- Create: `tools/python-standalone.lock` (URL and SHA-256), `tools/build_release_app.sh`, `tools/sign_release_app.sh`, `tools/package_release.sh`
- Modify: `tools/build_mac_app.sh` (`--release` calls it), `.gitignore` (`dist/`, `.cache/`)
- Test: `tests/test_release_bundle.py` (skipped unless `LB_RELEASE_APP` points at a built app)

**Interfaces:**
- `tools/build_release_app.sh OUT_DIR [--sign IDENTITY]`:
  - downloads the locked tarball into `.cache/` if missing, and checks its SHA-256 (mismatch → exit 1)
  - unpacks to `OUT_DIR/LoupedeckBridge.app/Contents/Resources/python`
  - `python3 -m pip install --no-cache-dir -r requirements.txt` into it
  - strips `test/`, `tests/`, `__pycache__/`, `idlelib/`, `tkinter/`, `ensurepip/` and headers, then `compileall`
  - copies `bridge/`, `config/` and `docs/lr_parameters_10.0.json` to `Contents/Resources/app/`
  - compiles the launcher
  - Info.plist: `LBRuntime=bundled`, `LBVersion` from `bridge/__init__.py`, `LBSignerSHA256` empty
  - then runs `sign_release_app.sh` (ad hoc unless `--sign`) and `package_release.sh`
- `tools/sign_release_app.sh APP [IDENTITY]`:
  - with an identity: writes the certificate's SHA-256 into `LBSignerSHA256`
  - signs every Mach-O file inside (`python3.12`, `*.so`, `*.dylib`), then the app (ad hoc without an identity)
  - the release workflow uses it to sign the exact build the tests ran on
- `tools/package_release.sh APP OUT_DIR`: `LoupedeckBridge-v<ver>-macos-arm64.zip` (`ditto -c -k --keepParent`) and its `.sha256`.

- [ ] **Step 1: Ask the user's go-ahead** for the build-time downloads: the python-build-standalone tarball (about 20 MB, from github.com/astral-sh/python-build-standalone) and three wheels from PyPI. Pick the newest 3.12 `install_only` build from at least two weeks ago, and record the URL and SHA-256 in the lock file.
- [ ] **Step 2: Write `tests/test_release_bundle.py`.** It's skipped without `LB_RELEASE_APP`. Tests:
  - `test_layout`: the python, app and Info.plist keys exist; `LBRuntime == "bundled"`
  - `test_bundled_python_runs_the_suite`: run `<python> -m pytest -q` in the repo with `PYTHONPATH=<bundle>/Contents/Resources/app`, with the repo's `tests/` available; it passes
  - `test_rtmidi_imports`: `<python> -c "import rtmidi, mido, websockets"` exits 0
  - `test_no_dev_leftovers`: no `tests`, `__pycache__` or `idlelib` directories under `Resources/python/lib/python3.12`
- [ ] **Step 3: Implement the build script.** Build into the scratchpad (`LB_RELEASE_APP=<scratch>/LoupedeckBridge.app`), then run `pytest tests/test_release_bundle.py` → PASS (spec "To verify" 1).
- [ ] **Step 4: Run the whole suite** → all pass (the bundle tests skip without the variable).
- [ ] **Step 5: Commit:** "Release app: bundled Python 3.12, code, Info.plist, signing hook".

---

### Task 3: Update decisions (pure Swift, tested)

**Files:**
- Modify: `macos/launcher/Policies.swift`, `macos/launcher/tests/PolicyTests.swift`, `tests/test_launcher_policies.py`

**Interfaces:**
- `struct Version: Comparable { init?(_ text: String) }` takes `"0.5.0"` or `"v0.5.0"` (three numeric parts) and compares them numerically.
- `struct ReleaseInfo: Equatable { let version: Version; let zipURL: URL; let sha256URL: URL; static func parse(_ data: Data) -> ReleaseInfo? }`:
  - reads the GitHub "latest release" JSON: `tag_name`, and `assets[].name` / `browser_download_url`
  - requires both `LoupedeckBridge-v<ver>-macos-arm64.zip` and its `.sha256`
  - ignores `draft` and `prerelease` releases
- `struct UpdateSchedule`:
  - `interval = 86_400`, `firstDelay = 30`
  - `func shouldCheck(now: Date, lastCheck: Date?, enabled: Bool, isDev: Bool, sinceLaunch: TimeInterval) -> Bool`
- `struct UpdateNotice`: `mutating func announce(_ v: Version, current: Version) -> Bool`, true once per newer version.
- `enum InstallStep: Equatable { case download, unzip, verify, stopBridge, moveOldToTrash, moveNewIntoPlace, launchNew }`, and `static let installOrder: [InstallStep]` in that order. Verify comes before anything is moved.
- `func installProblem(bundleID: String, version: Version?, current: Version, signatureOK: Bool, appCount: Int, allowOlder: Bool) -> String?` gives the first failed check in plain words, or nil.

- [ ] **Step 1: Write the failing checks:**
  - `version_compare`: `0.10.0 > 0.9.9`; `v0.5.1 > 0.5.0`; `"0.5"` → nil; `"x.y.z"` → nil
  - `release_parse_accepts_a_real_shape`: sample JSON with two assets → `ReleaseInfo` with the right URLs
  - `release_parse_rejects_garbage` (Review Focus 5): empty data, `{}`, an API rate-limit body `{"message":"API rate limit exceeded"}`, a release without the `.sha256` asset, `"draft": true`, `"prerelease": true` → nil
  - `check_schedule` (Review Focus 5):
    - false for dev, when disabled, and before 30 s
    - true with no last check; true at 24 h; false at 23 h
  - `notice_once_per_version`: announce 0.6.0 → true, 0.6.0 again → false, 0.6.1 → true, 0.5.0 → false
  - `install_plan_order` (Review Focus 2): `installOrder.firstIndex(of: .verify)` is before `.stopBridge`, `.moveOldToTrash` and `.moveNewIntoPlace`
  - `install_plan_refuses_*` (Review Focus 1), checking that `installProblem` names the problem for:
    - a wrong bundle id
    - a bad signature
    - two apps in the zip
    - an older or equal version without `allowOlder`
    - and that it returns nil for a valid newer one
- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest -q tests/test_launcher_policies.py` → FAIL (compile errors).
- [ ] **Step 3: Implement** in `Policies.swift` (Foundation only).
- [ ] **Step 4: Run the whole suite** → all pass.
- [ ] **Step 5: Commit:** "Update decisions: versions, release parsing, schedule, install checks".

---

### Task 4: The updater, the installer, and "go back"

**Files:**
- Create: `macos/launcher/Updater.swift`, `tools/install.sh`
- Modify: `macos/launcher/StatusMenu.swift`, `tools/bridgectl` (`install` → `install.sh`)
- Test: `tests/test_install_script.py`

**Interfaces:**
- `Updater` (in the app; release builds only):
  - `checkIfDue()` on launch + 30 s and on a 1 h timer, using `UpdateSchedule`; `checkNow()` from the menu
  - `GET` the latest-release URL with URLSession (a `User-Agent: LoupedeckBridge/<ver>` header, a 15 s timeout), then `ReleaseInfo.parse`
  - stores `lastUpdateCheck` and `autoUpdateCheck` (default true) in `UserDefaults`
  - on a newer version: the menu shows "Update available: v<x> – Install…", and `UpdateNotice` decides the one alert
  - `install(_ release:)` follows `installOrder`:
    - download the zip and `.sha256` to a temp folder and compare the SHA-256
    - `ditto -x -k` it
    - find exactly one `.app`
    - read its Info.plist
    - run `/usr/bin/codesign --verify --strict -R='identifier "io.github.megamattmiller.loupedeckbridge" and certificate leaf = H"<LBSignerSHA256>"' <app>`
    - `installProblem(...)`
    - stop the bridge with the supervisor's quit path, but don't terminate
    - `FileManager.trashItem` the running app, recording the Trash URL in `UserDefaults` as `previousAppPath`
    - move the new app to the running app's path
    - `open -n` it
    - `NSApp.terminate`
  - any failure before `moveOldToTrash` → an alert naming the step; the bridge restarts if it was stopped
- Menu: "Check for updates now", "Check for updates automatically" (a checkmark), the update item when one exists. "Go back to the previous version" appears when `supervisor` shows the restart budget used up and `previousAppPath` exists; it swaps back the same way, and the signature check still applies.
- `tools/install.sh [vX.Y.Z|latest] [--allow-older]` (bash, only built-in tools):
  - `PINNED_SIGNER_SHA256=""` is set in Task 6
  - `RELEASES_API`, and a `LB_INSTALL_DIR` override (default `/Applications`)
  - downloads with `curl -fL`, checks the SHA-256 with `shasum -a 256`, unzips with `ditto`
  - verifies with `codesign` (the same requirement), compares versions (`sort -V`)
  - stops a running release, moves the old app to `~/.Trash/`, `ditto`s the new one into place, `open`s it
  - exit codes: 0 ok, 1 refused (a check failed, nothing replaced), 2 usage
  - `curl`, `codesign` and `open` are looked up on `PATH`, so tests can stand them in
- `tools/bridgectl install [args]` runs `tools/install.sh`.

- [ ] **Step 1: Write the failing tests** in `tests/test_install_script.py`. They use stand-in `curl` (serving files from a temp "release"), `codesign` (accepts or refuses by an env var) and `open` (records), with `LB_INSTALL_DIR` and `HOME` in a temp dir:
  - `test_install_into_empty_dir`: a valid release → the app is in place and `open` is called
  - `test_install_refuses_wrong_signature` (Review Focus 1): `codesign` refuses → exit 1, the old app untouched, nothing in the Trash
  - `test_install_refuses_bad_sha256`: exit 1, nothing replaced
  - `test_install_failure_leaves_app_in_place` (Review Focus 2): `curl` fails, or the zip is corrupt → exit 1, the old app untouched
  - `test_older_needs_flag`: an older version → exit 1; with `--allow-older` → installed
  - `test_old_app_goes_to_trash`: after an update, the old app is in `$HOME/.Trash/`
- [ ] **Step 2: Run to verify they fail** → FAIL (no script).
- [ ] **Step 3: Implement** `install.sh`, `Updater.swift` and the menu items. `swiftc -typecheck macos/launcher/*.swift` is clean; `bash -n tools/install.sh`.
- [ ] **Step 4: Run the whole suite** → all pass.
- [ ] **Step 5: Commit:** "In-app updates, the standalone installer, and go back".

---

### Task 5: GitHub workflows, release checks, signing identity script

**Files:**
- Create:
  - `.github/workflows/ci.yml` and `.github/workflows/release.yml`
  - `tools/check_release.py`, `tools/release.sh`, `tools/make_signing_identity.sh`
  - `CHANGELOG.md` (with `## v0.5.0`, summarizing milestones 1–6)
- Test: `tests/test_check_release.py`

**Interfaces:**
- `tools/check_release.py VERSION`:
  - exit 0 and print that version's changelog section, if `bridge.__version__ == VERSION` and `CHANGELOG.md` has `## vVERSION`
  - otherwise exit 1 with the reason
- `tools/release.sh VERSION`:
  - checks a clean tree on `main`, up to date with `origin/main`
  - runs `check_release.py` and the suite
  - creates tag `vVERSION`, then **asks** "Push tag vVERSION? GitHub will then build it and wait for your approval [y/N]" before `git push origin vVERSION`
- `ci.yml` (no secrets): on `push` and `pull_request`, on `macos-15`:
  - set up Python 3.9 and run the suite
  - build an unsigned release app (`tools/build_release_app.sh dist`) and run `tests/test_release_bundle.py` against it
  - `permissions: contents: read`
- `release.yml`: on `push` of tags `v*` and `workflow_dispatch` (input `version`).
  - **Job `build`** (`macos-15`):
    - `check_release.py`
    - build unsigned
    - `test_release_bundle.py`
    - upload the app as an artifact
  - **Job `sign_and_publish`** (needs `build`, `environment: release`, `permissions: contents: write`):
    - download the artifact
    - decode `MAC_SIGNING_P12` (base64) with `MAC_SIGNING_P12_PASSWORD` into a temp keychain (`security create-keychain`, `import`, `set-key-partition-list`)
    - `tools/sign_release_app.sh <app> "LoupedeckBridge Release"`, then `tools/package_release.sh`: signs the exact tested build
    - verify with `codesign` against the requirement
    - `gh release create vVERSION <zip> <sha256> --notes "$(python3 tools/check_release.py VERSION)"`
    - always delete the keychain
  - Only `actions/checkout`, `actions/setup-python`, `actions/upload-artifact` and `actions/download-artifact`, pinned to commit SHAs. No `pull_request` triggers in this file.
- `tools/make_signing_identity.sh` (**run by the user**):
  - `openssl` makes a code-signing key and certificate (CN "LoupedeckBridge Release", extendedKeyUsage codeSigning, 10 years)
  - packs them into a `.p12` with a random password, compatible with macOS `security import`
  - `gh secret set MAC_SIGNING_P12 --env release` and `gh secret set MAC_SIGNING_P12_PASSWORD --env release`, with values read from files, never echoed
  - prints the certificate's SHA-256
  - deletes the temp files unless `--keep BACKUP_DIR`

- [ ] **Step 1: Write the failing tests** (Review Focus 4):
  - `test_check_release_ok`: matching version and section → exit 0, the section printed
  - `test_check_release_version_mismatch` → exit 1
  - `test_check_release_missing_section` → exit 1
- [ ] **Step 2: Run to verify they fail** → FAIL.
- [ ] **Step 3: Implement** the scripts and workflows. `bash -n` every script. Workflow YAML is checked when the CI first runs in Task 6.
- [ ] **Step 4: Run the whole suite** → all pass.
- [ ] **Step 5: Commit:** "Release tooling: CI, release workflow, checks, signing identity script, changelog".

---

### Task 6: First release, v0.5.0 (with the user)

**Files:**
- Modify: `tools/install.sh` (`PINNED_SIGNER_SHA256`), `docs/FINDINGS.md`, and `README.md`:
  - installing (`install.sh` on any Mac), updating from the menu, and turning automatic checks off
  - that only the menu-bar app talks to GitHub, while the bridge stays local
  - releasing (`release.sh`, approving on GitHub), and the dev build (`bridgectl --dev`)
  - the roadmap: 6 = releases ✅ once done, 7 = Windows

- [ ] **Step 1: Ask, then push** `main` and the branch (pre-push checks as before). CI must pass on GitHub; fix it if not.
- [ ] **Step 2: The user creates** the GitHub `release` environment with themselves as required reviewer (Settings → Environments), or the assistant does it with `gh api`, with their go-ahead.
- [ ] **Step 3: The user runs** `tools/make_signing_identity.sh` and reads out the certificate's SHA-256. Commit it as `PINNED_SIGNER_SHA256` in `install.sh`.
- [ ] **Step 4: Merge to `main` with the user's go-ahead, then** `tools/release.sh 0.5.0`. The push asks. The user approves the run on GitHub, and the release appears.
- [ ] **Step 5: Install with the user** (`tools/install.sh`). Check:
  - a first-run permission grant; then the menu shows v0.5.0 and the bridge works
  - Lightroom connects with no new Allow dialog (spec "To verify" 3)
  - spec "To verify" 5 (the signature passes on this Mac)
  - the dev app paused or stopped
- [ ] **Step 6: Commit** the docs and FINDINGS.

---

### Task 7: v0.5.1 through the menu (proves updates)

**Files:**
- Modify: a few deferred minors (e.g. "Open settings…" can't be disabled → `autoenablesItems = false`; the spawn-failure wording; child signals reset to default with `posix_spawnattr_setsigdefault`), each with its test; `bridge/__init__.py` → `0.5.1`; `CHANGELOG.md`; `docs/FINDINGS.md`

- [ ] **Step 1: TDD each small fix** (a Swift check, or a test, first).
- [ ] **Step 2:** `tools/release.sh 0.5.1` (asks), and the user approves the run on GitHub.
- [ ] **Step 3: With the user:**
  - the v0.5.0 app's menu shows "Update available: v0.5.1" within its daily check (or "Check for updates now"); Install
  - the app restarts as v0.5.1
  - the permissions are still granted (spec "To verify" 2)
  - the old app is in the Trash (spec "To verify" 4)
- [ ] **Step 4: Commit** FINDINGS.
