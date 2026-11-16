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
        tasks = [asyncio.create_task(self.session.run_forever(), name="lightroom session"),
                 asyncio.create_task(self.dials.run(), name="dial engine"),
                 asyncio.create_task(self._consume(), name="midi input")]
        try:
            # None of these should ever finish. If one dies, stop loudly rather than leave a
            # bridge that silently ignores input (a supervisor such as launchd can restart it).
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                exc = task.exception()
                if exc is not None:
                    log.error("bridge stopping: the %s failed", task.get_name(), exc_info=exc)
                    raise exc
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _consume(self) -> None:
        async for event in self.midi.events():
            try:
                await self.dispatcher.handle(event)
            except Exception:  # one bad action mustn't stop all input
                log.exception("handling %s failed; carrying on", event)


def build(config_dir: Path, midi, port: Optional[int] = None, state_file: Optional[Path] = None,
          feel=detent_amount, frame_log: Optional[Path] = None) -> App:
    mapping = Mapping.load(config_dir / "mapping.json")  # logs its own warnings
    session = LightroomSession(APP_NAME, APP_VERSION, port=port, state_file=state_file, frame_log=frame_log)
    dials = DialEngine(session, feel=feel)
    dispatcher = Dispatcher(mapping, session, dials)
    session.on_connect = dispatcher.resolve_presets   # logs preset warnings after every connect
    session.on_disconnect = dials.reset               # never replay stale detents
    if hasattr(midi, "on_open"):                      # a replugged device may be in another mode
        midi.on_open = dispatcher.device_reconnected
    return App(midi, session, dials, dispatcher)


async def run(debug: bool = False) -> None:
    plat = platform.current()
    frame_log = plat.log_dir() / "frames.jsonl" if debug else None
    log.info("settings: %s", plat.config_dir() / "mapping.json")
    await build(plat.config_dir(), MidiInput(HardwareMap.load()), frame_log=frame_log).run()
