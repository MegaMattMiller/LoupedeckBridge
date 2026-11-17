"""The per-control list the Buttons & dials tab shows (milestone 4)."""
from __future__ import annotations

from bridge.commands import CommandCatalog
from bridge.hardware import HardwareMap
from bridge.mapping import Mapping
from bridge.settings.layout import YOUR_BUTTONS, fixed_reason, rows


def build(tmp_path):
    return rows(Mapping.load(tmp_path / "m.json"), CommandCatalog.load(), HardwareMap.load().controls)


def test_rows_order_groups_and_fn(tmp_path):
    r = build(tmp_path)
    by = {row["control"]: row for row in r}
    assert [row["control"] for row in r[:9]] == YOUR_BUTTONS
    assert all(row["group"] == "your" for row in r[:9])
    assert "fn" not in by
    assert len(r) == len(HardwareMap.load().controls) - 1
    groups = [row["group"] for row in r]
    assert groups == sorted(groups, key=["your", "buttons", "dials", "colour"].index)  # sections in order
    exposure = by["exposure"]
    assert exposure["slots"] == ["turn", "press"] and exposure["group"] == "dials"
    assert exposure["normal"]["press"]["label"] == "Reset this dial's slider"
    assert exposure["normal"]["turn"]["label"] == "Exposure"
    assert "fn.press" in by["export"]["fixed"] and by["export"]["fn"]["press"]["label"] == "Export with previous settings"
    assert "normal.press" in by["p1"]["fixed"] and "fn.press" not in by["p1"]["fixed"]
    assert set(by["clr_bw"]["fixed"]) == {"normal.press", "fn.press"}
    assert by["hue_red"]["group"] == "colour" and by["hue_red"]["bank"] == "hue"
    assert by["c3"]["slots"] == ["press"] and by["c3"]["name"] == "C3"
    assert by["custom_mode"]["note"] and by["hue"]["note"] and by["c3"]["note"] is None
    banks = [row["bank"] for row in r if row["group"] == "colour"]
    assert banks == sorted(banks, key=["hue", "sat", "lum", "bw"].index)


def test_fn_column_same_as_normal_is_none(tmp_path):
    by = {row["control"]: row for row in build(tmp_path)}
    assert by["c3"]["fn"]["press"] is None
    assert by["exposure"]["fn"] == {"turn": None, "press": None}


def test_fixed_reasons():
    assert fixed_reason("clr_bw", "fn", "press") and fixed_reason("clr_bw", "normal", "press")
    assert fixed_reason("export", "fn", "press") and fixed_reason("export", "normal", "press") is None
    assert fixed_reason("p8", "normal", "press") and fixed_reason("p8", "fn", "press") is None
    assert fixed_reason("c3", "fn", "press") is None
