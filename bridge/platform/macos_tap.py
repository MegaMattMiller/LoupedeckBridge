"""Keep the Loupedeck's held modifiers alive under real mouse/keyboard input (macOS).

Every real mouse or keyboard event carries the *physical* keyboard's modifier flags, and
macOS resets its modifier state to match, so a Shift/Alt/Cmd held on the Loupedeck vanished
on the next mouse move or key press (live check, milestone 2). This active event tap adds
the held Loupedeck modifiers to those events as they pass, so Lightroom sees an Alt-drag or a
Shift-click as if the real key were held. Needs the Accessibility permission (the same one
the keys need); macOS refuses the tap without it.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging
import threading
from typing import Callable, Optional

log = logging.getLogger("modifier-tap")

# CGEventType values: mouse buttons, moves, drags, scroll, keys, modifier changes.
TYPES = (1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 22, 25, 26, 27)
_DISABLED_BY_TIMEOUT, _DISABLED_BY_USER = 0xFFFFFFFE, 0xFFFFFFFF
_SESSION_TAP, _HEAD_INSERT, _ACTIVE = 1, 0, 0

_CALLBACK = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p)
_cg = None


def _lib():
    global _cg
    if _cg is None:
        cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices"))
        cg.CGEventTapCreate.restype = ctypes.c_void_p
        cg.CGEventTapCreate.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint64,
                                        _CALLBACK, ctypes.c_void_p]
        cg.CGEventTapEnable.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        cg.CGEventGetFlags.restype = ctypes.c_uint64
        cg.CGEventGetFlags.argtypes = [ctypes.c_void_p]
        cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        cg.CFMachPortCreateRunLoopSource.restype = ctypes.c_void_p
        cg.CFMachPortCreateRunLoopSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
        cg.CFRunLoopGetCurrent.restype = ctypes.c_void_p
        cg.CFRunLoopAddSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        cg.CFRunLoopStop.argtypes = [ctypes.c_void_p]
        cg.CFRelease.argtypes = [ctypes.c_void_p]
        _cg = cg
    return _cg


class ModifierTap:
    def __init__(self, held_flags: Callable[[], int]):
        self.held_flags = held_flags
        self._tap: Optional[int] = None
        self._runloop: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._enabled = False
        self._errors_logged = False
        self._callback = _CALLBACK(self._on_event)  # kept alive for as long as the tap exists

    def adjust(self, event_type: int, flags: int) -> Optional[int]:
        """The flags this event should carry, or None to leave it untouched."""
        held = self.held_flags()
        if not held or event_type not in TYPES:
            return None
        new = flags | held
        return new if new != flags else None

    def start(self) -> bool:
        cg = _lib()
        mask = 0
        for t in TYPES:
            mask |= 1 << t
        tap = cg.CGEventTapCreate(_SESSION_TAP, _HEAD_INSERT, _ACTIVE, mask, self._callback, None)
        if not tap:
            return False  # no permission (or Input Monitoring needed)
        self._tap = tap
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), name="modifier-tap", daemon=True)
        self._thread.start()
        ready.wait(2)
        return True

    def _run(self, ready: threading.Event) -> None:
        cg = _lib()
        self._runloop = cg.CFRunLoopGetCurrent()
        source = cg.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        modes = ctypes.c_void_p.in_dll(cg, "kCFRunLoopCommonModes")
        cg.CFRunLoopAddSource(self._runloop, source, modes)
        cg.CGEventTapEnable(self._tap, self._enabled)  # starts off: only on while a modifier is held
        ready.set()
        cg.CFRunLoopRun()
        cg.CFRelease(source)

    def enable(self, on: bool) -> None:
        """Route real input through the tap only while a Loupedeck modifier is held."""
        self._enabled = on
        if self._tap is not None:
            _lib().CGEventTapEnable(self._tap, on)

    def stop(self) -> None:
        if self._tap is None:
            return
        cg = _lib()
        self._enabled = False
        cg.CGEventTapEnable(self._tap, False)
        if self._runloop is not None:
            cg.CFRunLoopStop(self._runloop)
        if self._thread is not None:
            self._thread.join(timeout=2)
        cg.CFRelease(self._tap)
        self._tap = None

    def _on_event(self, proxy, event_type, event, refcon):
        try:
            if event_type in (_DISABLED_BY_TIMEOUT, _DISABLED_BY_USER):
                if self._enabled:  # macOS disabled us (e.g. a slow callback) while it's needed
                    _lib().CGEventTapEnable(self._tap, True)
                return event
            if not self.held_flags():  # fast path: nothing to add, don't even read the event
                return event
            new = self.adjust(event_type, _lib().CGEventGetFlags(event))
            if new is not None:
                _lib().CGEventSetFlags(event, new)
        except Exception:  # never let an exception escape into CoreGraphics (or flood the log)
            if not self._errors_logged:
                self._errors_logged = True
                log.exception("modifier tap callback failed (further errors not logged)")
        return event
