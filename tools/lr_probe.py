#!/usr/bin/env python3
"""Step 2 probe: register with Lightroom and make READ-ONLY calls to learn the reply shapes.

    .venv/bin/python tools/lr_probe.py

Nothing here changes a photo or a setting. The first run makes Lightroom show an
Allow dialog; after that the saved client GUID skips it.
Every frame sent/received goes to captures/lr-frames-<time>.jsonl (GUID redacted).
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from bridge.lightroom import Lightroom, LightroomError  # noqa: E402

P = "Exposure2012"
READ_ONLY_CALLS = [
    ("appVersionString",),
    ("appVersionTable",),
    ("getPanelNames",),
    ("getParameterType", P),
    ("getRange", P),
    ("getDefault", P),
    ("getLabel", P),
    ("getValue", P),
    ("getWhiteBalanceModel",),
    ("isBlackAndWhiteOn",),
    ("getSelectedTool",),
    ("getFlag",),
    ("getRating",),
    ("getColorLabel",),
    ("thisIsNotARealMessage",),  # on purpose: shows what an error reply looks like
]


def show(value, limit: int = 300) -> str:
    text = json.dumps(value)
    return text if len(text) <= limit else text[:limit] + f" … ({len(text)} chars)"


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="  [%(name)s] %(message)s")
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    frames = PROJECT / "captures" / f"lr-frames-{stamp}.jsonl"
    lr = Lightroom("Loupedeck+ Bridge", "0.1", frame_log=frames)
    await lr.connect()
    try:
        print("register … (click Allow in Lightroom if it asks)", flush=True)
        resp = await lr.register()
        shown = ["<clientGUID>"] + resp[1:] if isinstance(resp, list) else "<redacted>"
        print("  ->", show(shown), flush=True)

        names = await lr.call("getParameterNames")  # full dump: tools/lr_dump_params.py
        print("getParameterNames -> first entries:", show(names, 300))

        for msg, *params in READ_ONLY_CALLS:
            label = f"{msg}({', '.join(map(repr, params))})"
            try:
                reply = await lr.request(msg, *params)
                print(f"{label:<34} -> {show(reply.get('response'))}")
            except LightroomError as e:
                print(f"{label:<34} -> success=false, full reply: {show(e.reply)}")
            except asyncio.TimeoutError:
                print(f"{label:<34} -> TIMEOUT (no reply in 10 s)")
    finally:
        await lr.close()
        print(f"\nframes logged to {frames.relative_to(PROJECT)}")


if __name__ == "__main__":
    asyncio.run(main())
