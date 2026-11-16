"""How a dial turn becomes slider movement. `detent_amount` is written by the project owner."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ---- Tune these after trying the dials -------------------------------------------------------
SLOW_FRACTION = 0.005  # one slow click moves 0.5% of the full travel (1 pt on ±100 sliders, 0.05 EV)
ACCEL_START = 5.0      # clicks/s at or below which there's no acceleration (careful nudging)
ACCEL_FULL = 100.0     # clicks/s at which acceleration reaches its maximum
MAX_MULTIPLIER = 8.0   # a full-speed spin moves this many times the slow amount per click
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ParamRange:
    """One parameter's range, as Lightroom's getRange returns it (read live, per photo)."""
    min: float
    max: float
    decimals: int               # 0 = whole numbers, 2 = e.g. 0.33 EV
    small_step: float           # Lightroom's own small nudge (10 for ±100 sliders, 0.1 EV for Exposure)
    large_step: Optional[float]  # missing for a few parameters (e.g. straightenAngle)

    @classmethod
    def from_reply(cls, values: list) -> "ParamRange":
        """getRange replies with 5 values, or 4 when there's no large step."""
        lo, hi, decimals, small = values[:4]
        large = values[4] if len(values) > 4 else None
        return cls(lo, hi, int(decimals), small, large)


def detent_amount(rng: ParamRange, detents_per_sec: float) -> float:
    """How far ONE detent (one click of a dial) moves this parameter, given how fast the dial
    is turning right now. The dial engine multiplies by the number of detents and rounds the
    result to `rng.decimals`, then sends it to Lightroom as increment/decrement.

    Inputs you can use:
      rng.max - rng.min   the full travel (200 for Contrast, 10 EV for Exposure, 90° for Straighten)
      rng.decimals        the finest visible step is 10 ** -rng.decimals
      rng.small_step      Lightroom's keyboard nudge (coarse: 10 on ±100 sliders)
      detents_per_sec     ~0–5 slow and careful, ~20 brisk, 60–150 a fast spin

    The tests in tests/test_dial_feel.py pin only the essentials:
      - one detent always makes a visible change   (>= 10 ** -decimals)
      - slow turns are fine-grained                 (<= 1% of the full travel at <= 5 detents/s)
      - faster never means smaller                  (non-decreasing in speed)
      - fast spins really accelerate                (150/s gives >= 2x the amount at 1/s)
    """
    fine = 10 ** -rng.decimals                                 # smallest change Lightroom can show
    base = max(fine, (rng.max - rng.min) * SLOW_FRACTION)      # slow clicks: precise, never invisible
    # 0 when slow, 1 at full speed; squared so brisk turning stays close to 1x and only
    # a real spin takes off.
    t = min(max((detents_per_sec - ACCEL_START) / (ACCEL_FULL - ACCEL_START), 0.0), 1.0)
    return base * (1 + (MAX_MULTIPLIER - 1) * t * t)
