#!/bin/bash
# Sign the release app: every Mach-O file inside it (the bundled Python, its .so and .dylib files), then the
# app itself.
#   tools/sign_release_app.sh APP [IDENTITY]      no IDENTITY: ad hoc (local builds)
# The release workflow signs the tested build with "LoupedeckBridge Release" from its temporary keychain.
# No hardened runtime, and no timestamp (a self-signed identity can't get Apple's).
set -euo pipefail

[ $# -ge 1 ] && [ $# -le 2 ] || { echo "usage: tools/sign_release_app.sh APP [IDENTITY]" >&2; exit 2; }
APP="$1"
IDENTITY="${2:--}"
[ -f "$APP/Contents/Info.plist" ] || { echo "not an app: $APP" >&2; exit 1; }

count=0
while IFS= read -r -d '' file; do
  if file -b "$file" | grep -q '^Mach-O'; then
    codesign --force --sign "$IDENTITY" --timestamp=none "$file"
    count=$((count + 1))
  fi
done < <(find "$APP/Contents/Resources" -type f \( -name '*.so' -o -name '*.dylib' -o -perm -u+x \) -print0)
codesign --force --sign "$IDENTITY" --timestamp=none "$APP"
codesign --verify --strict "$APP"
echo "signed $APP and $count files of code inside it ($([ "$IDENTITY" = - ] && echo "ad hoc" || echo "$IDENTITY"))"
