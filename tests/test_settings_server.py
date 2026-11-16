"""The settings page server: real websockets client ↔ real server, mapping and dispatcher; fake Lightroom."""
from __future__ import annotations

import asyncio
import http.client
import json
import logging
import socket

import pytest
import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

from bridge.actions import Dispatcher
from bridge.hardware import Press
from bridge.mapping import Mapping
from bridge.presets import PresetCatalog
from bridge.settings.server import SettingsServer
from tests.test_actions import FakeSession, SpyDials

TOKEN = "T0KEN-for-tests"


class Session(FakeSession):
    async def call(self, message, *params):
        if not self.connected:
            raise ConnectionError("Lightroom isn't connected")
        return await super().call(message, *params)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Rig:
    def __init__(self, tmp_path, mapping_text=None, connected=True):
        path = tmp_path / "m.json"
        if mapping_text is not None:
            path.write_text(mapping_text)
        self.path = path
        self.mapping = Mapping.load(path)
        self.session = Session()
        self.session.connected = connected
        self.catalog = PresetCatalog(self.session)
        self.dispatcher = Dispatcher(self.mapping, self.session, SpyDials(), catalog=self.catalog)
        self.port = free_port()
        self.server = SettingsServer(self.port, self.mapping, self.dispatcher, self.catalog, token=TOKEN)
        self.origin = f"http://127.0.0.1:{self.port}"

    async def __aenter__(self):
        self.task = asyncio.create_task(self.server.serve())
        for _ in range(200):
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.1):
                    break
            except OSError:
                await asyncio.sleep(0.01)
        return self

    async def __aexit__(self, *exc):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)

    def connect(self, origin=None):
        return websockets.connect(f"ws://127.0.0.1:{self.port}/ws", origin=origin or self.origin)

    async def hello(self, ws, token=TOKEN):
        await ws.send(json.dumps({"op": "hello", "token": token}))
        return await self.next(ws, "state")

    @staticmethod
    async def next(ws, kind):
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
            if msg["type"] == kind:
                return msg

    async def http_get(self, path, host=None):
        def get():
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
            conn.request("GET", path, headers={"Host": host or f"127.0.0.1:{self.port}"})
            r = conn.getresponse()
            return r.status, dict(r.getheaders()), r.read().decode()
        return await asyncio.get_running_loop().run_in_executor(None, get)


def slot(state, name):
    return next(s for s in state["slots"] if s["slot"] == name)


def test_serves_page_with_token(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            status, headers, body = await rig.http_get("/")
            assert status == 200 and headers["Content-Type"].startswith("text/html")
            assert TOKEN in body
            assert "default-src 'self'" in headers["Content-Security-Policy"]
            assert (await rig.http_get("/app.js"))[0] == 200
            assert (await rig.http_get("/nope"))[0] == 404
    asyncio.run(main())


def test_page_assets_are_local(tmp_path):
    # The page must work offline and leak nothing: no CDN, fonts or analytics.
    import re

    async def main():
        async with Rig(tmp_path) as rig:
            pages = [await rig.http_get(p) for p in ("/", "/app.js", "/app.css")]
        return pages
    pages = asyncio.run(main())
    for status, _, body in pages:
        assert status == 200
        urls = re.findall(r"https?://[^\s\"')]+", body)
        assert all(re.match(r"https?://(127\.0\.0\.1|localhost)[:/]", u) for u in urls), urls
    html, js, _ = (body for _, _, body in pages)
    assert 'src="/app.js"' in html and 'href="/app.css"' in html
    assert "<script>" not in html                 # no inline script (the CSP forbids it)
    assert "innerHTML" not in js                  # preset names are shown as text, never as HTML


def test_wrong_host_refused(tmp_path):
    # DNS rebinding: a malicious site makes its own hostname resolve to 127.0.0.1.
    async def main():
        async with Rig(tmp_path) as rig:
            for path in ("/", "/app.js", "/ws"):
                status, _, body = await rig.http_get(path, host=f"evil.example:{rig.port}")
                assert status == 403 and TOKEN not in body
    asyncio.run(main())


def test_foreign_origin_refused(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            with pytest.raises(InvalidStatus):
                async with rig.connect(origin="http://evil.example"):
                    pass
    asyncio.run(main())


def test_bad_token_closed(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as ws:
                await ws.send(json.dumps({"op": "hello", "token": "guess"}))
                with pytest.raises(ConnectionClosed) as closed:
                    await asyncio.wait_for(ws.recv(), 3)
                assert closed.value.rcvd.code == 1008
    asyncio.run(main())


def test_presets_list(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as ws:
                state = await rig.hello(ws)
                assert [s["slot"] for s in state["slots"]] == [f"p{i}" for i in range(1, 9)]
                await ws.send(json.dumps({"op": "presets"}))
                msg = await rig.next(ws, "presets")
                assert ["ID-WARM", "Warm"] in msg["items"] and len(msg["items"]) == 3
    asyncio.run(main())


def test_presets_progress_then_list(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            rig.catalog.chunk = 1                       # 3 fake presets → 3 progress steps
            async with rig.connect() as ws:
                await rig.hello(ws)
                await ws.send(json.dumps({"op": "presets"}))
                progress = []
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
                    if msg["type"] == "progress":
                        progress.append((msg["done"], msg["total"]))
                    elif msg["type"] == "presets":
                        break
                assert progress == [(1, 3), (2, 3), (3, 3)]
    asyncio.run(main())


def test_refresh_refetches_names(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as ws:
                await rig.hello(ws)
                await ws.send(json.dumps({"op": "presets"}))
                await rig.next(ws, "presets")
                before = [m for m, _ in rig.session.calls].count("getPresetName")
                await ws.send(json.dumps({"op": "presets", "refresh": True}))
                await rig.next(ws, "presets")
                assert [m for m, _ in rig.session.calls].count("getPresetName") == before + 3
    asyncio.run(main())


def test_presets_while_lightroom_down(tmp_path):
    async def main():
        async with Rig(tmp_path, connected=False) as rig:
            async with rig.connect() as ws:
                state = await rig.hello(ws)
                assert state["lightroom"] is False
                await ws.send(json.dumps({"op": "presets"}))
                msg = await rig.next(ws, "error")
                assert "Lightroom" in msg["message"]
    asyncio.run(main())


def test_assign_by_id(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as ws:
                await rig.hello(ws)
                # "Heavy" is ambiguous by name, but the page assigns by id
                await ws.send(json.dumps({"op": "assign", "slot": "p3", "id": "ID-H2", "name": "Heavy"}))
                state = await rig.next(ws, "state")
                assert slot(state, "p3") == {"slot": "p3", "id": "ID-H2", "name": "Heavy", "status": "ok"}
            assert json.loads(rig.path.read_text())["controls"]["p3"]["press"]["id"] == "ID-H2"
            await rig.dispatcher.handle(Press("p3"))
            assert rig.session.calls[-1] == ("applyPreset", ["ID-H2"])
    asyncio.run(main())


def test_clear_slot(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as ws:
                await rig.hello(ws)
                await ws.send(json.dumps({"op": "assign", "slot": "p1", "id": "ID-WARM", "name": "Warm"}))
                await rig.next(ws, "state")
                await ws.send(json.dumps({"op": "clear", "slot": "p1"}))
                state = await rig.next(ws, "state")
                assert slot(state, "p1")["status"] == "empty"
            assert json.loads(rig.path.read_text())["controls"]["p1"]["press"] == \
                {"type": "preset", "id": None, "name": None}
    asyncio.run(main())


def test_invalid_assign_rejected(tmp_path):
    # The page may only change preset slots, and only to well-formed presets.
    async def main():
        async with Rig(tmp_path) as rig:
            before = rig.path.read_text()
            async with rig.connect() as ws:
                await rig.hello(ws)
                for bad in ({"op": "assign", "slot": "c1", "id": "ID-WARM", "name": "Warm"},
                            {"op": "assign", "slot": "p1", "id": 5, "name": "Warm"},
                            {"op": "launch_missiles"}):
                    await ws.send(json.dumps(bad))
                    await rig.next(ws, "error")
            assert rig.path.read_text() == before
    asyncio.run(main())


def test_assign_refused_when_mapping_unreadable(tmp_path):
    async def main():
        async with Rig(tmp_path, mapping_text="{not json") as rig:
            async with rig.connect() as ws:
                state = await rig.hello(ws)
                assert state["writable"] is False
                await ws.send(json.dumps({"op": "assign", "slot": "p1", "id": "ID-WARM", "name": "Warm"}))
                msg = await rig.next(ws, "error")
                assert "couldn't be read" in msg["message"]
            assert rig.path.read_text() == "{not json"
    asyncio.run(main())


def test_change_broadcast_to_all_tabs(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as a, rig.connect() as b:
                await rig.hello(a)
                await rig.hello(b)
                await a.send(json.dumps({"op": "assign", "slot": "p2", "id": "ID-WARM", "name": "Warm"}))
                state_b = await rig.next(b, "state")
                assert slot(state_b, "p2")["id"] == "ID-WARM"
    asyncio.run(main())


def test_device_press_highlights_slot(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as ws:
                await rig.hello(ws)
                rig.server.on_event(Press("c1"))   # not a preset slot: ignored
                rig.server.on_event(Press("p2"))
                msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
                assert msg == {"type": "pressed", "slot": "p2"}
    asyncio.run(main())


def test_port_busy_does_not_stop_bridge(tmp_path, caplog):
    async def main():
        rig = Rig(tmp_path)
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", rig.port))
        blocker.listen()
        try:
            task = asyncio.create_task(rig.server.serve())
            await asyncio.sleep(0.2)
            assert not task.done()  # never returns or raises: the bridge carries on without the page
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        finally:
            blocker.close()
    with caplog.at_level(logging.ERROR):
        asyncio.run(main())
    assert any("settings page" in r.getMessage() for r in caplog.records)
