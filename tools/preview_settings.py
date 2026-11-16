#!/usr/bin/env python3
"""Preview the settings page with a fake Lightroom (no device, no Lightroom, no real mapping).

    .venv/bin/python tools/preview_settings.py [--port 7691] [--presets 1500] [--down]

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
from bridge.mapping import Mapping  # noqa: E402
from bridge.presets import PresetCatalog  # noqa: E402
from bridge.settings.server import SettingsServer  # noqa: E402

WORDS = ["Warm", "Cool", "Matte", "Film", "Portrait", "Landscape", "B&W", "Vivid", "Soft", "Moody", "Golden",
         "Blue Hour", "Clean", "Faded", "Punchy", "Street", "Travel", "Wedding", "Night", "Food"]


class FakeLightroom:
    def __init__(self, n: int, connected: bool):
        rnd = random.Random(7)
        self.names = {f"ID{i:04d}": f"{rnd.choice(WORDS)} {rnd.choice(WORDS)} {i}" for i in range(n)}
        self.names["ID-DUP-1"] = self.names["ID-DUP-2"] = "Heavy"
        self.connected = connected

    async def call(self, message, *params):
        if not self.connected:
            raise ConnectionError("Lightroom isn't connected")
        if message == "getPresetIDs":
            return [list(self.names)]
        if message == "getPresetName":
            return [self.names[params[0]]]
        return {}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7691)
    ap.add_argument("--presets", type=int, default=1500)
    ap.add_argument("--down", action="store_true", help="pretend Lightroom is closed")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")
    tmp = Path(tempfile.mkdtemp(prefix="lb-preview-"))
    mapping = Mapping.load(tmp / "mapping.json")
    lightroom = FakeLightroom(args.presets, connected=not args.down)
    catalog = PresetCatalog(lightroom)
    dispatcher = Dispatcher(mapping, lightroom, dials=None, catalog=catalog)
    server = SettingsServer(args.port, mapping, dispatcher, catalog)
    print(f"preview: {server.url}  (mapping in {tmp})", flush=True)
    await dispatcher.resolve_presets()
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
