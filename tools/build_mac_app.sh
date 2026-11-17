#!/bin/bash
# Build the macOS menu-bar app.
#   tools/build_mac_app.sh [--dev] [OUT_DIR]     "LoupedeckBridge Dev.app" (default, into build/): runs this repo's
#                                                code with its .venv; its own bundle id, so it never mixes with the
#                                                installed release in Login Items, notifications or Accessibility
#   tools/build_mac_app.sh --release OUT_DIR …   the self-contained release app (tools/build_release_app.sh)
# Rebuilding the dev app may make macOS ask for its permissions again (it's signed ad hoc).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
if [ "${1:-}" = "--release" ]; then
  shift
  exec "$REPO/tools/build_release_app.sh" "$@"
fi
[ "${1:-}" = "--dev" ] && shift
OUT="${1:-$REPO/build}"
NAME="LoupedeckBridge Dev"
APP="$OUT/$NAME.app"
BUNDLE_ID="io.github.megamattmiller.loupedeckbridge.dev"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$REPO/bridge/__init__.py")"

[ -x "$REPO/.venv/bin/python" ] || { echo "No .venv yet: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2; exit 1; }
[ -n "$VERSION" ] || { echo "couldn't read __version__ from bridge/__init__.py" >&2; exit 1; }
xml_escape() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' <<<"$1"; }

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
swiftc -O "$REPO"/macos/launcher/*.swift -o "$APP/Contents/MacOS/LoupedeckBridge"   # not tests/

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME</string>
  <key>CFBundleExecutable</key><string>LoupedeckBridge</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSUIElement</key><true/>
  <key>LBRuntime</key><string>repo</string>
  <key>LBRepoPath</key><string>$(xml_escape "$REPO")</string>
  <key>LBVersion</key><string>$VERSION</string>
  <key>LBIsDev</key><true/>
  <key>LBSignerSHA256</key><string></string>
</dict>
</plist>
PLIST

codesign --force --sign - "$APP"
echo "built $APP"
