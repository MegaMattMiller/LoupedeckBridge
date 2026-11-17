"""The list the Buttons & dials tab shows: every control (except Fn) with its normal and Fn actions."""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from bridge.commands import CommandCatalog
from bridge.hardware import COL, FIVE, FIVE_MODES
from bridge.mapping import FN_KEY, LAYERS

log = logging.getLogger("settings")

YOUR_BUTTONS = ["l1", "l2", "l3", "c1", "c2", "c3", "c4", "c5", "c6"]  # what the user mainly remaps
P_SLOTS = [f"p{i}" for i in range(1, 9)]
BANKS = ["hue", "sat", "lum", "bw"]
BANK_NAMES = {"hue": "Hue", "sat": "Sat", "lum": "Lum", "bw": "B&W"}
GROUPS = ["your", "five", "buttons", "dials", "colour"]
NAMES = {"clr_bw": "clr/bw", "col": "--/col", "custom_mode": "Custom mode", "before_after": "Before/After",
         "screen_mode": "Screen mode", "command": "Cmd", "ctrl": "Ctrl", "hue": "HUE", "sat": "SAT", "lum": "LUM",
         "up": "↑", "down": "↓", "left": "←", "right": "→"}
# Fixed slots with no mapped action of their own: what they do, shown instead.
FIXED_LABELS = {(COL, "normal", "press"): "Switch Ratings ↔ Colours", (COL, "fn", "press"): "Keys on / off"}
NOTES = {"custom_mode": "This button opens this page",
         "hue": "Also switches the colour dials' bank", "sat": "Also switches the colour dials' bank",
         "lum": "Also switches the colour dials' bank"}


def fixed_reason(control: str, layer: str, slot: str) -> Optional[str]:
    """Why a slot can't be changed on the page, or None if it can."""
    if control == "clr_bw" and slot == "press":
        return "Keeps the photo's black & white in step with the device"
    if (control, layer, slot) == ("export", "fn", "press"):
        return "Fixed: export with previous settings"
    if control in P_SLOTS and layer == "normal" and slot == "press":
        return "Set on the Presets tab"
    if control == COL and slot == "press":
        return "The five buttons' mode switch: Ratings ↔ Colours, and with Fn, Keys on / off"
    return None


def slots_of(kind: str) -> List[str]:
    return ["turn", "press"] if kind == "dial" else ["press"]


def _five_place(control: str) -> Optional[tuple]:
    """(mode, position) for the five buttons' per-mode ids, or None."""
    if control in FIVE:
        return "keys", FIVE.index(control) + 1
    head, _, tail = control.partition("_")
    if head in FIVE_MODES[:2] and tail.isdigit():
        return head, int(tail)
    return None


def _bank(control: str) -> Optional[str]:
    head = control.split("_", 1)[0]
    return head if "_" in control and head in BANKS else None


def _name(control: str) -> str:
    if control in NAMES:
        return NAMES[control]
    five = _five_place(control)
    if five and five[0] != "keys":
        return f"Button {five[1]}"
    if re.fullmatch(r"[a-z]\d", control):
        return control.upper()
    bank = _bank(control)
    if bank:
        return f"{BANK_NAMES[bank]} {control.split('_', 1)[1]}"
    return control.replace("_", " ").capitalize()


def _group(control: str, kind: str) -> str:
    if control in YOUR_BUTTONS:
        return "your"
    if _five_place(control):
        return "five"
    if kind == "button":
        return "buttons"
    return "colour" if _bank(control) else "dials"


def _describe(commands: CommandCatalog, control: str, action: dict) -> dict:
    """describe(), but one odd hand-edited action never takes the whole page down."""
    try:
        return commands.describe(action)
    except Exception:  # noqa: BLE001 — anything describe() can't handle
        log.warning("%s: can't show %r on the settings page", control, action)
        return {"label": "Unreadable action (see mapping.json)", "choice": None}


def rows(mapping, commands: CommandCatalog, controls: Dict[str, str]) -> List[dict]:
    """One row per control except Fn, in the order the tab shows them."""
    def order(c: str) -> tuple:
        five = _five_place(c)
        within = (YOUR_BUTTONS.index(c) if c in YOUR_BUTTONS else
                  (FIVE_MODES.index(five[0]), five[1]) if five else
                  BANKS.index(_bank(c)) if _bank(c) else 0)
        return GROUPS.index(_group(c, controls[c])), within

    ordered = sorted((c for c in controls if c != FN_KEY), key=order)  # stable: hardware order otherwise
    result = []
    for control in ordered:
        kind = controls[control]
        slots = slots_of(kind)
        normal = {s: _describe(commands, control,
                               mapping.turn_action(control) if s == "turn" else mapping.press_action(control))
                  for s in slots}
        fn = {}
        for s in slots:
            own = mapping.fn_action(control, s)
            fn[s] = None if own is None else _describe(commands, control, own)
        fixed = {}
        for layer in LAYERS:
            for s in slots:
                reason = fixed_reason(control, layer, s)
                if reason:
                    fixed[f"{layer}.{s}"] = reason
                if (control, layer, s) in FIXED_LABELS:
                    (normal if layer == "normal" else fn)[s] = {"label": FIXED_LABELS[(control, layer, s)], "choice": None}
        row = {"control": control, "name": _name(control), "group": _group(control, kind), "slots": slots,
               "normal": normal, "fn": fn, "fixed": fixed, "note": NOTES.get(control)}
        if row["group"] == "colour":
            row["bank"] = _bank(control)
        elif row["group"] == "five":
            row["bank"] = _five_place(control)[0]
        result.append(row)
    return result
