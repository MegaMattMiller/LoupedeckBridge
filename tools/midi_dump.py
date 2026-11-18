#!/usr/bin/env python3
"""Raw MIDI dump for the Loupedeck+ (Step 1 of docs/HANDOFF.md).

Prints every incoming MIDI message and appends it to a JSONL capture file.
While it runs, type a label (e.g. "exposure dial") and press Enter: every
message after that is tagged with the label until you type another one.
That makes the capture self-describing, so we can build the control map
from the file afterwards.

    .venv/bin/python tools/midi_dump.py            # interactive
    .venv/bin/python tools/midi_dump.py --list     # list MIDI ports
    .venv/bin/python tools/midi_dump.py --duration 3   # no prompt, N seconds
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import mido

PROJECT = Path(__file__).resolve().parent.parent
_lock = threading.Lock()
_label = ""          # current label; plain str assignment is atomic in CPython
_t0 = time.monotonic()


def find_port(names: list[str], wanted: str) -> str:
    matches = [n for n in names if wanted.lower() in n.lower()]
    if not matches:
        sys.exit(f"No MIDI input matching {wanted!r}. Available: {names or 'none'}\n"
                 "Is the Loupedeck software running and holding the device?")
    return matches[0]


def to_record(msg: mido.Message) -> dict:
    rec = {
        "t": round(time.monotonic() - _t0, 4),
        "label": _label,
        "type": msg.type,
        "bytes": msg.hex(),
    }
    # Keep only the fields that exist on this message type.
    for field in ("channel", "control", "note", "value", "velocity", "pitch", "program"):
        if hasattr(msg, field):
            rec[field] = getattr(msg, field)
    if msg.type == "sysex":
        rec["data"] = list(msg.data)
    return rec


def fmt(rec: dict) -> str:
    num = (f"cc={rec['control']:<3}" if "control" in rec else
           f"note={rec['note']:<3}" if "note" in rec else "")
    val = rec.get("value", rec.get("velocity", rec.get("pitch", "")))
    ch = f"ch={rec['channel']}" if "channel" in rec else ""
    tag = f"[{rec['label']}]" if rec["label"] else ""
    return f"{rec['t']:9.3f}s {tag:<22} {rec['type']:<15} {ch:<5} {num:<9} val={val!s:<6} {rec['bytes']}"


def main() -> None:
    global _label
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="Loupedeck", help="substring of the MIDI input name")
    ap.add_argument("--list", action="store_true", help="list MIDI ports and exit")
    ap.add_argument("--duration", type=float, help="run N seconds without the label prompt")
    ap.add_argument("--out", type=Path, help="JSONL capture file (default: captures/raw-<time>.jsonl)")
    args = ap.parse_args()

    inputs = mido.get_input_names()
    if args.list:
        print("inputs: ", inputs)
        print("outputs:", mido.get_output_names())
        return

    out = args.out or PROJECT / "captures" / f"raw-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("a", buffering=1, encoding="utf-8")  # line-buffered: survives Ctrl-C mid-capture

    def write(rec: dict) -> None:
        with _lock:
            fh.write(json.dumps(rec) + "\n")

    def on_msg(msg: mido.Message) -> None:
        if msg.type in ("clock", "active_sensing"):
            return
        rec = to_record(msg)
        write(rec)
        print(fmt(rec), flush=True)

    name = find_port(inputs, args.port)
    with mido.open_input(name, callback=on_msg):
        print(f"Listening on {name!r} -> {out}")
        if args.duration is not None:
            time.sleep(args.duration)
        else:
            print("Type a label + Enter before each control (e.g. 'exposure dial'). "
                  "Empty line shows the current label, 'q' or Ctrl-C quits.\n")
            try:
                while True:
                    line = input().strip()
                    if line.lower() in ("q", "quit", "exit"):
                        break
                    if not line:
                        print(f"  current label: {_label or '(none)'}")
                        continue
                    _label = line
                    write({"t": round(time.monotonic() - _t0, 4), "marker": line})
                    print(f"  --- label: {line} ---")
            except (KeyboardInterrupt, EOFError):
                pass
    fh.close()
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
