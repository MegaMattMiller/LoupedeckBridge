"""`python -m bridge` on Windows (milestone 7): stopped through the control pipe, never by a signal, and stopping by
itself when the tray app's end of that pipe closes; status lines on the status pipe; a single instance.

Each process test runs the real bridge with LOCALAPPDATA and APPDATA in a temp dir, whose Lightroom port file names
an unused port, and a MIDI name that doesn't exist, so the user's Lightroom and Loupedeck are never touched."""
from __future__ import annotations

import json
import os
import site
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_log_handlers_skip_console_when_stderr_is_the_log(tmp_path):
    # The tray app sends the bridge's stderr into bridge.log (for crashes before logging starts), so a console
    # copy would double every line; it says so with LB_STDERR_IS_LOG=1.
    from bridge.__main__ import log_handlers
    log_file = tmp_path / "bridge.log"
    handlers = log_handlers(log_file, stderr=sys.stderr, environ={"LB_STDERR_IS_LOG": "1"})
    assert [type(h).__name__ for h in handlers] == ["RotatingFileHandler"]
    for h in handlers:
        h.close()
    handlers = log_handlers(log_file, stderr=sys.stderr, environ={})
    assert [type(h).__name__ for h in handlers] == ["StreamHandler", "RotatingFileHandler"]
    for h in handlers:
        h.close()


# ---- the real process -----------------------------------------------------------------------------------------

PROCS = []


@pytest.fixture(autouse=True)
def kill_leftovers():
    # A bridge left running would outlive its temp folders and reach for the user's real Lightroom.
    yield
    while PROCS:
        p = PROCS.pop()
        if p.poll() is None:
            p.kill()
            p.wait(timeout=5)


def isolated_env(tmp_path):
    local, roaming = tmp_path / "Local", tmp_path / "Roaming"
    connections = local / "Adobe" / "Lightroom CC" / "Connections" / "connections.json"
    connections.parent.mkdir(parents=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    connections.write_text(json.dumps({"port": port}), encoding="utf-8")
    env = {**os.environ, "LOCALAPPDATA": str(local), "APPDATA": str(roaming)}
    return env, local / "loupedeck-lr-bridge" / "logs" / "bridge.log", port


class Pipes:
    """The two pipes the tray app gives the bridge: control (app → bridge) and status (bridge → app)."""

    def __init__(self):
        import msvcrt
        self.control_r, self.control_w = os.pipe()
        self.status_r, self.status_w = os.pipe()
        self.handles = [msvcrt.get_osfhandle(self.control_r), msvcrt.get_osfhandle(self.status_w)]
        for h in self.handles:
            os.set_handle_inheritable(h, True)

    def env(self):
        return {"LB_CONTROL_HANDLE": str(self.handles[0]), "LB_STATUS_HANDLE": str(self.handles[1])}

    def started(self):
        os.close(self.control_r)       # the child has its own copies now
        os.close(self.status_w)


def start(env, port, pipes=None, cwd=REPO, python=sys.executable):
    args = [python, "-m", "bridge", "--midi-port", "NoSuchDevice", "--lightroom-port", str(port),
            "--settings-port", "0"]
    kwargs = {}
    if pipes is not None:
        env = {**env, **pipes.env()}
        kwargs["startupinfo"] = subprocess.STARTUPINFO(lpAttributeList={"handle_list": pipes.handles})
    p = subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True, **kwargs)
    PROCS.append(p)
    if pipes is not None:
        pipes.started()
    return p


def wait_for_log(log: Path, text: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log.exists() and text in log.read_text(encoding="utf-8", errors="replace"):
            return
        time.sleep(0.05)
    raise AssertionError(f"{text!r} never appeared in {log}")


@windows_only
def test_stop_line_stops_cleanly(tmp_path):
    env, log, port = isolated_env(tmp_path)
    pipes = Pipes()
    proc = start(env, port, pipes)
    wait_for_log(log, "waiting for a MIDI input")
    os.write(pipes.control_w, b"stop\n")
    assert proc.wait(timeout=10) == 0
    assert log.read_text(encoding="utf-8").rstrip().endswith("bridge stopped")
    os.close(pipes.control_w)
    os.close(pipes.status_r)


@windows_only
def test_closed_control_pipe_stops_cleanly(tmp_path):
    # Review Focus 2: the tray app killed (Task Manager → End task) closes its end; the bridge stops by itself,
    # through its normal clean-up, which lets go of every held key.
    env, log, port = isolated_env(tmp_path)
    pipes = Pipes()
    proc = start(env, port, pipes)
    wait_for_log(log, "waiting for a MIDI input")
    os.close(pipes.control_w)
    assert proc.wait(timeout=10) == 0
    assert log.read_text(encoding="utf-8").rstrip().endswith("bridge stopped")
    os.close(pipes.status_r)


@windows_only
def test_status_lines_arrive(tmp_path):
    env, log, port = isolated_env(tmp_path)
    pipes = Pipes()
    proc = start(env, port, pipes)
    lines = []
    reader = threading.Thread(target=lambda: lines.append(os.fdopen(pipes.status_r, "r", encoding="utf-8").readline()),
                              daemon=True)
    reader.start()
    reader.join(15)
    assert lines and lines[0].strip(), "no status line"
    state = json.loads(lines[0])
    assert state["loupedeck"] is False and state["loupedeck_busy"] is False
    os.write(pipes.control_w, b"stop\n")
    assert proc.wait(timeout=10) == 0
    os.close(pipes.control_w)


@windows_only
def test_second_instance_exits_3(tmp_path):
    env, log, port = isolated_env(tmp_path)
    pipes = Pipes()
    first = start(env, port, pipes)
    wait_for_log(log, "waiting for a MIDI input")
    second = start(env, port)
    assert second.wait(timeout=15) == 3
    assert "already running" in log.read_text(encoding="utf-8")
    assert first.poll() is None
    os.write(pipes.control_w, b"stop\n")
    assert first.wait(timeout=10) == 0
    os.close(pipes.control_w)
    os.close(pipes.status_r)


@windows_only
def test_bridge_steps_out_of_its_start_folder(tmp_path):
    # The tray app starts the bridge in <install>\app, and an update renames the install folder: Windows won't rename
    # a folder that is a process's current folder (the bridge's, or that of a browser it opens), so it steps out.
    env, log, port = isolated_env(tmp_path)
    start_dir = tmp_path / "app"
    start_dir.mkdir()
    # The venv's python.exe is a launcher that runs the real one as its child, and stays where it started; the release
    # runs its python.exe directly, so this runs the real one too, with the venv's packages.
    python = getattr(sys, "_base_executable", None) or str(Path(sys.base_prefix) / "python.exe")
    path = os.pathsep.join([str(REPO), *site.getsitepackages()])
    pipes = Pipes()
    proc = start({**env, "PYTHONPATH": path}, port, pipes, cwd=start_dir, python=python)
    wait_for_log(log, "waiting for a MIDI input")
    try:
        start_dir.rename(tmp_path / "app-moved")
    finally:
        os.write(pipes.control_w, b"stop\n")
        assert proc.wait(timeout=10) == 0
        os.close(pipes.control_w)
        os.close(pipes.status_r)
