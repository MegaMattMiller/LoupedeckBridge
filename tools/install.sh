#!/bin/bash
# Install or update LoupedeckBridge from its GitHub releases, on any Mac: no repo, no gh, no GitHub login.
#   install.sh [latest | vX.Y.Z] [--allow-older]
#
# On a Mac without this repo:
#   curl -fsSLo install.sh https://raw.githubusercontent.com/MegaMattMiller/LoupedeckBridge/main/tools/install.sh
#   less install.sh        # read it if you like
#   bash install.sh
#
# It downloads the release with curl (so macOS adds no "downloaded from the internet" flag and there's no
# "Open Anyway" step), checks its SHA-256, checks the app's signature is valid AND made with the
# LoupedeckBridge release key (the certificate's SHA-256 is pinned below), and only then replaces
# /Applications/LoupedeckBridge.app. The old app goes to the Trash. If any check fails, nothing is replaced.
set -euo pipefail

# The LoupedeckBridge release certificate's SHA-256 (public, not a secret). Set when the key was made.
PINNED_SIGNER_SHA256_DEFAULT=""
PINNED="${LB_PINNED_SIGNER_SHA256-$PINNED_SIGNER_SHA256_DEFAULT}"

SLUG="MegaMattMiller/LoupedeckBridge"
API="${LB_RELEASES_API:-https://api.github.com/repos/$SLUG/releases}"
DOWNLOADS="${LB_DOWNLOAD_BASE:-https://github.com/$SLUG/releases/download}"
INSTALL_DIR="${LB_INSTALL_DIR:-/Applications}"
BUNDLE_ID="io.github.megamattmiller.loupedeckbridge"
APP="$INSTALL_DIR/LoupedeckBridge.app"
EXE="$APP/Contents/MacOS/LoupedeckBridge"

say() { echo "install.sh: $*"; }
fail() { echo "install.sh: $*; nothing was changed." >&2; exit 1; }
usage() { echo "usage: install.sh [latest | vX.Y.Z] [--allow-older]" >&2; exit 2; }

want="latest"; allow_older=0
for a in "$@"; do
  case "$a" in
    --allow-older) allow_older=1 ;;
    latest) want="latest" ;;
    v[0-9]*.[0-9]*.[0-9]*|[0-9]*.[0-9]*.[0-9]*) want="${a#v}" ;;
    *) usage ;;
  esac
done
[ -n "$PINNED" ] || fail "this installer has no pinned release key yet (PINNED_SIGNER_SHA256_DEFAULT)"

# version_gt A B: true if A > B (three numeric parts).
version_gt() {
  local IFS=.
  local a=($1) b=($2) i
  for i in 0 1 2; do
    [ "${a[i]:-0}" -gt "${b[i]:-0}" ] && return 0
    [ "${a[i]:-0}" -lt "${b[i]:-0}" ] && return 1
  done
  return 1
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# ---- which version --------------------------------------------------------------
if [ "$want" = "latest" ]; then
  curl -fsSL "$API/latest" -o "$work/latest.json" || fail "couldn't ask GitHub for the latest release"
  tag="$(plutil -extract tag_name raw "$work/latest.json" 2>/dev/null)" || fail "GitHub's answer had no release tag"
  want="${tag#v}"
fi
[[ "$want" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "'$want' isn't a release version"
name="LoupedeckBridge-v$want-macos-arm64.zip"

# ---- download and check ----------------------------------------------------------
say "downloading v$want"
curl -fL --silent --show-error -o "$work/$name" "$DOWNLOADS/v$want/$name" || fail "the download failed"
curl -fL --silent --show-error -o "$work/$name.sha256" "$DOWNLOADS/v$want/$name.sha256" || fail "the checksum download failed"
expected="$(awk '{print $1; exit}' "$work/$name.sha256")"
actual="$(shasum -a 256 "$work/$name" | awk '{print $1}')"
[ -n "$expected" ] && [ "$expected" = "$actual" ] || fail "the download's SHA-256 doesn't match"

mkdir "$work/unzipped"
ditto -x -k "$work/$name" "$work/unzipped" 2>/dev/null || fail "the download isn't a valid zip"
apps=("$work/unzipped"/*.app)
[ "${#apps[@]}" -eq 1 ] && [ -d "${apps[0]}" ] || fail "the download should hold exactly one app"
new="${apps[0]}"
new_id="$(plutil -extract CFBundleIdentifier raw "$new/Contents/Info.plist" 2>/dev/null || true)"
new_version="$(plutil -extract LBVersion raw "$new/Contents/Info.plist" 2>/dev/null || true)"
[ "$new_id" = "$BUNDLE_ID" ] || fail "it isn't the LoupedeckBridge release ($new_id)"
[ "$new_version" = "$want" ] || fail "it says it's v$new_version, not v$want"

codesign --verify --strict "$new" 2>/dev/null || fail "its signature isn't valid"
codesign -d --extract-certificates="$work/cert" "$new" 2>/dev/null || fail "couldn't read its signing certificate"
signer="$(shasum -a 256 "$work/cert0" 2>/dev/null | awk '{print $1}')" || true   # none: signed ad hoc
[ "$signer" = "$PINNED" ] || fail "it isn't signed with the LoupedeckBridge release key"

if [ -d "$APP" ]; then
  old_version="$(plutil -extract LBVersion raw "$APP/Contents/Info.plist" 2>/dev/null || echo 0.0.0)"
  if ! version_gt "$new_version" "$old_version" && [ "$allow_older" = 0 ]; then
    fail "v$new_version isn't newer than the installed v$old_version (use --allow-older to go back)"
  fi
fi

# ---- replace ----------------------------------------------------------------------
if pgrep -f "$EXE" >/dev/null; then
  say "stopping the running LoupedeckBridge"
  pkill -TERM -f "$EXE" || true
  for _ in $(seq 1 80); do pgrep -f "$EXE" >/dev/null || break; sleep 0.1; done
fi
trashed=""
if [ -d "$APP" ]; then
  mkdir -p "$HOME/.Trash"
  trashed="$HOME/.Trash/LoupedeckBridge v$old_version $(date +%Y%m%d-%H%M%S).app"
  mv "$APP" "$trashed" || fail "couldn't move the old app to the Trash"
fi
mkdir -p "$INSTALL_DIR"
if ! ditto "$new" "$APP"; then
  rm -rf "$APP"
  [ -n "$trashed" ] && mv "$trashed" "$APP"
  fail "couldn't put the new app in place (the old one is back)"
fi
open "$APP"
say "installed LoupedeckBridge v$new_version${trashed:+ (the previous version is in the Trash)}"
