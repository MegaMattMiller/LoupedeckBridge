from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge.hardware import HardwareMap
from bridge.mapping import DEFAULT_PATH, Mapping, MappingNotWritable

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
    assert m.press_action("before_after") == {"type": "shortcut", "mac": ["\\"], "windows": ["\\"]}  # Show Original
    assert m.press_action("screen_mode") == {"type": "shortcut", "mac": ["f"], "windows": ["f"]}     # Full Screen Loupe
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


def two_defaults(tmp_path):
    """An 'old' and a 'new' shipped default that differ only in before_after."""
    old = json.loads(DEFAULT_PATH.read_text())
    old["controls"]["before_after"] = {"press": {"type": "none"}}
    old_path = tmp_path / "default_old.json"
    old_path.write_text(json.dumps(old))
    return old_path, DEFAULT_PATH


def test_unedited_mapping_follows_new_default(tmp_path):
    # Live-check finding: a mapping created from milestone 1's default kept "none" for
    # Before/After and screen mode after the default gained shortcuts for them.
    old_default, new_default = two_defaults(tmp_path)
    user = tmp_path / "m.json"
    Mapping.load(user, default_path=old_default)            # first run: copy of the old default
    m = Mapping.load(user, default_path=new_default)        # a release ships a better default
    assert m.press_action("before_after") == {"type": "shortcut", "mac": ["\\"], "windows": ["\\"]}
    assert json.loads(user.read_text()) == json.loads(new_default.read_text())  # file updated too


def test_unedited_controls_follow_new_default_even_if_others_edited(tmp_path):
    # Milestone 3: assigning presets must not freeze the rest of the layout.
    old_default, new_default = two_defaults(tmp_path)
    user = tmp_path / "m.json"
    Mapping.load(user, default_path=old_default)
    data = json.loads(user.read_text())
    data["controls"]["c3"] = {"press": {"type": "call", "message": "rating3", "args": []}}  # the user's own edit
    user.write_text(json.dumps(data))
    m = Mapping.load(user, default_path=new_default)
    assert m.press_action("c3") == {"type": "call", "message": "rating3", "args": []}             # kept
    assert m.press_action("before_after") == {"type": "shortcut", "mac": ["\\"], "windows": ["\\"]}  # followed
    assert m.warnings == []
    assert json.loads(user.read_text())["controls"]["before_after"]["press"]["type"] == "shortcut"


def test_user_change_wins_and_is_mentioned(tmp_path):
    old_default, new_default = two_defaults(tmp_path)
    user = tmp_path / "m.json"
    Mapping.load(user, default_path=old_default)
    data = json.loads(user.read_text())
    data["controls"]["before_after"] = {"press": {"type": "call", "message": "undo", "args": []}}
    user.write_text(json.dumps(data))
    m = Mapping.load(user, default_path=new_default)  # the default changed before_after too
    assert m.press_action("before_after") == {"type": "call", "message": "undo", "args": []}
    assert any("before_after" in w for w in m.warnings)


PRESET = {"type": "preset", "id": "A", "name": "Warm"}


def test_set_press_action_saves_atomically(tmp_path):
    user = tmp_path / "m.json"
    m = Mapping.load(user)
    m.set_press_action("p3", PRESET)
    assert m.press_action("p3") == PRESET
    assert Mapping.load(user).press_action("p3") == PRESET          # on disk, and kept on reload
    assert sorted(p.name for p in tmp_path.iterdir()) == ["m.base.json", "m.json"]  # no temp file left
    assert m.path == user


def test_set_press_action_rejects_invalid(tmp_path):
    user = tmp_path / "m.json"
    m = Mapping.load(user)
    before = user.read_text()
    with pytest.raises(ValueError):
        m.set_press_action("p3", {"type": "adjust", "param": "Exposure2012"})  # a turn action on a press
    assert user.read_text() == before


def test_unreadable_file_is_never_overwritten(tmp_path):
    user = tmp_path / "m.json"
    user.write_text("{not json")
    m = Mapping.load(user)
    with pytest.raises(MappingNotWritable):
        m.set_press_action("p3", PRESET)
    assert user.read_text() == "{not json"


def test_failed_save_leaves_no_phantom_change(tmp_path, monkeypatch):
    # Review: the in-memory document changed before the write; after a failed save, the next
    # successful one wrote the "failed" change too.
    from bridge import mapping as mapping_module
    user = tmp_path / "m.json"
    m = Mapping.load(user)
    real_write = mapping_module._write_atomic

    def full_disk(path, text):
        raise OSError("No space left on device")
    monkeypatch.setattr(mapping_module, "_write_atomic", full_disk)
    with pytest.raises(OSError):
        m.set_press_action("p3", PRESET)
    assert m.press_action("p3") != PRESET
    monkeypatch.setattr(mapping_module, "_write_atomic", real_write)
    m.set_press_action("p4", {"type": "preset", "id": "B", "name": "Cool"})
    saved = json.loads(user.read_text())["controls"]
    assert saved["p3"]["press"] == {"type": "preset", "id": None, "name": None}  # no phantom P3
    assert saved["p4"]["press"]["id"] == "B"


def test_assign_replaces_a_hand_broken_entry(tmp_path):
    user = write(tmp_path / "m.json", {"p3": "oops"})
    m = Mapping.load(user)
    m.set_press_action("p3", PRESET)
    assert Mapping.load(user).press_action("p3") == PRESET


def test_broken_controls_with_a_new_default_still_start(tmp_path):
    # Review: a broken file plus a changed default made Mapping.load raise, so the bridge
    # wouldn't start — instead of falling back to the default as the README promises.
    old_default, new_default = two_defaults(tmp_path)
    user = tmp_path / "m.json"
    Mapping.load(user, default_path=old_default)
    user.write_text(json.dumps({"version": 1, "controls": []}))
    m = Mapping.load(user, default_path=new_default)
    assert m.turn_action("exposure") == {"type": "adjust", "param": "Exposure2012"}
    assert m.writable is False


def test_open_settings_action(tmp_path):
    m = Mapping.load(tmp_path / "m.json")
    assert m.press_action("custom_mode") == {"type": "open_settings"}
    m2 = Mapping.load(write(tmp_path / "x.json", {"d1": {"turn": {"type": "open_settings"}}}))
    assert m2.turn_action("d1") == NONE and any("d1" in w for w in m2.warnings)


def test_user_file_replaces_default(tmp_path):
    m = Mapping.load(write(tmp_path / "m.json", {"c1": {"press": {"type": "call", "message": "undo", "args": []}}}))
    assert m.press_action("c1") == {"type": "call", "message": "undo", "args": []}
    assert m.turn_action("exposure") == NONE  # not in the user's file → nothing (no merging)
