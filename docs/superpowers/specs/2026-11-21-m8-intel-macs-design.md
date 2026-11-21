# Milestone 8: Intel Macs (design)

Date: 2026-11-21 · Status: draft for approval · Part of: [the bridge design](2026-11-16-loupedeck-bridge-design.md),
after [milestone 7](2026-11-17-m7-windows-design.md)

## Intent
Release LoupedeckBridge for **Intel Macs** as a first-class platform, alongside Apple Silicon and Windows. An Intel
Mac gets the same `install.sh` command, the same signed releases, and the same updates from the menu as an Apple
Silicon one. The user's own Mac for this milestone is an **Intel iMac**, so the live checks happen on the real
machine and the real device.

Nothing about the *behaviour* changes: this milestone is entirely about the release and distribution layer.

## Found on the user's Mac (2026-11-21)
- **iMac19,1** (27" 2019), Intel Core i5-8500, **macOS 15.7.9** (24G830), Xcode installed (Apple Swift 6.2.4,
  clang 17.0.0, both targeting `x86_64-apple-macosx15.0`). Not Rosetta: `hw.optional.arm64` doesn't exist.
- `/usr/bin/python3` is 3.9.6, as on the Apple Silicon Mac. A fresh `.venv` installed `mido`, `python-rtmidi` and
  `websockets` from native x86_64 wheels with no trouble.
- **The repo's code is already architecture-clean.** On this Mac, with no changes at all:
  - the full suite passes: **381 passed, 135 skipped**;
  - `tools/bridgectl build` produced a working **thin x86_64** `LoupedeckBridge Dev.app` (the dev build has no arch
    gate, and `swiftc` with no `-target` builds for the host);
  - the Swift launcher's own checks pass natively: **50 passed** (`tests/test_launcher_policies.py`).
- So only six places pin arm64, all of them in the release and distribution layer:

  | Place | What's pinned |
  |---|---|
  | `tools/build_release_app.sh:25` | a hard `uname -m = arm64` gate; `-target arm64-apple-macos14.0` at `:80` |
  | `tools/python-standalone.lock` | the `aarch64-apple-darwin` CPython |
  | `tools/package_release.sh:12` | the `-macos-arm64.zip` asset name |
  | `tools/install.sh:73` | the same name, to download |
  | `macos/launcher/Policies.swift:269` | `ReleaseInfo.assetName`, and `parse` returns nil without that asset |
  | `.github/workflows/release.yml:39` | `runs-on: macos-15` (arm64) |

## Verified before this design (so the how doesn't rest on guesses)
- **The Intel Python exists in the build already pinned.** `cpython-3.12.16+20261026-x86_64-apple-darwin-install_only.tar.gz`
  is in the same python-build-standalone release (20261026) as the arm64 one, same CPython **3.12.16**.
  SHA-256 `a962e47df522889eaa7ff0d6a56203f1079f68aabb65ffdbe8455f362bc769f3`, from that release's `SHA256SUMS`, whose
  aarch64 line matches `tools/python-standalone.lock` exactly.
- **Both compiled wheels have cp312 Intel builds:** `python_rtmidi-1.5.8-cp312-cp312-macosx_10_9_x86_64.whl`
  (`5443634597eb340cdec0734f76267a827c2d366f00a6f9195141c78828016ac2`) and
  `websockets-15.0.1-cp312-cp312-macosx_10_13_x86_64.whl`
  (`592f1a9fe869c778694f0aa806ba0374e97648ab57936f092fd9d87f8bc03665`). The other four pins
  (`mido`, `packaging`, `pytest`, `iniconfig`, `pluggy`) are pure-Python `py3-none-any`, so both Macs share them.
- **An Intel CI runner exists:** `macos-15-intel` (macOS 15 on x86_64, available since 2025-09-19). `macos-13`, the
  old Intel image, was retired on 2025-12-04. **`macos-15-intel` retires in August 2027 and is the last x86_64
  macOS image GitHub will offer** — see *Constraints*.
- **The build job runs the bundled Python it just built** (`release.yml:82`), so an Intel app cannot be
  cross-built on an arm64 runner and tested there. It needs its own job on an Intel runner.
- **The sign job executes the app** (`"$app/Contents/MacOS/LoupedeckBridge" --check-signature "$app"`,
  `release.yml:239`) and runs on arm64. An Intel app's own signature check therefore cannot run in that job.

## What the user gets (agreed in conversation)
- **Install on an Intel Mac** with the same two lines as on Apple Silicon. `install.sh` works out which Mac it's on
  and fetches that Mac's download.
- **Updates from the menu** on an Intel Mac, with the same signature check against the same release key.
- **Every Apple Silicon Mac already out there keeps updating, untouched.** v0.5.0–v0.6.2 apps in the field look for
  `…-macos-arm64.zip` by name, for ever, so that name keeps meaning exactly what it means today.
- **macOS 14 or later on both,** the minimum it already is (the user's decision). On Intel that covers Macs from
  2018–2019 on, which includes this iMac.
- **Two downloads per release, picked by architecture** (the user's decision), not one universal app.

## Approaches (the user picked A)
- **A. Two arch-specific zips.** Keep `-macos-arm64.zip` exactly as it is; add `-macos-x86_64.zip`. Installer and
  updater pick by architecture. Each build stays a thin binary with one Python inside it, built and tested natively.
  Installed apps are unaffected.
- **B. One universal2 app.** One download for everyone, no picking. Rejected: python-build-standalone ships no
  universal2 build, so the two CPython trees would have to be `lipo`-merged dylib by dylib and extension by
  extension, roughly doubling the app to ~60 MB, with a fragile build and nothing upstream to lean on.
- **C. Cross-build Intel on the arm64 runner.** Rejected: the bundled Python couldn't be tested (the build job runs
  it), and `--check-signature` couldn't run either. It would trade a supported Intel runner for an untested build.

## Decided (how it's built)

### Naming
`x86_64` throughout, to match `uname -m` and the wheel tags (`-windows-x64` on Windows is Microsoft's own spelling
and stays). The asset is `LoupedeckBridge-v<ver>-macos-x86_64.zip`, plus its `.sha256`.
File suffixes follow milestone 7's precedent (`…-windows.lock`): **`-intel`** for the new pinned pair, since it
names the platform rather than the file's own contents.

### The build (`tools/build_release_app.sh`)
- The `uname -m = arm64` gate becomes: build natively for the host, which must be `arm64` or `x86_64`; anything else
  is refused with the same kind of message.
- The host arch picks the lock and the requirements file:
  - `arm64` → `tools/python-standalone.lock`, `tools/release-requirements.txt` (unchanged)
  - `x86_64` → `tools/python-standalone-intel.lock`, `tools/release-requirements-intel.txt` (new)
- `swiftc -target "$(uname -m)-apple-macos14.0"`. `MIN_MACOS` stays `14.0` for both.
- The Info.plist gains **`LBArch`** (`arm64` or `x86_64`), so the app, `install.sh`'s check and
  `tests/test_release_bundle.py` can all say which Mac a bundle is for without running it.
- Everything else is untouched: the same strip list, the same `unchecked-hash` precompile, the same ad hoc or
  `--sign` signing. `tools/sign_release_app.sh` is already arch-neutral.

### The new pinned pair
- `tools/python-standalone-intel.lock`: the `x86_64-apple-darwin` tarball above, with its SHA-256.
- `tools/release-requirements-intel.txt`: the same versions as `requirements.txt`, with the Intel wheel hashes above
  and the shared pure-Python ones.
- **Both Mac locks must pin the same CPython version and the same python-build-standalone build date.** This is a
  new test, not just a convention: two Macs on different Pythons would be two different products.

### Packaging (`tools/package_release.sh`)
Reads `LBArch` from the app's Info.plist (it already reads `LBVersion` the same way) and names the zip
`LoupedeckBridge-v<ver>-macos-<arch>.zip`. No new argument, so no caller changes.

### `tools/install.sh`
- Works out the Mac: `uname -m`, **but** if `sysctl -n sysctl.proc_translated` is `1` the shell is running under
  Rosetta on an Apple Silicon Mac, so it installs the **arm64** build. Without this, running the installer from a
  translated terminal would put the Intel app on an Apple Silicon Mac.
- Downloads that arch's zip and `.sha256`, with every existing check unchanged.
- **One new check, after the bundle id and version:** the app's `LBArch` is the arch being installed. A mismatch
  fails like any other check, replacing nothing.
- `LB_ARCH` overrides the detected arch, for the tests (and for deliberately fetching the other build).

### The menu-bar app (`macos/launcher/`)
- `Policies.swift`: `assetName(for:arch:)` takes the arch, so both values are testable anywhere, and
  `ReleaseInfo.parse(_:arch:)` looks for that arch's zip and `.sha256`. A release missing the *other* arch's
  download is still a valid update.
- The running app's own arch is a compile-time constant (`#if arch(arm64)` / `#elseif arch(x86_64)`, anything else a
  compile error), so it can never drift from the binary it's in and needs no plist read at runtime.
- `Updater.swift`'s one call site passes it. Nothing else in the launcher changes: the download, hash, unzip,
  signature and swap steps are all arch-blind.

### The release workflow (`.github/workflows/release.yml`)
- **`build-intel`**, on `runs-on: macos-15-intel`: the same steps as `build`, including the full suite and
  `test_release_bundle.py` on the bundled Intel Python, and the same "the tests left the build exactly as it was
  saved" check. It uploads `unsigned-app-intel` and outputs its commit and zip SHA-256.
- **`sign`** also needs `build-intel`, checks its commit matches the other two, downloads and hash-checks the second
  artifact, and signs both apps with the key in the same single approved step. It keeps running the arm64 app's
  `--check-signature` itself, and packages both Mac zips.
- **`verify-intel`**, on `runs-on: macos-15-intel`, needing `[build-intel, sign]`: unzips the signed Intel download
  and runs the Intel app's own `--check-signature` plus the `install.sh` pin checks — exactly the role
  `verify-windows` plays for Windows, and the reason it has to be a separate job.
- **`publish`** also needs `build-intel` and `verify-intel`, and its gate becomes **seven** files: both Mac zips and
  their `.sha256`, the Windows zip, its `.sha256` and its `.p7s`. As now, a missing file publishes nothing.

### CI (`.github/workflows/ci.yml`)
The Mac release-build-and-test job gains an `macos-15-intel` leg, so an Intel release app is built and its suite run
on every push — the same cover Apple Silicon has. The 3.9 suite leg gains Intel too.

### Docs
`README.md` (status, both install sections, the layout table), `CHANGELOG.md` (a `## v0.7.0` section), and
**`CLAUDE.md`'s trap** — today it says the latest release must include the Mac download; it must now say **both**
Mac downloads, or one kind of Mac stops seeing updates. `docs/FINDINGS.md` records what the live checks prove.

## Goals, non-goals, anti-goals
**Goals**
- An Intel Mac installs, runs and updates exactly as an Apple Silicon one does, from one signed release.
- Apple Silicon Macs already installed keep updating with no action from anyone.
- Both Mac builds are built *and tested* natively, on the same commit, signed in one approved step.

**Non-goals**
- A universal binary (approach B), or any change to what the bridge does.
- Supporting Intel Macs that can't run macOS 14.
- Changing the Windows release in any way beyond the publish gate's file count.

**Anti-goals**
- No second signing key, and no second approval step.
- No arch guessing at runtime from anything but the compiled-in constant.
- No cross-building, and no shipping a bundle whose Python was never run.

## Constraints
- **`macos-15-intel` retires in August 2027,** and GitHub will offer no x86_64 macOS image after that. This
  milestone is therefore time-boxed by someone else's calendar. When that date approaches the choices are a
  self-hosted Intel runner (this iMac), dropping the Intel release, or revisiting approach B. This belongs in
  `docs/FINDINGS.md` so it isn't rediscovered in 2027.
- The release key is unchanged and still lives only in the GitHub `release` environment. Both Mac apps are signed
  with it, so an Intel app will accept an Intel update from the same key.
- `codesign` is arch-independent, so one arm64 runner signs both apps — one approval, as now.
- Python 3.9 compatibility for the repo's code, 3.12 inside both release apps.
- The repo stays public: no paths, emails or client ID in anything committed.

## To verify first (may change the how, not the what)
1. `macos-15-intel` really is x86_64, and has the Xcode and Python the build needs.
2. The Intel release app builds on this iMac and its bundled Python runs the whole suite.
3. `install.sh`'s Rosetta check behaves on a real Apple Silicon Mac (`arch -x86_64 bash install.sh` should still
   install the arm64 build). The user has an Apple Silicon Mac to try this on.
4. ~~The Swift launcher needs no availability guards at `x86_64-apple-macos14.0`.~~ **Checked 2026-11-21:**
   `swiftc -O -target x86_64-apple-macos14.0 macos/launcher/*.swift` compiles with no errors and no warnings on this
   iMac, and the binary's `LC_BUILD_VERSION` reads `minos 14.0`. No guards needed.

## Live checks with the user (on this iMac, and once on the Apple Silicon Mac)
- `install.sh` installs the Intel release from GitHub onto this iMac, and the app runs: dials, buttons, presets,
  keyboard keys (after the Accessibility grant), the settings page.
- The menu's update check finds a newer version and installs it, Intel to Intel.
- On the Apple Silicon Mac: its update check and an install still work, unchanged, from the same release.
- Record all of it in `docs/FINDINGS.md`.

## Left to the builder
- Whether `build-intel` is a separate job or a matrix leg of `build` (a matrix shares the steps but makes the two
  jobs' outputs clumsier to name; either is fine if `sign` gets both artifacts and both commits).
- The exact wording of the installer's and launcher's new messages.
- Whether `tests/test_install_script.py` gets an arch parameter or a second set of cases.
