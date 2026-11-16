from __future__ import annotations

import asyncio

from bridge.instance import acquire, parent_gone


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
