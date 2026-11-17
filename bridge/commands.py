"""What the settings page may put on a control, and how to describe any action in plain words.

The page sends a *choice* ({"kind": "command", "id": "rating_3"}, {"kind": "slider", "param": …}, …);
`action_for` turns it into a mapping action, and nothing outside these kinds can be made. In
particular, keyboard keys and shortcuts can't: the page's secret must never be enough to make the
Loupedeck type keys.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
COMMANDS_PATH = ROOT / "config" / "commands.json"
PARAMS_PATH = ROOT / "docs" / "lr_parameters_10.0.json"

KEY_LABELS = {"shift": "Shift", "ctrl": "Ctrl", "cmd": "Cmd", "alt": "Alt", "tab": "Tab",
              "left": "Left arrow", "right": "Right arrow", "up": "Up arrow", "down": "Down arrow"}
# Calls the page doesn't offer but that appear in the default layout.
SPECIAL_LABELS = {"toggleBlackAndWhite": "Black & white (kept in step with the device)",
                  "exportWithPrevious": "Export with previous settings"}
PRESS_ONLY = {"command", "reset_dial", "open_settings"}
TURN_ONLY = {"slider", "pair"}


HSL = re.compile(r"(Hue|Saturation|Luminance)Adjustment(\w+)")
PRIMARY = re.compile(r"(Red|Green|Blue)(Hue|Saturation)")
GRAY = re.compile(r"GrayMixer(\w+)")


def _words(name: str) -> list:
    return re.findall(r"[A-Z]+(?=[A-Z][a-z]|\b|\d)|[A-Z]?[a-z]+|\d+", name.replace(".", " "))


def _slider_labels(params: Dict[str, dict]) -> Dict[str, str]:
    """Lightroom's labels repeat (11 sliders are just "Hue"), so a repeated label gets a qualifier
    from the parameter's name: "Hue (HSL red)", "Hue (Red primary)", "Clarity (SDR)"."""
    plain = {name: (info.get("label") or name).rstrip(":").strip() for name, info in params.items()
             if isinstance(info, dict) and info.get("type") == "number"}
    counts = Counter(plain.values())
    labels: Dict[str, str] = {}
    for name, label in plain.items():
        gray = GRAY.fullmatch(name)
        if gray:  # Lightroom labels these just "Red", "Orange", …
            label = f"B&W mix ({gray.group(1).lower()})"
        elif counts[label] > 1:
            hsl, primary = HSL.fullmatch(name), PRIMARY.fullmatch(name)
            if hsl:
                qualifier = f"HSL {hsl.group(2).lower()}"
            elif primary:
                qualifier = f"{primary.group(1)} primary"
            else:
                taken = {w.lower() for w in _words(label)} | {"2012"}
                qualifier = " ".join(w for w in _words(name) if w.lower() not in taken)
            label = f"{label} ({qualifier})" if qualifier else label
        labels[name] = label
    clashes = Counter(labels.values())
    return {name: (f"{label} [{name}]" if clashes[label] > 1 else label) for name, label in labels.items()}


def _call(command: dict) -> dict:
    return {"type": "call", "message": command["message"], "args": list(command["args"])}


class CommandCatalog:
    def __init__(self, commands: Dict[str, dict], pairs: Dict[str, dict], sliders: Dict[str, str]):
        self.commands, self.pairs, self.sliders = commands, pairs, sliders
        self._by_call: Dict[Tuple[str, str], str] = {
            (c["message"], json.dumps(c["args"])): cid for cid, c in commands.items()}

    @classmethod
    def load(cls, commands_path: Path = COMMANDS_PATH, params_path: Path = PARAMS_PATH) -> "CommandCatalog":
        raw = json.loads(commands_path.read_text())
        commands = {c["id"]: {"id": c["id"], "label": c["label"], "group": c["group"],
                              "message": c["message"], "args": list(c.get("args", []))} for c in raw["commands"]}
        pairs = {p["id"]: {"id": p["id"], "label": p["label"], "cw": p["cw"], "ccw": p["ccw"]} for p in raw["pairs"]}
        return cls(commands, pairs, _slider_labels(json.loads(params_path.read_text())))

    # ---- page choice → mapping action -------------------------------------------
    def action_for(self, choice: dict, slot: str) -> Optional[dict]:
        """The mapping action for a page choice in a slot ("turn"/"press"); None means "same as normal".
        Raises ValueError for anything the page isn't allowed to make."""
        if slot not in ("turn", "press"):
            raise ValueError(f"unknown slot {slot!r}")
        kind = choice.get("kind") if isinstance(choice, dict) else None
        if kind == "same":
            return None
        if kind == "none":
            return {"type": "none"}
        if (kind in PRESS_ONLY and slot != "press") or (kind in TURN_ONLY and slot != "turn"):
            raise ValueError(f"{kind!r} can't go on a {slot}")
        if kind == "command" and choice.get("id") in self.commands:
            return _call(self.commands[choice["id"]])
        if kind == "reset_dial":
            return {"type": "reset_dial"}
        if kind == "open_settings":
            return {"type": "open_settings"}
        if kind == "slider" and choice.get("param") in self.sliders:
            return {"type": "adjust", "param": choice["param"]}
        if kind == "pair" and choice.get("id") in self.pairs:
            pair = self.pairs[choice["id"]]
            return {"type": "step", "cw": _call(self.commands[pair["cw"]]), "ccw": _call(self.commands[pair["ccw"]])}
        raise ValueError(f"not something the settings page can assign: {choice!r}")

    # ---- mapping action → words ---------------------------------------------------
    def describe(self, action: dict) -> dict:
        """{"label": plain words for any mapping action, "choice": the page choice that makes it, or None}."""
        kind = action.get("type")
        if kind == "none":
            return {"label": "Nothing", "choice": {"kind": "none"}}
        if kind == "open_settings":
            return {"label": "Open this settings page", "choice": {"kind": "open_settings"}}
        if kind == "reset_dial":
            return {"label": "Reset this dial's slider", "choice": {"kind": "reset_dial"}}
        if kind == "adjust":
            param = action["param"]
            if param in self.sliders:
                return {"label": self.sliders[param], "choice": {"kind": "slider", "param": param}}
            return {"label": f"Slider: {param}", "choice": None}
        if kind == "step":
            cw, ccw = self._command_id(action["cw"]), self._command_id(action["ccw"])
            for pair in self.pairs.values():
                if (pair["cw"], pair["ccw"]) == (cw, ccw):
                    return {"label": pair["label"], "choice": {"kind": "pair", "id": pair["id"]}}
            return {"label": f"Lightroom: {action['ccw']['message']} / {action['cw']['message']}", "choice": None}
        if kind == "call":
            cid = self._command_id(action)
            if cid is not None:
                return {"label": self.commands[cid]["label"], "choice": {"kind": "command", "id": cid}}
            message, args = action["message"], action.get("args", [])
            if message == "resetToDefault" and args:
                return {"label": f"Reset {self.sliders.get(args[0], args[0])}", "choice": None}
            return {"label": SPECIAL_LABELS.get(message, f"Lightroom: {message}"), "choice": None}
        if kind == "key":
            return {"label": f"Key: {KEY_LABELS.get(action['key'], action['key'])}", "choice": None}
        if kind == "shortcut":
            return {"label": "Shortcut: " + " + ".join(action.get("mac", [])), "choice": None}
        if kind == "preset":
            name = action.get("name") or action.get("id")
            return {"label": f"Preset: {name}" if name else "Empty", "choice": None}
        return {"label": str(kind), "choice": None}

    def _command_id(self, call: dict) -> Optional[str]:
        return self._by_call.get((call.get("message"), json.dumps(list(call.get("args", [])))))

    def to_page(self) -> dict:
        return {"type": "catalog",
                "commands": [{"id": c["id"], "label": c["label"], "group": c["group"]} for c in self.commands.values()],
                "pairs": [{"id": p["id"], "label": p["label"]} for p in self.pairs.values()],
                "sliders": sorted(([p, label] for p, label in self.sliders.items()), key=lambda s: s[1].casefold())}
