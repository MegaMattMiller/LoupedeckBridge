"""App.run supervision (review finding 2)."""
from __future__ import annotations

import asyncio
import logging

import pytest

from bridge.app import App
from bridge.hardware import Press


class Midi:
    def __init__(self, events):
        self._events = events

    async def events(self):
        for e in self._events:
            yield e
        await asyncio.Event().wait()


class Idle:
    """Stands in for a background service that runs until cancelled."""

    async def run_forever(self):
        await asyncio.Event().wait()

    async def run(self):
        await asyncio.Event().wait()


class Crashing(Idle):
    async def run(self):
        raise RuntimeError("dial engine bug")


class FlakyDispatcher:
    def __init__(self):
        self.handled = []
        self.released = 0

    async def handle(self, event):
        self.handled.append(event)
        if event == Press("c1"):
            raise ValueError("handler bug")

    def release_all_keys(self):
        self.released += 1


def test_held_keys_released_on_shutdown():
    async def main():
        d = FlakyDispatcher()
        task = asyncio.create_task(App(Midi([]), Idle(), Idle(), d).run())
        await asyncio.sleep(0.02)
        task.cancel()  # Ctrl-C / SIGTERM
        await asyncio.gather(task, return_exceptions=True)
        return d.released
    assert asyncio.run(main()) == 1


def test_held_keys_released_on_device_disconnect(tmp_path):
    from bridge import app as appmod
    from tests.test_actions import FakeKeyboard

    class HookedMidi:
        on_open = None
        on_close = None

        async def events(self):
            await asyncio.Event().wait()
            yield  # pragma: no cover

    kb, midi = FakeKeyboard(), HookedMidi()
    bridge = appmod.build(config_dir=tmp_path, midi=midi, port=1, state_file=tmp_path / "client.json", keyboard=kb)
    asyncio.run(bridge.dispatcher.handle(Press("shift")))
    midi.on_close()  # the Loupedeck was unplugged while Shift was held
    assert kb.events == [("down", "shift"), ("up", "shift")]


def test_handler_error_does_not_stop_input(caplog):
    async def main():
        d = FlakyDispatcher()
        app = App(Midi([Press("c1"), Press("c2")]), Idle(), Idle(), d)
        task = asyncio.create_task(app.run())
        for _ in range(100):
            if len(d.handled) == 2:
                break
            await asyncio.sleep(0.01)
        assert not task.done()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return d.handled
    with caplog.at_level(logging.ERROR):
        handled = asyncio.run(main())
    assert handled == [Press("c1"), Press("c2")]
    assert any("handler bug" in (r.exc_text or "") or "c1" in r.getMessage() for r in caplog.records)


def test_dead_background_task_stops_app_loudly(caplog):
    # A dead dial engine or session must not leave a bridge that silently ignores input.
    async def main():
        app = App(Midi([]), Idle(), Crashing(), FlakyDispatcher())
        await asyncio.wait_for(app.run(), 1)
    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="dial engine bug"):
            asyncio.run(main())
    assert any(r.levelno >= logging.ERROR for r in caplog.records)
