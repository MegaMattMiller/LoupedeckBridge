from __future__ import annotations

import pytest

from bridge.dial_feel import ParamRange, detent_amount

# Real ranges from docs/lr_parameters_10.0.json
RANGES = {
    "Exposure2012": ParamRange(-5, 5, 2, 0.1, 0.33),
    "Contrast2012": ParamRange(-100, 100, 0, 10, 20),
    "Temperature": ParamRange(0, 100, 0, 1, 10),
    "straightenAngle": ParamRange(-45, 45, 1, 10, None),
}
SPEEDS = [0, 1, 5, 20, 60, 150]  # detents per second
ranges = pytest.mark.parametrize("name", sorted(RANGES))


def test_from_reply_five_and_four():
    assert ParamRange.from_reply([-5, 5, 2, 0.1, 0.33]) == ParamRange(-5, 5, 2, 0.1, 0.33)
    assert ParamRange.from_reply([-45, 45, 1, 10]) == ParamRange(-45, 45, 1, 10, None)


@ranges
def test_amount_is_visible(name):
    rng = RANGES[name]
    for speed in SPEEDS:
        assert detent_amount(rng, speed) >= 10 ** -rng.decimals, (name, speed)


@ranges
def test_slow_is_fine(name):
    rng = RANGES[name]
    for speed in (0, 1, 5):
        assert detent_amount(rng, speed) <= (rng.max - rng.min) / 100, (name, speed)


@ranges
def test_monotonic(name):
    rng = RANGES[name]
    amounts = [detent_amount(rng, s) for s in SPEEDS]
    assert amounts == sorted(amounts), (name, amounts)


@ranges
def test_fast_accelerates(name):
    rng = RANGES[name]
    assert detent_amount(rng, 150) >= 2 * detent_amount(rng, 1), name
