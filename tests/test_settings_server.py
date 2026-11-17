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
from bridge.hardware import Press, Release, Turn
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
            pages = [await rig.http_get(p) for p in ("/", "/app.js", "/app.css", "/remap.js")]
        return pages
    pages = asyncio.run(main())
    for status, _, body in pages:
        assert status == 200
        urls = re.findall(r"https?://[^\s\"')]+", body)
        assert all(re.match(r"https?://(127\.0\.0\.1|localhost)[:/]", u) for u in urls), urls
    html, js, _, remap = (body for _, _, body in pages)
    assert 'src="/app.js"' in html and 'href="/app.css"' in html
    assert html.index('src="/app.js"') < html.index('src="/remap.js"')   # remap.js uses app.js's helpers
    assert "<script>" not in html                 # no inline script (the CSP forbids it)
    assert "innerHTML" not in js and "innerHTML" not in remap   # names are shown as text, never as HTML


def test_serves_remap_js(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            return await rig.http_get("/remap.js")
    status, headers, body = asyncio.run(main())
    assert status == 200 and headers["Content-Type"].startswith("text/javascript")
    assert "Remap" in body


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
    # Milestone 4: any control's use is announced (the Presets tab flashes P slots).
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as ws:
                await rig.hello(ws)
                await rig.next(ws, "layout")
                rig.server.on_event(Press("p2"))
                assert await rig.next(ws, "used") == {"type": "used", "control": "p2", "layer": "normal", "slot": "press"}
    asyncio.run(main())


def test_foreign_origin_refused_quietly(tmp_path, caplog):
    # Review: websockets logged every refused origin at ERROR with a traceback, so any web page
    # the user visited could fill the bridge log.
    async def main():
        async with Rig(tmp_path) as rig:
            for origin in ("http://evil.example", None):
                with pytest.raises(InvalidStatus) as refused:
                    async with websockets.connect(f"ws://127.0.0.1:{rig.port}/ws", origin=origin):
                        pass
                assert refused.value.response.status_code == 403
    with caplog.at_level(logging.WARNING):
        asyncio.run(main())
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_localhost_address_also_works(tmp_path):
    # Guards the bridge's own Origin check: the page may be opened as localhost as well as 127.0.0.1.
    async def main():
        async with Rig(tmp_path) as rig:
            url = f"ws://localhost:{rig.port}/ws"
            async with websockets.connect(url, origin=f"http://localhost:{rig.port}") as ws:
                assert (await rig.hello(ws))["type"] == "state"
    asyncio.run(main())


def test_non_ascii_token_refused_cleanly(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as ws:
                await ws.send(json.dumps({"op": "hello", "token": "pâté"}))
                with pytest.raises(ConnectionClosed) as closed:
                    await asyncio.wait_for(ws.recv(), 3)
                assert closed.value.rcvd.code == 1008
    asyncio.run(main())


def test_save_error_reported(tmp_path, monkeypatch):
    async def main():
        async with Rig(tmp_path) as rig:
            def full_disk(slot, action):
                raise OSError("No space left on device")
            monkeypatch.setattr(rig.mapping, "set_press_action", full_disk)
            async with rig.connect() as ws:
                await rig.hello(ws)
                await ws.send(json.dumps({"op": "assign", "slot": "p1", "id": "ID-WARM", "name": "Warm"}))
                msg = await rig.next(ws, "error")
                assert "couldn't save" in msg["message"] and "No space" in msg["message"]
                await ws.send(json.dumps({"op": "presets"}))   # the connection is still fine
                await rig.next(ws, "presets")
    asyncio.run(main())


def test_state_broadcast_when_lightroom_changes(tmp_path):
    # Review: the page was never told when Lightroom came or went.
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as a, rig.connect() as b:
                assert (await rig.hello(a))["lightroom"] is True
                await rig.hello(b)
                rig.session.connected = False
                await rig.server.broadcast_state()
                assert (await rig.next(a, "state"))["lightroom"] is False
                assert (await rig.next(b, "state"))["lightroom"] is False
    asyncio.run(main())


def test_progress_reaches_every_tab(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            rig.catalog.chunk = 1
            async with rig.connect() as a, rig.connect() as b:
                await rig.hello(a)
                await rig.hello(b)
                await a.send(json.dumps({"op": "presets"}))
                assert (await rig.next(b, "progress"))["total"] == 3   # the other tab sees the load too
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


# ---- milestone 4: the Buttons & dials tab ------------------------------------------
def row_of(layout, control):
    return next(r for r in layout["rows"] if r["control"] == control)


def set_op(control, layer, slot, choice):
    return json.dumps({"op": "set", "control": control, "layer": layer, "slot": slot, "choice": choice})


def test_connect_sends_catalog_and_layout(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as ws:
                await rig.hello(ws)
                catalog = json.loads(await asyncio.wait_for(ws.recv(), 3))
                layout = json.loads(await asyncio.wait_for(ws.recv(), 3))
                assert catalog["type"] == "catalog" and any(c["id"] == "rating_3" for c in catalog["commands"])
                assert layout["type"] == "layout" and row_of(layout, "c3")["fn"]["press"] is None
    asyncio.run(main())


def test_set_fn_command_saves_and_broadcasts(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as a, rig.connect() as b:
                await rig.hello(a)
                await rig.hello(b)
                await rig.next(b, "layout")
                await a.send(set_op("c3", "fn", "press", {"kind": "command", "id": "rating_3"}))
                row = row_of(await rig.next(b, "layout"), "c3")
                assert row["fn"]["press"]["choice"] == {"kind": "command", "id": "rating_3"}
                assert rig.mapping.press_action("c3", fn=True)["message"] == "rating3"
    asyncio.run(main())


def test_set_same_clears_fn_and_slider_pair_on_dials(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as ws:
                await rig.hello(ws)
                await rig.next(ws, "layout")
                await ws.send(set_op("c3", "fn", "press", {"kind": "command", "id": "rating_3"}))
                await rig.next(ws, "layout")
                await ws.send(set_op("c3", "fn", "press", {"kind": "same"}))
                assert row_of(await rig.next(ws, "layout"), "c3")["fn"]["press"] is None
                await ws.send(set_op("exposure", "fn", "turn", {"kind": "slider", "param": "Contrast2012"}))
                await rig.next(ws, "layout")
                await ws.send(set_op("d1", "normal", "turn", {"kind": "pair", "id": "pair_photo"}))
                await rig.next(ws, "layout")
        m = Mapping.load(rig.path)
        assert m.press_action("c3", fn=True) == m.press_action("c3")
        assert m.turn_action("exposure", fn=True) == {"type": "adjust", "param": "Contrast2012"}
        assert m.turn_action("d1")["type"] == "step" and m.turn_action("d1")["cw"]["message"] == "nextPhoto"
    asyncio.run(main())


def test_set_refuses_what_the_page_cannot_change(tmp_path):
    # Review Focus 4: a stale or hostile page message is refused; the file doesn't change.
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as ws:
                await rig.hello(ws)
                await rig.next(ws, "layout")
                before = rig.path.read_bytes()
                rating = {"kind": "command", "id": "rating_3"}
                refused = [
                    set_op("fn", "normal", "press", rating),
                    set_op("clr_bw", "normal", "press", rating),
                    set_op("clr_bw", "fn", "press", rating),
                    set_op("export", "fn", "press", rating),
                    set_op("p1", "normal", "press", rating),
                    set_op("c3", "normal", "press", {"kind": "key", "key": "shift"}),
                    set_op("c3", "fn", "press", {"kind": "shortcut", "mac": ["cmd", "q"], "windows": ["alt", "f4"]}),
                    set_op("c3", "normal", "press", {"kind": "command", "id": "no_such_command"}),
                    set_op("c3", "normal", "press", {"kind": "slider", "param": "Exposure2012"}),
                    set_op("c3", "normal", "turn", rating),
                    set_op("c3", "normal", "press", {"kind": "same"}),
                    set_op("nope", "normal", "press", rating),
                    set_op("c3", "shift", "press", rating),
                    json.dumps({"op": "reset", "control": "fn"}),
                    # wrongly typed fields (review): refused, the connection stays up
                    set_op([], "normal", "press", rating),
                    set_op({}, "normal", "press", rating),
                    set_op("c3", [], "press", rating),
                    set_op("c3", "normal", {}, rating),
                    set_op("c3", "normal", "press", {"kind": []}),
                    set_op("c3", "normal", "press", {"kind": "command", "id": []}),
                    set_op("exposure", "normal", "turn", {"kind": "slider", "param": {}}),
                    set_op("c3", "normal", "press", []),
                    json.dumps({"op": "reset", "control": {}}),
                ]
                for raw in refused:
                    await ws.send(raw)
                    assert (await rig.next(ws, "error"))["message"], raw
                    assert rig.path.read_bytes() == before, raw
                await ws.send(set_op("c3", "fn", "press", rating))           # the connection still works
                assert row_of(await rig.next(ws, "layout"), "c3")["fn"]["press"]["label"]
    asyncio.run(main())


def test_reset_and_restore_defaults_keep_presets(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            rig.mapping.set_press_action("p1", {"type": "preset", "id": "ID-WARM", "name": "Warm"})
            rig.mapping.set_action("p1", "press", RATING3, layer="fn")
            rig.mapping.set_action("c3", "press", RATING3, layer="fn")
            async with rig.connect() as ws:
                await rig.hello(ws)
                await rig.next(ws, "layout")
                await ws.send(json.dumps({"op": "reset", "control": "p1"}))
                await rig.next(ws, "layout")
                assert rig.mapping.press_action("p1")["id"] == "ID-WARM" and rig.mapping.fn_action("p1", "press") is None
                await ws.send(json.dumps({"op": "restore_defaults"}))
                assert row_of(await rig.next(ws, "layout"), "c3")["fn"]["press"] is None
                assert slot(await rig.next(ws, "state"), "p1")["id"] == "ID-WARM"
        m = Mapping.load(rig.path)
        assert m.press_action("p1")["name"] == "Warm" and m.fn_action("c3", "press") is None
    asyncio.run(main())


def test_restore_refused_when_mapping_unreadable(tmp_path):
    async def main():
        async with Rig(tmp_path, mapping_text="{not json") as rig:
            async with rig.connect() as ws:
                await rig.hello(ws)
                await ws.send(json.dumps({"op": "restore_defaults"}))
                assert "couldn't be read" in (await rig.next(ws, "error"))["message"]
            assert rig.path.read_text() == "{not json"
    asyncio.run(main())


def test_device_use_and_fn_are_broadcast(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as ws:
                await rig.hello(ws)
                await rig.next(ws, "layout")
                await rig.dispatcher.handle(Press("fn"))
                rig.server.on_event(Press("fn"))
                assert await rig.next(ws, "fn") == {"type": "fn", "held": True}
                await rig.dispatcher.handle(Press("c3"))
                rig.server.on_event(Press("c3"))
                assert await rig.next(ws, "used") == {"type": "used", "control": "c3", "layer": "fn", "slot": "press"}
                await rig.dispatcher.handle(Release("fn"))
                rig.server.on_event(Release("fn"))
                assert await rig.next(ws, "fn") == {"type": "fn", "held": False}
    asyncio.run(main())


def test_turns_are_throttled_for_the_page(tmp_path):
    # Review Focus 5: a dial sends up to ~150 messages a second; the page gets at most 4 a second.
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as ws:
                await rig.hello(ws)
                await rig.next(ws, "layout")
                for _ in range(3):
                    rig.server.on_event(Turn("exposure", 1))
                used = await rig.next(ws, "used")
                assert (used["control"], used["slot"]) == ("exposure", "turn")   # a turn selects the Turn slot
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(ws.recv(), 0.3)
    asyncio.run(main())


def test_other_action_on_a_p_button_shows_its_label(tmp_path):
    from bridge.commands import CommandCatalog
    text = json.dumps({"version": 1, "controls": {"p8": {"press": RATING3}}})
    async def main():
        async with Rig(tmp_path, mapping_text=text) as rig:
            async with rig.connect() as ws:
                return slot(await rig.hello(ws), "p8")
    p8 = asyncio.run(main())
    assert p8["status"] == "other" and p8["label"] == CommandCatalog.load().describe(RATING3)["label"]


RATING3 = {"type": "call", "message": "rating3", "args": []}


def test_five_mode_in_state_and_used(tmp_path):
    async def main():
        async with Rig(tmp_path) as rig:
            async with rig.connect() as ws:
                assert (await rig.hello(ws))["five_mode"] == "ratings"
                await rig.next(ws, "layout")
                await rig.dispatcher.handle(Press("shift"))
                rig.server.on_event(Press("shift"))
                assert (await rig.next(ws, "used"))["control"] == "ratings_1"
                before = rig.path.read_bytes()
                await ws.send(set_op("col", "normal", "press", {"kind": "command", "id": "rating_3"}))
                await rig.next(ws, "error")
                assert rig.path.read_bytes() == before
                await ws.send(set_op("colours_2", "normal", "press", {"kind": "command", "id": "rating_3"}))
                assert row_of(await rig.next(ws, "layout"), "colours_2")["normal"]["press"]["choice"]["id"] == "rating_3"
    asyncio.run(main())


def test_odd_hand_edits_dont_break_the_page(tmp_path):
    # Review: one odd action in mapping.json made every page connection fail.
    text = json.dumps({"version": 1, "controls": {
        "c5": {"press": {"type": "shortcut", "mac": ["cmd", 5], "windows": ["ctrl", 5]}},
        "c6": {"press": {"type": "call", "message": "resetToDefault", "args": [[1]]}},
        "c4": {"press": {"type": "call", "message": "resetToDefault", "args": [{"a": 1}]}}}})
    async def main():
        async with Rig(tmp_path, mapping_text=text) as rig:
            async with rig.connect() as ws:
                await rig.hello(ws)
                layout = await rig.next(ws, "layout")
                assert row_of(layout, "c5")["normal"]["press"]["label"] == "Nothing"
                assert row_of(layout, "c6")["normal"]["press"]["label"]
                await ws.send(set_op("c3", "fn", "press", {"kind": "command", "id": "rating_3"}))
                await rig.next(ws, "layout")                 # still working
    asyncio.run(main())
