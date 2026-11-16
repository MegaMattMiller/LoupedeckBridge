from __future__ import annotations

import asyncio
import socket

import pytest

from bridge.session import SETUP_CALLS, LightroomSession
from tests.fake_lightroom import FakeLightroom


async def wait_until(cond, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_session(tmp_path, port, **kw) -> LightroomSession:
    return LightroomSession("Test", "1", port=port, state_file=tmp_path / "client.json", retry_delay=0.05, **kw)


def registers(fake):
    return [params for msg, params in fake.calls if msg == "register"]


def test_session_registers_and_runs_setup(tmp_path):
    async def main():
        fake = FakeLightroom()
        port = await fake.start()
        seen_at_connect = []

        async def on_connect():
            seen_at_connect.append(list(fake.calls))

        session = make_session(tmp_path, port, on_connect=on_connect)
        task = asyncio.create_task(session.run_forever())
        try:
            await wait_until(lambda: session.connected and seen_at_connect)
            assert fake.calls[0] == ("register", ["Test", "1"])
            assert fake.calls[1:4] == [(m, p) for m, p in SETUP_CALLS]
            assert SETUP_CALLS == [("revealAdjustedControls", [True]), ("setTrackingDelay", [2.0]),
                                   ("setMultipleAdjustmentThreshold", [1.0])]
            assert seen_at_connect == [fake.calls[:4]]  # on_connect ran once, after the setup calls
            assert await session.call("getRating") == []
        finally:
            task.cancel()
            await fake.stop()
    asyncio.run(main())


def test_session_reconnects_after_drop(tmp_path):
    async def main():
        fake = FakeLightroom()
        port = await fake.start()
        drops = []
        session = make_session(tmp_path, port, on_disconnect=lambda: drops.append(1))
        task = asyncio.create_task(session.run_forever())
        try:
            await wait_until(lambda: session.connected)
            await fake.drop_clients()
            await wait_until(lambda: drops == [1])
            await wait_until(lambda: session.connected and len(registers(fake)) == 2)
            assert registers(fake)[1] == ["Test", "1", "FAKE-GUID"]  # reuses the saved GUID
        finally:
            task.cancel()
            await fake.stop()
    asyncio.run(main())


def test_session_waits_while_lightroom_down(tmp_path):
    async def main():
        port = free_port()
        session = make_session(tmp_path, port)
        task = asyncio.create_task(session.run_forever())
        fake = FakeLightroom()
        try:
            await asyncio.sleep(0.3)
            assert not session.connected
            await fake.start(port)
            await wait_until(lambda: session.connected)
        finally:
            task.cancel()
            await fake.stop()
    asyncio.run(main())


def test_refused_registration_backs_off(tmp_path):
    async def main():
        fake = FakeLightroom()
        fake.failing.add("register")  # e.g. the user clicked Deny
        port = await fake.start()
        session = make_session(tmp_path, port, denied_delay=5.0)
        task = asyncio.create_task(session.run_forever())
        try:
            await wait_until(lambda: len(registers(fake)) == 1)
            await asyncio.sleep(0.3)  # many retry_delays, far below denied_delay
            assert len(registers(fake)) == 1
            assert not session.connected
        finally:
            task.cancel()
            await fake.stop()
    asyncio.run(main())


def test_call_while_disconnected_raises(tmp_path):
    async def main():
        session = make_session(tmp_path, free_port())
        with pytest.raises(ConnectionError):
            await session.call("undo")
    asyncio.run(main())
