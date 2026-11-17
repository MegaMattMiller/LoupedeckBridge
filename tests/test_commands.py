"""The command catalog: what the settings page may put on a control (milestone 4)."""
from __future__ import annotations

import json

import pytest

from bridge.commands import COMMANDS_PATH, CommandCatalog
from bridge.mapping import DEFAULT_PATH

REQUIRED = {  # id: (message, args) — the defaults and the design's examples
    "flag_pick_toggle": ("flagPickToggle", []), "flag_reject_toggle": ("flagRejectToggle", []),
    "rating_3": ("rating3", []), "rating_up": ("ratingIncrease", []), "rating_down": ("ratingDecrease", []),
    "label_red": ("colorLabelRed", []), "next_photo": ("nextPhoto", []), "previous_photo": ("previousPhoto", []),
    "zoom_to_fit": ("zoomToFit", []), "crop_tool": ("selectTool", ["crop"]), "auto_tone": ("setAutoTone", []),
    "undo": ("undo", []), "redo": ("redo", []), "copy_settings": ("copyEditSettings", []),
    "paste_settings": ("pasteEditSettings", []), "open_export": ("openExport", []),
}
EXCLUDED = {"exportWithPrevious", "toggleBlackAndWhite", "applyPreset", "setTrackingDelay",
            "setMultipleAdjustmentThreshold", "startTracking", "stopTracking", "increment", "decrement"}


@pytest.fixture(scope="module")
def c():
    return CommandCatalog.load()


def test_required_and_excluded(c):
    for cid, (msg, args) in REQUIRED.items():
        assert (c.commands[cid]["message"], c.commands[cid]["args"]) == (msg, args), cid
    messages = {x["message"] for x in c.commands.values()}
    assert not messages & EXCLUDED
    assert not [m for m in messages if m.startswith(("get", "is", "can", "add")) or m.endswith("WithName")]


def test_ids_unique_and_pairs_reference_commands(c):
    raw = json.loads(COMMANDS_PATH.read_text())
    ids = [x["id"] for x in raw["commands"]] + [x["id"] for x in raw["pairs"]]
    assert len(ids) == len(set(ids))
    for pair in c.pairs.values():
        assert pair["cw"] in c.commands and pair["ccw"] in c.commands, pair["id"]
    directions = {(p["ccw"], p["cw"]) for p in c.pairs.values()}
    assert {("previous_photo", "next_photo"), ("rating_down", "rating_up")} <= directions
    assert any(c.commands[ccw]["message"] == "zoomOutSome" and c.commands[cw]["message"] == "zoomInSome"
               for ccw, cw in directions)


def test_sliders_are_number_params(c):
    assert c.sliders["Exposure2012"] == "Exposure"
    assert "AutoGrayscaleMix" not in c.sliders            # a boolean, not a slider
    assert len(c.sliders) > 100


def test_slider_labels_are_unique_and_readable(c):
    # Browser check: Lightroom's own labels repeat (11 sliders are just "Hue"), so the list
    # and the colour-dial rows couldn't be told apart.
    labels = list(c.sliders.values())
    assert len(labels) == len(set(labels))
    assert c.sliders["Clarity2012"] == "Clarity" and c.sliders["Exposure2012"] == "Exposure"
    assert c.sliders["HueAdjustmentRed"] == "Hue (HSL red)"
    assert c.sliders["SaturationAdjustmentAqua"] == "Saturation (HSL aqua)"
    assert c.sliders["RedHue"] == "Hue (Red primary)"
    assert c.sliders["SDRClarity"] == "Clarity (SDR)"
    assert c.sliders["SharpenDetail"] == "Detail (Sharpen)"
    assert c.sliders["GrayMixerRed"] == "B&W mix (red)"          # Lightroom just says "Red"


def test_action_for_each_kind_and_refusals(c):
    assert c.action_for({"kind": "command", "id": "rating_3"}, "press") == \
        {"type": "call", "message": "rating3", "args": []}
    assert c.action_for({"kind": "slider", "param": "Exposure2012"}, "turn") == \
        {"type": "adjust", "param": "Exposure2012"}
    pid = next(p["id"] for p in c.pairs.values() if p["cw"] == "next_photo")
    assert c.action_for({"kind": "pair", "id": pid}, "turn") == {
        "type": "step", "cw": {"type": "call", "message": "nextPhoto", "args": []},
        "ccw": {"type": "call", "message": "previousPhoto", "args": []}}
    assert c.action_for({"kind": "reset_dial"}, "press") == {"type": "reset_dial"}
    assert c.action_for({"kind": "open_settings"}, "press") == {"type": "open_settings"}
    assert c.action_for({"kind": "none"}, "turn") == {"type": "none"}
    assert c.action_for({"kind": "same"}, "press") is None
    refused = [
        ({"kind": "slider", "param": "Exposure2012"}, "press"),
        ({"kind": "command", "id": "rating_3"}, "turn"),
        ({"kind": "command", "id": "no_such_command"}, "press"),
        ({"kind": "slider", "param": "AutoGrayscaleMix"}, "turn"),
        ({"kind": "pair", "id": "no_such_pair"}, "turn"),
        ({"kind": "key", "key": "shift"}, "press"),
        ({"kind": "shortcut", "mac": ["cmd", "q"]}, "press"),
        ({"kind": "reset_dial"}, "turn"),
        ({"kind": "open_settings"}, "turn"),
        ({"kind": "command"}, "press"),
        ({}, "press"),
        ({"kind": "none"}, "spin"),
    ]
    for choice, slot in refused:
        with pytest.raises(ValueError):
            c.action_for(choice, slot)


def test_describe_round_trips_every_choice(c):
    for cid in c.commands:
        choice = {"kind": "command", "id": cid}
        assert c.describe(c.action_for(choice, "press"))["choice"] == choice
    for param in c.sliders:
        choice = {"kind": "slider", "param": param}
        assert c.describe(c.action_for(choice, "turn"))["choice"] == choice
    for pid in c.pairs:
        choice = {"kind": "pair", "id": pid}
        assert c.describe(c.action_for(choice, "turn"))["choice"] == choice
    for kind, slot in (("reset_dial", "press"), ("open_settings", "press"), ("none", "press")):
        assert c.describe(c.action_for({"kind": kind}, slot))["choice"] == {"kind": kind}


def test_describe_labels(c):
    def label(action):
        return c.describe(action)["label"]
    assert label({"type": "call", "message": "resetToDefault", "args": ["Exposure2012"]}) == "Reset Exposure"
    assert label({"type": "key", "key": "shift"}) == "Key: Shift"
    assert label({"type": "shortcut", "mac": ["cmd", "e"], "windows": ["ctrl", "e"]}) == "Shortcut: cmd + e"
    assert label({"type": "preset", "id": "A", "name": "Warm"}) == "Preset: Warm"
    assert label({"type": "reset_dial"}) == "Reset this dial's slider"
    assert label({"type": "none"}) == "Nothing"
    assert label({"type": "open_settings"}) == "Open this settings page"
    assert label({"type": "call", "message": "exportWithPrevious", "args": []}) == "Export with previous settings"
    assert label({"type": "call", "message": "toggleBlackAndWhite", "args": []}) == \
        "Black & white (kept in step with the device)"
    odd = c.describe({"type": "call", "message": "fooBar", "args": []})
    assert odd == {"label": "Lightroom: fooBar", "choice": None}
    assert c.describe({"type": "key", "key": "shift"})["choice"] is None   # the page can't make keys
    for control, entry in json.loads(DEFAULT_PATH.read_text())["controls"].items():
        for layer in (entry, entry.get("fn", {})):
            for slot in ("turn", "press"):
                if slot in layer:
                    assert not label(layer[slot]).startswith("Lightroom:"), (control, layer[slot])


def test_to_page(c):
    page = c.to_page()
    assert page["type"] == "catalog"
    assert {"id": "rating_3", "label": c.commands["rating_3"]["label"], "group": c.commands["rating_3"]["group"]} \
        in page["commands"]
    labels = [label for _, label in page["sliders"]]
    assert labels == sorted(labels, key=str.casefold)
