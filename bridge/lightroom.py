"""Async client for the Lightroom (cloud) Controller API over WebSocket.

Protocol (docs/adobe/LrControllerAPI_10.0_Setup.html):
  request  {"requestId": <uuid>, "object": <handle|null>, "message": <op>, "params": [...]}
  response {"requestId": <same>, "success": <bool>, "response": ...}
One request may get several responses (observers), so replies are routed by requestId:
the first one resolves the awaiting call, later ones go to an optional listener.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

import websockets

from bridge import platform

log = logging.getLogger("lightroom")

DEFAULT_PORT = 7682


class LightroomError(Exception):
    """Lightroom answered with success: false (the full reply is in .reply)."""

    def __init__(self, reply: dict):
        super().__init__(f"{reply.get('response')!r}")
        self.reply = reply


def lightroom_port(path: Optional[Path] = None) -> int:
    """The port Lightroom actually listens on (it falls back if 7682 is busy)."""
    if path is None:
        path = platform.current().lightroom_connections_json()
    try:
        return int(json.loads(path.read_text())["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_PORT


class Lightroom:
    def __init__(self, app_name: str, app_version: str, frame_log: Optional[Path] = None,
                 state_file: Optional[Path] = None):
        self.app_name, self.app_version = app_name, app_version
        self.frame_log = frame_log
        # The client GUID lets this app connect without the Allow dialog, so it lives in the
        # per-user state dir (outside the repo and outside iCloud), never in the project.
        self.state_file = state_file or platform.current().state_dir() / "client.json"
        self.ws = None
        self._pending: dict[str, asyncio.Future] = {}
        self._listeners: dict[str, Callable[[dict], None]] = {}
        self._redact: set[str] = set()
        self._register_rids: set[str] = set()
        self._reader: Optional[asyncio.Task] = None

    # ---- connection -------------------------------------------------------
    async def connect(self, port: Optional[int] = None) -> None:
        url = f"ws://127.0.0.1:{port or lightroom_port()}"
        self.ws = await websockets.connect(url, max_size=None)  # renderImage can be large
        self._reader = asyncio.create_task(self._read_loop())
        log.info("connected to %s", url)

    @property
    def connected(self) -> bool:
        """True while the socket is open and replies are being read."""
        return self._reader is not None and not self._reader.done()

    async def wait_closed(self) -> None:
        """Return once the connection has ended, for whatever reason."""
        if self._reader is not None:
            await asyncio.gather(self._reader, return_exceptions=True)

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()
        if self._reader is not None:
            await asyncio.gather(self._reader, return_exceptions=True)

    async def _read_loop(self) -> None:
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    self._log_frame("recv", raw)
                    log.warning("non-JSON frame: %r", raw[:200])
                    continue
                rid = msg.get("requestId")
                if rid in self._register_rids:  # learn the GUID before this frame reaches the log
                    guid = _find_guid(msg.get("response"))
                    if guid:
                        self._redact.add(guid)
                self._log_frame("recv", raw)
                fut = self._pending.pop(rid, None)
                if fut is not None and not fut.done():
                    fut.set_result(msg)
                elif rid in self._listeners:
                    self._listeners[rid](msg)
                else:
                    log.info("unrouted frame: %s", msg)
        finally:
            err = ConnectionError("Lightroom connection closed")
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(err)
            self._pending.clear()

    # ---- requests ---------------------------------------------------------
    async def request(self, message: str, *params: Any, obj: Optional[str] = None,
                      timeout: float = 10, listener: Optional[Callable[[dict], None]] = None) -> dict:
        """Send one message; return the first reply. Later replies go to `listener`."""
        rid = str(uuid.uuid4())
        frame = {"requestId": rid, "object": obj, "message": message, "params": list(params)}
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        if message == "register":
            self._register_rids.add(rid)
        if listener is not None:
            self._listeners[rid] = listener
        await self.ws.send(json.dumps(frame))
        self._log_frame("send", frame)
        try:
            reply = await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(rid, None)
        if not reply.get("success"):
            raise LightroomError(reply)
        return reply

    async def call(self, message: str, *params: Any, **kw: Any) -> Any:
        """Like request(), but returns only the reply's "response" payload."""
        return (await self.request(message, *params, **kw)).get("response")

    # ---- registration -----------------------------------------------------
    async def register(self, timeout: float = 120) -> Any:
        """First call on every connection. Without a saved GUID, Lightroom shows an
        Allow dialog, so the timeout is long. Saves the GUID it hands back."""
        state = _load_state(self.state_file)
        guid = state.get("clientGUID")
        if guid:
            self._redact.add(guid)
        params = [self.app_name, self.app_version] + ([guid] if guid else [])
        reply = await self.request("register", *params, timeout=timeout)
        resp = reply.get("response")
        new_guid = _find_guid(resp)
        if new_guid:
            self._redact.add(new_guid)
            if new_guid != guid:
                _save_state(self.state_file, {**state, "clientGUID": new_guid})
                log.info("saved new client GUID to %s", self.state_file)
        else:
            log.warning("couldn't find a client GUID in the register reply; nothing saved")
        return resp

    # ---- frame log (discovery aid) ----------------------------------------
    def _log_frame(self, direction: str, frame: Any) -> None:
        if self.frame_log is None:
            return
        text = frame if isinstance(frame, str) else json.dumps(frame)
        for secret in self._redact:
            text = text.replace(secret, "<clientGUID>")
        with self.frame_log.open("a") as fh:
            fh.write(json.dumps({"dir": direction, "frame": text}) + "\n")


def _find_guid(resp: Any) -> Optional[str]:
    """The register reply's shape isn't documented: accept a dict with a *guid* key,
    or a list whose first item is the GUID."""
    if isinstance(resp, dict):
        for key, val in resp.items():
            if "guid" in key.lower() and isinstance(val, str):
                return val
    if isinstance(resp, (list, tuple)) and resp and isinstance(resp[0], str):
        return resp[0]
    return None


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))
    path.chmod(0o600)
