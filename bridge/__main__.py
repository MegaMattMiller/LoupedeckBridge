"""python -m bridge [--debug]"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

from bridge import app, platform


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m bridge", description="Loupedeck+ → Lightroom bridge")
    ap.add_argument("--debug", action="store_true", help="verbose log plus a Lightroom frame log (GUID redacted)")
    args = ap.parse_args()

    log_dir = platform.current().log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    handlers = [logging.StreamHandler(sys.stderr),
                RotatingFileHandler(log_dir / "bridge.log", maxBytes=1_000_000, backupCount=3)]
    for h in handlers:
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, handlers=handlers)
    logging.getLogger("websockets").setLevel(logging.INFO)  # its DEBUG output is per-frame noise
    logging.getLogger("app").info("log file: %s", log_dir / "bridge.log")

    try:
        asyncio.run(app.run(debug=args.debug))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
