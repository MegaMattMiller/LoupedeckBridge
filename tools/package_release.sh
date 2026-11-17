#!/bin/bash
# Zip a signed release app for GitHub: LoupedeckBridge-v<version>-macos-arm64.zip and its .sha256, in OUT_DIR.
#   tools/package_release.sh APP OUT_DIR
set -euo pipefail

[ $# -eq 2 ] || { echo "usage: tools/package_release.sh APP OUT_DIR" >&2; exit 2; }
APP="$1"
OUT="$2"
[ "$(basename "$APP")" = LoupedeckBridge.app ] || { echo "expected LoupedeckBridge.app, not $(basename "$APP")" >&2; exit 1; }
codesign --verify --strict "$APP" || { echo "$APP isn't validly signed" >&2; exit 1; }
VERSION="$(plutil -extract LBVersion raw "$APP/Contents/Info.plist")"
NAME="LoupedeckBridge-v$VERSION-macos-arm64.zip"

mkdir -p "$OUT"
rm -f "$OUT/$NAME" "$OUT/$NAME.sha256"
ditto -c -k --keepParent "$APP" "$OUT/$NAME"              # the zip holds LoupedeckBridge.app
(cd "$OUT" && shasum -a 256 "$NAME" > "$NAME.sha256")
echo "$OUT/$NAME"
