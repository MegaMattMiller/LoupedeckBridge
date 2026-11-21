#!/bin/bash
# Install or update LoupedeckBridge from its GitHub releases, on any Mac: no repo, no gh, no GitHub login.
#   install.sh [latest | vX.Y.Z] [--allow-older]
#
# On a Mac without this repo:
#   curl -fsSLo install.sh https://raw.githubusercontent.com/MegaMattMiller/LoupedeckBridge/main/tools/install.sh
#   less install.sh        # read it if you like
#   bash install.sh
#
# It works out which Mac it's on (Apple Silicon or Intel) and fetches that Mac's download.
# It downloads the release with curl (so macOS adds no "downloaded from the internet" flag and there's no
# "Open Anyway" step), checks its SHA-256, checks the app's signature is valid AND made with the
# LoupedeckBridge release key (the certificate's SHA-256 is pinned below), and only then replaces
# /Applications/LoupedeckBridge.app. The old app goes to the Trash. If any check fails, nothing is replaced.
# It prints the release key's fingerprint first: on a new Mac, compare it with the one you noted (README.md).
set -euo pipefail

# The LoupedeckBridge release certificate's SHA-256 (public, not a secret), from tools/make_signing_identity.sh
# on 2026-11-17. The release build copies it into each app, which checks every update against it.
PINNED_SIGNER_SHA256_DEFAULT="4927ccbb8cc8c7e3c32afa79d58f11f2129b84b3c7638cb530cb2ced0faa2cf4"
PINNED="${LB_PINNED_SIGNER_SHA256-$PINNED_SIGNER_SHA256_DEFAULT}"

SLUG="MegaMattMiller/LoupedeckBridge"
API="${LB_RELEASES_API:-https://api.github.com/repos/$SLUG/releases}"
DOWNLOADS="${LB_DOWNLOAD_BASE:-https://github.com/$SLUG/releases/download}"
INSTALL_DIR="${LB_INSTALL_DIR:-/Applications}"
BUNDLE_ID="io.github.megamattmiller.loupedeckbridge"
APP="$INSTALL_DIR/LoupedeckBridge.app"
EXE="$APP/Contents/MacOS/LoupedeckBridge"
MAX_BYTES=209715200        # 200 MB: a release is about 30 MB, so anything bigger isn't one

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

# ---- which Mac this is -----------------------------------------------------------
# Each release carries a download per architecture. LB_ARCH forces one (the tests, or fetching the other
# deliberately).
arch="${LB_ARCH-}"
if [ -z "$arch" ]; then
  arch="$(uname -m)"
  # A Rosetta shell on an Apple Silicon Mac reports x86_64, but that Mac wants the arm64 build.
  [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" = 1 ] && arch=arm64
fi
case "$arch" in
  arm64|x86_64) ;;
  *) fail "this Mac's architecture ($arch) has no LoupedeckBridge download" ;;
esac
# Shown first, so a first install on a new Mac can be compared with the fingerprint noted elsewhere.
if [ "$PINNED" = "$PINNED_SIGNER_SHA256_DEFAULT" ]; then
  say "release key (certificate SHA-256): $PINNED"
else
  say "release key (certificate SHA-256): $PINNED - not the built-in key (LB_PINNED_SIGNER_SHA256)"
fi

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
name="LoupedeckBridge-v$want-macos-$arch.zip"

# ---- download and check ----------------------------------------------------------
say "downloading v$want for $arch"
curl -fL --silent --show-error --max-filesize "$MAX_BYTES" -o "$work/$name" "$DOWNLOADS/v$want/$name" \
  || fail "the download failed"
curl -fL --silent --show-error --max-filesize 4096 -o "$work/$name.sha256" "$DOWNLOADS/v$want/$name.sha256" \
  || fail "the checksum download failed"
expected="$(awk '{print $1; exit}' "$work/$name.sha256")"
actual="$(shasum -a 256 "$work/$name" | awk '{print $1}')"
[ -n "$expected" ] && [ "$expected" = "$actual" ] || fail "the download's SHA-256 doesn't match"

mkdir "$work/unzipped"
if ! unzip_errors="$(ditto -x -k "$work/$name" "$work/unzipped" 2>&1)"; then
  fail "couldn't unzip it (${unzip_errors//$'\n'/ })"          # e.g. a full disk, or not a zip at all
fi
apps=("$work/unzipped"/*.app)
[ "${#apps[@]}" -eq 1 ] && [ -d "${apps[0]}" ] || fail "the download should hold exactly one app"
new="${apps[0]}"
new_id="$(plutil -extract CFBundleIdentifier raw "$new/Contents/Info.plist" 2>/dev/null || true)"
new_version="$(plutil -extract LBVersion raw "$new/Contents/Info.plist" 2>/dev/null || true)"
[ "$new_id" = "$BUNDLE_ID" ] || fail "it isn't the LoupedeckBridge release ($new_id)"
[ "$new_version" = "$want" ] || fail "it says it's v$new_version, not v$want"
new_arch="$(plutil -extract LBArch raw "$new/Contents/Info.plist" 2>/dev/null || true)"
[ "$new_arch" = "$arch" ] || fail "it's the ${new_arch:-unknown} build, not $arch"

codesign --verify --strict -R="identifier \"$BUNDLE_ID\"" "$new" 2>/dev/null \
  || fail "its signature isn't valid for $BUNDLE_ID"
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
was_running=0
# reopen the old app if this script stopped it (after a failure that left it in place)
restart_old() { if [ "$was_running" = 1 ] && [ -d "$APP" ]; then open "$APP" || true; fi; }
if pgrep -f "$EXE" >/dev/null; then
  was_running=1
  say "stopping the running LoupedeckBridge"
  pkill -TERM -f "$EXE" || true
  for _ in $(seq 1 80); do pgrep -f "$EXE" >/dev/null || break; sleep 0.1; done
  if pgrep -f "$EXE" >/dev/null; then
    fail "LoupedeckBridge is still running after 8 s; quit it from its menu, then run this again"
  fi
fi
trashed=""
if [ -d "$APP" ]; then
  mkdir -p "$HOME/.Trash"
  trashed="$HOME/.Trash/LoupedeckBridge v$old_version $(date +%Y%m%d-%H%M%S).app"
  if ! mv "$APP" "$trashed"; then
    restart_old
    fail "couldn't move the old app to the Trash"
  fi
fi
mkdir -p "$INSTALL_DIR"
if ! copy_errors="$(ditto "$new" "$APP" 2>&1)"; then
  rm -rf "$APP"
  [ -n "$trashed" ] && mv "$trashed" "$APP"
  restart_old
  fail "couldn't put the new app in place (${copy_errors//$'\n'/ }); the old one is back"
fi
open "$APP"
say "installed LoupedeckBridge v$new_version${trashed:+ (the previous version is in the Trash)}"
