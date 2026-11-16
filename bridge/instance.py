"""Only one bridge at a time: on macOS two bridges would both read the Loupedeck and apply
every dial turn twice (e.g. one in a terminal, one from LoupedeckBridge.app)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import IO, Optional


def acquire(path: Path) -> Optional[IO]:
    """Lock `path` for this process. Returns the open file (keep it open while running; the OS
    releases the lock when the process exits), or None if another bridge holds it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
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
