"""The user's layout: which action each Loupedeck control triggers.

File format: {"version": 1, "controls": {"<control id>": {"turn": <action>, "press": <action>}}}.
The user's file replaces the shipped default entirely (no merging), so what they see is what runs.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

log = logging.getLogger("mapping")

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "default_mapping.json"
KEY_NAMES = {"shift", "ctrl", "cmd", "alt", "tab", "left", "right", "up", "down"}
NONE: dict = {"type": "none"}


def _is_call(obj) -> bool:
    return (isinstance(obj, dict) and isinstance(obj.get("message"), str)
            and isinstance(obj.get("args", []), list))


def _with_args(obj: dict) -> dict:
    return {**obj, "args": list(obj.get("args", []))}


def _check(slot: str, action) -> Optional[dict]:
    """Return the normalised action, or None if it isn't valid for this slot ("turn"/"press")."""
    if not isinstance(action, dict):
        return None
    kind = action.get("type")
    if kind == "none":
        return NONE
    if slot == "turn":
        if kind == "adjust" and isinstance(action.get("param"), str):
            return action
        if kind == "step" and _is_call(action.get("cw")) and _is_call(action.get("ccw")):
            return {**action, "cw": _with_args(action["cw"]), "ccw": _with_args(action["ccw"])}
        return None
    if kind == "call" and _is_call(action):
        return _with_args(action)
    if kind == "preset" and all(action.get(k) is None or isinstance(action.get(k), str) for k in ("id", "name")):
        return {"type": "preset", "id": action.get("id"), "name": action.get("name")}
    if kind == "key" and isinstance(action.get("key"), str) and action["key"] in KEY_NAMES:
        return action
    if kind == "shortcut" and all(isinstance(action.get(k), list) for k in ("mac", "windows")):
        return action
    return None


class Mapping:
    def __init__(self, controls: Dict[str, dict], warnings: List[str]):
        self._controls = controls
        self.warnings = warnings

    @classmethod
    def load(cls, user_path: Path, default_path: Path = DEFAULT_PATH) -> "Mapping":
        warnings: List[str] = []
        # mapping.base.json = the default the user's file started from. It tells an unedited
        # mapping (follows new defaults automatically) from an edited one (always kept).
        base_path = user_path.with_name(user_path.stem + ".base.json")
        if not user_path.exists():
            user_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(default_path, user_path)
            shutil.copyfile(default_path, base_path)
            log.info("created %s from the default layout", user_path)
        else:
            cls._follow_new_default(user_path, base_path, default_path, warnings)
        try:
            raw = json.loads(user_path.read_text())["controls"]
            if not isinstance(raw, dict):
                raise ValueError("'controls' isn't an object")
        except (OSError, ValueError, KeyError, TypeError) as e:
            msg = f"{user_path.name} couldn't be read ({e}); using the default layout. Your file was left as is."
            log.error(msg)
            warnings.append(msg)
            raw = json.loads(default_path.read_text())["controls"]

        controls: Dict[str, dict] = {}
        for control, entry in raw.items():
            checked = {}
            if not isinstance(entry, dict):
                warnings.append(f"{control}: expected an object like {{\"turn\": …, \"press\": …}}; it will do nothing")
                entry = {}
            for slot, action in entry.items():
                good = _check(slot, action) if slot in ("turn", "press") else None
                if good is None:
                    warnings.append(f"{control}.{slot}: invalid action {action!r}; it will do nothing")
                    good = NONE
                checked[slot] = good
            controls[control] = checked
        for w in warnings:
            log.warning(w)
        return cls(controls, warnings)

    @staticmethod
    def _follow_new_default(user_path: Path, base_path: Path, default_path: Path, warnings: List[str]) -> None:
        try:
            base = json.loads(base_path.read_text())
            user = json.loads(user_path.read_text())
        except (OSError, ValueError):
            return  # no snapshot (older install) or an unreadable file: leave everything as is
        default = json.loads(default_path.read_text())
        if base == default:
            return
        if user == base:
            shutil.copyfile(default_path, user_path)
            log.info("updated %s to the new default layout (you hadn't changed it)", user_path)
        else:
            warnings.append(f"A newer default layout is available ({default_path}); your edited "
                            f"{user_path.name} was kept as is.")
        shutil.copyfile(default_path, base_path)  # mention each new default once

    def turn_action(self, control: str) -> dict:
        return self._controls.get(control, {}).get("turn", NONE)

    def press_action(self, control: str) -> dict:
        return self._controls.get(control, {}).get("press", NONE)

    def press_items(self) -> Iterator[Tuple[str, dict]]:
        """(control, press action) for every control that has a press action."""
        for control, slots in self._controls.items():
            if "press" in slots:
                yield control, slots["press"]
