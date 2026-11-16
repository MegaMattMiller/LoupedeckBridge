from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, List, Set, Tuple

from bridge.actions import Dispatcher
from bridge.hardware import Press, Release, Turn
from bridge.lightroom import LightroomError
from bridge.mapping import Mapping

PRESET_NAMES = {"ID-WARM": "Warm", "ID-H1": "Heavy", "ID-H2": "Heavy"}


class FakeSession:
    """Answers like LightroomSession.call, with the real reply shapes."""

    def __init__(self) -> None:
        self.connected = True
        self.calls: List[Tuple[str, list]] = []
        self.failing: Set[str] = set()
        self.photo_bw = False  # Lightroom's B&W state for the current photo

    async def call(self, message, *params):
        self.calls.append((message, list(params)))
        if message in self.failing:
            raise LightroomError({"success": False, "response": ["invalid_request"], "requestId": "x"})
        if message == "isBlackAndWhiteOn":
            return [self.photo_bw, {"enabled": True, "title": "Convert to Black ＆ White", "checked": self.photo_bw}]
        if message == "toggleBlackAndWhite":
            self.photo_bw = not self.photo_bw
            return {}
        if message == "getPresetIDs":
            return [list(PRESET_NAMES)]
        if message == "getPresetName":
            return [PRESET_NAMES[params[0]]]
        return {}


class SpyDials:
    def __init__(self) -> None:
        self.added: List[Tuple[str, int]] = []

    def add(self, param, detents):
        self.added.append((param, detents))


def setup(tmp_path, controls: Dict[str, dict] = None):
    path = tmp_path / "m.json"
    if controls is not None:
        path.write_text(json.dumps({"version": 1, "controls": controls}))
    session, dials = FakeSession(), SpyDials()
    return Dispatcher(Mapping.load(path), session, dials), session, dials


def run(coro):
    return asyncio.run(coro)


def test_turn_adjust_goes_to_dials(tmp_path):
    d, s, dials = setup(tmp_path)  # default layout
    run(d.handle(Turn("exposure", -1)))
    assert dials.added == [("Exposure2012", -1)]
    assert s.calls == []


def test_step_calls_per_detent(tmp_path):
    d, s, _ = setup(tmp_path, {"control": {"turn": {
        "type": "step", "cw": {"message": "nextPhoto"}, "ccw": {"message": "previousPhoto"}}}})
    run(d.handle(Turn("control", -2)))
    run(d.handle(Turn("control", 1)))
    assert s.calls == [("previousPhoto", []), ("previousPhoto", []), ("nextPhoto", [])]


def test_press_call(tmp_path):
    d, s, _ = setup(tmp_path)
    run(d.handle(Press("c1")))
    run(d.handle(Press("c2")))
    assert s.calls == [("flagPickToggle", []), ("flagRejectToggle", [])]


def test_dial_click_resets(tmp_path):
    d, s, _ = setup(tmp_path)
    run(d.handle(Press("exposure")))
    assert s.calls == [("resetToDefault", ["Exposure2012"])]


def test_release_does_nothing(tmp_path):
    d, s, dials = setup(tmp_path)
    run(d.handle(Release("c1")))
    assert s.calls == [] and dials.added == []


def test_dropped_while_disconnected(tmp_path):
    d, s, dials = setup(tmp_path)
    s.connected = False
    run(d.handle(Turn("exposure", 3)))
    run(d.handle(Press("c1")))
    assert s.calls == [] and dials.added == []


def test_preset_by_id(tmp_path):
    d, s, _ = setup(tmp_path, {"p1": {"press": {"type": "preset", "id": "ID-WARM", "name": "Old name"}}})
    run(d.resolve_presets())
    run(d.handle(Press("p1")))
    assert s.calls[-1] == ("applyPreset", ["ID-WARM"])
    assert [m for m, _ in s.calls].count("getPresetName") == 0  # the id was enough
    assert d.preset_warnings == []


def test_preset_by_name_when_id_missing(tmp_path):
    d, s, _ = setup(tmp_path, {"p2": {"press": {"type": "preset", "id": "GONE", "name": "Warm"}}})
    run(d.resolve_presets())
    run(d.handle(Press("p2")))
    assert s.calls[-1] == ("applyPreset", ["ID-WARM"])


def test_preset_ambiguous_name_unresolved(tmp_path):
    d, s, _ = setup(tmp_path, {"p3": {"press": {"type": "preset", "id": None, "name": "Heavy"}}})
    run(d.resolve_presets())
    run(d.handle(Press("p3")))
    assert "applyPreset" not in [m for m, _ in s.calls]
    assert any("p3" in w and "Heavy" in w for w in d.preset_warnings)


def test_preset_missing_name_unresolved(tmp_path):
    d, s, _ = setup(tmp_path, {"p4": {"press": {"type": "preset", "id": None, "name": "Nope"}}})
    run(d.resolve_presets())
    run(d.handle(Press("p4")))
    assert "applyPreset" not in [m for m, _ in s.calls]
    assert any("p4" in w and "Nope" in w for w in d.preset_warnings)


def test_unassigned_preset_slot_is_quiet(tmp_path):
    d, s, _ = setup(tmp_path)  # default: p1–p8 unassigned
    run(d.resolve_presets())
    run(d.handle(Press("p5")))
    assert d.preset_warnings == []
    assert "applyPreset" not in [m for m, _ in s.calls]


def toggles(session):
    return [m for m, _ in session.calls].count("toggleBlackAndWhite")


def test_clr_bw_follows_device_mode_from_dial(tmp_path):
    # The live-check case: device in B&W mode (lights off), photo in colour.
    d, s, _ = setup(tmp_path)
    run(d.handle(Turn("bw_red", 1)))     # tells us the device is in its B&W mode
    run(d.handle(Press("clr_bw")))       # device → colour (HUE lights up)
    assert toggles(s) == 0 and s.photo_bw is False  # photo already colour: leave it
    run(d.handle(Press("clr_bw")))       # device → B&W (lights off)
    assert toggles(s) == 1 and s.photo_bw is True
    run(d.handle(Press("clr_bw")))       # device → colour
    assert toggles(s) == 2 and s.photo_bw is False


def test_clr_bw_after_mode_button(tmp_path):
    d, s, _ = setup(tmp_path)
    s.photo_bw = True                    # out of step: photo B&W…
    run(d.handle(Press("sat")))          # …device in colour mode (SAT lit)
    run(d.handle(Press("clr_bw")))       # device → B&W: photo already B&W, leave it
    assert toggles(s) == 0 and s.photo_bw is True


def test_clr_bw_colour_dial_means_colour_mode(tmp_path):
    d, s, _ = setup(tmp_path)
    run(d.handle(Turn("lum_aqua", -1)))  # device in colour mode
    run(d.handle(Press("clr_bw")))       # → B&W
    assert s.photo_bw is True


def test_clr_bw_unknown_mode_plain_toggle(tmp_path):
    d, s, _ = setup(tmp_path)            # nothing seen yet: best guess is a plain toggle
    run(d.handle(Press("clr_bw")))
    assert toggles(s) == 1
    assert "isBlackAndWhiteOn" not in [m for m, _ in s.calls]


def test_device_mode_tracked_while_disconnected(tmp_path):
    d, s, _ = setup(tmp_path)
    s.connected = False
    run(d.handle(Turn("bw_blue", 1)))    # dropped for Lightroom, but the device's mode is still learned
    s.connected = True
    run(d.handle(Press("clr_bw")))       # device → colour; photo is colour: nothing to do
    assert toggles(s) == 0


def test_lightroom_error_does_not_raise(tmp_path):
    d, s, _ = setup(tmp_path)
    s.failing.update({"flagPickToggle", "getPresetIDs"})
    run(d.handle(Press("c1")))
    run(d.resolve_presets())


def test_key_action_is_noop(tmp_path, caplog):
    d, s, dials = setup(tmp_path)
    with caplog.at_level(logging.INFO):
        run(d.handle(Press("shift")))
        run(d.handle(Press("left")))
    assert s.calls == [] and dials.added == []
    assert sum("milestone 2" in r.getMessage() for r in caplog.records) == 1  # said once, not per press
