from __future__ import annotations

import asyncio
import json
import logging
import sys
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
        self.slow: Set[str] = set()   # messages that wait for `gate` (a busy Lightroom)
        self.gate = None
        self.can_export = True        # canExportWithPrevious's answer

    async def call(self, message, *params):
        self.calls.append((message, list(params)))
        if message in self.slow:
            await self.gate.wait()
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
        if message == "canExportWithPrevious":
            return [self.can_export]
        return {}


class SpyDials:
    def __init__(self) -> None:
        self.added: List[Tuple[str, int]] = []

    def add(self, param, detents):
        self.added.append((param, detents))


class FakeKeyboard:
    """Records what the bridge would type; mirrors MacKeyboard's interface."""

    def __init__(self, trusted=True) -> None:
        self.events: List[tuple] = []
        self.trusted = trusted

    def _check(self, names):
        for n in names:
            if n == "hyper":
                raise ValueError("unknown key name 'hyper'")

    def key_down(self, name):
        self._check([name])
        self.events.append(("down", name))

    def key_up(self, name):
        self.events.append(("up", name))

    def key_repeat(self, name):
        self.events.append(("repeat", name))

    def tap(self, keys):
        self._check(keys)
        self.events.append(("tap", list(keys)))

    def is_trusted(self):
        return self.trusted


def setup(tmp_path, controls: Dict[str, dict] = None, keyboard=None):
    path = tmp_path / "m.json"
    if controls is not None:
        path.write_text(json.dumps({"version": 1, "controls": controls}))
    session, dials = FakeSession(), SpyDials()
    d = Dispatcher(Mapping.load(path), session, dials, keyboard=keyboard, repeat_delay=0.02, repeat_interval=0.01)
    return d, session, dials


def run(coro):
    return asyncio.run(coro)


def test_turn_adjust_goes_to_dials(tmp_path):
    d, s, dials = setup(tmp_path)  # default layout
    run(d.handle(Turn("exposure", -1)))
    assert dials.added == [("Exposure2012", -1)]
    assert s.calls == []


STEP_MAPPING = {"control": {"turn": {
    "type": "step", "cw": {"message": "nextPhoto"}, "ccw": {"message": "previousPhoto"}}},
    "c1": {"press": {"type": "call", "message": "flagPickToggle"}}}


async def settle():
    for _ in range(20):
        await asyncio.sleep(0)


def test_step_calls_per_detent(tmp_path):
    d, s, _ = setup(tmp_path, STEP_MAPPING)

    async def main():
        await d.handle(Turn("control", -2))
        await settle()
        await d.handle(Turn("control", 1))
        await settle()
    run(main())
    assert s.calls == [("previousPhoto", []), ("previousPhoto", []), ("nextPhoto", [])]


def test_step_drops_while_busy_and_never_blocks(tmp_path):
    # Review finding 4: steps were awaited inline, one per detent — a fast spin on a slow
    # action (nextPhoto) queued up, kept going after the user stopped, and blocked every other control.
    d, s, _ = setup(tmp_path, STEP_MAPPING)

    async def main():
        s.gate, s.slow = asyncio.Event(), {"nextPhoto"}
        for _ in range(10):  # a fast spin while Lightroom is busy with the first photo change
            await asyncio.wait_for(d.handle(Turn("control", 1)), 0.1)  # never waits on Lightroom
        await asyncio.wait_for(d.handle(Press("c1")), 0.1)            # other controls aren't blocked
        assert ("flagPickToggle", []) in s.calls
        s.gate.set()
        await settle()
    run(main())
    assert [m for m, _ in s.calls].count("nextPhoto") == 1  # no backlog: detents during the busy call are dropped


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


def test_bw_click_ignored_when_photo_colour(tmp_path):
    # Review finding 5: the B&W guard covered turns but not clicks — a click reset a saved B&W mix
    # on a colour photo. Spec: B&W-bank dials do nothing unless the photo is black & white.
    d, s, _ = setup(tmp_path)
    run(d.handle(Press("bw_red")))
    assert "resetToDefault" not in [m for m, _ in s.calls]
    s.photo_bw = True
    run(d.handle(Press("bw_red")))
    assert ("resetToDefault", ["GrayMixerRed"]) in s.calls


def test_device_mode_forgotten_on_reconnect(tmp_path):
    # Review finding 7: after an unplug the device may come back in its power-on mode; a stale
    # memory of its mode would make clr/bw leave lights and photo opposite again.
    d, s, _ = setup(tmp_path)
    run(d.handle(Turn("bw_red", 1)))  # learned: device in B&W mode
    d.device_reconnected()
    run(d.handle(Press("clr_bw")))     # mode unknown again → plain toggle
    assert toggles(s) == 1
    assert "isBlackAndWhiteOn" not in [m for m, _ in s.calls]


def test_slot_status(tmp_path):
    d, s, _ = setup(tmp_path, {
        "p1": {"press": {"type": "preset", "id": "ID-WARM", "name": "Warm"}},
        "p2": {"press": {"type": "preset", "id": None, "name": "Heavy"}},   # two presets have this name
        "p3": {"press": {"type": "preset", "id": None, "name": "Nope"}},    # no such preset
        "p4": {"press": {"type": "preset", "id": None, "name": None}},      # empty
    })
    assert d.slot_status("p1")["status"] == "unknown"   # before Lightroom has been asked
    assert d.slot_status("p4")["status"] == "empty"
    run(d.resolve_presets())
    assert d.slot_status("p1") == {"slot": "p1", "id": "ID-WARM", "name": "Warm", "status": "ok"}
    assert d.slot_status("p2")["status"] == "ambiguous"
    assert d.slot_status("p3")["status"] == "missing"
    assert d.slot_status("p4") == {"slot": "p4", "id": None, "name": None, "status": "empty"}


def test_reload_presets_after_a_change(tmp_path):
    d, s, _ = setup(tmp_path)  # default layout: p5 empty
    run(d.resolve_presets())
    d.mapping.set_press_action("p5", {"type": "preset", "id": "ID-WARM", "name": "Warm"})
    run(d.reload_presets())
    run(d.handle(Press("p5")))
    assert s.calls[-1] == ("applyPreset", ["ID-WARM"])


def test_stale_reload_does_not_overwrite_a_newer_one(tmp_path):
    # Review: a slow re-check started before a change finished after a newer one and put the
    # old preset back on P3 — the page said one preset, the button applied another.
    d, s, _ = setup(tmp_path, {"p3": {"press": {"type": "preset", "id": "ID-WARM", "name": "Warm"}}})
    real_ids = d.catalog.ids
    calls, gate = [], []

    async def slow_first_ids():
        calls.append(1)
        if len(calls) == 1:
            await gate[0].wait()
        return await real_ids()
    d.catalog.ids = slow_first_ids

    async def main():
        gate.append(asyncio.Event())                     # made inside the loop (Python 3.9)
        old = asyncio.ensure_future(d.reload_presets())   # e.g. the reconnect check, stuck waiting
        await asyncio.sleep(0)
        d.mapping.set_press_action("p3", {"type": "preset", "id": "ID-H2", "name": "Heavy"})
        await d.reload_presets()                         # the page's check after the change
        gate[0].set()
        await old
        await d.handle(Press("p3"))
    run(main())
    assert s.calls[-1] == ("applyPreset", ["ID-H2"])
    assert d.slot_status("p3")["id"] == "ID-H2"


def test_open_settings_opens_url(tmp_path):
    opened = []
    path = tmp_path / "m.json"
    session, dials = FakeSession(), SpyDials()
    d = Dispatcher(Mapping.load(path), session, dials, opener=opened.append, settings_url="http://127.0.0.1:7690/")
    session.connected = False                  # works without Lightroom
    run(d.handle(Press("custom_mode")))        # default layout: custom mode opens the settings page
    assert opened == ["http://127.0.0.1:7690/"]
    assert session.calls == []


def test_lightroom_error_does_not_raise(tmp_path):
    d, s, _ = setup(tmp_path)
    s.failing.update({"flagPickToggle", "getPresetIDs"})
    run(d.handle(Press("c1")))
    run(d.resolve_presets())


def test_no_keyboard_logs_once(tmp_path, caplog):
    d, s, dials = setup(tmp_path)  # keyboard=None, e.g. Windows before milestone 6
    with caplog.at_level(logging.INFO):
        run(d.handle(Press("shift")))
        run(d.handle(Press("left")))
        run(d.handle(Release("left")))
    assert s.calls == [] and dials.added == []
    assert sum("keyboard" in r.getMessage().lower() for r in caplog.records) == 1  # said once, not per press


def test_key_press_release_holds_key(tmp_path):
    kb = FakeKeyboard()
    d, s, _ = setup(tmp_path, keyboard=kb)
    run(d.handle(Press("shift")))
    assert kb.events == [("down", "shift")]
    run(d.handle(Release("shift")))
    assert kb.events == [("down", "shift"), ("up", "shift")]
    assert s.calls == []  # keys never touch Lightroom


def test_press_twice_single_down(tmp_path):
    kb = FakeKeyboard()
    d, _, _ = setup(tmp_path, keyboard=kb)
    run(d.handle(Press("command")))
    run(d.handle(Press("command")))  # e.g. a lost note-off
    run(d.handle(Release("command")))
    assert kb.events == [("down", "cmd"), ("up", "cmd")]


def test_release_without_press_noop(tmp_path):
    kb = FakeKeyboard()
    d, _, _ = setup(tmp_path, keyboard=kb)
    run(d.handle(Release("shift")))
    assert kb.events == []


def test_shortcut_taps_os_keys(tmp_path, monkeypatch):
    kb = FakeKeyboard()
    d, _, _ = setup(tmp_path, keyboard=kb)  # default layout
    monkeypatch.setattr(sys, "platform", "darwin")
    run(d.handle(Press("before_after")))
    run(d.handle(Press("screen_mode")))
    run(d.handle(Release("before_after")))  # a shortcut is a tap: nothing on release
    assert kb.events == [("tap", ["\\"]), ("tap", ["f"])]

    kb2 = FakeKeyboard()
    (tmp_path / "w").mkdir()
    d2, _, _ = setup(tmp_path / "w", {"c3": {"press": {"type": "shortcut", "mac": ["cmd", "z"], "windows": ["ctrl", "z"]}}},
                     keyboard=kb2)
    monkeypatch.setattr(sys, "platform", "win32")
    run(d2.handle(Press("c3")))
    assert kb2.events == [("tap", ["ctrl", "z"])]


def test_keys_without_permission_log_once(tmp_path, caplog):
    kb = FakeKeyboard(trusted=False)
    d, s, dials = setup(tmp_path, keyboard=kb)
    with caplog.at_level(logging.WARNING):
        run(d.handle(Press("shift")))
        run(d.handle(Release("shift")))
        run(d.handle(Press("before_after")))
        run(d.handle(Turn("exposure", 1)))  # other controls keep working
    assert kb.events == []
    assert dials.added == [("Exposure2012", 1)]
    warnings = [r.getMessage() for r in caplog.records if "Accessibility" in r.getMessage()]
    assert len(warnings) == 1 and "LoupedeckBridge" in warnings[0]


def test_keys_work_while_lightroom_disconnected(tmp_path):
    kb = FakeKeyboard()
    d, s, _ = setup(tmp_path, keyboard=kb)
    s.connected = False
    run(d.handle(Press("tab")))
    run(d.handle(Release("tab")))
    assert kb.events[0] == ("down", "tab") and kb.events[-1] == ("up", "tab")


def test_arrow_repeats_while_held(tmp_path):
    kb = FakeKeyboard()
    d, _, _ = setup(tmp_path, keyboard=kb)  # repeat_delay 0.02, repeat_interval 0.01

    async def main():
        await d.handle(Press("right"))
        await asyncio.sleep(0.08)
        await d.handle(Release("right"))
        repeats = kb.events.count(("repeat", "right"))
        await asyncio.sleep(0.05)
        return repeats
    repeats = run(main())
    assert repeats >= 2
    assert kb.events.count(("repeat", "right")) == repeats  # none after release
    assert kb.events[0] == ("down", "right") and kb.events[-1] == ("up", "right")


def test_modifier_does_not_repeat(tmp_path):
    kb = FakeKeyboard()
    d, _, _ = setup(tmp_path, keyboard=kb)

    async def main():
        await d.handle(Press("alt"))
        await asyncio.sleep(0.08)
    run(main())
    assert kb.events == [("down", "alt")]


def test_release_all_keys(tmp_path):
    kb = FakeKeyboard()
    d, _, _ = setup(tmp_path, keyboard=kb)

    async def main():
        await d.handle(Press("shift"))
        await d.handle(Press("down"))
        d.release_all_keys()
        await asyncio.sleep(0.06)  # the arrow's repeat must have stopped too
    run(main())
    assert ("up", "shift") in kb.events and ("up", "down") in kb.events
    assert ("repeat", "down") not in kb.events
    d.release_all_keys()  # nothing held: no extra ups
    assert sum(1 for e in kb.events if e[0] == "up") == 2


def test_unknown_shortcut_key_logged(tmp_path, caplog):
    kb = FakeKeyboard()
    d, _, _ = setup(tmp_path, {"c3": {"press": {"type": "shortcut", "mac": ["hyper"], "windows": ["hyper"]}}},
                    keyboard=kb)
    with caplog.at_level(logging.WARNING):
        run(d.handle(Press("c3")))  # must not raise
    assert kb.events == []
    assert any("c3" in r.getMessage() for r in caplog.records)


# ---- milestone 4: the Fn layer -------------------------------------------------
NONE = {"type": "none"}
RATING3 = {"type": "call", "message": "rating3", "args": []}


def test_key_released_even_if_fn_let_go_first(tmp_path):
    kb = FakeKeyboard()
    d, _, _ = setup(tmp_path, {"c3": {"press": NONE, "fn": {"press": {"type": "key", "key": "shift"}}}}, keyboard=kb)

    async def main():
        for e in (Press("fn"), Press("c3"), Release("fn"), Release("c3")):
            await d.handle(e)
    run(main())
    assert kb.events == [("down", "shift"), ("up", "shift")]


def test_reset_dial_follows_the_layers_turn(tmp_path):
    d, s, _ = setup(tmp_path, {"exposure": {"turn": {"type": "adjust", "param": "Exposure2012"},
                                            "press": {"type": "reset_dial"},
                                            "fn": {"turn": {"type": "adjust", "param": "Contrast2012"}}},
                               "d1": {"turn": NONE, "press": {"type": "reset_dial"}}})

    async def main():
        await d.handle(Press("exposure"))
        await d.handle(Release("exposure"))
        await d.handle(Press("fn"))
        await d.handle(Press("exposure"))
        await d.handle(Release("exposure"))
        await d.handle(Release("fn"))
        await d.handle(Press("d1"))
    run(main())
    assert s.calls == [("resetToDefault", ["Exposure2012"]), ("resetToDefault", ["Contrast2012"])]


def test_fn_layer_press_and_turn(tmp_path):
    d, s, dials = setup(tmp_path, {"c3": {"press": NONE, "fn": {"press": RATING3}},
                                   "exposure": {"turn": {"type": "adjust", "param": "Exposure2012"},
                                                "fn": {"turn": {"type": "adjust", "param": "Contrast2012"}}}})

    async def main():
        await d.handle(Press("c3"))
        await d.handle(Release("c3"))
        assert s.calls == []                       # normal layer: nothing
        await d.handle(Press("fn"))
        await d.handle(Press("c3"))
        await d.handle(Release("c3"))
        await d.handle(Turn("exposure", 1))
        await d.handle(Release("fn"))
        await d.handle(Turn("exposure", 1))
    run(main())
    assert s.calls == [("rating3", [])]
    assert dials.added == [("Contrast2012", 1), ("Exposure2012", 1)]


def test_fn_presses_do_nothing_else(tmp_path):
    d, s, _ = setup(tmp_path, {"fn": {"press": RATING3}})

    async def main():
        await d.handle(Press("fn"))
        held = d.fn_held
        await d.handle(Release("fn"))
        return held
    assert run(main()) is True
    assert d.fn_held is False
    assert s.calls == []


def test_fn_cleared_on_unplug_and_reconnect(tmp_path):
    # Review Focus 2: a layer can't stick after the device goes away.
    d, _, _ = setup(tmp_path)
    run(d.handle(Press("fn")))
    d.release_all_keys()                           # unplugged (or the bridge stopping)
    assert d.fn_held is False
    run(d.handle(Press("fn")))
    d.device_reconnected()
    assert d.fn_held is False


def test_clr_bw_syncs_whatever_it_maps_to(tmp_path):
    d, s, _ = setup(tmp_path, {"clr_bw": {"press": NONE, "fn": {"press": RATING3}},
                               "bw_red": {"turn": {"type": "adjust", "param": "GrayMixerRed"}}})

    async def main():
        await d.handle(Turn("bw_red", 1))          # the device is in its B&W mode
        await d.handle(Press("fn"))
        await d.handle(Press("clr_bw"))            # device → colour; photo is colour: in step
        await d.handle(Release("clr_bw"))
        await d.handle(Press("clr_bw"))            # device → B&W; photo colour → toggle
        await d.handle(Release("clr_bw"))
    run(main())
    messages = [m for m, _ in s.calls]
    assert messages.count("toggleBlackAndWhite") == 1 and "rating3" not in messages


def test_bw_guard_only_for_gray_mixer_resets(tmp_path):
    d, s, _ = setup(tmp_path, {"bw_red": {"turn": {"type": "adjust", "param": "GrayMixerRed"},
                                          "press": RATING3},
                               "bw_blue": {"turn": {"type": "adjust", "param": "GrayMixerBlue"},
                                           "press": {"type": "reset_dial"}}})
    run(d.handle(Press("bw_red")))                 # photo is colour, but this isn't a B&W mix reset
    run(d.handle(Press("bw_blue")))                # a B&W mix reset on a colour photo: ignored
    messages = [m for m, _ in s.calls]
    assert "rating3" in messages and "resetToDefault" not in messages


def test_export_with_previous_checks_first(tmp_path):
    d, s, _ = setup(tmp_path)

    async def fn_export():
        await d.handle(Press("fn"))
        await d.handle(Press("export"))
        await d.handle(Release("export"))
        await d.handle(Release("fn"))
    s.can_export = False
    run(fn_export())
    assert s.calls == [("canExportWithPrevious", [])]
    s.can_export = True
    run(fn_export())
    assert s.calls[-2:] == [("canExportWithPrevious", []), ("exportWithPrevious", [])]
