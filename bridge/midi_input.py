"""Read the Loupedeck+ over MIDI, surviving unplug/replug."""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Callable, List, Optional

import mido

from bridge.hardware import Event, HardwareMap

log = logging.getLogger("midi")


class MidiInput:
    def __init__(self, hardware: HardwareMap, port_hint: str = "Loupedeck",
                 list_ports: Callable[[], List[str]] = mido.get_input_names,
                 open_port: Callable = mido.open_input, poll: float = 1.0):
        self.hardware, self.port_hint = hardware, port_hint
        self.list_ports, self.open_port, self.poll = list_ports, open_port, poll
        self.on_open: Optional[Callable[[], None]] = None  # called each time the device (re)appears

    async def events(self) -> AsyncIterator[Event]:
        loop = asyncio.get_running_loop()
        while True:
            name = await self._wait_for_port()
            queue: asyncio.Queue = asyncio.Queue()
            # rtmidi calls back from its own thread; hand messages to the event loop safely.
            port = self.open_port(name, callback=lambda msg: loop.call_soon_threadsafe(queue.put_nowait, msg))
            log.info("Loupedeck connected (%s)", name)
            if self.on_open is not None:
                try:
                    self.on_open()
                except Exception:
                    log.exception("on_open hook failed")
            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=self.poll)
                    except asyncio.TimeoutError:
                        if name not in self.list_ports():
                            log.info("Loupedeck disconnected; waiting for it to come back")
                            break
                        continue
                    event = self._decode(msg)
                    if event is not None:
                        yield event
            finally:
                port.close()

    async def _wait_for_port(self) -> str:
        waiting_logged = False
        while True:
            name = self._find_port()
            if name is not None:
                return name
            if not waiting_logged:
                log.info("waiting for a MIDI input named like %r (is the Loupedeck+ plugged in, "
                         "and the Loupedeck software quit?)", self.port_hint)
                waiting_logged = True
            await asyncio.sleep(self.poll)

    def _find_port(self) -> Optional[str]:
        for name in self.list_ports():
            if self.port_hint.lower() in name.lower():
                return name
        return None

    def _decode(self, msg: mido.Message) -> Optional[Event]:
        if msg.type == "control_change":
            event = self.hardware.decode(msg.type, msg.control, msg.value)
        elif msg.type in ("note_on", "note_off"):
            event = self.hardware.decode(msg.type, msg.note, msg.velocity)
        else:
            event = None
        if event is None and msg.type not in ("clock", "active_sensing"):
            log.debug("ignored MIDI message %s", msg)
        return event
