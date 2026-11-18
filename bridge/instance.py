"""Only one bridge at a time: on macOS two bridges would both read the Loupedeck and apply
every dial turn twice (e.g. one in a terminal, one from LoupedeckBridge.app)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import IO, Callable, Optional


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
