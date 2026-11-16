from __future__ import annotations

import asyncio

import pytest

from bridge.presets import PresetCatalog


class Session:
    """Answers like LightroomSession.call: getPresetIDs → [[ids]], getPresetName → [name]."""

    def __init__(self, n: int):
        self.ids = [f"ID{i}" for i in range(n)]
        self.calls = []
        self.connected = True
        self.in_flight = self.max_in_flight = 0

    async def call(self, message, *params):
        if not self.connected:
            raise ConnectionError("Lightroom isn't connected")
        self.calls.append(message)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0)
        self.in_flight -= 1
        if message == "getPresetIDs":
            return [list(self.ids)]
        return [f"Name {params[0]}"]


def run(coro):
    return asyncio.run(coro)


def test_catalog_fetches_names_in_chunks_and_caches():
    s = Session(120)
    c = PresetCatalog(s, chunk=50)
    items = run(c.items())
    assert len(items) == 120 and items[0] == ("ID0", "Name ID0") and items[-1] == ("ID119", "Name ID119")
    assert s.calls.count("getPresetIDs") == 1 and s.calls.count("getPresetName") == 120
    assert 1 < s.max_in_flight <= 50          # concurrent, but never more than one chunk at a time
    run(c.items())
    assert len(s.calls) == 121                # cached
    c.invalidate()
    run(c.items())
    assert s.calls.count("getPresetIDs") == 2  # fetched again after invalidate


def test_ids_without_names():
    s = Session(30)
    c = PresetCatalog(s)
    assert run(c.ids()) == [f"ID{i}" for i in range(30)]
    assert s.calls == ["getPresetIDs"]         # resolving by id never fetches 1,500 names


def test_catalog_raises_when_disconnected():
    s = Session(5)
    s.connected = False
    with pytest.raises(ConnectionError):
        run(PresetCatalog(s).items())
