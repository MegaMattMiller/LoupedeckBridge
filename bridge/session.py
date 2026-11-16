"""Keep a registered Lightroom connection alive: connect, register, set up, and reconnect after drops."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, List, Optional, Tuple

from websockets.exceptions import WebSocketException

from bridge.lightroom import Lightroom, LightroomError

log = logging.getLogger("session")

# Sent after every successful register:
#  - open the panel of whatever is being adjusted
#  - tracking (fast redraw, one history step) ends 2 s after the last change
#  - dials turned within 1 s of each other share one history step
SETUP_CALLS: List[Tuple[str, list]] = [
    ("revealAdjustedControls", [True]),
    ("setTrackingDelay", [2.0]),
    ("setMultipleAdjustmentThreshold", [1.0]),
]


class LightroomSession:
    def __init__(self, app_name: str, app_version: str, port: Optional[int] = None,
                 state_file: Optional[Path] = None, retry_delay: float = 2.0, denied_delay: float = 30.0,
                 on_connect: Optional[Callable[[], Awaitable[None]]] = None,
                 on_disconnect: Optional[Callable[[], None]] = None,
                 frame_log: Optional[Path] = None):
        self.app_name, self.app_version = app_name, app_version
        self.port, self.state_file, self.frame_log = port, state_file, frame_log
        self.retry_delay = retry_delay
        # A refused registration (e.g. the user clicked Deny) waits longer, so the Allow
        # dialog doesn't pop up again every couple of seconds.
        self.denied_delay = denied_delay
        self.on_connect, self.on_disconnect = on_connect, on_disconnect
        self._lr: Optional[Lightroom] = None

    @property
    def lr(self) -> Optional[Lightroom]:
        """The live, registered client, or None."""
        return self._lr if self._lr is not None and self._lr.connected else None

    @property
    def connected(self) -> bool:
        return self.lr is not None

    async def call(self, message: str, *params: Any, **kw: Any) -> Any:
        lr = self.lr
        if lr is None:
            raise ConnectionError("Lightroom isn't connected")
        return await lr.call(message, *params, **kw)

    async def run_forever(self) -> None:
        outage_logged = False
        while True:
            lr = Lightroom(self.app_name, self.app_version, frame_log=self.frame_log, state_file=self.state_file)
            delay = self.retry_delay
            try:
                await lr.connect(self.port)
                await lr.register()
                await self._setup(lr)
                self._lr = lr
                outage_logged = False
                log.info("Lightroom connected")
                if self.on_connect is not None:
                    try:
                        await self.on_connect()
                    except Exception:  # a hook failure mustn't take the connection down
                        log.exception("on_connect hook failed")
                await lr.wait_closed()
                log.info("Lightroom connection closed")
            except LightroomError as e:
                log.warning("Lightroom refused registration (%s); retrying in %.0f s", e, self.denied_delay)
                delay = self.denied_delay
            except (OSError, asyncio.TimeoutError, ConnectionError, WebSocketException) as e:
                if not outage_logged:
                    log.info("Lightroom not reachable (%s); retrying every %.1f s", e, self.retry_delay)
                    outage_logged = True
            finally:
                was_connected = self._lr is lr
                self._lr = None
                await lr.close()
                if was_connected and self.on_disconnect is not None:
                    self.on_disconnect()
            await asyncio.sleep(delay)

    @staticmethod
    async def _setup(lr: Lightroom) -> None:
        for message, params in SETUP_CALLS:
            try:
                await lr.call(message, *params)
            except LightroomError as e:  # nice-to-have settings; never block the connection
                log.warning("%s failed: %s", message, e)
