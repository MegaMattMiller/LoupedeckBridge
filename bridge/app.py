"""Wire the pieces together: MIDI in → dispatcher → dial engine / Lightroom session, plus the settings page."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional, Set

from bridge import platform
from bridge.actions import Dispatcher
from bridge.dial_feel import detent_amount
from bridge.dials import DialEngine
from bridge.hardware import HardwareMap
from bridge.mapping import Mapping
from bridge.midi_input import MidiInput
from bridge.presets import PresetCatalog
from bridge.session import LightroomSession
from bridge.settings.server import SettingsServer
from bridge.status import StatusReporter

log = logging.getLogger("app")

APP_NAME, APP_VERSION = "Loupedeck+ Bridge", "0.1"
SETTINGS_PORT = 7690


class App:
    def __init__(self, midi, session: LightroomSession, dials: DialEngine, dispatcher: Dispatcher,
                 settings: Optional[SettingsServer] = None, status: Optional[StatusReporter] = None):
        self.midi, self.session, self.dials, self.dispatcher = midi, session, dials, dispatcher
        self.settings = settings
        self.status = status or StatusReporter(None)

    async def run(self) -> None:
        tasks = [asyncio.create_task(self.session.run_forever(), name="lightroom session"),
                 asyncio.create_task(self.dials.run(), name="dial engine"),
                 asyncio.create_task(self._consume(), name="midi input")]
        if self.settings is not None:
            tasks.append(asyncio.create_task(self.settings.serve(), name="settings page"))
        # Not supervised like the others: it may finish (once keys are allowed), and it's a convenience.
        status_task = asyncio.create_task(self.status.run(), name="status")
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
            # Stop reporting first: closing the MIDI port on the way out isn't the Loupedeck being
            # unplugged, and the menu-bar app would alert "disconnected" for it.
            self.status.close()
            self.dispatcher.release_all_keys()  # never leave Shift/Cmd stuck down on the way out
            for task in tasks + [status_task]:
                task.cancel()
            await asyncio.gather(*tasks, status_task, return_exceptions=True)

    async def _consume(self) -> None:
        async for event in self.midi.events():
            try:
                await self.dispatcher.handle(event)
                if self.settings is not None:
                    self.settings.on_event(event)
            except Exception:  # one bad action mustn't stop all input
                log.exception("handling %s failed; carrying on", event)


def build(config_dir: Path, midi, port: Optional[int] = None, state_file: Optional[Path] = None,
          feel=detent_amount, frame_log: Optional[Path] = None, keyboard=None,
          settings_port: Optional[int] = None, cache_dir: Optional[Path] = None,
          status: Optional[StatusReporter] = None) -> App:
    mapping = Mapping.load(config_dir / "mapping.json")  # logs its own warnings
    session = LightroomSession(APP_NAME, APP_VERSION, port=port, state_file=state_file, frame_log=frame_log)
    dials = DialEngine(session, feel=feel)
    catalog = PresetCatalog(session, cache_path=cache_dir / "preset_names.json" if cache_dir else None)
    dispatcher = Dispatcher(mapping, session, dials, keyboard=keyboard, catalog=catalog)
    settings = None
    if settings_port:
        settings = SettingsServer(settings_port, mapping, dispatcher, catalog)
        dispatcher.settings_url = settings.url        # the custom mode button opens it
    background: Set[asyncio.Task] = set()            # keeps fire-and-forget announcements alive
    status = status or StatusReporter(None)            # the menu-bar app's status lines (milestone 5)
    status.set(settings_url=settings.url if settings is not None else None)

    async def lightroom_connected() -> None:
        status.set(lightroom=True)
        if settings is not None:
            await settings.broadcast_state()          # open pages can start loading presets now
        await dispatcher.resolve_presets()            # logs preset warnings after every connect
        if settings is not None:
            await settings.broadcast_state()          # with each slot's badge checked

    def announce() -> None:
        """Tell open settings pages the state changed (from code that isn't async)."""
        if settings is not None:
            task = asyncio.get_running_loop().create_task(settings.broadcast_state())
            background.add(task)
            task.add_done_callback(background.discard)

    def lightroom_disconnected() -> None:
        dials.reset()                                 # never replay stale detents
        status.set(lightroom=False)
        announce()

    def mode_changed() -> None:                       # --/Col: the page and the menu show the mode
        status.set(five_mode=dispatcher.five_mode)
        announce()

    def device_opened() -> None:
        dispatcher.device_reconnected()               # a replugged device may be in another mode
        status.set(loupedeck=True)

    def device_closed() -> None:
        dispatcher.release_all_keys()                 # unplugged mid-press: let go of held keys
        status.set(loupedeck=False)

    session.on_connect = lightroom_connected
    session.on_disconnect = lightroom_disconnected
    dispatcher.on_mode_change = mode_changed
    if hasattr(midi, "on_open"):
        midi.on_open = device_opened
    if hasattr(midi, "on_close"):
        midi.on_close = device_closed
    return App(midi, session, dials, dispatcher, settings, status)


async def run(debug: bool = False, midi_port: str = "Loupedeck", lightroom_port: Optional[int] = None,
              settings_port: Optional[int] = SETTINGS_PORT) -> None:
    plat = platform.current()
    frame_log = plat.log_dir() / "frames.jsonl" if debug else None
    log.info("settings: %s", plat.config_dir() / "mapping.json")
    keyboard = plat.keyboard()
    try:
        await build(plat.config_dir(), MidiInput(HardwareMap.load(), port_hint=midi_port), port=lightroom_port,
                    frame_log=frame_log, keyboard=keyboard, settings_port=settings_port,
                    cache_dir=plat.state_dir(), status=StatusReporter.from_env(keyboard=keyboard)).run()
    finally:
        if keyboard is not None:
            keyboard.close()  # stops the modifier tap, after App.run has released any held keys
