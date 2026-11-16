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
    conn = home / "Library/Application Support/Adobe/Lightroom CC/Connections"
    conn.mkdir(parents=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    (conn / "connections.json").write_text(json.dumps({"port": port}))
    return {**os.environ, "HOME": str(home)}, home / "Library/Logs/loupedeck-lr-bridge/bridge.log"


def start(env):
    return subprocess.Popen([sys.executable, "-m", "bridge", "--midi-port", "NoSuchDevice"], cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_for_log(log: Path, text: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log.exists() and text in log.read_text():
            return
        time.sleep(0.05)
    raise AssertionError(f"{text!r} never appeared in {log}")


def test_sigterm_exits_cleanly(tmp_path):
    env, log = isolated_env(tmp_path)
    proc = start(env)
    try:
        wait_for_log(log, "waiting for a MIDI input")  # up and running
        proc.send_signal(signal.SIGTERM)                # what `bridgectl stop` / the launcher send
        assert proc.wait(timeout=3) == 0
        assert "bridge stopped" in log.read_text()
    finally:
        if proc.poll() is None:
            proc.kill()


def test_second_process_exits_3(tmp_path):
    env, log = isolated_env(tmp_path)
    first = start(env)
    try:
        wait_for_log(log, "waiting for a MIDI input")
        second = start(env)
        assert second.wait(timeout=10) == 3
        assert "already running" in log.read_text()
        assert first.poll() is None  # the first bridge is unaffected
    finally:
        first.terminate()
        first.wait(timeout=5)
