#!/bin/bash
# Build build/LoupedeckBridge.app: a small launcher that runs this repo's bridge, so macOS
# grants the keyboard (Accessibility) permission to LoupedeckBridge instead of your terminal.
# Rebuilding may make macOS ask for the permission again (the app is signed locally).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="$REPO/build/LoupedeckBridge.app"
BUNDLE_ID="io.github.megamattmiller.loupedeckbridge"

[ -x "$REPO/.venv/bin/python" ] || { echo "No .venv yet: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2; exit 1; }
xml_escape() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' <<<"$1"; }

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
swiftc -O "$REPO/macos/launcher/main.swift" -o "$APP/Contents/MacOS/LoupedeckBridge"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleName</key><string>LoupedeckBridge</string>
  <key>CFBundleDisplayName</key><string>LoupedeckBridge</string>
  <key>CFBundleExecutable</key><string>LoupedeckBridge</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSUIElement</key><true/>
  <key>LBRepoPath</key><string>$(xml_escape "$REPO")</string>
</dict>
</plist>
PLIST

codesign --force --sign - "$APP"
echo "built $APP"
