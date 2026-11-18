"""tools/bridgectl.ps1 acts on the installed release, or with -Dev on the dev build (milestone 7), like the Mac's
tools/bridgectl. The real script runs against two copies of a stand-in exe (windows/launcher/tests/FakeApp), the
"release" and the "dev" build, which log what they're asked to do."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests.windows_build import CAN_BUILD, LAUNCHER, REPO, build

SCRIPT = REPO / "tools" / "bridgectl.ps1"
pytestmark = pytest.mark.skipif(not CAN_BUILD or shutil.which("pwsh") is None,
                                reason="needs Windows, the .NET SDK and PowerShell 7")


@pytest.fixture(scope="module")
def fake_exe(tmp_path_factory):
    out = tmp_path_factory.mktemp("fakeapp")
    built = build(LAUNCHER / "tests" / "FakeApp" / "FakeApp.csproj", out)
    if built.returncode != 0:
        pytest.fail("FakeApp doesn't build:\n" + built.stdout[-3000:])
    return out / "LoupedeckBridge.exe"


class Rig:
    def __init__(self, tmp_path: Path, fake_exe: Path):
        self.release = tmp_path / "Programs" / "LoupedeckBridge" / "LoupedeckBridge.exe"
        self.dev = tmp_path / "repo build" / "LoupedeckBridge Dev" / "LoupedeckBridge.exe"
        for exe in (self.release, self.dev):
            exe.parent.mkdir(parents=True)
            shutil.copy(fake_exe, exe)
        self.local = tmp_path / "Local"
        self.log = tmp_path / "fake.log"
        self.marker = self.local / "loupedeck-lr-bridge" / "release-paused"
        self.env = {**os.environ, "LB_BRIDGECTL_RELEASE_APP": str(self.release), "LB_BRIDGECTL_DEV_APP": str(self.dev),
                    "LOCALAPPDATA": str(self.local), "LB_FAKE_LOG": str(self.log), "LB_FAKE_STAY": "1"}
        self.procs = []

    def run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-File", str(SCRIPT), *args],
                              capture_output=True, text=True, env=self.env, timeout=60)

    def start_release(self) -> None:
        self.procs.append(subprocess.Popen([str(self.release)], env=self.env))
        time.sleep(0.5)

    def logged(self, exe: Path) -> "list[str]":
        if not self.log.exists():
            return []
        return [line[len(str(exe)):].strip() for line in self.log.read_text(encoding="utf-8").splitlines()
                if line.lower().startswith(str(exe).lower())]

    def running(self, exe: Path) -> bool:
        out = subprocess.run(["pwsh", "-NoProfile", "-Command",
                              f"[bool](Get-Process | Where-Object {{ $_.Path -ieq '{exe}' }})"],
                             capture_output=True, text=True)
        return out.stdout.strip() == "True"

    def close(self) -> None:
        for exe in (self.release, self.dev):
            subprocess.run(["pwsh", "-NoProfile", "-Command",
                            f"Get-Process | Where-Object {{ $_.Path -ieq '{exe}' }} | Stop-Process -Force"],
                           capture_output=True)
        for p in self.procs:
            if p.poll() is None:
                p.kill()


@pytest.fixture
def rig(tmp_path, fake_exe):
    r = Rig(tmp_path, fake_exe)
    yield r
    r.close()


def test_status_targets(rig):
    assert rig.run("status").stdout.strip() == "not running"
    rig.start_release()
    assert rig.run("status").stdout.strip() == "running"
    assert rig.run("status", "-Dev").stdout.strip() == "not running"


def test_start_dev_pauses_the_release(rig):
    rig.start_release()
    result = rig.run("start", "-Dev")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--quit" in rig.logged(rig.release)
    assert rig.marker.exists()
    assert "" in rig.logged(rig.dev)              # started with no arguments
    assert rig.running(rig.dev) and not rig.running(rig.release)


def test_stop_dev_resumes_the_release(rig):
    rig.marker.parent.mkdir(parents=True)
    rig.marker.write_text("")
    rig.procs.append(subprocess.Popen([str(rig.dev)], env=rig.env))
    time.sleep(0.5)
    result = rig.run("stop", "-Dev")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--quit" in rig.logged(rig.dev)
    assert not rig.marker.exists()
    assert rig.running(rig.release)


def test_stop_dev_without_marker_leaves_release_alone(rig):
    rig.procs.append(subprocess.Popen([str(rig.dev)], env=rig.env))
    time.sleep(0.5)
    assert rig.run("stop", "-Dev").returncode == 0
    assert rig.logged(rig.release) == []


def test_release_start_refuses_while_dev_runs(rig):
    rig.procs.append(subprocess.Popen([str(rig.dev)], env=rig.env))
    time.sleep(0.5)
    result = rig.run("start")
    assert result.returncode == 1 and "stop -Dev" in result.stdout + result.stderr
    assert rig.logged(rig.release) == []


def test_stop_reports_an_app_that_wont_quit(rig):
    rig.start_release()
    rig.env["LB_FAKE_WONT_QUIT"] = "1"
    result = rig.run("stop")
    assert result.returncode == 1 and "still running" in result.stdout + result.stderr
