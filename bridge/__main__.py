"""python -m bridge [--debug] [--midi-port NAME] [--check-permission]"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler

from bridge import app, instance, platform

log = logging.getLogger("app")

EXIT_ALREADY_RUNNING = 3


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m bridge", description="Loupedeck+ → Lightroom bridge")
    ap.add_argument("--debug", action="store_true", help="verbose log plus a Lightroom frame log (GUID redacted)")
    ap.add_argument("--midi-port", default="Loupedeck", help="part of the Loupedeck's MIDI port name")
    ap.add_argument("--lightroom-port", type=int, default=None,
                    help="Lightroom's controller port (default: read from Lightroom's connections.json)")
    ap.add_argument("--check-permission", action="store_true",
                    help="macOS: check (and prompt for) the keyboard permission, then exit")
    args = ap.parse_args()

    plat = platform.current()
    log_dir = plat.log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    handlers = [logging.StreamHandler(sys.stderr),
                RotatingFileHandler(log_dir / "bridge.log", maxBytes=1_000_000, backupCount=3)]
    for h in handlers:
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, handlers=handlers)
    logging.getLogger("websockets").setLevel(logging.INFO)  # its DEBUG output is per-frame noise
    log.info("log file: %s", log_dir / "bridge.log")

    if args.check_permission:
        _check_permission()
        return

    lock = instance.acquire(plat.state_dir() / "bridge.lock")
    if lock is None:
        log.error("Another LoupedeckBridge is already running; not starting a second one "
                  "(it would apply every dial turn twice).")
        sys.exit(EXIT_ALREADY_RUNNING)
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass
    log.info("bridge stopped")


async def _run(args) -> None:
    # Ctrl-C, SIGTERM (`bridgectl stop`, the launcher) and SIGHUP all cancel the bridge, so its
    # cleanup runs: held keys are released and ports closed. A plain SIGTERM would just kill it.
    main_task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, main_task.cancel)
        except (NotImplementedError, RuntimeError):  # Windows: Ctrl-C still raises KeyboardInterrupt
            pass

    async def stop_when_parent_gone() -> None:
        await instance.parent_gone(os.getppid())
        log.warning("the app that started the bridge has gone (force-quit?); stopping")
        main_task.cancel()

    watcher = asyncio.create_task(stop_when_parent_gone())
    try:
        await app.run(debug=args.debug, midi_port=args.midi_port, lightroom_port=args.lightroom_port)
    except asyncio.CancelledError:
        pass
    finally:
        watcher.cancel()


def _check_permission() -> None:
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
