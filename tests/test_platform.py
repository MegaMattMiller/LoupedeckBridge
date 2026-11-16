from __future__ import annotations

import sys

import pytest

from bridge import platform
from bridge.lightroom import lightroom_port
from bridge.platform import macos, windows


def test_macos_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert macos.lightroom_connections_json() == (
        tmp_path / "Library/Application Support/Adobe/Lightroom CC/Connections/connections.json")
    assert macos.state_dir() == tmp_path / "Library/Application Support/loupedeck-lr-bridge"
    assert macos.config_dir() == tmp_path / "Library/Application Support/loupedeck-lr-bridge"
    assert macos.log_dir() == tmp_path / "Library/Logs/loupedeck-lr-bridge"


def test_windows_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "L"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "R"))
    conn = windows.lightroom_connections_json()
    assert conn.parts[-4:] == ("Adobe", "Lightroom CC", "Connections", "connections.json")
    assert conn.is_relative_to(tmp_path / "L")
    assert windows.state_dir() == tmp_path / "L" / "loupedeck-lr-bridge"
    assert windows.config_dir() == tmp_path / "R" / "loupedeck-lr-bridge"
    assert windows.log_dir() == tmp_path / "L" / "loupedeck-lr-bridge" / "logs"


def test_current_picks_module_and_rejects_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert platform.current() is macos
    monkeypatch.setattr(sys, "platform", "win32")
    assert platform.current() is windows
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Lightroom doesn't run there"):
        platform.current()


def test_port_from_file(tmp_path):
    good = tmp_path / "connections.json"
    good.write_text('{"port": 7700}')
    assert lightroom_port(good) == 7700
    assert lightroom_port(tmp_path / "missing.json") == 7682
    garbage = tmp_path / "garbage.json"
    garbage.write_text("garbage")
    assert lightroom_port(garbage) == 7682
