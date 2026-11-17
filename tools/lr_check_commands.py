#!/usr/bin/env python3
"""Milestone 4: check that Lightroom accepts every command in config/commands.json.

    .venv/bin/python tools/lr_check_commands.py --list
    .venv/bin/python tools/lr_check_commands.py --group Rating --yes-this-is-a-test-photo

THIS SENDS REAL COMMANDS TO LIGHTROOM. Run it on a photo picked for testing, in the Edit view,
one group at a time, and watch Lightroom while it runs. To keep it gentle:
- commands that open a dialog or another app, or create a photo, are skipped (check those by hand)
- each photo edit is undone right after it's checked, and toggles are sent twice
- ratings, flags and colour labels on the test photo are changed (they're metadata; set them back by hand)
- the Photos and View groups move away from the photo and come back; reselect it if needed
  (View and Tools end back in the single-photo view with no tool active)
It registers with the bridge's saved client ID, so Lightroom shows no new Allow dialog. Never sends
exportWithPrevious (it isn't in the list).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bridge.app import APP_NAME, APP_VERSION  # noqa: E402
from bridge.commands import CommandCatalog  # noqa: E402
from bridge.lightroom import Lightroom, LightroomError, lightroom_port  # noqa: E402

SKIP = {"openExport", "openPreferences", "openPanoramaMerge", "openHDRMerge", "openHDRPanoramaMerge",
        "showCopyEditSettings", "editInPhotoshop", "duplicatePhoto"}
UNDO_AFTER = {"rotateLeft", "rotateRight", "flipHorizontal", "flipVertical", "setAutoTone", "setAutoWhiteBalance",
              "setWhiteBalance", "setUpright", "resetCrop", "resetAllDevelopAdjustments", "pasteEditSettings"}
TWICE = {"showClipping", "toggleZoom", "toggleConstrainAspectRatio", "toggleHDR", "rotateAspectRatio"}
GAP = 0.5  # seconds between commands, so you can watch
# These move to another photo, view or selection: sent after every edit, so no edit lands on another photo.
NAVIGATE = {"nextPhoto", "previousPhoto", "goBack", "goForward", "selectAll", "selectNone", "showView"}
BACK = {"View": ("showView", "loupe"), "Tools": ("selectTool", "loupe")}  # where each group leaves you afterwards


async def check(groups, port) -> int:
    catalog = CommandCatalog.load()
    lr = Lightroom(APP_NAME, APP_VERSION)
    await lr.connect(port or lightroom_port())
    await lr.register()
    refused = 0
    try:
        chosen = [c for c in catalog.commands.values() if c["group"] in groups]
        chosen.sort(key=lambda c: c["message"] in NAVIGATE)  # stable: list order otherwise
        for command in chosen:
            name = f"{command['id']:<24} {command['message']}{tuple(command['args']) if command['args'] else '()'}"
            if command["message"] in SKIP:
                print(f"skip     {name}  (opens a dialog/app or adds a photo: check by hand)")
                continue
            try:
                reply = await lr.call(command["message"], *command["args"])
                print(f"ok       {name}  {reply if reply not in ({}, None) else ''}")
                if command["message"] in TWICE:
                    await asyncio.sleep(GAP)
                    await lr.call(command["message"], *command["args"])
                if command["message"] in UNDO_AFTER:
                    await asyncio.sleep(GAP)
                    await lr.call("undo")
            except LightroomError as e:
                refused += 1
                print(f"REFUSED  {name}  {e.reply.get('response')}")
            await asyncio.sleep(GAP)
        for group in groups:
            if group in BACK:
                await lr.call(*BACK[group])
    finally:
        await lr.close()
    return refused


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--group", action="append", help="a group from --list (repeatable)")
    ap.add_argument("--list", action="store_true", help="list the groups and their commands, send nothing")
    ap.add_argument("--port", type=int, help="Lightroom's port (default: from connections.json)")
    ap.add_argument("--yes-this-is-a-test-photo", action="store_true", dest="ok")
    args = ap.parse_args()
    catalog = CommandCatalog.load()
    groups = list(dict.fromkeys(c["group"] for c in catalog.commands.values()))
    if args.list or not args.group:
        for g in groups:
            print(f"{g}: " + ", ".join(c["id"] for c in catalog.commands.values() if c["group"] == g))
        return
    unknown = [g for g in args.group if g not in groups]
    if unknown:
        sys.exit(f"unknown group(s) {unknown}; see --list")
    if not args.ok:
        sys.exit("This sends real commands to Lightroom. Open a test photo, then add --yes-this-is-a-test-photo.")
    refused = asyncio.run(check(set(args.group), args.port))
    print(f"\n{refused} refused" if refused else "\nall accepted")
    print("If the Photos or View group ran, reselect your test photo in Lightroom.")


if __name__ == "__main__":
    main()
