#!/bin/bash
# Release a version:  tools/release.sh 0.5.1
#
# Checks first: on main, nothing uncommitted, the same as GitHub's main, the tag is new, bridge.__version__
# and CHANGELOG.md match (tools/check_release.py), tools/install.sh and tools/install.ps1 pin the same release
# key, and the suite passes. Then it tags vVERSION and asks before pushing the tag. Works on the Mac and in Git Bash
# on Windows (milestone 7). Pushing it starts
# .github/workflows/release.yml on GitHub: build and test, wait for your approval, then sign and publish.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
fail() { echo "release.sh: $*" >&2; exit 1; }
[ $# -eq 1 ] || { echo "usage: tools/release.sh VERSION   (e.g. 0.5.1)" >&2; exit 2; }
version="${1#v}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "usage: tools/release.sh VERSION   (e.g. 0.5.1)" >&2; exit 2; }
tag="v$version"
python=".venv/bin/python"
[ -x "$python" ] || python=".venv/Scripts/python.exe"      # Git Bash on Windows
[ -x "$python" ] || python=python3

[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || fail "switch to main first"
[ -z "$(git status --porcelain)" ] || fail "commit or stash your changes first"
git fetch --quiet --tags origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || fail "main isn't the same as GitHub's main (push or pull first)"
if git rev-parse --quiet --verify "refs/tags/$tag" >/dev/null; then fail "$tag already exists"; fi
"$python" tools/check_release.py "$version" >/dev/null || fail "bump bridge/__init__.py and add a CHANGELOG.md section first"
mac_pin="$(sed -n 's/^PINNED_SIGNER_SHA256_DEFAULT="\([0-9a-f]\{64\}\)"$/\1/p' tools/install.sh)"
windows_pin="$(sed -n 's/^\$PinnedSignerSha256Default = "\([0-9a-f]\{64\}\)"$/\1/p' tools/install.ps1)"
[ -n "$mac_pin" ] || fail "tools/install.sh has no pinned release key yet (tools/make_signing_identity.sh)"
[ "$mac_pin" = "$windows_pin" ] || fail "tools/install.sh and tools/install.ps1 must pin the same release key"
"$python" -m pytest -q || fail "the tests fail"

git tag -a "$tag" -m "LoupedeckBridge $tag"
answer=""
read -r -p "Push tag $tag? GitHub will then build it and wait for your approval [y/N] " answer || true
case "$answer" in
  y|Y|yes)
    git push origin "$tag"
    echo "Pushed. When the build has passed, approve the signing step on GitHub:"
    echo "  https://github.com/MegaMattMiller/LoupedeckBridge/actions/workflows/release.yml" ;;
  *)
    echo "Not pushed. Later: git push origin $tag   (or drop the tag: git tag -d $tag)" ;;
esac
