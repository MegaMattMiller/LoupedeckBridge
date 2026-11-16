"""macOS paths."""
from __future__ import annotations

from pathlib import Path

APP_DIR_NAME = "loupedeck-lr-bridge"


def _app_support() -> Path:
    return Path.home() / "Library" / "Application Support"


def lightroom_connections_json() -> Path:
    return _app_support() / "Adobe" / "Lightroom CC" / "Connections" / "connections.json"


def state_dir() -> Path:
    return _app_support() / APP_DIR_NAME


def config_dir() -> Path:
    return _app_support() / APP_DIR_NAME


def log_dir() -> Path:
    return Path.home() / "Library" / "Logs" / APP_DIR_NAME


def keyboard():
    """The real key sender (needs the Accessibility permission to have any effect)."""
    from bridge.platform.macos_keys import MacKeyboard
    return MacKeyboard()


def modifier_tap(keyboard):
    """Keeps the Loupedeck's held modifiers on real mouse/keyboard events (see macos_tap)."""
    from bridge.platform.macos_tap import ModifierTap
    return ModifierTap(keyboard.held_flags)
