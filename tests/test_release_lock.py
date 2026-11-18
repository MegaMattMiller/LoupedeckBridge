"""What the release app is built from (milestone 6): tools/python-standalone.lock (the bundled Python) and
tools/release-requirements.txt (its packages, with hashes), which must pin what requirements.txt pins."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def pins(path: Path) -> "dict[str, str]":
    out = {}
    for line in path.read_text().splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;]+)", line.strip())
        if match:
            out[match.group(1).lower()] = match.group(2)
    return out


def test_python_lock():
    lock = dict(line.split("=", 1) for line in (REPO / "tools" / "python-standalone.lock").read_text().splitlines()
                if line and not line.startswith("#"))
    assert lock["url"].startswith("https://github.com/astral-sh/python-build-standalone/releases/download/")
    assert re.search(r"/cpython-3\.12\.\d+%2B\d{8}-aarch64-apple-darwin-install_only\.tar\.gz$", lock["url"])
    assert re.fullmatch(r"[0-9a-f]{64}", lock["sha256"])


def test_release_requirements_pin_what_requirements_pins():
    release = REPO / "tools" / "release-requirements.txt"
    wanted, locked = pins(REPO / "requirements.txt"), pins(release)
    assert wanted and all(locked.get(name) == version for name, version in wanted.items()), (wanted, locked)
    for line in release.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            assert re.search(r"--hash=sha256:[0-9a-f]{64}", line), line


def test_release_test_tools_are_hash_pinned():
    # The test tools that run in the release build's job (milestone 6 review, Critical 1).
    tools = REPO / "tools" / "release-test-requirements.txt"
    assert pins(tools).get("pytest") == pins(REPO / "requirements-dev.txt")["pytest"]
    for line in tools.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            assert re.search(r"--hash=sha256:[0-9a-f]{64}", line), line


# ---- milestone 7: the Windows release ---------------------------------------------------------------------

def test_windows_python_lock():
    lock = dict(line.split("=", 1) for line in
                (REPO / "tools" / "python-standalone-windows.lock").read_text(encoding="utf-8").splitlines()
                if line and not line.startswith("#"))
    assert lock["url"].startswith("https://github.com/astral-sh/python-build-standalone/releases/download/")
    assert re.search(r"/cpython-3\.12\.\d+%2B\d{8}-x86_64-pc-windows-msvc-install_only\.tar\.gz$", lock["url"])
    assert re.fullmatch(r"[0-9a-f]{64}", lock["sha256"])


def test_windows_release_requirements_pin_what_requirements_pins():
    release = REPO / "tools" / "release-requirements-windows.txt"
    wanted, locked = pins(REPO / "requirements.txt"), pins(release)
    assert wanted and all(locked.get(name) == version for name, version in wanted.items()), (wanted, locked)
    for line in release.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            assert re.search(r"--hash=sha256:[0-9a-f]{64}", line), line


def test_both_installers_pin_the_same_key():
    # One release key signs both platforms: the Mac's install.sh and Windows' install.ps1 must pin the same certificate.
    mac = re.search(r'^PINNED_SIGNER_SHA256_DEFAULT="([0-9a-f]{64})"$',
                    (REPO / "tools" / "install.sh").read_text(encoding="utf-8"), re.M)
    windows = re.search(r'^\$PinnedSignerSha256Default = "([0-9a-f]{64})"$',
                        (REPO / "tools" / "install.ps1").read_text(encoding="utf-8"), re.M)
    assert mac and windows and mac.group(1) == windows.group(1)
