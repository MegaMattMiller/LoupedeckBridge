"""Only one bridge at a time: on macOS two bridges would both read the Loupedeck and apply
every dial turn twice (e.g. one in a terminal, one from LoupedeckBridge.app). And the bridge stops when the app
that started it has gone: on macOS by watching its parent, on Windows through the control pipe (milestone 7)."""
from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path
from typing import IO, Callable, Mapping, Optional

# Windows has no SIGTERM. The tray app passes the read end of a pipe (an inheritable handle) in this variable,
# writes "stop" to it to stop the bridge, and its end closes by itself if the tray app dies.
CONTROL_HANDLE_ENV = "LB_CONTROL_HANDLE"


def acquire(path: Path) -> Optional[IO]:
    """Lock `path` for this process. Returns the open file (keep it open while running; the OS
    releases the lock when the process exits), or None if another bridge holds it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+", encoding="utf-8")
    try:
        if sys.platform == "win32":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


async def parent_gone(parent_pid: int, getppid: Callable[[], int] = os.getppid, interval: float = 1.0) -> None:
    """Return once the process that started us has gone (our parent pid changes). Then a
    force-quit LoupedeckBridge.app (or a closed terminal) can't leave an invisible bridge
    holding the Loupedeck and the single-instance lock. Under launchd the parent never changes."""
    while getppid() == parent_pid:
        await asyncio.sleep(interval)


def open_control(environ: Mapping[str, str] = os.environ) -> Optional[IO[str]]:
    """The control pipe the Windows tray app passed in CONTROL_HANDLE_ENV, or None (not Windows, no variable, or a
    bad value: e.g. run from a terminal)."""
    if sys.platform != "win32":
        return None
    try:
        import msvcrt
        fd = msvcrt.open_osfhandle(int(environ[CONTROL_HANDLE_ENV]), os.O_RDONLY)
        return os.fdopen(fd, "r", encoding="utf-8")
    except (KeyError, ValueError, OSError):
        return None


def watch_control(stream: IO[str], on_stop: Callable[[], None]) -> threading.Thread:
    """Read the control pipe in a background thread: a "stop" line, or its end (the tray app has gone, e.g.
    killed), calls on_stop once. Other lines are ignored."""
    def run() -> None:
        try:
            while True:
                line = stream.readline()
                if not line or line.strip() == "stop":
                    break
        except (OSError, ValueError):
            pass
        on_stop()

    thread = threading.Thread(target=run, name="control pipe", daemon=True)
    thread.start()
    return thread
