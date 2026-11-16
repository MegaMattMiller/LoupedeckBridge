#!/usr/bin/env python3
"""Milestone 1, Task 1: check how Lightroom handles the writes the dials will make.

    .venv/bin/python tools/lr_verify_writes.py --yes-this-is-a-test-photo

THIS CHANGES THE PHOTO OPEN IN LIGHTROOM. Run it only on a photo picked for testing
(ideally a duplicate), in the Edit view. It records Exposure, Contrast and Straighten
first and puts them back at the end; the preset check is undone with undo().
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bridge.lightroom import Lightroom, LightroomError  # noqa: E402

RESTORED = ("Exposure2012", "Contrast2012", "straightenAngle")
FINGERPRINT = ("Exposure2012", "Contrast2012", "Highlights2012", "Shadows2012", "Temperature",
               "Saturation", "Clarity2012", "Vibrance")


async def main() -> None:
    lr = Lightroom("Loupedeck+ Bridge", "0.1")
    await lr.connect()

    async def call(msg, *params):
        try:
            return await lr.call(msg, *params)
        except LightroomError as e:
            return {"FAILED": e.reply.get("response")}

    async def value(param):
        return (await call("getValue", param))

    async def step(label, msg, *params, read=None):
        reply = await call(msg, *params)
        after = await value(read) if read else ""
        print(f"{label:<44} {msg}{tuple(params)!s:<32} -> {json.dumps(reply):<22} {read or ''} now {after}")

    try:
        await lr.register()
        print("tool:", await call("getSelectedTool"), "| B&W:", (await call("isBlackAndWhiteOn"))[:1])
        originals = {p: (await value(p))[0] for p in RESTORED}
        print("originals:", originals)

        await step("1 increment units (expect +0.1 EV)", "increment", "Exposure2012", 0.1, read="Exposure2012")
        await step("2 clamping (expect 100, not 500+)", "increment", "Contrast2012", 500, read="Contrast2012")
        await step("3 straighten outside crop tool", "increment", "straightenAngle", 1, read="straightenAngle")
        await step("4 reset straighten (expect 0)", "resetToDefault", "straightenAngle", read="straightenAngle")

        await call("startTracking", "Exposure2012")
        for _ in range(5):
            await call("increment", "Exposure2012", 0.05)
        await step("5 tracked burst: 5×0.05 (one history step?)", "stopTracking", read="Exposure2012")

        ids = (await call("getPresetIDs"))[0]
        name = (await call("getPresetName", ids[0]))[0]
        before = [(await value(p))[0] for p in FINGERPRINT]
        await step(f"6a applyPreset '{name}'", "applyPreset", ids[0])
        after = [(await value(p))[0] for p in FINGERPRINT]
        await step("6b undo", "undo")
        undone = [(await value(p))[0] for p in FINGERPRINT]
        print("   preset changed something:", before != after, "| undo restored it:", undone == before)
    finally:
        try:
            for p, v in originals.items():
                await call("setValue", p, v)
            print("restored:", {p: (await value(p))[0] for p in RESTORED})
        except NameError:
            pass
        await lr.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes-this-is-a-test-photo", action="store_true", required=True)
    ap.parse_args()
    asyncio.run(main())
