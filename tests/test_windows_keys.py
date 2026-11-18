"""Keyboard keys on Windows (milestone 7): SendInput with US-layout virtual-key codes, Cmd sends Ctrl.
The logic runs on every system with a recording sender; only the INPUT structures need Windows."""
from __future__ import annotations

import ctypes
import sys

import pytest

from bridge.platform import macos_keys, windows_keys
from bridge.platform.windows_keys import HOLDABLE_VKS, MENU_MASK_VK, VK, WindowsKeyboard


def keyboard():
    sent = []
    return WindowsKeyboard(send=lambda vk, down: sent.append((vk, down))), sent


def test_names_match_the_mac():
    # The mapping names keys once for both systems.
    assert set(VK) == set(macos_keys.KEYCODES)


def test_codes():
    expected = {"shift": 0x10, "ctrl": 0x11, "alt": 0x12, "cmd": 0x11, "tab": 0x09, "left": 0x25, "up": 0x26,
                "right": 0x27, "down": 0x28, "f": 0x46, "\\": 0xDC, "return": 0x0D, "escape": 0x1B, "delete": 0x08,
                "space": 0x20, "f1": 0x70, "f12": 0x7B, "a": 0x41, "0": 0x30, "`": 0xC0}
    assert {name: VK[name] for name in expected} == expected
    assert HOLDABLE_VKS == (0x10, 0x11, 0x12, 0x09, 0x25, 0x26, 0x27, 0x28)
    assert MENU_MASK_VK == 0xE8


def test_cmd_sends_ctrl_and_ctrl_stays_until_both_released():
    kb, sent = keyboard()
    kb.key_down("ctrl")
    kb.key_down("cmd")
    assert sent == [(0x11, True)]
    kb.key_up("ctrl")
    assert sent == [(0x11, True)]            # Cmd still holds it
    kb.key_up("cmd")
    assert sent == [(0x11, True), (0x11, False)]


def test_alt_release_is_masked():
    # An Alt pressed and released alone would focus Lightroom's menu bar; an unassigned key in between stops that.
    kb, sent = keyboard()
    kb.key_down("alt")
    kb.key_up("alt")
    assert sent == [(0x12, True), (0xE8, True), (0xE8, False), (0x12, False)]


def test_tap_keeps_held_modifiers():
    kb, sent = keyboard()
    kb.key_down("shift")
    sent.clear()
    kb.tap(["shift", "f"])
    assert sent == [(0x46, True), (0x46, False)]


def test_tap_presses_and_releases_its_modifiers_in_order():
    kb, sent = keyboard()
    kb.tap(["ctrl", "shift", "e"])
    assert sent == [(0x11, True), (0x10, True), (0x45, True), (0x45, False), (0x10, False), (0x11, False)]


def test_tap_validates_before_sending():
    kb, sent = keyboard()
    with pytest.raises(ValueError):
        kb.tap(["ctrl", "nope"])
    assert sent == []


def test_unknown_key_is_refused():
    kb, sent = keyboard()
    with pytest.raises(ValueError):
        kb.key_down("hyper")
    assert sent == []


def test_repeat_sends_down_again():
    kb, sent = keyboard()
    kb.key_down("left")
    kb.key_repeat("left")
    assert sent == [(0x25, True), (0x25, True)]


def test_needs_no_permission():
    kb, _ = keyboard()
    assert kb.is_trusted() is True
    kb.close()


def test_windows_platform_gives_this_keyboard(monkeypatch):
    from bridge.platform import windows
    assert isinstance(windows.keyboard(), WindowsKeyboard)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_inputs_for_arrows_are_extended():
    left = windows_keys._input_for(0x25, True)
    assert left.type == 1                                      # INPUT_KEYBOARD
    assert left.u.ki.wVk == 0x25 and left.u.ki.wScan != 0
    assert left.u.ki.dwFlags == windows_keys.KEYEVENTF_EXTENDEDKEY
    f_up = windows_keys._input_for(0x46, False)
    assert f_up.u.ki.dwFlags == windows_keys.KEYEVENTF_KEYUP
    assert ctypes.sizeof(windows_keys.INPUT) == (40 if sys.maxsize > 2**32 else 28)
