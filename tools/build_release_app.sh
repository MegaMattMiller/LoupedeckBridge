#!/bin/bash
# Build the self-contained release app (milestone 6): LoupedeckBridge.app with its own Python 3.12 and this
# repo's code, for Apple Silicon Macs on macOS 14 or later.
#   tools/build_release_app.sh OUT_DIR [--sign IDENTITY]
# It's signed ad hoc unless --sign names an identity (the release workflow signs the tested build itself,
# with tools/sign_release_app.sh). Package it with tools/package_release.sh.
#
# Downloads: the Python in tools/python-standalone.lock (once, into .cache/; its SHA-256 is checked on every
# build) and the wheels in tools/release-requirements.txt (pip checks their hashes).
# The app pins the release key that tools/install.sh pins (LB_SIGNER_SHA256 overrides it: CI's rehearsal).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
usage() { echo "usage: tools/build_release_app.sh OUT_DIR [--sign IDENTITY]" >&2; exit 2; }
[ $# -ge 1 ] || usage
OUT="$1"
shift
identity=""
while [ $# -gt 0 ]; do
  case "$1" in
    --sign) [ $# -ge 2 ] || usage; identity="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[ "$(uname -m)" = arm64 ] || { echo "The release app is built on, and for, Apple Silicon." >&2; exit 1; }

NAME="LoupedeckBridge"
BUNDLE_ID="io.github.megamattmiller.loupedeckbridge"
MIN_MACOS="14.0"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
APP="$OUT/$NAME.app"
RES="$APP/Contents/Resources"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$REPO/bridge/__init__.py")"
SIGNER="${LB_SIGNER_SHA256-$(sed -n 's/^PINNED_SIGNER_SHA256_DEFAULT="\(.*\)"$/\1/p' "$REPO/tools/install.sh")}"
url="$(sed -n 's/^url=//p' "$REPO/tools/python-standalone.lock")"
sha="$(sed -n 's/^sha256=//p' "$REPO/tools/python-standalone.lock")"
[ -n "$VERSION" ] && [ -n "$url" ] && [ -n "$sha" ] || { echo "couldn't read the version or the Python lock" >&2; exit 1; }

# ---- the Python: downloaded once, checked every time ----------------------------
tarball="$REPO/.cache/$(basename "$url" | sed 's/%2B/+/g')"
if [ ! -f "$tarball" ]; then
  mkdir -p "$REPO/.cache"
  echo "downloading $(basename "$tarball")"
  curl -fL --retry 3 --silent --show-error -o "$tarball.part" "$url"
  mv "$tarball.part" "$tarball"
fi
if [ "$(shasum -a 256 "$tarball" | awk '{print $1}')" != "$sha" ]; then
  rm -f "$tarball"
  echo "The Python download didn't match tools/python-standalone.lock's SHA-256, so it was deleted." >&2
  exit 1
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$RES/app/docs"
tar -xzf "$tarball" -C "$RES"                                  # → Resources/python
PY="$RES/python/bin/python3"
STDLIB="$RES/python/lib/python3.12"

# ---- its packages: exactly the locked wheels ------------------------------------
PYTHONDONTWRITEBYTECODE=1 "$PY" -E -m pip install --quiet --no-cache-dir --disable-pip-version-check \
  --only-binary=:all: --no-deps --require-hashes -r "$REPO/tools/release-requirements.txt"

# ---- the code ---------------------------------------------------------------------
cp -R "$REPO/bridge" "$REPO/config" "$RES/app/"
cp "$REPO/docs/lr_parameters_10.0.json" "$RES/app/docs/"

# ---- strip what the app never uses, then precompile everything --------------------
# (pip stays: CI runs the test suite with this Python, through a venv that shares its packages)
rm -rf "$STDLIB"/{test,idlelib,tkinter,turtledemo,ensurepip} "$STDLIB"/lib-dynload/_tkinter*.so \
       "$RES/python/include" "$RES/python/share" "$RES/python/lib"/{tcl,tk,itcl,thread}* \
       "$RES/python/lib"/lib{tcl,tk}*
find "$RES" \( -name __pycache__ -o -name test -o -name tests \) -type d -prune -exec rm -rf {} +
find "$RES" \( -name .DS_Store -o -name '*.pyc' -o -name '*.a' \) -type f -delete
# unchecked-hash: Python uses the .pyc without comparing it to the source, and with -B (as the app runs it)
# never writes one, so the signed bundle never changes
"$PY" -E -m compileall -q -j 0 --invalidation-mode unchecked-hash "$STDLIB" "$RES/app" >/dev/null

# ---- the launcher and Info.plist --------------------------------------------------
swiftc -O -target "arm64-apple-macos$MIN_MACOS" "$REPO"/macos/launcher/*.swift -o "$APP/Contents/MacOS/$NAME"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME</string>
  <key>CFBundleExecutable</key><string>$NAME</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>$MIN_MACOS</string>
  <key>LSUIElement</key><true/>
  <key>LBRuntime</key><string>bundled</string>
  <key>LBVersion</key><string>$VERSION</string>
  <key>LBIsDev</key><false/>
  <key>LBSignerSHA256</key><string>$SIGNER</string>
</dict>
</plist>
PLIST

"$REPO/tools/sign_release_app.sh" "$APP" ${identity:+"$identity"}
echo "built $APP (v$VERSION, $(du -sh "$APP" | awk '{print $1}'))"
