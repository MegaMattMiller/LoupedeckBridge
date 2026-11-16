"""The user's layout: which action each Loupedeck control triggers.

File format: {"version": 1, "controls": {"<control id>": {"turn": <action>, "press": <action>}}}.
The user's file is what runs; it isn't merged with the default at load time. It does follow
new default layouts control by control: a control the user never changed takes the new default,
and a control they changed (e.g. a preset on P3) stays as they set it.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

log = logging.getLogger("mapping")

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "default_mapping.json"
KEY_NAMES = {"shift", "ctrl", "cmd", "alt", "tab", "left", "right", "up", "down"}
NONE: dict = {"type": "none"}


class MappingNotWritable(Exception):
    """The user's mapping.json couldn't be read at load, so it must not be overwritten."""


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
    if kind == "open_settings":
        return {"type": "open_settings"}
    return None


def _dumps(doc: dict) -> str:
    """The shipped default's style: one line per control, so the file stays readable and diffable."""
    controls = doc.get("controls", {})
    lines = [f"    {json.dumps(c)}: {json.dumps(e)}" for c, e in controls.items()]
    head = {k: v for k, v in doc.items() if k != "controls"}
    head_lines = [f"  {json.dumps(k)}: {json.dumps(v)}," for k, v in head.items()]
    return "{\n" + "\n".join(head_lines) + "\n  \"controls\": {\n" + ",\n".join(lines) + "\n  }\n}\n"


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


class Mapping:
    def __init__(self, controls: Dict[str, dict], warnings: List[str], path: Optional[Path] = None,
                 doc: Optional[dict] = None):
        self._controls = controls
        self.warnings = warnings
        self.path = path
        self._doc = doc  # the user's file as read; None if it couldn't be read (never overwritten then)

    @classmethod
    def load(cls, user_path: Path, default_path: Path = DEFAULT_PATH) -> "Mapping":
        warnings: List[str] = []
        # mapping.base.json = the default the user's file started from; it tells which controls
        # the user never changed (those follow new defaults) from the ones they did.
        base_path = user_path.with_name(user_path.stem + ".base.json")
        if not user_path.exists():
            user_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(default_path, user_path)
            shutil.copyfile(default_path, base_path)
            log.info("created %s from the default layout", user_path)
        else:
            cls._follow_new_default(user_path, base_path, default_path, warnings)
        doc: Optional[dict] = None
        try:
            doc = json.loads(user_path.read_text())
            raw = doc["controls"]
            if not isinstance(raw, dict):
                raise ValueError("'controls' isn't an object")
        except (OSError, ValueError, KeyError, TypeError) as e:
            msg = f"{user_path.name} couldn't be read ({e}); using the default layout. Your file was left as is."
            log.error(msg)
            warnings.append(msg)
            doc = None
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
        return cls(controls, warnings, path=user_path, doc=doc)

    @staticmethod
    def _follow_new_default(user_path: Path, base_path: Path, default_path: Path, warnings: List[str]) -> None:
        try:
            base = json.loads(base_path.read_text())["controls"]
            user_doc = json.loads(user_path.read_text())
            user = user_doc["controls"]
        except (OSError, ValueError, KeyError, TypeError):
            return  # no snapshot (older install) or an unreadable file: leave everything as is
        default_doc = json.loads(default_path.read_text())
        default = default_doc["controls"]
        if base == default:
            return
        followed, kept = [], []
        for control in sorted(set(base) | set(default)):
            if user.get(control) == base.get(control):  # the user never changed this control
                if control in default:
                    if user.get(control) != default[control]:
                        user[control] = default[control]
                        followed.append(control)
                elif control in user:
                    del user[control]
                    followed.append(control)
            elif base.get(control) != default.get(control):
                kept.append(control)
        if followed:
            _write_atomic(user_path, _dumps(user_doc))
            log.info("updated %s to the new default for: %s", user_path.name, ", ".join(followed))
        if kept:
            warnings.append(f"Newer defaults exist for {', '.join(kept)}; your own settings for them were kept.")
        shutil.copyfile(default_path, base_path)  # mention each new default once

    @property
    def writable(self) -> bool:
        """False when the user's file couldn't be read (it's then never overwritten)."""
        return self._doc is not None and self.path is not None

    def set_press_action(self, control: str, action: dict) -> None:
        """Change one control's press action and save the file (atomically)."""
        if self._doc is None or self.path is None:
            raise MappingNotWritable(f"{self.path.name if self.path else 'mapping.json'} couldn't be read, so "
                                     "it won't be overwritten; fix or delete it, then restart the bridge")
        good = _check("press", action)
        if good is None:
            raise ValueError(f"invalid press action {action!r}")
        entry = self._doc["controls"].setdefault(control, {})
        entry["press"] = good
        _write_atomic(self.path, _dumps(self._doc))
        self._controls.setdefault(control, {})["press"] = good

    def turn_action(self, control: str) -> dict:
        return self._controls.get(control, {}).get("turn", NONE)

    def press_action(self, control: str) -> dict:
        return self._controls.get(control, {}).get("press", NONE)

    def press_items(self) -> Iterator[Tuple[str, dict]]:
        """(control, press action) for every control that has a press action."""
        for control, slots in self._controls.items():
            if "press" in slots:
                yield control, slots["press"]
