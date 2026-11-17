"""The user's layout: which action each Loupedeck control triggers.

File format: {"version": 1, "controls": {"<control id>": {"turn": <action>, "press": <action>,
"fn": {"turn": <action>, "press": <action>}}}}. "fn" is the layer used while the Fn button is held;
a slot missing from it means "same as normal".
The user's file is what runs; it isn't merged with the default at load time. It does follow
new default layouts control by control: a control the user never changed takes the new default,
and a control they changed (e.g. a preset on P3) stays as they set it.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Tuple

log = logging.getLogger("mapping")

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "default_mapping.json"
KEY_NAMES = {"shift", "ctrl", "cmd", "alt", "tab", "left", "right", "up", "down"}
NONE: dict = {"type": "none"}
FN_KEY = "fn"  # the Fn button's control id, and the key of a control's Fn layer in the file
SLOTS = ("turn", "press")
LAYERS = ("normal", "fn")


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
    if kind == "shortcut" and all(isinstance(action.get(k), list) and all(isinstance(key, str) for key in action[k])
                                  for k in ("mac", "windows")):
        return action
    if kind == "open_settings":
        return {"type": "open_settings"}
    if kind == "reset_dial":  # reset whatever slider this dial's turn adjusts (in the layer in use)
        return {"type": "reset_dial"}
    return None


def _rule_problem(control: str, layer: str, slot: str, action: dict) -> Optional[str]:
    """Rules beyond an action's own shape, which depend on where it's placed."""
    if layer == "fn" and action.get("type") == "preset":
        return "presets can't go on the Fn layer"
    kind = action.get("type")
    calls = [action] if kind == "call" else [action.get("cw"), action.get("ccw")] if kind == "step" else []
    if any(isinstance(c, dict) and c.get("message") == "exportWithPrevious" for c in calls) \
            and (control, layer, slot) != ("export", "fn", "press"):
        return "export with previous settings only works as Fn + Export"  # never without a dialog by accident
    return None


def _checked(control: str, layer: str, slot: str, action) -> Tuple[Optional[dict], str]:
    """(the normalised action, "") or (None, why it isn't allowed there)."""
    if slot not in SLOTS:
        return None, f"unknown slot {slot!r}"
    good = _check(slot, action)
    if good is None:
        return None, f"invalid action {action!r}"
    problem = _rule_problem(control, layer, slot, good)
    return (None, problem) if problem else (good, "")


def _parse(raw: dict, warnings: List[str]) -> Dict[str, dict]:
    """Validate every control's actions; anything invalid does nothing (and gets a warning)."""
    controls: Dict[str, dict] = {}
    for control, entry in raw.items():
        checked: dict = {}
        if not isinstance(entry, dict):
            warnings.append(f"{control}: expected an object like {{\"turn\": …, \"press\": …}}; it will do nothing")
            entry = {}
        for slot, action in entry.items():
            if slot == FN_KEY:
                if not isinstance(action, dict):
                    warnings.append(f"{control}.fn: expected an object like {{\"press\": …}}; ignored")
                    continue
                fn: dict = {}
                for fn_slot, fn_action in action.items():
                    good, problem = _checked(control, "fn", fn_slot, fn_action)
                    if good is None:
                        warnings.append(f"{control}.fn.{fn_slot}: {problem}; it will do nothing")
                        if fn_slot not in SLOTS:
                            continue
                        good = NONE
                    fn[fn_slot] = good
                if fn:
                    checked[FN_KEY] = fn
                continue
            good, problem = _checked(control, "normal", slot, action)
            if good is None:
                warnings.append(f"{control}.{slot}: {problem}; it will do nothing")
                good = NONE
            checked[slot] = good
        controls[control] = checked
    return controls


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
                 doc: Optional[dict] = None, default_path: Path = DEFAULT_PATH):
        self._controls = controls
        self.warnings = warnings
        self.path = path
        self._doc = doc  # the user's file as read; None if it couldn't be read (never overwritten then)
        self.default_path = default_path

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

        controls = _parse(raw, warnings)
        for w in warnings:
            log.warning(w)
        return cls(controls, warnings, path=user_path, doc=doc, default_path=default_path)

    @staticmethod
    def _follow_new_default(user_path: Path, base_path: Path, default_path: Path, warnings: List[str]) -> None:
        try:
            base = json.loads(base_path.read_text())["controls"]
            user_doc = json.loads(user_path.read_text())
            user = user_doc["controls"]
        except (OSError, ValueError, KeyError, TypeError):
            return  # no snapshot (older install) or an unreadable file: leave everything as is
        if not isinstance(base, dict) or not isinstance(user, dict):
            return  # a broken file: load() falls back to the default and leaves the file alone
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
        """Change one control's normal press action and save the file (atomically)."""
        self.set_action(control, "press", action)

    def set_action(self, control: str, slot: str, action: Optional[dict], layer: str = "normal") -> None:
        """Change one slot ("turn"/"press") of one layer ("normal"/"fn") and save the file.

        action=None (Fn layer only) means "same as normal": the Fn slot is removed."""
        if slot not in SLOTS or layer not in LAYERS:
            raise ValueError(f"unknown slot {slot!r} or layer {layer!r}")
        if action is None:
            if layer != "fn":
                raise ValueError("only an Fn slot can be 'same as normal'")
            good = None
        else:
            good, problem = _checked(control, layer, slot, action)
            if good is None:
                raise ValueError(f"{control}: {problem}")

        def change(controls: dict) -> None:
            entry = controls.get(control)
            entry = dict(entry) if isinstance(entry, dict) else {}  # a hand-broken entry is replaced
            if layer == "normal":
                entry[slot] = good
            else:
                fn = entry.get(FN_KEY)
                fn = dict(fn) if isinstance(fn, dict) else {}
                if good is None:
                    fn.pop(slot, None)
                else:
                    fn[slot] = good
                if fn:
                    entry[FN_KEY] = fn
                else:
                    entry.pop(FN_KEY, None)
            controls[control] = entry
        self._edit(change)

    def reset_control(self, control: str, keep_normal_press: bool = False) -> None:
        """Give one control its default actions (both layers); optionally keep its normal press."""
        default = self._default_controls()

        def change(controls: dict) -> None:
            current = controls.get(control)
            new = copy.deepcopy(default.get(control))
            if keep_normal_press and isinstance(current, dict) and "press" in current:
                new = {**(new or {}), "press": current["press"]}  # its Fn layer is the default's
            if new is None:
                controls.pop(control, None)
            else:
                controls[control] = new
        self._edit(change)

    def restore_defaults(self, keep_normal_press: Iterable[str] = ()) -> None:
        """The whole default layout, except the normal press of the listed controls (e.g. P1–P8)."""
        default = self._default_controls()

        def change(controls: dict) -> None:
            kept = {c: controls[c]["press"] for c in keep_normal_press
                    if isinstance(controls.get(c), dict) and "press" in controls[c]}
            controls.clear()
            controls.update(copy.deepcopy(default))
            for c, press in kept.items():
                controls[c] = {**controls.get(c, {}), "press": press}
        self._edit(change)

    def _default_controls(self) -> dict:
        return json.loads(self.default_path.read_text())["controls"]

    def _edit(self, change: Callable[[dict], None]) -> None:
        """Apply change() to a copy of the file and keep it only once it's saved: a failed save
        (full disk) must not leave a change in memory that the next successful save would write too."""
        if self._doc is None or self.path is None:
            raise MappingNotWritable(f"{self.path.name if self.path else 'mapping.json'} couldn't be read, so "
                                     "it won't be overwritten; fix or delete it, then restart the bridge")
        doc = {**self._doc, "controls": dict(self._doc["controls"])}
        change(doc["controls"])
        _write_atomic(self.path, _dumps(doc))
        self._doc = doc
        self._controls = _parse(doc["controls"], [])

    def turn_action(self, control: str, fn: bool = False) -> dict:
        return self._action(control, "turn", fn)

    def press_action(self, control: str, fn: bool = False) -> dict:
        return self._action(control, "press", fn)

    def fn_action(self, control: str, slot: str) -> Optional[dict]:
        """The Fn layer's own action for a slot; None means "same as normal"."""
        return self._controls.get(control, {}).get(FN_KEY, {}).get(slot)

    def _action(self, control: str, slot: str, fn: bool) -> dict:
        entry = self._controls.get(control, {})
        if fn and slot in entry.get(FN_KEY, {}):
            return entry[FN_KEY][slot]
        return entry.get(slot, NONE)

    def press_items(self) -> Iterator[Tuple[str, dict]]:
        """(control, press action) for every control that has a press action."""
        for control, slots in self._controls.items():
            if "press" in slots:
                yield control, slots["press"]
