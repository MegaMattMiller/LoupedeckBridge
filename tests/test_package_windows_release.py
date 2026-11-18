"""tools/package_windows_release.ps1 (milestone 7): the release zip holds one LoupedeckBridge\\ folder, under
forward-slash entry names, with a shasum-style .sha256 beside it."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile

import pytest

from tests.windows_build import REPO

pytestmark = pytest.mark.skipif(sys.platform != "win32" or shutil.which("pwsh") is None,
                                reason="needs Windows and PowerShell 7")


def test_package_layout(tmp_path):
    app = tmp_path / "build" / "LoupedeckBridge"
    (app / "app" / "bridge").mkdir(parents=True)
    (app / "LoupedeckBridge.exe").write_bytes(b"MZ fake")
    (app / "LoupedeckBridge.json").write_text(json.dumps({"runtime": "bundled", "version": "0.6.0", "is_dev": False,
                                                           "signer_sha256": "ab"}), encoding="utf-8")
    (app / "app" / "bridge" / "__init__.py").write_text('__version__ = "0.6.0"\n', encoding="utf-8")
    out = tmp_path / "out"
    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(REPO / "tools" / "package_windows_release.ps1"),
                             str(app), str(out)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    name = "LoupedeckBridge-v0.6.0-windows-x64.zip"
    zip_path = out / name
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
    assert sorted(names) == ["LoupedeckBridge/LoupedeckBridge.exe", "LoupedeckBridge/LoupedeckBridge.json",
                             "LoupedeckBridge/app/bridge/__init__.py"], names
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert (out / (name + ".sha256")).read_bytes() == f"{digest}  {name}\n".encode()


def test_package_refuses_a_dev_build(tmp_path):
    app = tmp_path / "LoupedeckBridge"
    app.mkdir()
    (app / "LoupedeckBridge.exe").write_bytes(b"MZ fake")
    (app / "LoupedeckBridge.json").write_text(json.dumps({"runtime": "repo", "version": "0.6.0", "is_dev": True}),
                                              encoding="utf-8")
    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(REPO / "tools" / "package_windows_release.ps1"),
                             str(app), str(tmp_path / "out")], capture_output=True, text=True, timeout=120)
    assert result.returncode != 0
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").iterdir())
