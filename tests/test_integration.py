"""End to end: replay a real Loupedeck+ capture through the real wiring into a fake Lightroom."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from bridge import app
from bridge.hardware import HardwareMap
from tests.fake_lightroom import FakeLightroom

CAPTURE = Path(__file__).resolve().parent.parent / "captures" / "raw-20261116-001458.jsonl"


class ReplayMidi:
    """Yields the capture's events with their real timing (gaps capped at 0.2 s), once `ready` is set."""

    def __init__(self, labels):
        self.ready = asyncio.Event()
        hw = HardwareMap.load()
        self.timeline = []
        for line in CAPTURE.read_text().splitlines():
            rec = json.loads(line)
            if "marker" in rec or rec["label"] not in labels:
                continue
            event = hw.decode(rec["type"], rec.get("control", rec.get("note")), rec.get("value", rec.get("velocity")))
            self.timeline.append((rec["t"], event))

    async def events(self):
        await self.ready.wait()
        prev = None
        for t, event in self.timeline:
            if prev is not None:
                await asyncio.sleep(min(t - prev, 0.2))
            prev = t
            yield event
        await asyncio.Event().wait()  # like a real device: the stream stays open


def test_integration_exposure_capture(tmp_path):
    async def main():
        fake = FakeLightroom()
        fake.responses["getRange"] = [-5, 5, 2, 0.1, 0.33]
        port = await fake.start()
        midi = ReplayMidi({"exposure dial", "exposure click"})
        bridge = app.build(config_dir=tmp_path, midi=midi, port=port, state_file=tmp_path / "client.json",
                           feel=lambda r, s: 0.1)
        task = asyncio.create_task(bridge.run())
        try:
            for _ in range(200):
                if bridge.session.connected:
                    break
                await asyncio.sleep(0.01)
            midi.ready.set()
            for _ in range(300):
                if ("resetToDefault", ["Exposure2012"]) in fake.calls:
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.1)  # let the last flush go out
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await fake.stop()
        calls = fake.calls
        assert ("startTracking", ["Exposure2012"]) in calls
        incs = [p for m, p in calls if m == "increment" and p[0] == "Exposure2012"]
        decs = [p for m, p in calls if m == "decrement" and p[0] == "Exposure2012"]
        assert incs and decs
        assert round(sum(a for _, a in incs) - sum(a for _, a in decs), 2) == 0.2  # 4 cw − 2 ccw at 0.1 each
        assert ("resetToDefault", ["Exposure2012"]) in calls
        assert (tmp_path / "mapping.json").exists()  # the user's mapping was created on first run
    asyncio.run(main())
