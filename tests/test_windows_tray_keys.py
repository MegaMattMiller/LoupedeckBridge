"""The Windows tray app lets go of exactly the keys the bridge can hold (milestone 7, Review Focus 2): when the
bridge ends without its own clean-up (killed after a stop timed out, or crashed), windows/launcher/KeyRelease.cs
sends a key-up for each. Read as text, so it runs everywhere."""
from __future__ import annotations

import re
from pathlib import Path

from bridge.platform.windows_keys import HOLDABLE_VKS

SOURCE = Path(__file__).resolve().parent.parent / "windows" / "launcher" / "KeyRelease.cs"


def test_tray_releases_every_holdable_key():
    match = re.search(r"HoldableKeys\s*=\s*\{([^}]*)\}", SOURCE.read_text(encoding="utf-8"))
    assert match, "KeyRelease.cs has no HoldableKeys list"
    codes = tuple(int(token, 0) for token in re.findall(r"0x[0-9A-Fa-f]+|\d+", match.group(1)))
    assert codes == HOLDABLE_VKS
