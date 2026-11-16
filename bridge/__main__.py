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
    ap.add_argument("--midi-port", default="Loupedeck", help="part of the Loupedeck's MIDI port name")
    ap.add_argument("--check-permission", action="store_true",
                    help="macOS: check (and prompt for) the keyboard permission, then exit")
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

    if args.check_permission:
        _check_permission()
        return
    try:
        asyncio.run(app.run(debug=args.debug, midi_port=args.midi_port))
    except KeyboardInterrupt:
        pass


def _check_permission() -> None:
    log = logging.getLogger("app")
    if sys.platform != "darwin":
        log.info("Accessibility permission: not needed on this system")
        return
    from bridge.platform import macos_ax
    if macos_ax.request_permission(prompt=True):
        log.info("Accessibility permission: granted")
    else:
        log.warning("Accessibility permission: missing. macOS is asking now: allow it in System Settings → "
                    "Privacy & Security → Accessibility (for the app that started the bridge, "
                    "e.g. LoupedeckBridge).")


if __name__ == "__main__":
    main()
