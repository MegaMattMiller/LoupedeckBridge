"""The settings page: served by the bridge on 127.0.0.1, changes over a token-protected WebSocket.

Security (see the design): any web page open in the browser can send requests to 127.0.0.1, so
- requests are only answered when their Host header is this server's own address (DNS rebinding),
- the WebSocket accepts only the page's own Origin,
- and its first message must carry the random token embedded in the page, which other sites
  can't read (same-origin policy).
Changes are limited to presets on P1–P8 and to what bridge.commands can make (Lightroom commands,
sliders, command pairs): never keyboard keys or shortcuts, never Fn, clr/bw or Fn + Export.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets
import time
from http import HTTPStatus
from pathlib import Path
from typing import Dict, Optional, Set

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response

from bridge.commands import CommandCatalog
from bridge.hardware import Event, HardwareMap, Press, Release, Turn
from bridge.lightroom import LightroomError
from bridge.mapping import FN_KEY, LAYERS, MappingNotWritable
from bridge.settings import layout

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
USED_INTERVAL = 0.25  # a turning dial re-selects its row on the page at most this often (seconds)
FILES = {"/": ("index.html", "text/html; charset=utf-8"),
         "/app.js": ("app.js", "text/javascript; charset=utf-8"),
         "/app.css": ("app.css", "text/css; charset=utf-8"),
         "/remap.js": ("remap.js", "text/javascript; charset=utf-8")}


class SettingsServer:
    def __init__(self, port: int, mapping, dispatcher, catalog, token: Optional[str] = None,
                 commands: Optional[CommandCatalog] = None, controls: Optional[Dict[str, str]] = None):
        self.port, self.mapping, self.dispatcher, self.catalog = port, mapping, dispatcher, catalog
        self.commands = commands or CommandCatalog.load()
        self.controls = controls or HardwareMap.load().controls
        self._used_at: Dict[str, float] = {}
        self._tasks: Set[asyncio.Task] = set()
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
            await ws.send(json.dumps(self.commands.to_page()))
            await ws.send(json.dumps(self._layout()))
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
        if op in ("set", "reset", "restore_defaults"):
            return await self._remap(ws, op, msg)
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
            return await self._error(ws, self._save_error(e))
        log.info("%s: %s", slot, f"preset {action['name']!r}" if action["id"] else "cleared")
        await self.dispatcher.reload_presets()
        await self._broadcast(self._state())
        await self._broadcast(self._layout())

    async def _remap(self, ws, op: str, msg: dict) -> None:
        """The Buttons & dials tab's changes. Everything is checked here; the page is never trusted."""
        try:
            if op == "restore_defaults":
                self.mapping.restore_defaults(keep_normal_press=SLOTS)  # presets live on the Presets tab
                log.info("restored the default layout (P1–P8 presets kept)")
            else:
                control = msg.get("control")
                if control not in self.controls or control == FN_KEY:
                    raise ValueError(f"there's no control {control!r} to change here")
                if op == "reset":
                    self.mapping.reset_control(control, keep_normal_press=control in SLOTS)
                    log.info("%s: reset to the default", control)
                else:
                    layer, slot = msg.get("layer"), msg.get("slot")
                    if layer not in LAYERS or slot not in layout.slots_of(self.controls[control]):
                        raise ValueError(f"{control} has no {layer} {slot} to change")
                    reason = layout.fixed_reason(control, layer, slot)
                    if reason:
                        raise ValueError(f"that can't be changed here ({reason})")
                    action = self.commands.action_for(msg.get("choice"), slot)
                    if action is None and layer != "fn":
                        raise ValueError("'Same as normal' is only for the Fn layer")
                    self.mapping.set_action(control, slot, action, layer=layer)
                    label = "same as normal" if action is None else self.commands.describe(action)["label"]
                    log.info("%s %s%s: %s", control, slot, " (Fn)" if layer == "fn" else "", label)
        except (MappingNotWritable, ValueError) as e:
            return await self._error(ws, str(e))
        except OSError as e:
            return await self._error(ws, self._save_error(e))
        await self._broadcast(self._layout())
        if op == "restore_defaults":
            await self._broadcast(self._state())

    def _save_error(self, e: OSError) -> str:
        name = self.mapping.path.name if self.mapping.path else "mapping.json"
        return f"couldn't save {name}: {e.strerror or e}"

    def _layout(self) -> dict:
        return {"type": "layout", "rows": layout.rows(self.mapping, self.commands, self.controls)}

    async def broadcast_state(self) -> None:
        """Tell every open page the current state (e.g. Lightroom came or went)."""
        await self._broadcast(self._state())

    def _state(self) -> dict:
        slots = []
        for s in SLOTS:
            status = self.dispatcher.slot_status(s)
            action = self.mapping.press_action(s)
            if action["type"] != "preset":  # e.g. a hand edit: say what it is, not "Empty"
                status = {**status, "status": "other", "label": self.commands.describe(action)["label"]}
            slots.append(status)
        return {"type": "state", "slots": slots,
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
        """Tell the page about device use (called after the dispatcher has handled the event):
        a used control is selected on the page, and Fn switches it to the Fn layer."""
        if not self._clients:
            return
        if event.control == FN_KEY:
            if isinstance(event, (Press, Release)):
                self._later({"type": "fn", "held": isinstance(event, Press)})
            return
        if isinstance(event, Turn):  # up to ~150 a second: re-select at most every USED_INTERVAL
            now = time.monotonic()
            if now - self._used_at.get(event.control, float("-inf")) < USED_INTERVAL:
                return
            self._used_at[event.control] = now
        elif not isinstance(event, Press):
            return
        self._later({"type": "used", "control": event.control,
                     "layer": "fn" if self.dispatcher.fn_held else "normal",
                     "slot": "turn" if isinstance(event, Turn) else "press"})

    def _later(self, msg: dict) -> None:
        task = asyncio.get_running_loop().create_task(self._broadcast(msg))
        self._tasks.add(task)  # keep a reference until it's sent
        task.add_done_callback(self._tasks.discard)
