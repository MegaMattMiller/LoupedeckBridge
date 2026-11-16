from __future__ import annotations

import asyncio
from typing import Dict, List, Set, Tuple

from bridge.dials import DialEngine
from bridge.lightroom import LightroomError

BW_MENU = {"enabled": True, "title": "Convert to Black ＆ White", "checked": False}


class FakeClient:
    """Answers like LightroomSession.call, with the real reply shapes from FINDINGS.md."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, list]] = []
        self.ranges: Dict[str, list] = {"Contrast2012": [-100, 100, 0, 10, 20],
                                        "Exposure2012": [-5, 5, 2, 0.1, 0.33],
                                        "GrayMixerRed": [-100, 100, 0, 10, 20]}
        self.bw = [False, BW_MENU]
        self.failing: Set[str] = set()

    async def call(self, message, *params):
        self.calls.append((message, list(params)))
        if message in self.failing:
            raise LightroomError({"success": False, "response": ["invalid_request"], "requestId": "x"})
        if message == "getRange":
            return list(self.ranges[params[0]])
        if message == "isBlackAndWhiteOn":
            return list(self.bw)
        return {}  # increment/decrement/startTracking reply with an empty object

    def named(self, message) -> List[list]:
        return [p for m, p in self.calls if m == message]


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def engine(client, clock, feel=lambda r, s: 1.0) -> DialEngine:
    return DialEngine(client, feel=feel, clock=clock)


def run(coro):
    return asyncio.run(coro)


def test_first_detent_starts_tracking_and_increments():
    c, clk = FakeClient(), Clock()
    e = engine(c, clk)
    e.add("Contrast2012", 1)
    run(e.flush())
    assert c.calls == [("getRange", ["Contrast2012"]), ("startTracking", ["Contrast2012"]),
                       ("increment", ["Contrast2012", 1])]


def test_negative_uses_decrement():
    c, clk = FakeClient(), Clock()
    e = engine(c, clk)
    e.add("Contrast2012", -1)
    run(e.flush())
    assert c.calls[-1] == ("decrement", ["Contrast2012", 1])
    assert c.named("increment") == []


def test_detents_coalesce():
    c, clk = FakeClient(), Clock()
    e = engine(c, clk)
    for _ in range(10):
        e.add("Contrast2012", 1)
    run(e.flush())
    assert c.named("increment") == [["Contrast2012", 10]]


def test_mixed_directions_net_out():
    c, clk = FakeClient(), Clock()
    e = engine(c, clk)
    for d in (1, 1, 1, -1):
        e.add("Contrast2012", d)
    run(e.flush())
    assert c.named("increment") == [["Contrast2012", 2]]


def test_flood_is_bounded():
    c, clk = FakeClient(), Clock()
    e = engine(c, clk)

    async def main():
        next_flush = clk.t + 0.025
        for _ in range(300):  # 150 detents/s for 2 s
            clk.t += 1 / 150
            e.add("Contrast2012", 1)
            if clk.t >= next_flush:
                await e.flush()
                next_flush += 0.025
        await e.flush()
    run(main())
    increments = c.named("increment")
    assert len(increments) <= 81
    assert sum(amount for _, amount in increments) == 300
    assert len(c.named("getRange")) == 1


def test_new_turn_after_gap():
    c, clk = FakeClient(), Clock()
    e = engine(c, clk)
    e.add("Contrast2012", 1)
    run(e.flush())
    clk.t += 0.6
    e.add("Contrast2012", 1)
    run(e.flush())
    assert len(c.named("getRange")) == 2
    assert len(c.named("startTracking")) == 2


def test_continuing_turn_reuses_range():
    c, clk = FakeClient(), Clock()
    e = engine(c, clk)
    e.add("Contrast2012", 1)
    run(e.flush())
    clk.t += 0.3  # shorter than turn_gap: same turn
    e.add("Contrast2012", 1)
    run(e.flush())
    assert len(c.named("getRange")) == 1
    assert len(c.named("increment")) == 2


def test_feel_gets_speed():
    c, clk = FakeClient(), Clock()
    speeds = []
    e = engine(c, clk, feel=lambda r, s: speeds.append(s) or 1.0)
    for _ in range(10):  # one detent every 0.02 s → 50 per second
        e.add("Contrast2012", 1)
        clk.t += 0.02
    clk.t -= 0.02
    run(e.flush())
    assert 45 <= speeds[-1] <= 55


def test_rounding_to_decimals():
    c, clk = FakeClient(), Clock()
    e = engine(c, clk, feel=lambda r, s: 0.033)
    e.add("Exposure2012", 1)
    run(e.flush())
    assert c.named("increment") == [["Exposure2012", 0.03]]


def test_amount_rounding_to_zero_sends_nothing():
    c, clk = FakeClient(), Clock()
    e = engine(c, clk, feel=lambda r, s: 0.004)
    e.add("Exposure2012", 1)
    run(e.flush())
    assert c.named("increment") == []


def test_bw_dial_blocked_when_not_bw():
    c, clk = FakeClient(), Clock()
    e = engine(c, clk)
    e.add("GrayMixerRed", 1)
    run(e.flush())
    clk.t += 0.1
    e.add("GrayMixerRed", 1)  # same turn: still blocked
    run(e.flush())
    assert c.named("increment") == []
    assert c.named("startTracking") == []  # never touches the photo
    c.bw = [True, {**BW_MENU, "checked": True}]
    clk.t += 0.6  # next turn re-checks
    e.add("GrayMixerRed", 1)
    run(e.flush())
    assert c.named("increment") == [["GrayMixerRed", 1]]


def test_lightroom_error_drops_turn():
    c, clk = FakeClient(), Clock()
    e = engine(c, clk)
    c.failing.add("getRange")  # e.g. no photo open
    e.add("Contrast2012", 1)
    run(e.flush())  # must not raise
    clk.t += 0.1
    e.add("Contrast2012", 1)  # same failed turn: dropped, no retry storm
    run(e.flush())
    assert c.named("increment") == []
    assert len(c.named("getRange")) == 1
    c.failing.clear()
    clk.t += 0.6
    e.add("Contrast2012", 1)
    run(e.flush())
    assert c.named("increment") == [["Contrast2012", 1]]


def test_disconnected_client_does_not_raise():
    class Gone(FakeClient):
        async def call(self, message, *params):
            raise ConnectionError("Lightroom isn't connected")
    e = engine(Gone(), Clock())
    e.add("Contrast2012", 1)
    run(e.flush())


def test_two_dials_independent():
    c, clk = FakeClient(), Clock()
    e = engine(c, clk)
    e.add("Exposure2012", 1)
    e.add("Contrast2012", -2)
    run(e.flush())
    assert c.named("increment") == [["Exposure2012", 1]]
    assert c.named("decrement") == [["Contrast2012", 2]]


def test_reset_drops_pending():
    c, clk = FakeClient(), Clock()
    e = engine(c, clk)
    e.add("Contrast2012", 5)
    e.reset()
    run(e.flush())
    assert c.calls == []
