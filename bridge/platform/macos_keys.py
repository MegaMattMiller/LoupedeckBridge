"""Send real key presses on macOS (CoreGraphics events through ctypes, no extra packages).

Needs the Accessibility permission for the app that started the bridge (LoupedeckBridge.app);
see macos_ax. Keycodes are the kVK_* values from Carbon's Events.h (ANSI layout positions).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging
from typing import Callable, List, Optional

from bridge.platform import macos_ax

log = logging.getLogger("keys")

FLAGS = {"shift": 0x20000, "ctrl": 0x40000, "alt": 0x80000, "cmd": 0x100000}
MODIFIER_MASK = 0x20000 | 0x40000 | 0x80000 | 0x100000

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


def _default_tap(keyboard: "MacKeyboard"):
    from bridge.platform.macos_tap import ModifierTap
    return ModifierTap(keyboard.held_flags)


class MacKeyboard:
    def __init__(self, post: Optional[Poster] = None, trusted: Optional[Callable[[], bool]] = None,
                 system_flags: Optional[Callable[[], int]] = None,
                 tap_factory: Optional[Callable[["MacKeyboard"], object]] = None):
        self._post = post or _cg_post
        self._trusted = trusted or macos_ax.is_trusted
        # Modifiers held on the real keyboard, so a Loupedeck key combines with them like a
        # second keyboard (e.g. real Shift + Loupedeck arrow).
        self._system_flags = system_flags or _system_modifier_flags
        # The modifier tap keeps Loupedeck modifiers alive under real input (see macos_tap).
        # Created on the first modifier press, which only happens with the permission, and
        # enabled only while a Loupedeck modifier is held.
        self._tap_factory = tap_factory or _default_tap
        self._tap = None
        self._tap_warned = False
        self._held_modifiers: set = set()

    def _event_flags(self, own_bit: int = 0) -> int:
        # A modifier's own bit is left out of the system flags: the system still shows it until
        # its key-up has been processed, which would make a release look like a press.
        return self.held_flags() | (self._system_flags() & MODIFIER_MASK & ~own_bit)

    def _tap_on(self) -> None:
        if self._tap is None:
            tap = self._tap_factory(self)
            if not tap.start():
                if not self._tap_warned:
                    self._tap_warned = True
                    log.warning("Loupedeck Shift/Ctrl/Alt/Cmd won't combine with your mouse or keyboard: macOS "
                                "refused the input tap. It needs the Accessibility permission for LoupedeckBridge "
                                "(some macOS versions also ask for Input Monitoring). Retrying on the next press.")
                return
            self._tap = tap
        self._tap.enable(True)

    def _tap_off(self) -> None:
        if self._tap is not None and not self._held_modifiers:
            self._tap.enable(False)

    def close(self) -> None:
        """Stop the modifier tap (call after releasing every held key)."""
        if self._tap is not None:
            self._tap.stop()
            self._tap = None

    def held_flags(self) -> int:
        """Flags of the modifiers currently held via the Loupedeck (read by the modifier tap)."""
        flags = 0
        for m in list(self._held_modifiers):
            flags |= FLAGS[m]
        return flags

    _flags = held_flags

    def key_down(self, name: str) -> None:
        code = _code(name)
        if name in FLAGS:
            self._held_modifiers.add(name)
            self._tap_on()
        self._post(code, True, self._event_flags(FLAGS.get(name, 0)), False)

    def key_up(self, name: str) -> None:
        code = _code(name)
        if name in FLAGS:
            self._held_modifiers.discard(name)
        self._post(code, False, self._event_flags(FLAGS.get(name, 0)), False)
        if name in FLAGS:
            self._tap_off()

    def key_repeat(self, name: str) -> None:
        self._post(_code(name), True, self._event_flags(), True)

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


def _system_modifier_flags() -> int:
    cg = _load()
    return cg.CGEventSourceFlagsState(1) & MODIFIER_MASK  # kCGEventSourceStateHIDSystemState


def _cg_post(code: int, down: bool, flags: int, autorepeat: bool) -> None:
    cg = _load()
    event = cg.CGEventCreateKeyboardEvent(None, code, down)
    if code in _MODIFIER_CODES:
        cg.CGEventSetType(event, 12)                # kCGEventFlagsChanged
    cg.CGEventSetFlags(event, flags)
    if autorepeat:
        cg.CGEventSetIntegerValueField(event, 8, 1)  # kCGKeyboardEventAutorepeat
    cg.CGEventPost(0, event)                        # kCGHIDEventTap
    cg.CFRelease(event)


def _load():
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
        _cg.CGEventSourceFlagsState.restype = ctypes.c_uint64
        _cg.CGEventSourceFlagsState.argtypes = [ctypes.c_int32]
    return _cg
