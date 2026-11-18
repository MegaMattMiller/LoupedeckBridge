"""Status lines for LoupedeckBridge.app's menu-bar icon (milestone 5).

The app starts the bridge with a pipe as file descriptor LB_STATUS_FD. The bridge writes its whole state as
one JSON line at start and after every change:
    {"loupedeck": bool, "lightroom": bool, "keys": "allowed"|"missing"|"unavailable",
     "five_mode": "ratings"|"colours"|"keys", "settings_url": str|null}
Run without the app (`python -m bridge`), there's no pipe and nothing is written. A write that fails
(the app is gone) turns reporting off; it never stops the bridge.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Callable, Mapping, Optional

log = logging.getLogger("status")

STATUS_FD_ENV = "LB_STATUS_FD"


class StatusReporter:
    def __init__(self, write: Optional[Callable[[str], None]], keyboard=None):
        self._write, self._keyboard = write, keyboard
        self._file = None  # set by from_env, closed by close()
        self.state = {"loupedeck": False, "lightroom": False, "keys": self._keys(), "five_mode": "ratings",
                      "settings_url": None}

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ, keyboard=None) -> "StatusReporter":
        """Write to the fd the app passed in LB_STATUS_FD; without one, report nothing."""
        try:
            f = os.fdopen(int(environ[STATUS_FD_ENV]), "w", buffering=1, encoding="utf-8")
        except (KeyError, ValueError, OSError):
            return cls(None, keyboard=keyboard)
        reporter = cls(f.write, keyboard=keyboard)
        reporter._file = f
        return reporter

    def set(self, **changes) -> None:
        """Update the state; write it only if something changed."""
        if all(self.state.get(k) == v for k, v in changes.items()):
            return
        self.state.update(changes)
        self._send()

    async def run(self, interval: float = 3.0) -> None:
        """Send the state once, then re-check the keyboard permission until it's allowed
        (so granting it shows in the menu without a restart). Never raises."""
        try:
            self._send()
            while self.state["keys"] == "missing" and self._write is not None:
                await asyncio.sleep(interval)
                self.set(keys=self._keys())
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — status is a convenience; the bridge must keep going
            log.exception("status reporting stopped")

    def close(self) -> None:
        """Stop reporting (nothing is written after this) and close the pipe."""
        self._write = None
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None

    def _keys(self) -> str:
        if self._keyboard is None:
            return "unavailable"
        return "allowed" if self._keyboard.is_trusted() else "missing"

    def _send(self) -> None:
        if self._write is None:
            return
        try:
            self._write(json.dumps(self.state) + "\n")
        except (OSError, ValueError) as e:  # the app went away (broken pipe) or the file is closed
            self._write = None
            if self._file is not None:
                try:
                    self._file.close()
                except OSError:
                    pass
                self._file = None
            log.info("status reporting off: %s", e)
