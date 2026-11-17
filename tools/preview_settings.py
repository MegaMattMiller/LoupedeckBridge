#!/usr/bin/env python3
"""Preview the settings page with a fake Lightroom (no device, no Lightroom, no real mapping).

    .venv/bin/python tools/preview_settings.py [--port 7691] [--presets 1500] [--down]
                                               [--lightroom-after S] [--name-delay S] [--demo-device]

Serves the real page and server code against sample presets and a throwaway mapping in a
temp folder, so the UI can be tried and tested without touching a running bridge.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bridge.actions import Dispatcher  # noqa: E402
from bridge.hardware import Press, Release, Turn  # noqa: E402
from bridge.mapping import Mapping  # noqa: E402
from bridge.presets import PresetCatalog  # noqa: E402
from bridge.settings.server import SettingsServer  # noqa: E402

WORDS = ["Warm", "Cool", "Matte", "Film", "Portrait", "Landscape", "B&W", "Vivid", "Soft", "Moody", "Golden",
         "Blue Hour", "Clean", "Faded", "Punchy", "Street", "Travel", "Wedding", "Night", "Food"]


class FakeLightroom:
    def __init__(self, n: int, connected: bool, name_delay: float = 0.0):
        rnd = random.Random(7)
        self.names = {f"ID{i:04d}": f"{rnd.choice(WORDS)} {rnd.choice(WORDS)} {i}" for i in range(n)}
        self.names["ID-DUP-1"] = self.names["ID-DUP-2"] = "Heavy"
        self.connected, self.name_delay = connected, name_delay

    async def call(self, message, *params):
        if not self.connected:
            raise ConnectionError("Lightroom isn't connected")
        if message == "getPresetIDs":
            return [list(self.names)]
        if message == "getPresetName":
            if self.name_delay:
                await asyncio.sleep(self.name_delay)
            return [self.names[params[0]]]
        return {}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7691)
    ap.add_argument("--presets", type=int, default=1500)
    ap.add_argument("--down", action="store_true", help="pretend Lightroom is closed")
    ap.add_argument("--lightroom-after", type=float, metavar="S", help="start closed; 'open' Lightroom after S s")
    ap.add_argument("--name-delay", type=float, default=0.0, metavar="S",
                    help="each preset name takes S s (the real Lightroom: about 0.02)")
    ap.add_argument("--demo-device", action="store_true",
                    help="every 4 s, act out holding Fn and pressing C3, then turning Exposure")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")
    tmp = Path(tempfile.mkdtemp(prefix="lb-preview-"))
    mapping = Mapping.load(tmp / "mapping.json")
    lightroom = FakeLightroom(args.presets, connected=not (args.down or args.lightroom_after is not None),
                              name_delay=args.name_delay)
    catalog = PresetCatalog(lightroom)
    dispatcher = Dispatcher(mapping, lightroom, dials=None, catalog=catalog)
    server = SettingsServer(args.port, mapping, dispatcher, catalog)
    print(f"preview: {server.url}  (mapping in {tmp})", flush=True)
    await dispatcher.resolve_presets()

    async def open_lightroom_later() -> None:  # what bridge.app does when Lightroom connects
        await asyncio.sleep(args.lightroom_after)
        lightroom.connected = True
        print("preview: Lightroom 'opened'", flush=True)
        await server.broadcast_state()
        await dispatcher.resolve_presets()
        await server.broadcast_state()

    async def demo_device() -> None:  # what the device and bridge.app would do
        async def use(event) -> None:
            if not isinstance(event, Turn):          # turns would need the dial engine; the page only needs to hear
                await dispatcher.handle(event)
            server.on_event(event)
        while True:
            await asyncio.sleep(4)
            for event in (Press("fn"), Press("c3"), Release("c3"), Release("fn"), Turn("exposure", 1)):
                await use(event)
                await asyncio.sleep(0.5)

    later = [open_lightroom_later()] if args.lightroom_after is not None else []
    if args.demo_device:
        later.append(demo_device())
    await asyncio.gather(server.serve(), *later)


if __name__ == "__main__":
    asyncio.run(main())
