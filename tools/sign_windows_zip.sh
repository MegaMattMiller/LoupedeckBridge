#!/bin/bash
# Sign a Windows release zip (milestone 7): a detached CMS / PKCS#7 signature over the zip's exact bytes, with the
# release key's .p12, written next to it as ZIP.p7s. The tray app and tools/install.ps1 check it with .NET's SignedCms,
# and compare the signer certificate's SHA-256 with the pinned one (the same key as the Mac's: tools/install.sh).
#   tools/sign_windows_zip.sh ZIP P12 PASSWORD_FILE
# The release workflow runs it in the one step where the key exists (macOS's LibreSSL); CI and the tests run it with
# throwaway identities. The key is unpacked into a private temporary folder only for the signing, and removed at once.
set -euo pipefail

[ $# -eq 3 ] || { echo "usage: tools/sign_windows_zip.sh ZIP P12 PASSWORD_FILE" >&2; exit 2; }
ZIP="$1"
P12="$2"
PASSWORD_FILE="$3"
OPENSSL="${OPENSSL:-openssl}"
[ -f "$ZIP" ] || { echo "sign_windows_zip.sh: no such file: $ZIP" >&2; exit 1; }

umask 077
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
"$OPENSSL" pkcs12 -in "$P12" -passin "file:$PASSWORD_FILE" -nodes -out "$work/identity.pem" 2>/dev/null \
  || { echo "sign_windows_zip.sh: couldn't read $P12" >&2; exit 1; }
"$OPENSSL" smime -sign -binary -noattr -md sha256 -outform DER -signer "$work/identity.pem" \
  -in "$ZIP" -out "$work/signature.p7s"
rm -f "$work/identity.pem"                       # the bare key, as soon as it's no longer needed
# the signature must verify over these bytes before it's put next to them
"$OPENSSL" smime -verify -binary -noverify -inform DER -in "$work/signature.p7s" -content "$ZIP" \
  -out "$work/verified" 2>/dev/null || { echo "sign_windows_zip.sh: the new signature doesn't verify" >&2; exit 1; }
mv "$work/signature.p7s" "$ZIP.p7s"
echo "$ZIP.p7s"
