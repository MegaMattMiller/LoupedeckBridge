#!/bin/bash
# Make the LoupedeckBridge release signing identity (milestone 6). You run this yourself, once.
#
#   tools/make_signing_identity.sh [--keep BACKUP_DIR] [--replace]
#       Makes a self-signed code-signing key and certificate ("LoupedeckBridge Release", 10 years), stores
#       them as secrets of this repo's GitHub `release` environment (MAC_SIGNING_P12 and
#       MAC_SIGNING_P12_PASSWORD), prints the certificate's SHA-256, and deletes the local copy, unless
#       --keep copies it to BACKUP_DIR (keep that offline: with both files anyone can sign as you).
#       Needs `gh` logged in, and the `release` environment with you as a required reviewer.
#   tools/make_signing_identity.sh --out DIR
#       A throwaway identity in DIR, uploaded nowhere (CI's signing rehearsal and the tests).
#
# Nothing goes into your keychain. The key only exists inside the .p12, and the .p12 only in GitHub's
# secrets (and your backup, if you asked for one). The SHA-256 it prints is public: it gets pinned in
# tools/install.sh, and every release app carries it to check updates against.
set -euo pipefail

OPENSSL=/usr/bin/openssl          # macOS's LibreSSL: its .p12 encoding is one `security import` reads
NAME="LoupedeckBridge Release"
ENVIRONMENT=release
SECRET_P12=MAC_SIGNING_P12
SECRET_PASSWORD=MAC_SIGNING_P12_PASSWORD
REPO="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  echo "usage: tools/make_signing_identity.sh [--keep BACKUP_DIR] [--replace]" >&2
  echo "       tools/make_signing_identity.sh --out DIR      (a throwaway identity; uploads nothing)" >&2
  exit 2
}

out=""; keep=""; replace=0
while [ $# -gt 0 ]; do
  case "$1" in
    --out) [ $# -ge 2 ] || usage; out="$2"; shift 2 ;;
    --keep) [ $# -ge 2 ] || usage; keep="$2"; shift 2 ;;
    --replace) replace=1; shift ;;
    *) usage ;;
  esac
done
if [ -n "$out" ] && { [ -n "$keep" ] || [ "$replace" = 1 ]; }; then usage; fi
umask 077

# make_identity DIR → DIR/LoupedeckBridge-Release.p12, DIR/p12-password, DIR/signer.sha256
make_identity() {
  local dir="$1" work
  mkdir -p "$dir"
  chmod 700 "$dir"
  work="$(mktemp -d)"
  cat > "$work/req.cnf" <<'CNF'
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = LoupedeckBridge Release
[ext]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = critical, codeSigning
subjectKeyIdentifier = hash
CNF
  "$OPENSSL" req -x509 -new -newkey rsa:3072 -nodes -sha256 -days 3650 -config "$work/req.cnf" \
    -keyout "$work/key.pem" -out "$work/cert.pem" 2>/dev/null
  "$OPENSSL" rand -base64 32 | tr -d '\n' > "$dir/p12-password"
  "$OPENSSL" pkcs12 -export -name "$NAME" -inkey "$work/key.pem" -in "$work/cert.pem" \
    -keypbe PBE-SHA1-3DES -certpbe PBE-SHA1-3DES -macalg sha1 \
    -passout "file:$dir/p12-password" -out "$dir/LoupedeckBridge-Release.p12"
  "$OPENSSL" x509 -in "$work/cert.pem" -outform der | shasum -a 256 | awk '{print $1}' > "$dir/signer.sha256"
  rm -rf "$work"                                  # the bare key
}

if [ -n "$out" ]; then
  make_identity "$out"
  echo "A throwaway identity (not the release key) is in $out. Certificate SHA-256: $(cat "$out/signer.sha256")"
  exit 0
fi

# ---- the real one ----------------------------------------------------------------
cd "$REPO"
command -v gh >/dev/null || { echo "This needs the GitHub CLI (gh), logged in." >&2; exit 1; }
rules="$(gh api "repos/{owner}/{repo}/environments/$ENVIRONMENT" --jq '[.protection_rules[]?.type] | join(" ")' 2>/dev/null)" || {
  echo "There's no '$ENVIRONMENT' environment yet. On GitHub: the repo's Settings → Environments → New" >&2
  echo "environment '$ENVIRONMENT', with yourself as a required reviewer. Then run this again." >&2
  exit 1
}
case " $rules " in
  *" required_reviewers "*) ;;
  *) echo "The '$ENVIRONMENT' environment has no required reviewer. Add yourself first (Settings → Environments →" >&2
     echo "$ENVIRONMENT), so the key can only be used after you approve a run." >&2
     exit 1 ;;
esac
if gh secret list --env "$ENVIRONMENT" --json name --jq '.[].name' | grep -qx "$SECRET_P12" && [ "$replace" = 0 ]; then
  echo "A signing identity is already stored ($SECRET_P12). Replacing it means every installed LoupedeckBridge" >&2
  echo "refuses the next update (each one only accepts the key it was signed with) and has to be reinstalled" >&2
  echo "with tools/install.sh. If that's really what you want, run again with --replace." >&2
  exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
make_identity "$work/id"
base64 < "$work/id/LoupedeckBridge-Release.p12" | tr -d '\n' | gh secret set "$SECRET_P12" --env "$ENVIRONMENT"
gh secret set "$SECRET_PASSWORD" --env "$ENVIRONMENT" < "$work/id/p12-password"
if [ -n "$keep" ]; then
  mkdir -p "$keep"
  chmod 700 "$keep"
  cp "$work/id/LoupedeckBridge-Release.p12" "$work/id/p12-password" "$keep/"
  echo "Kept a backup in $keep. Keep it offline: with both files, anyone can sign as you."
fi
echo
echo "Stored in GitHub's '$ENVIRONMENT' environment: $SECRET_P12 and $SECRET_PASSWORD."
echo "The certificate's SHA-256 (public, not a secret; this is what gets pinned):"
echo "  $(cat "$work/id/signer.sha256")"
