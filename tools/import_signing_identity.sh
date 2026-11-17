#!/bin/bash
# Put a signing identity (.p12) into a new keychain that codesign can use, on a GitHub runner only: the
# release workflow and CI's signing rehearsal. It changes the keychain search list, so it refuses to run
# anywhere else. Prints the identity's name and SHA-1 (public), nothing secret.
#   tools/import_signing_identity.sh P12 PASSWORD_FILE KEYCHAIN
# Afterwards: security delete-keychain KEYCHAIN
set -euo pipefail

[ $# -eq 3 ] || { echo "usage: tools/import_signing_identity.sh P12 PASSWORD_FILE KEYCHAIN" >&2; exit 2; }
if [ "${GITHUB_ACTIONS:-}" != true ]; then
  echo "import_signing_identity.sh only runs on GitHub's runners (it changes the keychain search list)." >&2
  exit 1
fi
p12="$1"; password_file="$2"; keychain="$3"

keychain_password="$(uuidgen)"
security create-keychain -p "$keychain_password" "$keychain"
security set-keychain-settings -lut 3600 "$keychain"
security unlock-keychain -p "$keychain_password" "$keychain"
security import "$p12" -k "$keychain" -f pkcs12 -P "$(cat "$password_file")" -T /usr/bin/codesign >/dev/null
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$keychain_password" "$keychain" >/dev/null
# codesign looks identities up through the user's keychain search list
# shellcheck disable=SC2046
security list-keychains -d user -s "$keychain" $(security list-keychains -d user | tr -d '"')
security find-identity -p codesigning "$keychain"
