"""The modifier tap: while a Loupedeck modifier is held, real mouse/keyboard events carry it too.

Live-check finding: every real mouse or keyboard event carries the physical keyboard's modifiers
and macOS resets its modifier state to match, so a Loupedeck Alt vanished on the first mouse move.
"""
from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")

SHIFT, ALT, CMD, NON_COALESCED = 0x20000, 0x80000, 0x100000, 0x100
MOUSE_MOVED, LEFT_DRAGGED, LEFT_DOWN, KEY_DOWN, FLAGS_CHANGED, SCROLL = 5, 6, 1, 10, 12, 22


def tap(held):
    from bridge.platform.macos_tap import ModifierTap
    return ModifierTap(lambda: held)


def test_adds_held_modifiers_to_real_input():
    t = tap(ALT)
    assert t.adjust(LEFT_DRAGGED, 0) == ALT                               # Alt-drag on a slider
    assert t.adjust(MOUSE_MOVED, NON_COALESCED) == NON_COALESCED | ALT    # other flag bits kept
    assert t.adjust(KEY_DOWN, SHIFT) == SHIFT | ALT                       # combines with a real Shift
    assert t.adjust(FLAGS_CHANGED, CMD) == CMD | ALT                      # real Cmd pressed meanwhile
    assert tap(SHIFT | CMD).adjust(LEFT_DOWN, 0) == SHIFT | CMD           # Shift/Cmd-click
    assert t.adjust(SCROLL, 0) == ALT


def test_no_change_when_nothing_held_or_already_present():
    assert tap(0).adjust(LEFT_DRAGGED, 0) is None        # the fast path: nothing to do
    assert tap(ALT).adjust(LEFT_DRAGGED, ALT) is None


def test_other_event_types_untouched():
    assert tap(ALT).adjust(29, 0) is None  # e.g. a gesture event


class FakeCG:
    """Stands in for CoreGraphics so tests never create a real, system-wide event tap."""

    def __init__(self, tap_handle=0):
        self.tap_handle, self.flag_reads, self.enabled = tap_handle, 0, []

    def CGEventTapCreate(self, *args):
        return self.tap_handle

    def CGEventGetFlags(self, event):
        self.flag_reads += 1
        return 0

    def CGEventSetFlags(self, event, flags):
        pass

    def CGEventTapEnable(self, tap, on):
        self.enabled.append(on)


def test_refused_tap_returns_false(monkeypatch):
    from bridge.platform import macos_tap
    monkeypatch.setattr(macos_tap, "_lib", lambda: FakeCG(tap_handle=0))  # macOS says no
    t = tap(0)
    assert t.start() is False
    t.stop()  # safe even though it never started


def test_callback_fast_path_when_nothing_held(monkeypatch):
    # Review: the callback read every event's flags before checking whether anything was held.
    from bridge.platform import macos_tap
    cg = FakeCG()
    monkeypatch.setattr(macos_tap, "_lib", lambda: cg)
    t = tap(0)
    assert t._on_event(None, MOUSE_MOVED, 1234, None) == 1234
    assert cg.flag_reads == 0


def test_disabled_tap_reenabled_only_while_held(monkeypatch):
    from bridge.platform import macos_tap
    cg = FakeCG()
    monkeypatch.setattr(macos_tap, "_lib", lambda: cg)
    t = tap(0)
    t._tap = 1
    t._on_event(None, 0xFFFFFFFE, 99, None)  # macOS disabled the tap (timeout) while idle
    assert cg.enabled == []                  # stays off: nothing is held
    t.enable(True)
    t._on_event(None, 0xFFFFFFFE, 99, None)  # disabled while a modifier is held
    assert cg.enabled == [True, True]
