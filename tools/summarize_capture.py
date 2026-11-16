#!/usr/bin/env python3
"""Summarize a midi_dump.py capture into a per-control table.

    .venv/bin/python tools/summarize_capture.py                 # newest capture
    .venv/bin/python tools/summarize_capture.py captures/raw-....jsonl

For each label typed during the capture, shows which MIDI source it maps to.
Capture convention: if you touched the wrong control first, just finish on the
right one. Per kind (dial turn = "cc", press = "note"), the LAST source seen
under a label is the one that counts; earlier ones are listed as discarded.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


def describe_cc(values: list[int]) -> str:
    """Loupedeck+ dials send one message per detent: 1 = clockwise, 127 = counter-clockwise
    (two's complement -1). Anything else would be a control type we haven't seen yet."""
    if set(values) <= {1, 127}:
        return f"dial ±1  ({values.count(1)} cw / {values.count(127)} ccw)"
    return f"UNEXPECTED values {sorted(set(values))}"


def newest_capture() -> Path:
    files = sorted((PROJECT / "captures").glob("raw-*.jsonl"))
    if not files:
        sys.exit("No captures yet. Run tools/midi_dump.py first.")
    return files[-1]


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else newest_capture()
    order: dict[str, list[tuple]] = defaultdict(list)        # label -> sources in arrival order
    values: dict[tuple, list] = defaultdict(list)             # (label, source) -> values
    for line in path.read_text().splitlines():
        rec = json.loads(line)
        if "marker" in rec:
            continue
        label = rec["label"] or "(unlabelled)"
        if rec["type"] == "control_change":
            src, val = ("cc", rec["channel"], rec["control"]), rec["value"]
        elif "note" in rec:  # note_on and note_off are one source: press + release
            src, val = ("note", rec["channel"], rec["note"]), rec["type"]
        else:
            src, val = (rec["type"], rec.get("channel"), None), rec.get("value")
        order[label].append(src)
        values[(label, src)].append(val)

    print(f"Capture: {path}\n")
    print(f"{'label':<28} {'kind':<5} {'ch':<3} {'#':<4} detail")
    for label, seq in order.items():
        last = {src[0]: src for src in seq}            # per kind, the last source wins
        discarded = sorted({s for s in seq if last[s[0]] != s}, key=seq.index)
        for kind, src in sorted(last.items()):
            vals = values[(label, src)]
            detail = (describe_cc(vals) if kind == "cc" else
                      f"{vals.count('note_on')} press / {vals.count('note_off')} release" if kind == "note" else
                      f"{len(vals)} msgs")
            print(f"{label:<28} {kind:<5} {src[1]!s:<3} {src[2]!s:<4} {detail}")
        for kind, ch, num in discarded:
            print(f"{'':<28} {kind:<5} {ch!s:<3} {num!s:<4} (discarded: touched before the final control)")


if __name__ == "__main__":
    main()
