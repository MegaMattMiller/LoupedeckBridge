from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge.hardware import HardwareMap, Press, Release, Turn

CAPTURES = Path(__file__).resolve().parent.parent / "captures"


@pytest.fixture(scope="module")
def hw() -> HardwareMap:
    return HardwareMap.load()


def test_turn_directions(hw):
    assert hw.decode("control_change", 33, 1) == Turn("exposure", 1)
    assert hw.decode("control_change", 33, 127) == Turn("exposure", -1)
    assert hw.decode("control_change", 33, 0) is None  # no movement, no event


def test_colour_banks(hw):
    assert hw.decode("control_change", 1, 1) == Turn("hue_red", 1)
    assert hw.decode("control_change", 16, 1) == Turn("sat_magenta", 1)
    assert hw.decode("control_change", 21, 127) == Turn("lum_aqua", -1)
    assert hw.decode("control_change", 25, 1) == Turn("bw_red", 1)
    assert hw.decode("control_change", 32, 1) == Turn("bw_magenta", 1)


def test_clicks_and_buttons(hw):
    assert hw.decode("note_on", 33, 64) == Press("exposure")
    assert hw.decode("note_off", 33, 64) == Release("exposure")
    assert hw.decode("note_on", 66, 64) == Press("shift")
    assert hw.decode("note_on", 66, 0) == Release("shift")
    assert hw.decode("note_on", 17, 64) == Press("lum_red")  # colour-dial click, LUM bank


def test_unknown_numbers(hw):
    assert hw.decode("control_change", 43, 1) is None
    assert hw.decode("note_on", 127, 64) is None
    assert hw.decode("pitchwheel", 0, 0) is None


def test_every_captured_message_decodes(hw):
    files = sorted(CAPTURES.glob("raw-*.jsonl"))
    assert files, "expected the Step 1 captures in captures/"
    seen = 0
    for path in files:
        for line in path.read_text().splitlines():
            rec = json.loads(line)
            if "marker" in rec:
                continue
            number = rec.get("control", rec.get("note"))
            value = rec.get("value", rec.get("velocity"))
            assert hw.decode(rec["type"], number, value) is not None, (path.name, rec)
            seen += 1
    assert seen > 1000


def test_controls_catalogue(hw):
    assert len(hw.controls) == 14 + 32 + 40 + 10      # + the five buttons' Ratings and Colours ids (milestone 4)
    assert hw.controls["ratings_1"] == "button" and hw.controls["colours_5"] == "button"
    assert hw.controls["exposure"] == "dial"
    assert hw.controls["bw_red"] == "dial"
    assert hw.controls["control"] == "dial"
    assert hw.controls["c1"] == "button"
    assert hw.controls["shift"] == "button"
