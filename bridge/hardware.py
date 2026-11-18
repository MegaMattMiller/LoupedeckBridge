"""Turn Loupedeck+ MIDI messages into control events, using config/loupedeck_plus.json."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Union

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "loupedeck_plus.json"


@dataclass(frozen=True)
class Turn:
    control: str
    detents: int  # +n clockwise, -n counter-clockwise


@dataclass(frozen=True)
class Press:
    control: str


@dataclass(frozen=True)
class Release:
    control: str


Event = Union[Turn, Press, Release]


def _entries(section: dict) -> Dict[str, int]:
    return {k: v for k, v in section.items() if not k.startswith("_")}


COL = "col"  # the --/Col button: switches what the five buttons next to it do
FIVE = ["shift", "ctrl", "command", "alt", "tab"]  # those five, in physical order (notes 66–70)
FIVE_MODES = ["ratings", "colours", "keys"]
# The device sends the same notes in every mode and shows no light (captured 2026-11-16): the bridge
# keeps the mode and gives each mode's buttons their own control ids. Keys mode keeps the original ids.
FIVE_IDS = [f"{mode}_{i}" for mode in FIVE_MODES[:2] for i in range(1, len(FIVE) + 1)]


def five_id(control: str, mode: str) -> str:
    """The control id one of the five buttons has in a mode."""
    return control if mode == "keys" else f"{mode}_{FIVE.index(control) + 1}"


class HardwareMap:
    def __init__(self, dials: Dict[str, int], buttons: Dict[str, int]):
        # Dials turn via CC and click via a note on the same number; buttons are notes only.
        self._cc = {num: cid for cid, num in dials.items()}
        self._note = {**self._cc, **{num: cid for cid, num in buttons.items()}}
        self.controls: Dict[str, str] = {**{c: "dial" for c in dials}, **{c: "button" for c in buttons},
                                         **{c: "button" for c in FIVE_IDS}}  # per-mode ids (not physical)

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "HardwareMap":
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        dials = _entries(raw["dials"])
        for bank, colours in _entries(raw["colour_dials"]).items():
            for colour, num in colours.items():
                dials[f"{bank}_{colour}"] = num
        return cls(dials, _entries(raw["buttons"]))

    def decode(self, msg_type: str, number: int, value: int) -> Optional[Event]:
        if msg_type == "control_change":
            control = self._cc.get(number)
            detents = value - 128 if value > 63 else value
            if control is None or detents == 0:
                return None
            return Turn(control, detents)
        if msg_type in ("note_on", "note_off"):
            control = self._note.get(number)
            if control is None:
                return None
            if msg_type == "note_on" and value > 0:
                return Press(control)
            return Release(control)
        return None
