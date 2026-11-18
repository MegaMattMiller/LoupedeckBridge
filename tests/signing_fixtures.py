"""Throwaway signing identities for the tests (milestone 7): never the release key. Each is a self-signed RSA-3072
certificate with the same extensions as tools/make_signing_identity.sh's, packed into a .p12, made with openssl.
Signing goes through the real tools/sign_windows_zip.sh."""
from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
SIGN_SCRIPT = REPO / "tools" / "sign_windows_zip.sh"
GIT = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git"
REQ_CNF = """[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = LoupedeckBridge Test {name}
[ext]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = critical, codeSigning
subjectKeyIdentifier = hash
"""


def tool(name: str) -> Optional[str]:
    """openssl, or bash: on Windows, Git for Windows' own (System32\\bash.exe is WSL's)."""
    if sys.platform == "win32":
        candidate = GIT / ("bin/bash.exe" if name == "bash" else f"usr/bin/{name}.exe")
        if candidate.exists():
            return str(candidate)
        return shutil.which(name) if name != "bash" else None
    return shutil.which(name)


CAN_SIGN = tool("openssl") is not None and tool("bash") is not None


@dataclass
class Identity:
    p12: Path
    password_file: Path
    sha256: str          # the certificate's SHA-256 (DER): what gets pinned


def make_identity(folder: Path, name: str = "A") -> Identity:
    folder.mkdir(parents=True, exist_ok=True)
    openssl = tool("openssl")
    cnf, key, cert, der = (folder / f"{name}.{ext}" for ext in ("cnf", "key.pem", "cert.pem", "cert.der"))
    cnf.write_text(REQ_CNF.format(name=name), encoding="utf-8")
    password = folder / f"{name}.password"
    password.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    p12 = folder / f"{name}.p12"
    for args in (["req", "-x509", "-new", "-newkey", "rsa:3072", "-nodes", "-sha256", "-days", "30", "-config", str(cnf),
                  "-keyout", str(key), "-out", str(cert)],
                 ["pkcs12", "-export", "-name", f"LoupedeckBridge Test {name}", "-inkey", str(key), "-in", str(cert),
                  "-passout", f"file:{password}", "-out", str(p12)],
                 ["x509", "-in", str(cert), "-outform", "der", "-out", str(der)]):
        subprocess.run([openssl, *args], check=True, capture_output=True)
    key.unlink()
    return Identity(p12, password, hashlib.sha256(der.read_bytes()).hexdigest())


def sign(file: Path, identity: Identity, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    """`bash tools/sign_windows_zip.sh FILE P12 PASSWORD_FILE` → FILE.p7s."""
    return subprocess.run([tool("bash"), str(SIGN_SCRIPT), str(file), str(identity.p12), str(identity.password_file)],
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ, "OPENSSL": tool("openssl"), **(env or {})})
