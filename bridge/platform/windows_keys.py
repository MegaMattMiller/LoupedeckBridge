"""Send real key presses on Windows (SendInput through ctypes, no extra packages; milestone 7).

Windows needs no permission for this. Keys go to whichever window is in front, like a second keyboard; Windows
doesn't let them reach a program running as administrator.

The names are the Mac's (macos_keys.KEYCODES), with US-layout virtual-key codes. Cmd sends Ctrl (the user's
decision): Lightroom on Windows uses Ctrl where the Mac uses Cmd. Ctrl and Cmd share one key, so it goes down on
the first press and up on the last release.
"""
from __future__ import annotations

import ctypes
import logging
from collections import Counter
from typing import Callable, List, Optional

log = logging.getLogger("keys")

VK = {
    "shift": 0x10, "ctrl": 0x11, "alt": 0x12, "cmd": 0x11,
    "tab": 0x09, "space": 0x20, "return": 0x0D, "escape": 0x1B, "delete": 0x08,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    **{f"f{n}": 0x6F + n for n in range(1, 13)},
    **{chr(c): c - 0x20 for c in range(ord("a"), ord("z") + 1)},
    **{str(d): 0x30 + d for d in range(10)},
    "=": 0xBB, "-": 0xBD, "]": 0xDD, "[": 0xDB, "'": 0xDE, ";": 0xBA, "\\": 0xDC, ",": 0xBC, "/": 0xBF,
    ".": 0xBE, "`": 0xC0,
}
# Every key the bridge can hold down (Shift, Ctrl, Alt, Tab, the arrows). The tray app lets go of exactly these
# if the bridge ends without its own clean-up (windows/launcher/KeyRelease.cs).
HOLDABLE_VKS = (0x10, 0x11, 0x12, 0x09, 0x25, 0x26, 0x27, 0x28)
MENU_MASK_VK = 0xE8          # unassigned: pressed just before Alt's release, so Alt alone doesn't focus a menu bar
_ALT = 0x12
_EXTENDED = {0x25, 0x26, 0x27, 0x28}

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

Sender = Callable[[int, bool], None]   # (virtual-key code, down)


def _vk(name: str) -> int:
    try:
        return VK[name]
    except KeyError:
        raise ValueError(f"unknown key name {name!r}") from None


class WindowsKeyboard:
    def __init__(self, send: Optional[Sender] = None):
        self._send = send or _send_input
        self._down: Counter = Counter()      # code → how many held keys press it (Ctrl and Cmd share one)

    def key_down(self, name: str) -> None:
        code = _vk(name)
        self._down[code] += 1
        if self._down[code] == 1:
            self._send(code, True)

    def key_up(self, name: str) -> None:
        code = _vk(name)
        if self._down[code] > 1:
            self._down[code] -= 1
            return
        self._down.pop(code, None)
        if code == _ALT:
            self._send(MENU_MASK_VK, True)
            self._send(MENU_MASK_VK, False)
        self._send(code, False)

    def key_repeat(self, name: str) -> None:
        self._send(_vk(name), True)

    def tap(self, keys: List[str]) -> None:
        """Press a shortcut: its modifiers down in order, the last key down and up, the modifiers up in
        reverse. Modifiers already held (e.g. via the Loupedeck) stay held."""
        for name in keys:
            _vk(name)  # validate everything before sending anything
        *modifiers, key = keys
        pressed = [m for m in modifiers if self._down[_vk(m)] == 0]
        for m in pressed:
            self.key_down(m)
        self.key_down(key)
        self.key_up(key)
        for m in reversed(pressed):
            self.key_up(m)

    def is_trusted(self) -> bool:
        return True

    def close(self) -> None:
        pass


# ---- SendInput ---------------------------------------------------------------------------------------------
# The structures are spelled out with fixed-size types (not ctypes.wintypes) so this module imports anywhere.
_ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", _ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):       # only here so the union, and INPUT, have Windows' size
    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("mouseData", ctypes.c_uint32),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", _ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("u", _INPUTUNION)]


_user32 = None
_send_failed_logged = False


def _load():
    global _user32
    if _user32 is None:
        _user32 = ctypes.WinDLL("user32", use_last_error=True)
        _user32.MapVirtualKeyW.restype = ctypes.c_uint
        _user32.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
        _user32.SendInput.restype = ctypes.c_uint
        _user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
    return _user32


def _input_for(vk: int, down: bool) -> INPUT:
    flags = (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0) | (0 if down else KEYEVENTF_KEYUP)
    scan = _load().MapVirtualKeyW(vk, 0)                  # MAPVK_VK_TO_VSC
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags)))


def _send_input(vk: int, down: bool) -> None:
    global _send_failed_logged
    event = _input_for(vk, down)
    if _load().SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1 and not _send_failed_logged:
        _send_failed_logged = True
        log.warning("Windows refused a key press (error %d); keys can't reach a program running as administrator",
                    ctypes.get_last_error())
