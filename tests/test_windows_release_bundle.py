"""The Windows release folder (tools/build_windows_app.ps1 -Release; milestone 7), checked when LB_WINDOWS_RELEASE_DIR
points at a built LoupedeckBridge folder: CI's Windows release build sets it; locally, build into a scratch folder
first. Python runs the way the tray app runs it (-E -s -B -X utf8, in app\\)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import bridge

REPO = Path(__file__).resolve().parent.parent
APP = Path(os.environ.get("LB_WINDOWS_RELEASE_DIR", "/nonexistent"))
PYTHON = APP / "python" / "python.exe"
STDLIB = APP / "python" / "Lib"

pytestmark = pytest.mark.skipif("LB_WINDOWS_RELEASE_DIR" not in os.environ or sys.platform != "win32",
                                reason="set LB_WINDOWS_RELEASE_DIR to a built Windows release folder")


def run_bundled(*args: str, env: "dict | None" = None) -> subprocess.CompletedProcess:
    return subprocess.run([str(PYTHON), "-E", "-s", "-B", "-X", "utf8", *args], cwd=APP / "app", capture_output=True,
                          text=True, encoding="utf-8", timeout=120, env=env)


def pinned_signer() -> str:
    if "LB_SIGNER_SHA256" in os.environ:                 # CI's rehearsal pins a throwaway identity
        return os.environ["LB_SIGNER_SHA256"]
    text = (REPO / "tools" / "install.sh").read_text(encoding="utf-8")
    return re.search(r'^PINNED_SIGNER_SHA256_DEFAULT="(.*)"$', text, re.M).group(1)


def test_layout():
    info = json.loads((APP / "LoupedeckBridge.json").read_text(encoding="utf-8"))
    assert info == {"runtime": "bundled", "version": bridge.__version__, "is_dev": False, "signer_sha256": pinned_signer()}
    exe = APP / "LoupedeckBridge.exe"
    assert exe.is_file()
    # Settings → Apps → Uninstall runs this copy (tools/install.ps1 -Uninstall)
    assert (APP / "install.ps1").read_bytes() == (REPO / "tools" / "install.ps1").read_bytes()
    for rel in ("app/bridge/__main__.py", "app/bridge/settings/static/index.html", "app/config/commands.json",
                "app/config/default_mapping.json", "app/config/loupedeck_plus.json", "app/docs/lr_parameters_10.0.json"):
        assert (APP / rel).is_file(), rel
    meta = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                           f"$v = (Get-Item '{exe}').VersionInfo; $v.FileDescription; $v.FileVersion; $v.ProductVersion"],
                          capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"})
    description, file_version, product_version = meta.stdout.split("\n")[:3]
    assert description.strip() == "LoupedeckBridge"
    assert file_version.strip() == bridge.__version__ + ".0" and product_version.strip() == bridge.__version__


def test_bundled_python_is_its_own_3_12():
    result = run_bundled("-c", "import sys; print(sys.version_info[:2] == (3, 12)); print(sys.prefix)")
    assert result.returncode == 0, result.stderr
    ok, prefix = result.stdout.split("\n")[:2]
    assert ok == "True" and Path(prefix).resolve() == (APP / "python").resolve()


def test_code_and_packages_load_from_the_bundle():
    result = run_bundled("-c", "import bridge, bridge.app, mido, rtmidi, websockets\n"
                               "print(bridge.__version__)\n"
                               "for m in (bridge, mido, rtmidi, websockets): print(m.__file__)")
    assert result.returncode == 0, result.stderr
    version, *files = result.stdout.split("\n")
    assert version == bridge.__version__
    assert all(Path(f).resolve().is_relative_to(APP.resolve()) for f in files if f), files


def test_winmm_opens():
    # The spec's "To verify first" 1: Windows MIDI works from the bundled interpreter.
    result = run_bundled("-c", "import rtmidi\nm = rtmidi.MidiIn()\nprint(len(m.get_ports()))\nm.delete()")
    assert result.returncode == 0, result.stderr


def test_bridge_command_line():
    result = run_bundled("-m", "bridge", "--help")
    assert result.returncode == 0 and "Loupedeck" in result.stdout, result.stderr


def test_no_dev_leftovers():
    for name in ("test", "idlelib", "tkinter", "turtledemo", "ensurepip"):
        assert not (STDLIB / name).exists(), name
    for name in ("include", "tcl", "libs"):
        assert not (APP / "python" / name).exists(), name
    for name in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll"):
        assert not (APP / "python" / "DLLs" / name).exists(), name
    leftovers = [p for p in APP.rglob("*") if p.is_dir() and p.name in ("test", "tests")]
    assert not leftovers, leftovers[:5]
    debug = [p for p in APP.rglob("*.pdb")]        # Python's debug symbols: 83 MB nobody needs
    assert not debug, debug[:5]


def test_everything_is_precompiled():
    # The tray app runs Python with -B, so it never writes bytecode into the install folder: every module needs its
    # .pyc already (unchecked-hash ones, which Python doesn't even compare with the source).
    script = ("import importlib.util, pathlib, sys\n"
              "missing = [str(p) for root in sys.argv[1:] for p in pathlib.Path(root).rglob('*.py')\n"
              "           if not pathlib.Path(importlib.util.cache_from_source(str(p))).exists()]\n"
              "print(len(missing)); print('\\n'.join(missing[:10]))")
    result = run_bundled("-c", script, str(STDLIB), str(APP / "app"))
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[0] == "0", result.stdout


def test_user_site_packages_are_ignored(tmp_path):
    # As on the Mac (milestone 6 review): with -s, a .pth in the user's own site-packages never runs in the app.
    site = tmp_path / "Python" / "Python312" / "site-packages"
    site.mkdir(parents=True)
    (site / "planted.pth").write_text("import sys; print('PLANTED')\n", encoding="utf-8")
    result = run_bundled("-c", "import mido; print(mido.__file__)", env={**os.environ, "APPDATA": str(tmp_path)})
    assert result.returncode == 0, result.stderr
    assert "PLANTED" not in result.stdout
    assert Path(result.stdout.split("\n")[-2]).resolve().is_relative_to(APP.resolve())
