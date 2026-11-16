"""Send real key presses on macOS (CoreGraphics events through ctypes, no extra packages).

Needs the Accessibility permission for the app that started the bridge (LoupedeckBridge.app);
see macos_ax. Keycodes are the kVK_* values from Carbon's Events.h (ANSI layout positions).
"""
from __future__ import annotations

import ctypes
import ctypes.util
from typing import Callable, List, Optional

from bridge.platform import macos_ax

FLAGS = {"shift": 0x20000, "ctrl": 0x40000, "alt": 0x80000, "cmd": 0x100000}

KEYCODES = {
    "shift": 56, "ctrl": 59, "alt": 58, "cmd": 55,
    "tab": 48, "space": 49, "return": 36, "escape": 53, "delete": 51,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "o": 31, "u": 32,
    "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
    "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26, "8": 28, "9": 25, "0": 29,
    "=": 24, "-": 27, "]": 30, "[": 33, "'": 39, ";": 41, "\\": 42, ",": 43, "/": 44,
    ".": 47, "`": 50,
}
_MODIFIER_CODES = {KEYCODES[m] for m in FLAGS}

Poster = Callable[[int, bool, int, bool], None]  # (keycode, down, flags, autorepeat)


def _code(name: str) -> int:
    try:
        return KEYCODES[name]
    except KeyError:
        raise ValueError(f"unknown key name {name!r}") from None


class MacKeyboard:
    def __init__(self, post: Optional[Poster] = None, trusted: Optional[Callable[[], bool]] = None):
        self._post = post or _cg_post
        self._trusted = trusted or macos_ax.is_trusted
        self._held_modifiers: set = set()

    def _flags(self) -> int:
        flags = 0
        for m in self._held_modifiers:
            flags |= FLAGS[m]
        return flags

    def key_down(self, name: str) -> None:
        code = _code(name)
        if name in FLAGS:
            self._held_modifiers.add(name)
        self._post(code, True, self._flags(), False)

    def key_up(self, name: str) -> None:
        code = _code(name)
        if name in FLAGS:
            self._held_modifiers.discard(name)
        self._post(code, False, self._flags(), False)

    def key_repeat(self, name: str) -> None:
        self._post(_code(name), True, self._flags(), True)

    def tap(self, keys: List[str]) -> None:
        """Press a shortcut: its modifiers down in order, the last key down and up, the
        modifiers up in reverse. Modifiers already held (e.g. via the Loupedeck) stay held."""
        for name in keys:
            _code(name)  # validate everything before sending anything
        *modifiers, key = keys
        pressed = [m for m in modifiers if m not in self._held_modifiers]
        for m in pressed:
            self.key_down(m)
        self.key_down(key)
        self.key_up(key)
        for m in reversed(pressed):
            self.key_up(m)

    def is_trusted(self) -> bool:
        return self._trusted()


_cg = None


def _cg_post(code: int, down: bool, flags: int, autorepeat: bool) -> None:
    global _cg
    if _cg is None:
        _cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices"))
        _cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        _cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
        _cg.CGEventSetType.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        _cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        _cg.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
        _cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        _cg.CFRelease.argtypes = [ctypes.c_void_p]
    event = _cg.CGEventCreateKeyboardEvent(None, code, down)
    if code in _MODIFIER_CODES:
        _cg.CGEventSetType(event, 12)                # kCGEventFlagsChanged
    _cg.CGEventSetFlags(event, flags)
    if autorepeat:
        _cg.CGEventSetIntegerValueField(event, 8, 1)  # kCGKeyboardEventAutorepeat
    _cg.CGEventPost(0, event)                        # kCGHIDEventTap
    _cg.CFRelease(event)
