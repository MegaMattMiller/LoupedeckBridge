#!/bin/bash
# Zip a signed release app for GitHub: LoupedeckBridge-v<version>-macos-<arch>.zip and its .sha256, in OUT_DIR.
# The arch comes from the app itself (LBArch), so each Mac's build names its own download.
#   tools/package_release.sh APP OUT_DIR
set -euo pipefail

[ $# -eq 2 ] || { echo "usage: tools/package_release.sh APP OUT_DIR" >&2; exit 2; }
APP="$1"
OUT="$2"
[ "$(basename "$APP")" = LoupedeckBridge.app ] || { echo "expected LoupedeckBridge.app, not $(basename "$APP")" >&2; exit 1; }
codesign --verify --strict "$APP" || { echo "$APP isn't validly signed" >&2; exit 1; }
VERSION="$(plutil -extract LBVersion raw "$APP/Contents/Info.plist")"
ARCH="$(plutil -extract LBArch raw "$APP/Contents/Info.plist" 2>/dev/null || true)"
case "$ARCH" in
  arm64|x86_64) ;;
  *) echo "$APP has no LBArch ('$ARCH'): rebuild it with tools/build_release_app.sh" >&2; exit 1 ;;
esac
NAME="LoupedeckBridge-v$VERSION-macos-$ARCH.zip"

mkdir -p "$OUT"
rm -f "$OUT/$NAME" "$OUT/$NAME.sha256"
ditto -c -k --keepParent "$APP" "$OUT/$NAME"              # the zip holds LoupedeckBridge.app
(cd "$OUT" && shasum -a 256 "$NAME" > "$NAME.sha256")
echo "$OUT/$NAME"
