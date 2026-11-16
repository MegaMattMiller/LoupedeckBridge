#!/usr/bin/env python3
"""Wait for a Loupedeck+ control that isn't in config/loupedeck_plus.json yet.

Ignores every dial/button already in the map (plus --ignore numbers). On the
first unknown CC or note it plays a chime, keeps listening --settle seconds to
catch everything that control sends, prints a summary and exits.

    .venv/bin/python tools/find_unknown.py [--ignore 25 26] [--timeout 900]

Everything heard (known or not) is also logged to captures/find-<time>.jsonl.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import mido

PROJECT = Path(__file__).resolve().parent.parent
CHIME = Path("/System/Library/Sounds/Glass.aiff")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="Loupedeck")
    ap.add_argument("--ignore", type=int, nargs="*", default=[], help="numbers to treat as known")
    ap.add_argument("--timeout", type=float, default=900, help="give up after N seconds")
    ap.add_argument("--settle", type=float, default=2.0, help="seconds to keep listening after the first hit")
    args = ap.parse_args()

    cfg = json.loads((PROJECT / "config" / "loupedeck_plus.json").read_text())
    hsl = {n for mode, m in cfg.get("colour_dials", {}).items() if not mode.startswith("_") for n in m.values()}
    known_cc = set(cfg["dials"].values()) | hsl | set(args.ignore)
    known_note = known_cc | set(cfg["buttons"].values())

    names = [n for n in mido.get_input_names() if args.port.lower() in n.lower()]
    if not names:
        sys.exit(f"No MIDI input matching {args.port!r}")

    log_path = PROJECT / "captures" / f"find-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    log = log_path.open("a", buffering=1)
    hits: list[tuple[float, str, int, object]] = []
    first = threading.Event()
    t0 = time.monotonic()

    def on_msg(msg: mido.Message) -> None:
        if msg.type == "control_change":
            kind, num, val = "cc", msg.control, msg.value
        elif msg.type in ("note_on", "note_off"):
            kind, num, val = "note", msg.note, msg.type
        else:
            return
        t = round(time.monotonic() - t0, 4)
        known = num in (known_cc if kind == "cc" else known_note)
        log.write(json.dumps({"t": t, "kind": kind, "num": num, "val": val, "known": known}) + "\n")
        if not known:
            hits.append((t, kind, num, val))
            first.set()

    with mido.open_input(names[0], callback=on_msg):
        print(f"listening on {names[0]!r}; ignoring {len(known_cc)} dials + {len(known_note - known_cc)} buttons",
              flush=True)
        if not first.wait(args.timeout):
            print("TIMEOUT: no unknown control heard")
            sys.exit(2)
        if CHIME.exists():
            subprocess.Popen(["afplay", str(CHIME)])
        time.sleep(args.settle)
    log.close()

    per: dict[tuple, list] = defaultdict(list)
    for t, kind, num, val in hits:
        per[(kind, num)].append((t, val))
    print(f"FOUND at {hits[0][0]:.2f}s (log: {log_path.name})")
    for (kind, num), evs in per.items():
        vals = [v for _, v in evs]
        if kind == "cc":
            detail = f"{vals.count(1)} cw / {vals.count(127)} ccw" + (
                "" if set(vals) <= {1, 127} else f"  OTHER VALUES {sorted(set(vals))}")
        else:
            detail = f"{vals.count('note_on')} press / {vals.count('note_off')} release"
        print(f"  {kind:<4} #{num:<4} n={len(vals):<3} first@{evs[0][0]:.2f}s  {detail}")
    # Interleaving tells us whether several numbers came from one control.
    print("  sequence:", " ".join(f"{k}{n}" for _, k, n, _ in hits[:30]) + (" …" if len(hits) > 30 else ""))


if __name__ == "__main__":
    main()
