"""Turn dial detents into Lightroom increment/decrement calls.

Detents arrive up to ~150/s. They're collected per parameter and flushed every
`flush_interval`, so Lightroom gets at most one call per parameter per interval with
no backlog. Each turn (activity after a pause of `turn_gap`) reads the parameter's
range live and starts tracking, which makes the whole turn one undo step.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, Optional

from bridge.dial_feel import ParamRange, detent_amount
from bridge.lightroom import LightroomError

log = logging.getLogger("dials")

_ERRORS = (LightroomError, ConnectionError, asyncio.TimeoutError)


@dataclass
class _Dial:
    pending: int = 0
    last_add: Optional[float] = None
    new_turn: bool = True
    usable: bool = False          # range known and the turn isn't blocked/failed
    rng: Optional[ParamRange] = None
    times: Deque[float] = field(default_factory=deque)


class DialEngine:
    def __init__(self, client, feel: Callable[[ParamRange, float], float] = detent_amount,
                 clock: Callable[[], float] = time.monotonic, flush_interval: float = 0.025,
                 turn_gap: float = 0.5, speed_window: float = 0.2):
        self.client, self.feel, self.clock = client, feel, clock
        self.flush_interval, self.turn_gap, self.speed_window = flush_interval, turn_gap, speed_window
        self._dials: Dict[str, _Dial] = {}

    def add(self, param: str, detents: int) -> None:
        now = self.clock()
        d = self._dials.setdefault(param, _Dial())
        if d.last_add is None or now - d.last_add >= self.turn_gap:
            d.new_turn = True
        d.last_add = now
        d.pending += detents
        d.times.append(now)
        while d.times and now - d.times[0] > self.speed_window:
            d.times.popleft()

    def reset(self) -> None:
        self._dials.clear()

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self.flush_interval)
            await self.flush()

    async def flush(self) -> None:
        for param, d in list(self._dials.items()):
            if d.pending == 0:
                continue
            take, d.pending = d.pending, 0  # detents arriving during the awaits wait for the next flush
            if d.new_turn:
                d.new_turn = False
                d.usable = await self._start_turn(param, d)
            if not d.usable:
                continue
            now = self.clock()
            speed = sum(1 for t in d.times if now - t <= self.speed_window) / self.speed_window
            amount = round(abs(take) * self.feel(d.rng, speed), d.rng.decimals)
            if d.rng.decimals == 0:
                amount = int(amount)
            if amount == 0:
                continue
            try:
                await self.client.call("increment" if take > 0 else "decrement", param, amount)
            except _ERRORS as e:
                log.warning("%s: %s failed (%s); ignoring the rest of this turn", param,
                            "increment" if take > 0 else "decrement", e)
                d.usable = False

    async def _start_turn(self, param: str, d: _Dial) -> bool:
        """Read the range, apply the B&W guard and start tracking. False = skip this turn."""
        try:
            d.rng = ParamRange.from_reply(await self.client.call("getRange", param))
            if param.startswith("GrayMixer"):
                bw = await self.client.call("isBlackAndWhiteOn")
                if not bw[0]:
                    log.info("%s ignored: the photo isn't black & white. The device is in its B&W mode; "
                             "press HUE/SAT/LUM, or clr/bw to convert the photo.", param)
                    return False
            await self.client.call("startTracking", param)
            return True
        except _ERRORS as e:
            log.warning("%s: couldn't start the turn (%s); ignoring it", param, e)
            return False
