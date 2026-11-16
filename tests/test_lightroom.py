from __future__ import annotations

import asyncio
import logging

import pytest

from bridge import lightroom
from bridge.lightroom import Lightroom
from tests.fake_lightroom import FakeLightroom


async def connected_client(tmp_path, fake):
    port = await fake.start()
    lr = Lightroom("Test", "1", state_file=tmp_path / "client.json")
    await lr.connect(port)
    await lr.register()
    return lr


def test_request_on_closing_socket_raises_connection_error(tmp_path):
    # Review finding 1: a send on a closed socket raised websockets' ConnectionClosedOK, which
    # nothing upstream catches (it isn't a ConnectionError) — it killed the dial engine.
    async def main():
        fake = FakeLightroom()
        lr = await connected_client(tmp_path, fake)
        try:
            await lr.ws.close()
            with pytest.raises(ConnectionError):
                await lr.request("undo")
        finally:
            await fake.stop()
    asyncio.run(main())


def test_request_before_connect_raises_connection_error(tmp_path):
    async def main():
        lr = Lightroom("Test", "1", state_file=tmp_path / "client.json")
        with pytest.raises(ConnectionError):
            await lr.request("undo")
    asyncio.run(main())


def test_await_reply_honours_cancel():
    # Review finding 12: on Python 3.9, asyncio.wait_for returns the result instead of raising
    # CancelledError when the cancel lands in the same loop step as the reply — Ctrl-C could hang.
    async def main():
        fut = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(lightroom._await_reply(fut, 10))
        await asyncio.sleep(0)       # task is now waiting for the reply
        fut.set_result(["reply"])    # reply arrives…
        task.cancel()                # …and Ctrl-C in the same step
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(main())


def test_await_reply_times_out():
    async def main():
        fut = asyncio.get_running_loop().create_future()
        with pytest.raises(asyncio.TimeoutError):
            await lightroom._await_reply(fut, 0.01)
    asyncio.run(main())


def test_unrouted_frame_log_is_redacted(tmp_path, caplog):
    # Review finding 11: a frame nobody waits for (e.g. a register reply after the timeout)
    # was logged raw, GUID included.
    async def main():
        fake = FakeLightroom()
        lr = await connected_client(tmp_path, fake)
        try:
            with caplog.at_level(logging.INFO, logger="lightroom"):
                await fake.push({"requestId": "late", "success": True, "response": ["FAKE-GUID", "10.0"]})
                for _ in range(100):
                    if any("unrouted" in r.getMessage() for r in caplog.records):
                        break
                    await asyncio.sleep(0.01)
        finally:
            await lr.close()
            await fake.stop()
    asyncio.run(main())
    messages = [r.getMessage() for r in caplog.records]
    assert any("unrouted" in m for m in messages)
    assert not any("FAKE-GUID" in m for m in messages)
