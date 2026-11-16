from __future__ import annotations

import pytest

from bridge.platform.macos_keys import MacKeyboard

SHIFT, CTRL, ALT, CMD = 0x20000, 0x40000, 0x80000, 0x100000


def keyboard():
    posted = []
    kb = MacKeyboard(post=lambda code, down, flags, repeat: posted.append((code, down, flags, repeat)),
                     trusted=lambda: True)
    return kb, posted


def test_modifier_down_up_flags():
    kb, posted = keyboard()
    kb.key_down("shift")
    kb.key_up("shift")
    assert posted == [(56, True, SHIFT, False), (56, False, 0, False)]


def test_key_carries_held_modifiers():
    kb, posted = keyboard()
    kb.key_down("cmd")
    kb.key_down("left")
    kb.key_up("left")
    assert posted[1:] == [(123, True, CMD, False), (123, False, CMD, False)]


def test_tap_shortcut_order():
    kb, posted = keyboard()
    kb.tap(["cmd", "shift", "e"])
    assert posted == [(55, True, CMD, False), (56, True, CMD | SHIFT, False),
                      (14, True, CMD | SHIFT, False), (14, False, CMD | SHIFT, False),
                      (56, False, CMD, False), (55, False, 0, False)]


def test_tap_backslash():
    kb, posted = keyboard()
    kb.tap(["\\"])
    assert posted == [(42, True, 0, False), (42, False, 0, False)]


def test_tap_keeps_users_held_modifier():
    kb, posted = keyboard()
    kb.key_down("alt")
    kb.tap(["f"])
    assert posted[1:] == [(3, True, ALT, False), (3, False, ALT, False)]  # no alt-up: still held
    kb.key_up("alt")
    assert posted[-1] == (58, False, 0, False)


def test_key_repeat_sets_autorepeat():
    kb, posted = keyboard()
    kb.key_repeat("right")
    assert posted == [(124, True, 0, True)]


def test_unknown_key_raises_before_sending_anything():
    kb, posted = keyboard()
    with pytest.raises(ValueError, match="hyper"):
        kb.tap(["cmd", "hyper"])
    with pytest.raises(ValueError):
        kb.key_down("hyper")
    assert posted == []


def test_held_flags_follow_modifiers():
    kb, _ = keyboard()
    kb.key_down("shift")
    kb.key_down("alt")
    assert kb.held_flags() == SHIFT | ALT
    kb.key_up("shift")
    assert kb.held_flags() == ALT
    kb.tap(["cmd", "z"])           # a shortcut's own modifiers aren't "held" afterwards
    assert kb.held_flags() == ALT


def test_is_trusted_delegates():
    assert MacKeyboard(post=lambda *a: None, trusted=lambda: False).is_trusted() is False
