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


def test_refuses_without_permission():
    # In a context without Accessibility (like this test run), macOS refuses the tap;
    # start() must say so instead of raising, and leave nothing running.
    from bridge.platform import macos_ax
    if macos_ax.is_trusted():
        pytest.skip("this context has Accessibility; covered by the live check")
    t = tap(0)
    assert t.start() is False
    t.stop()  # safe even though it never started
