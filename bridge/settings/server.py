"""The settings page: served by the bridge on 127.0.0.1, changes over a token-protected WebSocket.

Security (see the design): any web page open in the browser can send requests to 127.0.0.1, so
- requests are only answered when their Host header is this server's own address (DNS rebinding),
- the WebSocket accepts only the page's own Origin,
- and its first message must carry the random token embedded in the page, which other sites
  can't read (same-origin policy). Changes only ever touch preset slots P1–P8.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets
from http import HTTPStatus
from pathlib import Path
from typing import Optional, Set

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response

from bridge.hardware import Event, Press
from bridge.lightroom import LightroomError
from bridge.mapping import MappingNotWritable

log = logging.getLogger("settings")


class _QuietHandshakes(logging.Filter):
    """websockets logs every failed handshake as an ERROR with a traceback. Those are all the other
    side's doing: a browser pre-opening a connection it never uses, a port scan, a request that
    isn't a WebSocket. They're noted at debug level instead, so the log keeps its useful lines."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage() == "opening handshake failed":
            log.debug("a connection to the settings page didn't complete its handshake (%s)",
                      record.exc_info[1] if record.exc_info else "?")
            return False
        return True


_ws_log = logging.getLogger("settings.websocket")  # this server's websockets logger
_ws_log.setLevel(logging.WARNING)                   # like the bridge's other websockets logging
_ws_log.addFilter(_QuietHandshakes())

STATIC = Path(__file__).resolve().parent / "static"
SLOTS = [f"p{i}" for i in range(1, 9)]
FILES = {"/": ("index.html", "text/html; charset=utf-8"),
         "/app.js": ("app.js", "text/javascript; charset=utf-8"),
         "/app.css": ("app.css", "text/css; charset=utf-8")}


class SettingsServer:
    def __init__(self, port: int, mapping, dispatcher, catalog, token: Optional[str] = None):
        self.port, self.mapping, self.dispatcher, self.catalog = port, mapping, dispatcher, catalog
        self.token = token or secrets.token_urlsafe(24)
        self.url = f"http://127.0.0.1:{port}/"
        self._hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self._origins = [f"http://127.0.0.1:{port}", f"http://localhost:{port}"]
        self._clients: Set = set()

    # ---- serving ------------------------------------------------------------
    async def serve(self) -> None:
        """Run forever. If the port is taken, log it and carry on without the page."""
        try:
            async with serve(self._session, "127.0.0.1", self.port, process_request=self._http,
                             origins=self._origins, max_size=2 ** 20, logger=_ws_log):
                log.info("settings page: %s", self.url)
                await asyncio.Future()
        except OSError as e:
            log.error("settings page unavailable: port %d is in use (%s); the bridge keeps running without it",
                      self.port, e)
            await asyncio.Future()

    def _http(self, connection, request) -> Optional[Response]:
        if request.headers.get("Host", "") not in self._hosts:
            return connection.respond(HTTPStatus.FORBIDDEN, "Forbidden\n")
        if request.path == "/ws":
            # Checked here as well as by websockets, which would log every refusal as an ERROR with a
            # traceback: any web page the user visits could then fill the bridge log.
            if request.headers.get("Origin") not in self._origins:
                return connection.respond(HTTPStatus.FORBIDDEN, "Forbidden\n")
            return None  # the WebSocket handshake continues
        if request.path not in FILES:
            return connection.respond(HTTPStatus.NOT_FOUND, "Not found\n")
        name, content_type = FILES[request.path]
        body = (STATIC / name).read_text()
        if name == "index.html":
            body = body.replace("__TOKEN__", self.token)
        ws_sources = " ".join(f"ws://{h}" for h in sorted(self._hosts))
        headers = Headers([
            ("Content-Type", content_type),
            ("Cache-Control", "no-store"),
            ("Content-Security-Policy", f"default-src 'self'; connect-src {ws_sources}; frame-ancestors 'none'"),
            ("X-Frame-Options", "DENY"),
            ("Referrer-Policy", "no-referrer"),
        ])
        return Response(200, "OK", headers, body.encode())

    # ---- the page's WebSocket -------------------------------------------------
    async def _session(self, ws) -> None:
        try:
            hello = json.loads(await ws.recv())
        except (ValueError, ConnectionClosed):
            hello = None
        token = hello.get("token") if isinstance(hello, dict) and hello.get("op") == "hello" else None
        # Compared as bytes: compare_digest refuses str with non-ASCII characters.
        if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self.token.encode()):
            await ws.close(1008, "not allowed")  # the page reloads on 1008 (e.g. a token from before a restart)
            return
        self._clients.add(ws)
        try:
            await ws.send(json.dumps(self._state()))
            async for raw in ws:
                await self._handle(ws, raw)
        except ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)

    async def _handle(self, ws, raw) -> None:
        try:
            msg = json.loads(raw)
            op = msg.get("op")
        except (ValueError, AttributeError):
            return await self._error(ws, "couldn't read that request")
        if op == "presets":
            async def progress(done: int, total: int) -> None:
                # to every tab: a tab that asks while another's load runs shares that load
                await self._broadcast({"type": "progress", "done": done, "total": total})
            try:
                items = await self.catalog.items(refresh=bool(msg.get("refresh")), progress=progress)
            except ConnectionError:
                return await self._error(ws, "Lightroom isn't connected; open Lightroom to load your presets")
            except (LightroomError, asyncio.TimeoutError) as e:
                return await self._error(ws, f"Lightroom didn't list its presets ({e})")
            return await ws.send(json.dumps({"type": "presets", "items": [list(i) for i in items]}))
        if op not in ("assign", "clear"):
            return await self._error(ws, f"unknown request {op!r}")
        slot = msg.get("slot")
        if slot not in SLOTS:
            return await self._error(ws, "only the P1–P8 preset slots can be changed here")
        if op == "assign":
            pid, name = msg.get("id"), msg.get("name")
            if not isinstance(pid, str) or not isinstance(name, str):
                return await self._error(ws, "a preset needs an id and a name")
            action = {"type": "preset", "id": pid, "name": name}
        else:
            action = {"type": "preset", "id": None, "name": None}
        try:
            self.mapping.set_press_action(slot, action)
        except MappingNotWritable as e:
            return await self._error(ws, str(e))
        except OSError as e:  # e.g. a full disk; the file and the bridge's layout are unchanged
            name = self.mapping.path.name if self.mapping.path else "mapping.json"
            return await self._error(ws, f"couldn't save {name}: {e.strerror or e}")
        log.info("%s: %s", slot, f"preset {action['name']!r}" if action["id"] else "cleared")
        await self.dispatcher.reload_presets()
        await self._broadcast(self._state())

    async def broadcast_state(self) -> None:
        """Tell every open page the current state (e.g. Lightroom came or went)."""
        await self._broadcast(self._state())

    def _state(self) -> dict:
        return {"type": "state", "slots": [self.dispatcher.slot_status(s) for s in SLOTS],
                "writable": self.mapping.writable, "lightroom": bool(self.dispatcher.session.connected)}

    async def _error(self, ws, message: str) -> None:
        await ws.send(json.dumps({"type": "error", "message": message}))

    async def _broadcast(self, msg: dict) -> None:
        text = json.dumps(msg)
        for ws in list(self._clients):
            try:
                await ws.send(text)
            except ConnectionClosed:
                self._clients.discard(ws)

    # ---- device input ---------------------------------------------------------
    def on_event(self, event: Event) -> None:
        """Highlight a preset slot on the page when its button is pressed on the device."""
        if isinstance(event, Press) and event.control in SLOTS and self._clients:
            asyncio.get_running_loop().create_task(self._broadcast({"type": "pressed", "slot": event.control}))
