from __future__ import annotations

import pytest

from bridge.platform.macos_keys import MacKeyboard

SHIFT, CTRL, ALT, CMD = 0x20000, 0x40000, 0x80000, 0x100000


class FakeTap:
    def __init__(self, starts=True):
        self.starts, self.calls = starts, []

    def start(self):
        self.calls.append("start")
        return self.starts

    def enable(self, on):
        self.calls.append(("enable", on))

    def stop(self):
        self.calls.append("stop")


def keyboard(system=0, tap=None):
    posted = []
    tap = tap or FakeTap()
    kb = MacKeyboard(post=lambda code, down, flags, repeat: posted.append((code, down, flags, repeat)),
                     trusted=lambda: True, system_flags=lambda: system, tap_factory=lambda kb: tap)
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


def test_tap_only_on_while_a_modifier_is_held():
    # Review: the tap ran for the bridge's whole life and was tried from untrusted contexts.
    # Now it's created on the first (trusted) modifier press and enabled only while held.
    tap = FakeTap()
    kb, _ = keyboard(tap=tap)
    kb.key_down("left")
    kb.key_up("left")
    assert tap.calls == []                                  # plain keys never need it
    kb.key_down("shift")
    kb.key_down("alt")
    kb.key_up("shift")
    assert tap.calls == ["start", ("enable", True), ("enable", True)]
    kb.key_up("alt")                                        # last modifier released
    assert tap.calls[-1] == ("enable", False)
    kb.key_down("cmd")                                      # already created: no second start
    assert tap.calls.count("start") == 1 and tap.calls[-1] == ("enable", True)
    kb.close()
    assert tap.calls[-1] == "stop"


def test_tap_refused_warns_once_and_retries(caplog):
    # Review: a tap refused at startup was never retried after the permission was granted.
    tap = FakeTap(starts=False)
    kb, posted = keyboard(tap=tap)
    with caplog.at_level("WARNING"):
        kb.key_down("shift")
        kb.key_up("shift")
        kb.key_down("shift")
    assert tap.calls == ["start", "start"]                  # tried again on the next press
    assert sum("tap" in r.getMessage().lower() for r in caplog.records) == 1
    assert posted[0][:2] == (56, True)                      # the key itself is still sent


def test_real_modifiers_join_loupedeck_keys():
    # Review: a real Shift held while pressing the Loupedeck's arrow sent a plain arrow.
    kb, posted = keyboard(system=SHIFT)
    kb.key_down("left")
    assert posted[-1] == (123, True, SHIFT, False)
    kb.tap(["\\"])
    assert posted[-1] == (42, False, SHIFT, False)


def test_modifier_event_drops_its_own_bit_on_release():
    # The system state still shows a modifier until its key-up is processed, so the up event
    # must not take that bit from it (or the release would look like a press).
    kb, posted = keyboard(system=SHIFT | CMD)  # Loupedeck Shift held, real Cmd held
    kb.key_down("shift")
    kb.key_up("shift")
    assert posted == [(56, True, SHIFT | CMD, False), (56, False, CMD, False)]


def test_is_trusted_delegates():
    assert MacKeyboard(post=lambda *a: None, trusted=lambda: False).is_trusted() is False
