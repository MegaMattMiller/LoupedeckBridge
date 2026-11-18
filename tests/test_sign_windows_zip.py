"""tools/sign_windows_zip.sh (milestone 7): a detached signature (.p7s) over a Windows release zip's exact bytes, made
with the release key's .p12 in the release workflow's key step. Here with throwaway identities; it runs on macOS
(LibreSSL) in CI and on Windows (Git for Windows' OpenSSL 3)."""
from __future__ import annotations

import os
import subprocess

import pytest

from tests.signing_fixtures import CAN_SIGN, make_identity, sign, tool

pytestmark = pytest.mark.skipif(not CAN_SIGN, reason="needs bash and openssl")


def verifies(file, signature) -> bool:
    # -out a real file, not os.devnull: Git for Windows' openssl is an MSYS2 program, and makes a file named "nul"
    out = file.with_name(file.name + ".verified")
    result = subprocess.run([tool("openssl"), "smime", "-verify", "-binary", "-noverify", "-inform", "DER",
                             "-in", str(signature), "-content", str(file), "-out", str(out)], capture_output=True)
    return result.returncode == 0


def test_signature_verifies_and_a_change_does_not(tmp_path):
    identity = make_identity(tmp_path / "id")
    zip_file = tmp_path / "LoupedeckBridge-v0.6.0-windows-x64.zip"
    zip_file.write_bytes(os.urandom(4096))
    result = sign(zip_file, identity)
    assert result.returncode == 0, result.stdout + result.stderr
    signature = zip_file.with_name(zip_file.name + ".p7s")
    assert verifies(zip_file, signature)
    changed = tmp_path / "changed.zip"
    data = bytearray(zip_file.read_bytes())
    data[100] ^= 1
    changed.write_bytes(bytes(data))
    assert not verifies(changed, signature)


def test_no_key_left_behind(tmp_path):
    identity = make_identity(tmp_path / "id")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    zip_file = tmp_path / "x.zip"
    zip_file.write_bytes(b"release")
    result = sign(zip_file, identity, env={"TMPDIR": str(scratch)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert list(scratch.iterdir()) == []


def test_refuses_a_missing_file(tmp_path):
    identity = make_identity(tmp_path / "id")
    result = sign(tmp_path / "nope.zip", identity)
    assert result.returncode != 0
    assert not (tmp_path / "nope.zip.p7s").exists()
