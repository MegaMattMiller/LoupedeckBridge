"""Windows paths. Environment variables are read at call time."""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "loupedeck-lr-bridge"


def _local() -> Path:
    return Path(os.environ["LOCALAPPDATA"])


def _roaming() -> Path:
    return Path(os.environ["APPDATA"])


def lightroom_connections_json() -> Path:
    return _local() / "Adobe" / "Lightroom CC" / "Connections" / "connections.json"


def state_dir() -> Path:
    return _local() / APP_DIR_NAME


def config_dir() -> Path:
    return _roaming() / APP_DIR_NAME


def log_dir() -> Path:
    return _local() / APP_DIR_NAME / "logs"


def keyboard():
    """Keyboard keys on Windows arrive with milestone 6; until then key buttons do nothing."""
    return None
