"""Read the Loupedeck+ over MIDI, surviving unplug/replug."""
from __future__ import annotations

import asyncio
import ctypes
import logging
from typing import AsyncIterator, Callable, List, Optional

import mido

from bridge.hardware import Event, HardwareMap

log = logging.getLogger("midi")

# Ports whose close failed (milestone 7 live check, Windows): after an unplug, RtMidi's WinMM closePort fails in
# midiInUnprepareHeader, *after* closing the handle and freeing its buffers, but leaves the port marked open. Any
# later clean-up (mido's __del__, rtmidi's destructor) would run closePort again and free those buffers a second
# time, which can crash the process. So such a port is marked closed for mido and never destroyed: an extra
# reference, never released, keeps it alive until the process exits. The device itself can be opened again.
_UNCLOSABLE: list = []


def _keep_forever(port) -> None:
    try:
        port.closed = True                      # mido's close() and __del__ do nothing more
    except AttributeError:
        pass
    _UNCLOSABLE.append(port)
    try:
        ctypes.pythonapi.Py_IncRef(ctypes.py_object(port))   # not even interpreter shutdown frees it
    except (AttributeError, OSError):
        pass


class MidiInput:
    def __init__(self, hardware: HardwareMap, port_hint: str = "Loupedeck",
                 list_ports: Callable[[], List[str]] = mido.get_input_names,
                 open_port: Callable = mido.open_input, poll: float = 1.0, busy_retry: float = 3.0):
        self.hardware, self.port_hint = hardware, port_hint
        self.list_ports, self.open_port, self.poll = list_ports, open_port, poll
        self.busy_retry = busy_retry
        self.on_open: Optional[Callable[[], None]] = None   # called each time the device (re)appears
        self.on_close: Optional[Callable[[], None]] = None  # called each time its port closes
        # Called with True when another program holds the Loupedeck (on Windows a MIDI input opens for one program
        # at a time: usually the Loupedeck or Logi software), and with False once that's over (milestone 7).
        self.on_busy: Optional[Callable[[bool], None]] = None
        self._busy = False

    async def events(self) -> AsyncIterator[Event]:
        loop = asyncio.get_running_loop()
        while True:
            name = await self._wait_for_port()
            queue: asyncio.Queue = asyncio.Queue()
            try:
                # rtmidi calls back from its own thread; hand messages to the event loop safely.
                port = self.open_port(name, callback=lambda msg: loop.call_soon_threadsafe(queue.put_nowait, msg))
            except Exception as e:  # noqa: BLE001 — rtmidi raises its own error types; any failure here is "busy"
                if not self._busy:
                    log.warning("the Loupedeck is in use by another program (%s): quit the Loupedeck or Logi "
                                "software. Retrying every %g s.", e, self.busy_retry)
                    self._set_busy(True)
                await asyncio.sleep(self.busy_retry)
                continue
            self._set_busy(False)
            log.info("Loupedeck connected (%s)", name)
            if self.on_open is not None:
                try:
                    self.on_open()
                except Exception:
                    log.exception("on_open hook failed")
            getter: Optional[asyncio.Future] = None
            try:
                while True:
                    # Not asyncio.wait_for: on Python 3.9 it swallows a cancel that lands as a
                    # message arrives, which could hang `bridgectl stop` mid-spin.
                    if getter is None:
                        getter = asyncio.ensure_future(queue.get())
                    done, _ = await asyncio.wait({getter}, timeout=self.poll)
                    if not done:
                        if name not in self.list_ports():
                            log.info("Loupedeck disconnected; waiting for it to come back")
                            break
                        continue
                    msg, getter = getter.result(), None
                    event = self._decode(msg)
                    if event is not None:
                        yield event
            finally:
                if getter is not None:
                    getter.cancel()
                try:
                    port.close()
                except Exception as e:  # noqa: BLE001 — rtmidi raises its own error types
                    log.info("the Loupedeck's old port didn't close cleanly (%s); leaving it be", e)
                    _keep_forever(port)
                if self.on_close is not None:
                    try:
                        self.on_close()
                    except Exception:
                        log.exception("on_close hook failed")

    def _set_busy(self, busy: bool) -> None:
        if busy == self._busy:
            return
        self._busy = busy
        if self.on_busy is not None:
            try:
                self.on_busy(busy)
            except Exception:
                log.exception("on_busy hook failed")

    async def _wait_for_port(self) -> str:
        waiting_logged = False
        while True:
            name = self._find_port()
            if name is not None:
                return name
            self._set_busy(False)        # unplugged while another program held it: no longer "busy"
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
