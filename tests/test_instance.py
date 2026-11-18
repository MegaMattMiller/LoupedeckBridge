from __future__ import annotations

import asyncio
import os
import time

from bridge.instance import CONTROL_HANDLE_ENV, acquire, open_control, parent_gone, watch_control


def test_parent_gone_returns_when_the_launcher_dies():
    # Review: force-quitting LoupedeckBridge.app left the bridge running invisibly, holding the
    # lock (so `bridgectl start` silently failed). The bridge now notices its parent is gone.
    ppids = iter([500, 500, 500, 1, 1, 1])

    async def main():
        await asyncio.wait_for(parent_gone(500, getppid=lambda: next(ppids), interval=0.001), 1)
    asyncio.run(main())


def test_parent_gone_waits_while_parent_alive():
    async def main():
        task = asyncio.ensure_future(parent_gone(500, getppid=lambda: 500, interval=0.001))
        await asyncio.sleep(0.05)
        assert not task.done()
        task.cancel()
    asyncio.run(main())


def test_second_instance_refuses(tmp_path):
    lock = tmp_path / "state" / "bridge.lock"
    first = acquire(lock)
    assert first is not None
    assert acquire(lock) is None       # a second bridge must not start
    first.close()                      # the first one exits…
    again = acquire(lock)              # …and a new one may start
    assert again is not None
    again.close()


# ---- milestone 7: the control pipe from the Windows tray app ---------------------------------------------------

def control_pipe():
    r, w = os.pipe()
    return os.fdopen(r, "r", encoding="utf-8"), os.fdopen(w, "w", encoding="utf-8")


def test_control_stop_line_stops():
    stream, writer = control_pipe()
    stops = []
    thread = watch_control(stream, lambda: stops.append(1))
    writer.write("stop\n")
    writer.flush()
    thread.join(2)
    assert stops == [1] and not thread.is_alive()
    writer.close()                      # end of file afterwards changes nothing
    assert stops == [1]
    stream.close()


def test_control_eof_stops():
    # The tray app has gone (killed): its end of the pipe closes, and the bridge must stop, letting go of keys.
    stream, writer = control_pipe()
    stops = []
    thread = watch_control(stream, lambda: stops.append(1))
    writer.close()
    thread.join(2)
    assert stops == [1] and not thread.is_alive()
    stream.close()


def test_control_other_lines_ignored():
    stream, writer = control_pipe()
    stops = []
    thread = watch_control(stream, lambda: stops.append(1))
    writer.write("hello\n")
    writer.flush()
    time.sleep(0.1)
    assert stops == [] and thread.is_alive()
    writer.close()
    thread.join(2)
    stream.close()


def test_open_control_needs_a_handle():
    assert open_control({}) is None
    assert open_control({CONTROL_HANDLE_ENV: "not a number"}) is None
