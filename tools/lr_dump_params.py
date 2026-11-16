#!/usr/bin/env python3
"""Step 3: dump every Lightroom edit parameter's type, label, default and range (READ-ONLY).

    .venv/bin/python tools/lr_dump_params.py

Writes docs/lr_parameters_<version>.json. Reply shapes are documented in docs/FINDINGS.md:
every `response` is an array of return values, so single values are unwrapped with [0].
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from bridge.lightroom import Lightroom, LightroomError  # noqa: E402

RANGE_KEYS = ("min", "max", "decimals", "small_step", "large_step")


async def one(lr: Lightroom, msg: str, name: str):
    """First return value of msg(name), or {"error": ...}."""
    try:
        resp = await lr.call(msg, name)
        return resp[0] if isinstance(resp, list) and len(resp) == 1 else resp
    except LightroomError as e:
        return {"error": e.reply.get("response")}
    except asyncio.TimeoutError:
        return {"error": "timeout"}


async def main() -> None:
    lr = Lightroom("Loupedeck+ Bridge", "0.1")
    await lr.connect()
    try:
        await lr.register()
        version = (await lr.call("appVersionString"))[0]
        names = (await lr.call("getParameterNames"))[0]
        out: dict[str, dict] = {}
        for name in names:
            entry = {
                "type": await one(lr, "getParameterType", name),
                "label": await one(lr, "getLabel", name),
                "default": await one(lr, "getDefault", name),
            }
            if entry["type"] == "number":
                rng = await one(lr, "getRange", name)
                # Usually 5 values; some parameters omit the large step (4 values).
                if isinstance(rng, list) and len(rng) in (4, 5):
                    entry.update(zip(RANGE_KEYS, rng))
                else:
                    entry["range"] = rng
            out[name] = entry
    finally:
        await lr.close()

    path = PROJECT / "docs" / f"lr_parameters_{version}.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    types: dict[str, int] = {}
    for e in out.values():
        key = e["type"] if isinstance(e["type"], str) else "error"
        types[key] = types.get(key, 0) + 1
    errors = [n for n, e in out.items() if any(isinstance(v, dict) and "error" in v for v in e.values())
              or "range" in e]
    print(f"{len(out)} parameters -> {path.relative_to(PROJECT)}  types: {types}")
    print(f"entries with an error or odd range: {len(errors)} {errors[:15]}")


if __name__ == "__main__":
    asyncio.run(main())
