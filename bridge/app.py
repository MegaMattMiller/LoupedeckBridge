"""Wire the pieces together: MIDI in → dispatcher → dial engine / Lightroom session."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from bridge import platform
from bridge.actions import Dispatcher
from bridge.dial_feel import detent_amount
from bridge.dials import DialEngine
from bridge.hardware import HardwareMap
from bridge.mapping import Mapping
from bridge.midi_input import MidiInput
from bridge.session import LightroomSession

log = logging.getLogger("app")

APP_NAME, APP_VERSION = "Loupedeck+ Bridge", "0.1"


class App:
    def __init__(self, midi, session: LightroomSession, dials: DialEngine, dispatcher: Dispatcher):
        self.midi, self.session, self.dials, self.dispatcher = midi, session, dials, dispatcher

    async def run(self) -> None:
        background = [asyncio.create_task(self.session.run_forever()), asyncio.create_task(self.dials.run())]
        try:
            async for event in self.midi.events():
                await self.dispatcher.handle(event)
        finally:
            for task in background:
                task.cancel()
            await asyncio.gather(*background, return_exceptions=True)


def build(config_dir: Path, midi, port: Optional[int] = None, state_file: Optional[Path] = None,
          feel=detent_amount, frame_log: Optional[Path] = None) -> App:
    mapping = Mapping.load(config_dir / "mapping.json")  # logs its own warnings
    session = LightroomSession(APP_NAME, APP_VERSION, port=port, state_file=state_file, frame_log=frame_log)
    dials = DialEngine(session, feel=feel)
    dispatcher = Dispatcher(mapping, session, dials)
    session.on_connect = dispatcher.resolve_presets   # logs preset warnings after every connect
    session.on_disconnect = dials.reset               # never replay stale detents
    return App(midi, session, dials, dispatcher)


async def run(debug: bool = False) -> None:
    plat = platform.current()
    frame_log = plat.log_dir() / "frames.jsonl" if debug else None
    log.info("settings: %s", plat.config_dir() / "mapping.json")
    await build(plat.config_dir(), MidiInput(HardwareMap.load()), frame_log=frame_log).run()
