from __future__ import annotations

import json
from pathlib import Path

from bridge.hardware import HardwareMap
from bridge.mapping import DEFAULT_PATH, Mapping

REPO = Path(__file__).resolve().parent.parent
NONE = {"type": "none"}


def write(path: Path, controls: dict) -> Path:
    path.write_text(json.dumps({"version": 1, "controls": controls}))
    return path


def test_default_covers_every_control(tmp_path):
    m = Mapping.load(tmp_path / "m.json")
    raw = json.loads(DEFAULT_PATH.read_text())["controls"]
    for control, kind in HardwareMap.load().controls.items():
        assert control in raw, control
        if kind == "dial":
            assert "turn" in raw[control] and "press" in raw[control], control
        else:
            assert "press" in raw[control], control
    assert m.warnings == []  # the shipped default is itself valid


def test_default_layout_spot_checks(tmp_path):
    m = Mapping.load(tmp_path / "m.json")
    assert m.turn_action("exposure") == {"type": "adjust", "param": "Exposure2012"}
    assert m.press_action("exposure") == {"type": "call", "message": "resetToDefault", "args": ["Exposure2012"]}
    assert m.turn_action("control") == {"type": "adjust", "param": "straightenAngle"}
    assert m.turn_action("d2") == {"type": "adjust", "param": "Dehaze"}
    assert m.turn_action("sat_aqua") == {"type": "adjust", "param": "SaturationAdjustmentAqua"}
    assert m.turn_action("bw_magenta") == {"type": "adjust", "param": "GrayMixerMagenta"}
    assert m.press_action("c1") == {"type": "call", "message": "flagPickToggle", "args": []}
    assert m.press_action("c2") == {"type": "call", "message": "flagRejectToggle", "args": []}
    assert m.press_action("export") == {"type": "call", "message": "openExport", "args": []}
    assert m.press_action("p3") == {"type": "preset", "id": None, "name": None}
    assert m.press_action("command") == {"type": "key", "key": "cmd"}
    assert m.press_action("left") == {"type": "key", "key": "left"}
    assert m.press_action("before_after") == NONE
    assert m.press_action("l2") == NONE


def test_default_params_exist(tmp_path):
    known = json.loads((REPO / "docs" / "lr_parameters_10.0.json").read_text())
    raw = json.loads(DEFAULT_PATH.read_text())["controls"]
    params = []
    for entry in raw.values():
        turn, press = entry.get("turn", {}), entry.get("press", {})
        if turn.get("type") == "adjust":
            params.append(turn["param"])
        if press.get("type") == "call" and press["message"] == "resetToDefault":
            params.extend(press["args"])
    assert len(params) == 2 * (14 + 32)
    assert [p for p in params if p not in known] == []


def test_first_run_copies_default(tmp_path):
    user = tmp_path / "sub" / "m.json"
    Mapping.load(user)
    assert json.loads(user.read_text()) == json.loads(DEFAULT_PATH.read_text())


def test_corrupt_user_file_falls_back(tmp_path):
    user = tmp_path / "m.json"
    user.write_text("{not json")
    m = Mapping.load(user)
    assert m.turn_action("exposure") == {"type": "adjust", "param": "Exposure2012"}
    assert user.read_text() == "{not json"
    assert any("m.json" in w for w in m.warnings)


def test_invalid_entry_becomes_none(tmp_path):
    m = Mapping.load(write(tmp_path / "m.json", {"exposure": {"turn": {"type": "adjust"}},
                                                  "c1": {"press": {"type": "call", "message": "undo"}}}))
    assert m.turn_action("exposure") == NONE
    assert any("exposure" in w for w in m.warnings)
    assert m.press_action("c1") == {"type": "call", "message": "undo", "args": []}  # args default to []


def test_malformed_key_value_warns_instead_of_crashing(tmp_path):
    # Review finding 3: an unhashable "key" value raised TypeError and the bridge wouldn't start.
    m = Mapping.load(write(tmp_path / "m.json", {"shift": {"press": {"type": "key", "key": ["shift"]}},
                                                  "tab": {"press": {"type": "key", "key": {"k": 1}}}}))
    assert m.press_action("shift") == NONE and m.press_action("tab") == NONE
    assert any("shift" in w for w in m.warnings) and any("tab" in w for w in m.warnings)


def test_non_object_entry_warns(tmp_path):
    m = Mapping.load(write(tmp_path / "m.json", {"exposure": 5}))
    assert m.turn_action("exposure") == NONE
    assert any("exposure" in w for w in m.warnings)


def test_press_type_rejected_for_turn(tmp_path):
    m = Mapping.load(write(tmp_path / "m.json", {
        "exposure": {"turn": {"type": "call", "message": "undo", "args": []}},
        "c1": {"press": {"type": "adjust", "param": "Exposure2012"}},
        "c2": {"press": {"type": "key", "key": "capslock"}},
        "p1": {"press": {"type": "preset", "id": None, "name": None}},
    }))
    assert m.turn_action("exposure") == NONE
    assert m.press_action("c1") == NONE
    assert m.press_action("c2") == NONE
    assert m.press_action("p1") == {"type": "preset", "id": None, "name": None}  # unassigned slot is valid
    assert len(m.warnings) == 3


def test_press_items_lists_press_actions(tmp_path):
    m = Mapping.load(write(tmp_path / "m.json", {
        "p1": {"press": {"type": "preset", "id": "ABC", "name": "Warm"}},
        "exposure": {"turn": {"type": "adjust", "param": "Exposure2012"}},
    }))
    assert dict(m.press_items()) == {"p1": {"type": "preset", "id": "ABC", "name": "Warm"}}


def test_user_file_replaces_default(tmp_path):
    m = Mapping.load(write(tmp_path / "m.json", {"c1": {"press": {"type": "call", "message": "undo", "args": []}}}))
    assert m.press_action("c1") == {"type": "call", "message": "undo", "args": []}
    assert m.turn_action("exposure") == NONE  # not in the user's file → nothing (no merging)
