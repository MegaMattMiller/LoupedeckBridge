"""tools/make_signing_identity.sh --out DIR: the throwaway mode (no upload, no keychain), which the CI signing
rehearsal uses. The user's real identity is made by the same code, so this checks its shape: a .p12 that
macOS's `security import` accepts, holding a code-signing certificate, and the SHA-256 the app and
tools/install.sh pin."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "make_signing_identity.sh"
OPENSSL = "/usr/bin/openssl"

pytestmark = pytest.mark.skipif(sys.platform != "darwin" or not Path(OPENSSL).exists(), reason="needs macOS")


def test_throwaway_identity(tmp_path):
    out = tmp_path / "id"
    result = subprocess.run([str(SCRIPT), "--out", str(out)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    p12, password = out / "LoupedeckBridge-Release.p12", out / "p12-password"
    assert p12.exists() and password.exists()
    for path in (out, p12, password):
        assert path.stat().st_mode & 0o077 == 0, f"{path} is readable by others"
    assert not list(out.glob("*.pem")), "the bare key must not be left behind"

    # The certificate inside the .p12 (opened with the generated password): code signing, ours, 10 years.
    pem = subprocess.run([OPENSSL, "pkcs12", "-in", str(p12), "-nokeys", "-clcerts", "-passin", f"file:{password}"],
                         capture_output=True, text=True, check=True).stdout
    text = subprocess.run([OPENSSL, "x509", "-noout", "-text"], input=pem, capture_output=True, text=True,
                          check=True).stdout
    assert "CN=LoupedeckBridge Release" in text.replace(" = ", "=")
    assert "Code Signing" in text
    der = subprocess.run([OPENSSL, "x509", "-outform", "der"], input=pem.encode(), capture_output=True,
                         check=True).stdout
    sha = hashlib.sha256(der).hexdigest()
    assert (out / "signer.sha256").read_text().strip() == sha
    assert sha in result.stdout

    # The key is in it too, and the legacy (3DES / SHA-1 MAC) encoding macOS's `security import` needs.
    info = subprocess.run([OPENSSL, "pkcs12", "-in", str(p12), "-info", "-noout", "-passin", f"file:{password}"],
                          capture_output=True, text=True, check=True)
    assert "Shrouded Keybag" in info.stderr + info.stdout
    assert "RC2" not in info.stderr + info.stdout


def test_usage():
    assert subprocess.run([str(SCRIPT), "--nope"], capture_output=True, timeout=30).returncode == 2


def test_import_refuses_outside_github_runners(tmp_path):
    # It changes the keychain search list, so it must never run on the user's Mac.
    env = {k: v for k, v in os.environ.items() if k not in ("CI", "GITHUB_ACTIONS")}
    keychain = tmp_path / "x.keychain-db"
    result = subprocess.run([str(REPO / "tools" / "import_signing_identity.sh"), str(tmp_path / "id.p12"),
                             str(tmp_path / "pw"), str(keychain)], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and "GitHub" in result.stderr
    assert not keychain.exists()
