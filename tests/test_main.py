"""`python -m bridge` as a process: clean SIGTERM stop and a single instance.

Each test runs the real bridge with HOME pointed at a temp dir whose Lightroom port file names an
unused port, and a MIDI name that doesn't exist, so the user's Lightroom and Loupedeck are never touched.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS paths")

REPO = Path(__file__).resolve().parent.parent


def isolated_env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return {**os.environ, "HOME": str(home)}, home / "Library/Logs/loupedeck-lr-bridge/bridge.log", port


PROCS = []


@pytest.fixture(autouse=True)
def kill_leftovers():
    # A bridge left running would outlive its temp HOME and reach for the user's real Lightroom
    # (this happened once): every process a test starts is killed, pass or fail.
    yield
    while PROCS:
        p = PROCS.pop()
        if p.poll() is None:
            p.kill()
            p.wait(timeout=5)


def start(env, port):
    # --lightroom-port pins an unused port explicitly, so the bridge can never fall back to 7682.
    p = subprocess.Popen([sys.executable, "-m", "bridge", "--midi-port", "NoSuchDevice", "--lightroom-port", str(port),
                          "--settings-port", "0"],  # don't compete with a running bridge for the page's port
                         cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    PROCS.append(p)
    return p


def wait_for_log(log: Path, text: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log.exists() and text in log.read_text():
            return
        time.sleep(0.05)
    raise AssertionError(f"{text!r} never appeared in {log}")


def test_sigterm_exits_cleanly(tmp_path):
    env, log, port = isolated_env(tmp_path)
    proc = start(env, port)
    wait_for_log(log, "waiting for a MIDI input")  # up and running
    wait_for_log(log, str(port))                    # and talking to the pinned port, not Lightroom's
    proc.send_signal(signal.SIGTERM)                # what `bridgectl stop` / the launcher send
    assert proc.wait(timeout=3) == 0
    assert "bridge stopped" in log.read_text()


def test_second_process_exits_3(tmp_path):
    env, log, port = isolated_env(tmp_path)
    first = start(env, port)
    wait_for_log(log, "waiting for a MIDI input")
    second = start(env, port)
    assert second.wait(timeout=10) == 3
    assert "already running" in log.read_text()
    assert first.poll() is None  # the first bridge is unaffected


def test_no_console_copy_when_stderr_is_the_log(tmp_path):
    # Live check, 2026-11-16: under LoupedeckBridge.app the bridge's stderr *is* bridge.log, so the console
    # handler wrote every line a second time.
    from bridge.__main__ import log_handlers
    log_file = tmp_path / "bridge.log"
    log_file.write_text("")
    with open(log_file, "a") as same, open(tmp_path / "other.txt", "w") as other:
        kinds = [type(h).__name__ for h in log_handlers(log_file, stderr=same)]
        assert kinds == ["RotatingFileHandler"]
        kinds = [type(h).__name__ for h in log_handlers(log_file, stderr=other)]
        assert kinds == ["StreamHandler", "RotatingFileHandler"]      # a terminal (or anything else): both
    for h in log_handlers(log_file, stderr=sys.stderr):
        h.close()
