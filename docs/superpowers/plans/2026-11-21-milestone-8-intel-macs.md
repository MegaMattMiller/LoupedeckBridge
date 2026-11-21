# Milestone 8: Intel Macs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release LoupedeckBridge for Intel Macs as a first-class platform. One release carries both Macs' downloads; `install.sh` and the menu-bar app each fetch the one for the Mac they're on; every Apple Silicon app already installed keeps updating untouched.

**Architecture:**
- `tools/build_release_app.sh` builds natively for its host (`arm64` or `x86_64`), picking that arch's pinned Python and wheels, and stamps `LBArch` into the Info.plist.
- Two arch-specific downloads per release: `LoupedeckBridge-v<ver>-macos-arm64.zip` (unchanged) and `…-macos-x86_64.zip`.
- `tools/install.sh` detects the Mac (and sees through Rosetta) and fetches that arch's zip.
- `Policies.swift` takes the arch as a parameter; the running app's arch is a compile-time constant.
- The release workflow gains `build-intel` and `verify-intel` on `macos-15-intel`; `sign` signs both apps in the one approved step; `publish` gates on seven files.

**Tech Stack:** Python ≥3.9 (repo) / 3.12 (both release apps), Swift via `swiftc`, bash, `codesign`, `ditto`, `plutil`, `gh`, GitHub Actions (`macos-15`, `macos-15-intel`, `windows-2025`, `ubuntu-24.04`), `pytest`.

**Spec:** [docs/superpowers/specs/2026-11-21-m8-intel-macs-design.md](../specs/2026-11-21-m8-intel-macs-design.md), within [the bridge design](../specs/2026-11-16-loupedeck-bridge-design.md).

## Global Constraints

- Milestones 1–7 hold: the bridge is 127.0.0.1-only and Python 3.9-compatible in the repo; no new runtime dependencies; single instance (exit 3); the client GUID is never logged; the repo is public.
- **The arm64 asset name never changes.** Apps from v0.5.0–v0.6.2 ask for `LoupedeckBridge-v<ver>-macos-arm64.zip` by name for ever. Renaming it, or publishing a release without it, silently cuts off every Apple Silicon install.
- **Both Mac release apps are built *and* tested natively.** Nothing is cross-built, and no bundle ships whose Python was never run.
- The release key is unchanged, still only in the GitHub `release` environment, and still one approval per release. `codesign` is arch-independent, so one runner signs both.
- `MIN_MACOS` is `14.0` for both arches.
- Both Mac locks pin the same CPython version and the same python-build-standalone build date.
- Dev builds never check for or install updates.
- Verified facts this plan relies on (from the design doc, checked 2026-11-21):
  - Intel Python: `cpython-3.12.16+20261026-x86_64-apple-darwin-install_only.tar.gz`, SHA-256 `a962e47df522889eaa7ff0d6a56203f1079f68aabb65ffdbe8455f362bc769f3`
  - `python_rtmidi-1.5.8-cp312-cp312-macosx_10_9_x86_64.whl` → `5443634597eb340cdec0734f76267a827c2d366f00a6f9195141c78828016ac2`
  - `websockets-15.0.1-cp312-cp312-macosx_10_13_x86_64.whl` → `592f1a9fe869c778694f0aa806ba0374e97648ab57936f092fd9d87f8bc03665`
  - `swiftc -target x86_64-apple-macos14.0` compiles the launcher clean, `minos 14.0`
- **Ask the user first:** the Intel Python tarball download (a new build-time download), every push and tag, and the release run's approval.

## Review Focus

1. **The arm64 path is byte-for-byte unchanged** where it can be: same lock, same requirements, same asset name, same checks. A diff that perturbs the Apple Silicon build is a finding.
2. **Rosetta.** `uname -m` is `x86_64` in a translated shell on an Apple Silicon Mac. `install.sh` must not install the Intel app there.
3. **No execution across arches in CI.** The Intel app's `--check-signature` runs only on an Intel runner.
4. **The publish gate** refuses to publish unless all seven files are present, so neither Mac can lose its update path.
5. **`LBArch` is checked, not trusted.** `install.sh` compares it against the arch it meant to install.

---

### Task 1: The Intel pinned pair, and an arch-aware build

**Files:**
- Add: `tools/python-standalone-intel.lock`, `tools/release-requirements-intel.txt`
- Modify: `tools/build_release_app.sh` (host-arch gate, lock/requirements choice, `-target`, `LBArch`), `tools/package_release.sh` (name from `LBArch`)
- Test: `tests/test_release_lock.py`, `tests/test_release_bundle.py`

**Interfaces:**
- `tools/python-standalone-intel.lock`: same two keys as the arm64 lock (`url=`, `sha256=`), with a header comment saying it's the Intel half and must stay on the same build date as `tools/python-standalone.lock`.
- `tools/release-requirements-intel.txt`: the same four packages and versions as `tools/release-requirements.txt`, with the two Intel wheel hashes above; `mido` and `packaging` keep their `py3-none-any` hashes.
- `tools/build_release_app.sh`:
  - `ARCH="$(uname -m)"`; `arm64` and `x86_64` are accepted, anything else fails with `The release app is built natively, for arm64 or x86_64 (this is <arch>).`
  - `arm64` → `python-standalone.lock` + `release-requirements.txt`; `x86_64` → the `-intel` pair.
  - `swiftc -O -target "$ARCH-apple-macos$MIN_MACOS"`.
  - New Info.plist key `<key>LBArch</key><string>$ARCH</string>`.
  - The closing line names the arch: `built <app> (v<ver>, <arch>, <size>)`.
- `tools/package_release.sh`: `ARCH="$(plutil -extract LBArch raw "$APP/Contents/Info.plist")"`, failing with a clear message if absent (an app from an older build); `NAME="LoupedeckBridge-v$VERSION-macos-$ARCH.zip"`.

- [ ] **Step 1: Write the failing tests:**
  - `test_intel_python_lock` (`test_release_lock.py`): the Intel lock's `url` is under the python-build-standalone download prefix and matches `/cpython-3\.12\.\d+%2B\d{8}-x86_64-apple-darwin-install_only\.tar\.gz$`; `sha256` is 64 hex.
  - `test_both_mac_pythons_are_the_same_build`: the two Mac locks' URLs differ only in `aarch64` vs `x86_64` — i.e. same `3.12.x` version and same `%2B<date>` build. (This is the invariant, not a convention.)
  - `test_intel_release_requirements_pin_what_requirements_pins`: mirrors the arm64 and Windows cases — same versions as `requirements.txt`, every line hash-pinned.
  - `test_intel_and_arm64_requirements_pin_the_same_versions`: the two Mac requirements files pin identical versions, and differ only in the two compiled wheels' hashes.
  - `test_bundle_is_built_for_one_arch` (`test_release_bundle.py`, runs under `LB_RELEASE_APP`): the Info.plist has `LBArch`; it is `arm64` or `x86_64`; the launcher binary's `lipo -info` reports exactly that arch (thin, not fat); and the bundled `python3` reports it too.
- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest -q tests/test_release_lock.py tests/test_release_bundle.py` → FAIL.
- [ ] **Step 3: Ask the user** before the first Intel Python download (a new build-time download, ~70 MB into `.cache/`), then implement per the interfaces.
- [ ] **Step 4: Build it here and test it** — `tools/build_release_app.sh dist`, then the bundled Python runs the suite the way CI does:
  ```
  dist/LoupedeckBridge.app/Contents/Resources/python/bin/python3 -m venv --system-site-packages --without-pip .venv-rel
  .venv-rel/bin/python -m pip install --disable-pip-version-check --require-hashes --only-binary=:all: --no-deps -r tools/release-test-requirements.txt
  .venv-rel/bin/python -m pytest -q
  LB_RELEASE_APP="$PWD/dist/LoupedeckBridge.app" .venv-rel/bin/python -m pytest -q tests/test_release_bundle.py
  ```
  Also `tools/package_release.sh dist/LoupedeckBridge.app out` → `LoupedeckBridge-v<ver>-macos-x86_64.zip`. Then the repo suite, and `bash -n tools/*.sh`.
- [ ] **Step 5: Commit** — "build: the release app for Intel Macs as well as Apple Silicon".

---

### Task 2: `install.sh` picks the right Mac's download

**Files:**
- Modify: `tools/install.sh`
- Test: `tests/test_install_script.py`

**Interfaces:**
- Arch detection, near the top, before the download:
  ```
  arch="${LB_ARCH-}"
  if [ -z "$arch" ]; then
    arch="$(uname -m)"
    # A translated shell on an Apple Silicon Mac reports x86_64; that Mac wants the arm64 build.
    [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" = 1 ] && arch=arm64
  fi
  case "$arch" in arm64|x86_64) ;; *) fail "this Mac's architecture ($arch) has no LoupedeckBridge download" ;; esac
  ```
- `name="LoupedeckBridge-v$want-macos-$arch.zip"`.
- After the existing bundle-id and version checks, one more:
  ```
  new_arch="$(plutil -extract LBArch raw "$new/Contents/Info.plist" 2>/dev/null || true)"
  [ "$new_arch" = "$arch" ] || fail "it's the $new_arch build, not $arch"
  ```
- `say` the arch alongside the version when downloading, so a log shows which build was fetched.
- Every other check, the Trash move, the restart-on-failure path and `--allow-older` are untouched.

- [ ] **Step 1: Write the failing tests** in `tests/test_install_script.py`. Its harness puts stand-in `curl`, `codesign`, `open`, `pgrep`, `pkill`, `ditto` and `sleep` on `PATH` (`FAKES`); the fake `curl` serves `$FAKE_SERVER` by URL basename, and `$FAKE_LOG` records every call. Two harness changes come first:
  - `make_app()` and `publish()` take an `arch` (default `arm64`), writing `LBArch` into the Info.plist and naming the zip `…-macos-<arch>.zip`.
  - `FAKES` gains **`uname`** (prints `$FAKE_UNAME_M` for `-m`) and **`sysctl`** (prints `$FAKE_TRANSLATED`, default `0`, for `sysctl.proc_translated`), so the tests run the same on either Mac. Without a `uname` fake these tests would pass vacuously on one arch and fail on the other.

  Then:
  - `test_installs_the_arch_it_is_running_on`: parameterised over both arches — with `FAKE_UNAME_M=x86_64` the script fetches `…-macos-x86_64.zip` and installs it; with `arm64`, the arm64 zip. Parameterise the existing happy-path case this way so the arm64 coverage is kept, not replaced.
  - `test_refuses_a_bundle_built_for_the_other_arch`: the served zip says `LBArch=arm64` while the Mac is `x86_64` → non-zero exit, the message names both, and the pre-existing app is still in place.
  - `test_rosetta_gets_the_apple_silicon_build`: `FAKE_UNAME_M=x86_64` with `FAKE_TRANSLATED=1` → `$FAKE_LOG` shows the **arm64** zip was fetched.
  - `test_lb_arch_overrides_detection`: `LB_ARCH=arm64` on an `x86_64` Mac fetches the arm64 zip (and is what the other tests lean on being honoured).
  - `test_unknown_arch_is_refused`: `LB_ARCH=ppc64` → non-zero, and `$FAKE_LOG` shows no download was attempted.
- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest -q tests/test_install_script.py` → FAIL.
- [ ] **Step 3: Implement** per the interfaces.
- [ ] **Step 4: Run** `tests/test_install_script.py`, the whole suite, and `bash -n tools/install.sh`.
- [ ] **Step 5: Commit** — "feat(install): fetch the download for the Mac it's running on".

---

### Task 3: The menu-bar app asks for its own arch's update

**Files:**
- Modify: `macos/launcher/Policies.swift`, `macos/launcher/Updater.swift`
- Test: `macos/launcher/tests/PolicyTests.swift` (run by `tests/test_launcher_policies.py`)

**Interfaces:**
- `Policies.swift`:
  ```swift
  /// The architecture this build runs on, decided at compile time so it can never disagree with the binary.
  #if arch(arm64)
  let runningArch = "arm64"
  #elseif arch(x86_64)
  let runningArch = "x86_64"
  #else
  #error("LoupedeckBridge is released for arm64 and x86_64 only")
  #endif
  ```
  - `static func assetName(for version: Version, arch: String) -> String` → `"LoupedeckBridge-v\(version)-macos-\(arch).zip"`.
  - `static func parse(_ data: Data, arch: String) -> ReleaseInfo?` — looks for that arch's zip and its `.sha256`. A release that carries only the *other* arch's downloads is not an update (nil), and one carrying both is parsed for the one asked for.
  - The doc comment on `ReleaseInfo` is updated: it's the arch's own pair of assets that counts.
- `Updater.swift`: both call sites (`ReleaseInfo.parse` at `:93`, `assetName` at `:188`) pass `runningArch`. Nothing else changes — download, hash, unzip, signature check and swap are all arch-blind.

- [ ] **Step 1: Write the failing tests** (Swift, in `PolicyTests.swift`):
  - `release_parse_picks_the_running_arch`: a sample release JSON carrying all four Mac assets parses to the x86_64 URLs when asked for `x86_64`, and the arm64 URLs when asked for `arm64`.
  - `release_parse_needs_its_own_arch`: a release with only the arm64 pair → nil for `x86_64`, and parses for `arm64` (this is the back-compatibility case: an old release seen by a new Intel app offers no update rather than a wrong one).
  - `release_parse_still_needs_the_sha256`: the arch's zip present but its `.sha256` missing → nil. (Extends the existing negative cases over both arches.)
  - `asset_name_per_arch`: both names are exactly as above.
  - `running_arch_is_one_of_two`: `runningArch` is `arm64` or `x86_64` — so the test binary itself proves the compile-time constant resolved.
  - Update the existing `sampleRelease` fixture to carry both Macs' assets, keeping its arm64 assertions.
- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest -q tests/test_launcher_policies.py` → FAIL.
- [ ] **Step 3: Implement** per the interfaces.
- [ ] **Step 4: Run** the launcher tests and the whole suite. Compile for both targets to prove neither branch rots:
  `swiftc -O -target arm64-apple-macos14.0 macos/launcher/*.swift -o /tmp/lb-arm64` and the same for `x86_64`.
- [ ] **Step 5: Commit** — "feat(updater): each Mac's app updates from its own download".

---

### Task 4: The release workflow builds, signs and publishes both Macs

**Files:**
- Modify: `.github/workflows/release.yml`, `.github/workflows/ci.yml`
- Test: `tests/test_release_workflow.py`

**Interfaces:**
- **`build-intel`**: `runs-on: macos-15-intel`, otherwise the same steps as `build` — version and tag check, `check_release.py`, `tools/build_release_app.sh dist`, save the build *before any test code runs*, upload it as `unsigned-app-intel`, test it with its own Python, then the "the tests left the build exactly as it was saved" manifest check. Outputs `version`, `commit`, `zip_sha256`.
- **`sign`**: `needs: [build, build-windows, build-intel]`.
  - The commit check covers all three: any disagreement fails.
  - Downloads `unsigned-app-intel` into `dist-intel/` and hash-checks it against `needs.build-intel.outputs.zip_sha256`, exactly as the other two are checked.
  - One signing step, one key, both apps: `tools/sign_release_app.sh dist/LoupedeckBridge.app "LoupedeckBridge Release"` and the same for `dist-intel/LoupedeckBridge.app`, plus the Windows `.p7s` as now.
  - The "updater and install.sh will accept it" step keeps running the **arm64** app's `--check-signature`, and additionally does the `codesign --verify --strict -R=…` and pinned-certificate comparison for **both** apps (those don't execute anything).
  - Packages both: `tools/package_release.sh dist/LoupedeckBridge.app out` and `tools/package_release.sh dist-intel/LoupedeckBridge.app out`.
- **`verify-intel`**: `runs-on: macos-15-intel`, `needs: [build-intel, sign]`. Downloads `signed-release`, unzips the Intel zip, and runs that app's own `--check-signature` plus the `install.sh` pinned-key comparison — the Intel counterpart of `verify-windows`, and the only place an Intel binary may be executed.
- **`publish`**: `needs: [build, build-windows, build-intel, sign, verify-intel, verify-windows]`; the file list gains `…-macos-x86_64.zip` and its `.sha256`; the count becomes **7**; `sha256sum -c ./*.sha256` unchanged.
- **`ci.yml`**: the Mac release-build-and-test job becomes a matrix over `macos-15` and `macos-15-intel`; the Python 3.9 suite job likewise. Keep the existing signing rehearsal on `macos-15` only (it proves the signing path, which is arch-independent).

- [ ] **Step 1: Write the failing tests** in `tests/test_release_workflow.py`. It reads both workflows **as text** — there's no YAML parser in the test tools — using its own `outline()` (the layout GitHub reads, so a broken file fails here rather than passing vacuously) and `job(text, name)` helpers. Use those; don't add a YAML dependency.
  - `test_publish_requires_both_macs_downloads`: the publish gate's file list contains both Mac zips and their `.sha256`, the three Windows files, and asserts exactly seven.
  - `test_intel_build_runs_on_an_intel_runner`: a `build-intel` job exists, `runs-on: macos-15-intel`, and it uploads `unsigned-app-intel`.
  - `test_sign_needs_every_build_and_signs_both_macs`: `sign.needs` includes `build`, `build-windows` and `build-intel`; its steps reference both app paths.
  - `test_intel_app_is_only_executed_on_an_intel_runner`: no job whose `runs-on` isn't `macos-15-intel` runs `--check-signature` against a path under `dist-intel`; `verify-intel` exists, runs on `macos-15-intel`, and needs `[build-intel, sign]`.
  - `test_publish_needs_both_verifications`: `publish.needs` includes `verify-intel` and `verify-windows`.
  - `test_ci_builds_both_mac_releases`: the CI matrix includes both Mac runners.
- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest -q tests/test_release_workflow.py` → FAIL.
- [ ] **Step 3: Implement** both workflows. Keep every action pinned to the SHAs already in use.
- [ ] **Step 4: Run** the whole suite — `test_release_workflow.py`'s `outline()` checks are themselves the layout check, so a mis-indented job fails there.
- [ ] **Step 5: Ask the user before pushing.** CI on the branch is what actually proves `macos-15-intel` exists and has the Xcode and Python the build needs (*To verify first* #1). Commit: "ci: build, test, sign and verify Intel Mac releases".

---

### Task 5: The docs, and the trap that matters

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `CLAUDE.md`, `docs/FINDINGS.md`, `bridge/__init__.py`

**Interfaces:**
- `bridge/__init__.py`: `__version__ = "0.7.0"` (a new platform, as Windows was v0.6.x).
- `CHANGELOG.md`: a `## v0.7.0 — <date>` section, in the house voice, leading with Intel Macs and noting that Apple Silicon installs are unaffected.
- `README.md`: the status line (both Mac architectures), the Mac install section (one command, either Mac; `LB_ARCH` for forcing one), the "Releasing" section (seven downloads, the two Mac build jobs), and the layout table (`tools/python-standalone-intel.lock`, `tools/release-requirements-intel.txt`).
- **`CLAUDE.md`'s trap, rewritten:** GitHub's "latest release" must include **both** Mac downloads (`…-macos-arm64.zip` *and* `…-macos-x86_64.zip`), or that kind of Mac quietly finds no update; `release.yml`'s publish job refuses without all seven files.
- `docs/FINDINGS.md`: a `## Milestone 8: Intel Macs` section with the iMac's details, the three verified pins, the `macos-15-intel` runner **and its August 2027 retirement** (with the options when it comes), and what each live check proved.

- [ ] **Step 1: Write the failing test** — `tools/check_release.py` already checks the version and changelog agree; run it for `0.7.0` to watch it fail before the version and section exist (`python3 tools/check_release.py 0.7.0`).
- [ ] **Step 2: Implement** the version, changelog and docs.
- [ ] **Step 3: Run** `python3 tools/check_release.py 0.7.0` and the whole suite.
- [ ] **Step 4: Ask the user to read the changelog and README wording** before committing. Commit: "docs: Intel Macs, and v0.7.0".

---

### Task 6: One fresh review of the whole branch

- [ ] **Step 1:** A single review of every change on the branch, against *Review Focus* above, by a reviewer that hasn't been following along.
- [ ] **Step 2:** Fix what it finds, test-first where it's behavioural. Commit the fixes as one commit, as milestone 7 did ("fix: the final review's smaller Windows findings").

---

### Task 7: The first Intel release, v0.7.0 (with the user)

- [ ] **Step 1: Ask before pushing the branch and merging to `main`.** CI must pass on both Mac runners first.
- [ ] **Step 2:** The user runs `tools/release.sh 0.7.0`, which asks before pushing the tag.
- [ ] **Step 3:** The user approves the `release` environment on GitHub. Watch that `build`, `build-intel` and `build-windows` all built the same commit, and that `verify-intel` passes.
- [ ] **Step 4: Check the published release has all seven downloads**, the two Mac zips among them.
- [ ] **Step 5: Live check on this iMac, with the user:** `install.sh` from GitHub (it should print the release key's fingerprint, say `x86_64`, and install), then the Accessibility and notification grants, then the real device and Lightroom — dials, dial clicks, the colour dials, the five buttons' three modes, presets on P1–P8, the arrows and Tab, Before/After, the settings page, and a remap. The menu should show v0.7.0.
- [ ] **Step 6: Live check on the Apple Silicon Mac:** its menu's **Check for updates now** still finds v0.7.0 and installs it, proving the arm64 path is untouched by all of this.
- [ ] **Step 7: Record both in `docs/FINDINGS.md`.** Commit.

---

### Task 8: v0.7.1 through the menu on Intel (proves updates)

- [ ] **Step 1:** Whatever the review and the live checks turned up becomes v0.7.1, with its changelog section.
- [ ] **Step 2:** Release it as above (ask before the tag; the user approves).
- [ ] **Step 3: On this iMac,** wait for the daily check or use **Check for updates now**, then **Install…**. It must check the signature against the release key, stop the bridge, put v0.7.0 aside, install v0.7.1, start it, and come back with the device working — Intel to Intel, with the Accessibility grant surviving (same key, same place).
- [ ] **Step 4:** Try **Go back to the previous version** once, then update again.
- [ ] **Step 5: Record it in `docs/FINDINGS.md`.** This is the check that proves the whole Intel release path end to end. Commit.
