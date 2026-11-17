# Milestone 6: Mac releases with in-app updates (design)

Date: 2026-11-17 · Status: approved by the user · Part of: [the bridge design](2026-11-16-loupedeck-bridge-design.md)

**Roadmap change (the user's decision):** releases come before Windows. This is milestone 6, and Windows
becomes milestone 7. Mac releases are **for the user only**; Windows releases (milestone 7) will be for
the user and some friends, so their install needs are settled then.

## Intent
Install LoupedeckBridge as a versioned app that doesn't depend on this repo or Apple's developer tools,
update it with one click from its menu, and never lose the keyboard and notification permissions on an
update. Today the app runs the repo's code with the repo's Python (from Apple's developer tools), every
rebuild loses permissions (ad-hoc signature), and a change in the repo changes the copy used every day.

## What the user gets (agreed in conversation)
- **Versioned releases on GitHub** (`v0.5.0`, …) with release notes, and a `CHANGELOG.md`. The version
  comes from one place and shows in the app's menu.
- **A self-contained app**, `/Applications/LoupedeckBridge.app`, carrying its own Python, its three
  libraries and the bridge code. It needs neither this repo nor Apple's developer tools.
- **The user's setup carries over:** mapping, presets cache, client ID and logs already live in the user's
  folders (`~/Library/Application Support/loupedeck-lr-bridge`, `~/Library/Logs/loupedeck-lr-bridge`).
- **Updates keep permissions:** every release is signed with one fixed identity, so Accessibility and
  notifications carry over. Releases go on **this Mac and the user's other Macs**
  (the user's answer); all are Apple Silicon unless the user says otherwise.
- **Updates from the menu (the user's request):**
  - the app checks GitHub **automatically, at most once a day** (the user's choice), plus a
    "Check for updates now" item and an off switch
  - a new version shows as "Update available: v0.6.0 – Install…", with one alert per new version
  - it never installs without a click
  - Install: download, **verify the signature is the user's own**, stop the bridge cleanly, move the
    old app to the Trash, put the new one in place and start it; if any step fails, the current version
    keeps running and an alert says why
- **`tools/install.sh`** installs or updates from a terminal on any of the user's Macs, with or without
  this repo, and can go back to an older version.
- **Development stays:** `tools/bridgectl build` / `start` from the repo still work for trying changes.

## Approaches (the user picked A)
- **A. Bundle a portable Python in the app (chosen).**
  - How: a relocatable CPython build from the python-build-standalone project (version and checksum pinned)
    goes in the app, with the three libraries and the bridge's code. The Swift app starts it exactly as it
    starts the repo's Python today.
  - For: runs on a Mac without developer tools; easy to inspect and debug, since it's ordinary Python.
  - Against: about 40–50 MB, and building a release downloads that Python once.
- B. Freeze the bridge into one executable (PyInstaller / py2app). Rejected:
  - a new build tool with quirks around the ctypes calls into CoreGraphics and Accessibility
  - harder to debug, and it saves little size
- C. Use the Mac's own Python and install the libraries on first launch. Rejected: it depends on Apple's
  developer tools and their Python version, which is the dependence releases are meant to remove.

## Decided (how it's built)
- **Python:** python-build-standalone **CPython 3.12** for `aarch64-apple-darwin` (the user's Macs are Apple
  Silicon, an M4 Pro). The exact build and its SHA-256 are pinned in the build script. The bridge already
  supports 3.9 (the repo's Python) and 3.12+ (the design's Windows target). The release script runs the
  test suite with the bundled Python before publishing.
- **App layout:**
  - `Contents/Resources/python/`: the standalone Python, with `mido`, `python-rtmidi` and `websockets`
    installed from `requirements.txt` (pinned versions); tests, caches and headers stripped
  - `Contents/Resources/app/`: `bridge/`, `config/` and `docs/lr_parameters_10.0.json`, in the same layout the
    code expects today
  - Info.plist: `LBRuntime = bundled`, `LBVersion`, and the signing certificate's SHA-256 (`LBSignerSHA256`)
    that updates must match
  - The Swift launcher picks Python and working directory from `LBRuntime`: `bundled` uses the paths above,
    `repo` (dev builds) uses `LBRepoPath` as today.
- **Dev builds can't be mistaken for the release:** `tools/bridgectl build` makes **"LoupedeckBridge Dev"**
  with bundle id `io.github.megamattmiller.loupedeckbridge.dev`. The release keeps
  `io.github.megamattmiller.loupedeckbridge`. Login Items, notifications and Accessibility then never mix
  them up. Only one bridge runs at a time either way (the existing lock). *(My call.)*
- **One version, one place:** `bridge/__init__.py` `__version__ = "0.5.0"` (the first release, after five
  milestones; my call). The menu shows it, the settings page footer shows it, and the build script writes
  it into Info.plist.
  - The version **sent to Lightroom when registering stays "0.1"**, so Lightroom has no reason to ask
    "Allow" again (*my call; verified first*, below).
- **Releases are built and signed on GitHub (the user's decision, 2026-11-17)**, so no Mac has to build
  them, and milestone 7's Windows releases can use the same workflow. The user's GitHub account uses a
  passkey, and they accept that update safety rests on it.
  - **The signing identity:** a self-signed code-signing certificate, "LoupedeckBridge Release".
    `tools/make_signing_identity.sh`, **run by the user**:
    - creates it with `openssl`; no keychain change is needed
    - uploads the `.p12` and a random password as secrets of a GitHub **`release` environment**, with
      `gh secret set`
    - prints the certificate's SHA-256 (pinned in `tools/install.sh` and the app)
    - deletes the local copy unless the user asks to keep an offline backup
    The assistant never handles the key or its password.
  - **The workflow** (`.github/workflows/release.yml`):
    - triggered by pushing a `v*` tag (or "Run workflow" with a version)
    - runs on a GitHub-hosted Apple Silicon runner
    - checks that `__version__` and a `CHANGELOG.md` section match, builds the bundled app, and runs the
      test suite with its Python
    - imports the `.p12` into a temporary keychain and signs every file of code, then the app; deletes the
      keychain
    - zips with `ditto`, writes the SHA-256, and publishes the GitHub release with the changelog section
      as notes
  - **Hardening:**
    - the signing job uses the `release` environment with the user as **required reviewer**, so the key
      is usable only after they approve that run on GitHub
    - minimal `permissions` (only `contents: write` for publishing)
    - only GitHub's own actions, pinned to commit SHAs; the `gh` CLI does the publishing
    - no `pull_request` or `pull_request_target` triggers on the release workflow
  - **A separate test workflow** (`ci.yml`) runs the suite on every push and pull request (macOS, Python
    3.9 and the bundled 3.12). It has no secrets.
  - **Locally,** `tools/release.sh 0.5.0` only checks the version and changelog and creates the tag. It
    pushes it **after asking**. Releasing from another machine works too, by pushing a tag or using
    "Run workflow".
  - No hardened runtime or notarization: they aren't needed for the user's own Macs, and Python would
    need extra entitlements.
- **The update check (Swift, in the app):**
  - `GET https://api.github.com/repos/MegaMattMiller/LoupedeckBridge/releases/latest` (public, no account)
  - when: 30 s after launch, then every 24 h while running, skipped if a check happened in the last 24 h
    (time saved in the app's defaults)
  - a newer version (by numeric comparison) with a `…-macos-arm64.zip` asset → the menu item, and one alert
    per version
  - failures are quiet (logged)
  - **dev builds never check or update themselves**
- **Installing an update:**
  1. Download the asset to a temporary folder (URLSession; no quarantine flag).
  2. Unzip with `ditto`.
  3. Check that it's exactly one `LoupedeckBridge.app` with the release bundle id and a version newer than
     the running one, and that `codesign --verify --strict` passes with the requirement
     `identifier "io.github.megamattmiller.loupedeckbridge" and certificate leaf = H"<LBSignerSHA256>"`.
  4. Stop the bridge (the existing Quit path, keys released).
  5. Move the running app to the Trash and the new one to the same path.
  6. Start the new app, then exit.
  If any step fails, nothing is replaced and an alert says which step. *(The signature check is what makes
  the updater safe: only builds signed with the user's own key can be installed, even if a GitHub release
  were tampered with.)*
  - **An update is done when the new app has started** (the old one then exits). If the new version's
    bridge keeps failing (the restart budget is used up), its menu offers **"Go back to the previous
    version"**, which restores the copy in the Trash the same way. *(Builder check; my call: a safety net
    without a hand-off protocol between two running copies of the same app.)*
- **`tools/bridgectl` with two apps** (builder check; my call):
  - `start`, `stop`, `restart`, `status` and `login` act on the **installed release**
    (`/Applications/LoupedeckBridge.app`)
  - `--dev` acts on the dev build in `build/` instead
  - `start --dev` stops the release first (only one bridge can run) and `stop --dev` starts it again if it
    was running
  - the process match uses each app's full path, so the two are never confused
- **Proving the menu update:** milestone 6 publishes **v0.5.0, then v0.5.1** (a small real release, e.g. a
  few deferred minors), and v0.5.1 is installed from v0.5.0's menu for real. Each publish waits for the
  user's go-ahead. No test-only update feed ships in the app. *(Builder check; my call.)*
- **Installing on any of the user's Macs, including ones without this repo (the user's answer):**
  `tools/install.sh [vX.Y.Z]`, a standalone script that uses only built-in tools (`curl`, `ditto`,
  `codesign`, `shasum`) and no `gh` or GitHub login. On a Mac without the repo it's fetched from the repo's
  `main` branch on GitHub (raw URL), saved, read if wanted, then run. It:
  - downloads the release zip and its `.sha256` with `curl` (so no quarantine flag, and no "Open Anyway")
  - checks the SHA-256, and that the app's signature matches the **release certificate's SHA-256 pinned in
    the script** (committed once the certificate exists; a public fingerprint, not a secret)
  - stops a running LoupedeckBridge, moves the old app to the Trash, installs to `/Applications` and starts it
  Older versions only with `--allow-older`. `tools/bridgectl install` runs the same script.
  On a new Mac the user grants Accessibility and notifications once; updates keep them.
- **Network:**
  - the **Swift app** contacts `api.github.com` and GitHub's release-asset hosts (redirects to
    `objects.githubusercontent.com`), only for update checks and downloads
  - the **Python bridge stays 127.0.0.1-only**
  - the README says so plainly, including how to turn checks off

## Goals, non-goals, anti-goals
- **Goals:** a self-contained, versioned install; one-click updates that keep permissions; your setup kept;
  dev builds that still work and stay separate.
- **Non-goals:**
  - notarization and the Apple Developer Program (the user only)
  - Intel or universal builds
  - delta updates
  - Windows (milestone 7)
  - updating automatically without a click
- **Anti-goals:**
  - installing anything not signed by the user's own key
  - an update that leaves no working app
  - losing the mapping, presets or permissions on update
  - the dev build and the release fighting over Login Items, notifications or Accessibility
  - the Python bridge talking to the internet
  - the signing key usable by anything but a release run the user approved (it lives only in the GitHub
    `release` environment's secrets)

## Constraints
- macOS 27 on Apple Silicon.
- System frameworks only in Swift (Foundation's URLSession, AppKit, Security for reading the certificate if
  needed), with `codesign`/`ditto` run as tools.
- Python stays 3.9-compatible in the repo; the release runs 3.12.
- No new runtime dependencies. The bundled Python is a build-time download, pinned by checksum.
- Publishing needs the user's go-ahead each time: the assistant asks before pushing a tag, and GitHub asks
  the user to approve each release run.

## To verify first (may change the how, not the what)
1. The bundled Python 3.12 runs the whole test suite. `python-rtmidi 1.5.8` has a macOS arm64 wheel for
   3.12, and opening CoreMIDI works from the bundled interpreter.
2. Accessibility and notification permissions survive replacing the app with a newer build signed by the
   same self-signed identity, at the same path.
3. Lightroom accepts the saved client ID with the fixed registration version ("0.1") from the new app,
   without a new Allow dialog.
4. Moving the running app to the Trash and starting the new copy works from inside the running app.
5. A `.p12` made with `openssl` imports into a temporary keychain on GitHub's Apple Silicon runner and signs
   the app, and `codesign --verify` with the certificate-leaf requirement passes on the user's Mac.

## Left to the builder
- The release notes format beyond "the changelog section".
- The exact menu wording for updates, and where "Check for updates automatically" sits.
- The `tools/` script structure, and the precise strip list for the bundled Python.
- How the first-install fingerprint is shown and confirmed.
