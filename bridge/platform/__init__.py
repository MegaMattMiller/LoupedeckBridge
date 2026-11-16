"""Per-OS pieces. Everything platform-specific lives in one module per OS."""
from __future__ import annotations

import sys
from types import ModuleType


def current() -> ModuleType:
    """The module for the OS we're running on."""
    if sys.platform == "darwin":
        from bridge.platform import macos
        return macos
    if sys.platform == "win32":
        from bridge.platform import windows
        return windows
    raise RuntimeError("Linux/other systems aren't supported: Lightroom doesn't run there")
