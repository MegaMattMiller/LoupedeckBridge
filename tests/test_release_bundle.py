"""The release app (tools/build_release_app.sh), checked when LB_RELEASE_APP points at a built
LoupedeckBridge.app: CI's release build sets it; locally, build into a scratch folder first. Python runs the way
the app runs it (-E -B, in Contents/Resources/app). The whole suite also runs with the bundled Python in CI."""
from __future__ import annotations

import os
import plistlib
import re
import subprocess
from pathlib import Path

import pytest

import bridge

REPO = Path(__file__).resolve().parent.parent
APP = Path(os.environ.get("LB_RELEASE_APP", "/nonexistent"))
RESOURCES = APP / "Contents" / "Resources"
PYTHON = RESOURCES / "python" / "bin" / "python3"
STDLIB = RESOURCES / "python" / "lib" / "python3.12"

pytestmark = pytest.mark.skipif("LB_RELEASE_APP" not in os.environ,
                                reason="set LB_RELEASE_APP to a built release app")


def run_bundled(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(PYTHON), "-E", "-B", *args], cwd=RESOURCES / "app", capture_output=True, text=True,
                          timeout=120)


def pinned_signer() -> str:
    if "LB_SIGNER_SHA256" in os.environ:                 # CI's signing rehearsal pins a throwaway identity
        return os.environ["LB_SIGNER_SHA256"]
    match = re.search(r'^PINNED_SIGNER_SHA256_DEFAULT="(.*)"$', (REPO / "tools" / "install.sh").read_text(), re.M)
    return match.group(1)


def test_layout():
    info = plistlib.loads((APP / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == "io.github.megamattmiller.loupedeckbridge"
    assert info["CFBundleName"] == "LoupedeckBridge"
    assert info["LBRuntime"] == "bundled" and info["LBIsDev"] is False and "LBRepoPath" not in info
    assert info["LBVersion"] == info["CFBundleShortVersionString"] == bridge.__version__
    assert info["LSMinimumSystemVersion"] == "14.0"
    assert info["LBSignerSHA256"] == pinned_signer()
    assert (APP / "Contents" / "MacOS" / "LoupedeckBridge").is_file()
    for rel in ("app/bridge/__main__.py", "app/bridge/settings/static/index.html", "app/config/commands.json",
                "app/config/default_mapping.json", "app/config/loupedeck_plus.json", "app/docs/lr_parameters_10.0.json"):
        assert (RESOURCES / rel).is_file(), rel


def test_bundled_python_is_its_own_3_12():
    result = run_bundled("-c", "import sys; print(sys.version_info[:2] == (3, 12)); print(sys.prefix)")
    assert result.returncode == 0, result.stderr
    ok, prefix = result.stdout.split()
    assert ok == "True" and Path(prefix).resolve() == (RESOURCES / "python").resolve()


def test_code_and_packages_load_from_the_bundle():
    result = run_bundled("-c", "import bridge, bridge.app, mido, rtmidi, websockets\n"
                               "print(bridge.__version__)\n"
                               "for m in (bridge, mido, rtmidi, websockets): print(m.__file__)")
    assert result.returncode == 0, result.stderr
    version, *files = result.stdout.split()
    assert version == bridge.__version__
    assert all(Path(f).resolve().is_relative_to(RESOURCES.resolve()) for f in files), files


def test_coremidi_opens():
    # The spec's "To verify first" 1: CoreMIDI works from the bundled interpreter.
    result = run_bundled("-c", "import rtmidi\nm = rtmidi.MidiIn()\nprint(len(m.get_ports()))\nm.delete()")
    assert result.returncode == 0, result.stderr


def test_bridge_command_line():
    result = run_bundled("-m", "bridge", "--help")
    assert result.returncode == 0 and "Loupedeck" in result.stdout, result.stderr


def test_no_dev_leftovers():
    for name in ("test", "idlelib", "tkinter", "turtledemo", "ensurepip"):
        assert not (STDLIB / name).exists(), name
    assert not (RESOURCES / "python" / "include").exists()
    leftovers = [p for p in RESOURCES.rglob("*") if p.is_dir() and p.name in ("test", "tests")]
    assert not leftovers, leftovers[:5]


def test_everything_is_precompiled():
    # The app runs Python with -B, so it never writes bytecode into its signed bundle: every module needs its
    # .pyc already (unchecked-hash ones, which Python doesn't even compare with the source).
    script = ("import importlib.util, pathlib, sys\n"
              "missing = [str(p) for root in sys.argv[1:] for p in pathlib.Path(root).rglob('*.py')\n"
              "           if not pathlib.Path(importlib.util.cache_from_source(str(p))).exists()]\n"
              "print(len(missing)); print('\\n'.join(missing[:10]))")
    result = run_bundled("-c", script, str(STDLIB), str(RESOURCES / "app"))
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[0] == "0", result.stdout


def test_signature_is_valid():
    result = subprocess.run(["codesign", "--verify", "--strict", str(APP)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
