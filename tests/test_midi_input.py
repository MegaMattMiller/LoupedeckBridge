from __future__ import annotations

import asyncio

import mido

from bridge.hardware import HardwareMap, Turn
from bridge.midi_input import MidiInput

HW = HardwareMap.load()


class FakePort:
    def __init__(self, name, callback):
        self.name, self.callback, self.closed = name, callback, False

    def send_in(self, msg: mido.Message) -> None:
        """What rtmidi does when the device sends a message (from its own thread)."""
        self.callback(msg)

    def close(self) -> None:
        self.closed = True


class FakeMidi:
    def __init__(self, present=True):
        self.present = present
        self.ports = []

    def list_ports(self):
        return ["IAC Driver Bus 1", "Loupedeck+"] if self.present else ["IAC Driver Bus 1"]

    def open_port(self, name, callback=None):
        port = FakePort(name, callback)
        self.ports.append(port)
        return port


async def wait_until(cond, timeout=1.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not cond():
        assert asyncio.get_running_loop().time() < deadline, "condition not met in time"
        await asyncio.sleep(0.005)


def cc(number, value):
    return mido.Message("control_change", control=number, value=value)


def test_waits_for_device():
    async def main():
        midi = FakeMidi(present=False)
        events = MidiInput(HW, list_ports=midi.list_ports, open_port=midi.open_port, poll=0.01).events()
        nxt = asyncio.ensure_future(events.__anext__())
        await asyncio.sleep(0.05)
        assert midi.ports == []  # nothing to open yet
        midi.present = True
        await wait_until(lambda: len(midi.ports) == 1)
        assert midi.ports[0].name == "Loupedeck+"
        midi.ports[0].send_in(cc(33, 1))
        assert await asyncio.wait_for(nxt, 1) == Turn("exposure", 1)
        await events.aclose()
    asyncio.run(main())


def test_reopens_after_unplug():
    async def main():
        midi = FakeMidi()
        events = MidiInput(HW, list_ports=midi.list_ports, open_port=midi.open_port, poll=0.01).events()
        nxt = asyncio.ensure_future(events.__anext__())
        await wait_until(lambda: len(midi.ports) == 1)
        midi.ports[0].send_in(cc(33, 1))
        assert await asyncio.wait_for(nxt, 1) == Turn("exposure", 1)

        nxt = asyncio.ensure_future(events.__anext__())
        midi.present = False  # unplugged
        await wait_until(lambda: midi.ports[0].closed)
        midi.present = True   # plugged back in
        await wait_until(lambda: len(midi.ports) == 2)
        midi.ports[1].send_in(cc(46, 127))
        assert await asyncio.wait_for(nxt, 1) == Turn("contrast", -1)
        await events.aclose()
        assert midi.ports[1].closed  # closing the stream closes the port
    asyncio.run(main())


def test_on_open_called_each_time_the_device_appears():
    async def main():
        midi, opened = FakeMidi(), []
        source = MidiInput(HW, list_ports=midi.list_ports, open_port=midi.open_port, poll=0.01)
        source.on_open = lambda: opened.append(len(midi.ports))
        events = source.events()
        nxt = asyncio.ensure_future(events.__anext__())
        await wait_until(lambda: opened == [1])
        midi.present = False
        await wait_until(lambda: midi.ports[0].closed)
        midi.present = True
        await wait_until(lambda: opened == [1, 2])
        nxt.cancel()
        await asyncio.gather(nxt, return_exceptions=True)  # let the cancelled read finish first
        await events.aclose()
    asyncio.run(main())


def test_on_close_called_on_unplug():
    async def main():
        midi, closed = FakeMidi(), []
        source = MidiInput(HW, list_ports=midi.list_ports, open_port=midi.open_port, poll=0.01)
        source.on_close = lambda: closed.append(1)
        events = source.events()
        nxt = asyncio.ensure_future(events.__anext__())
        await wait_until(lambda: len(midi.ports) == 1)
        midi.present = False  # unplugged
        await wait_until(lambda: closed == [1])
        midi.present = True
        await wait_until(lambda: len(midi.ports) == 2)
        nxt.cancel()
        await asyncio.gather(nxt, return_exceptions=True)
        await events.aclose()  # closing the stream closes the port: on_close again
        assert closed == [1, 1]
    asyncio.run(main())


def test_unknown_messages_skipped():
    async def main():
        midi = FakeMidi()
        events = MidiInput(HW, list_ports=midi.list_ports, open_port=midi.open_port, poll=0.01).events()
        nxt = asyncio.ensure_future(events.__anext__())
        await wait_until(lambda: len(midi.ports) == 1)
        midi.ports[0].send_in(cc(43, 1))  # not a Loupedeck+ control
        midi.ports[0].send_in(mido.Message("clock"))
        midi.ports[0].send_in(cc(33, 1))
        assert await asyncio.wait_for(nxt, 1) == Turn("exposure", 1)
        await events.aclose()
    asyncio.run(main())
