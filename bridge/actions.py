"""Route control events to their mapped actions: dial adjustments, API calls and presets."""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

from bridge.hardware import Event, Press, Turn
from bridge.lightroom import LightroomError
from bridge.mapping import Mapping

log = logging.getLogger("actions")

_ERRORS = (LightroomError, ConnectionError, asyncio.TimeoutError)


class Dispatcher:
    def __init__(self, mapping: Mapping, session, dials):
        self.mapping, self.session, self.dials = mapping, session, dials
        self.preset_warnings: List[str] = []
        self._presets: Dict[str, str] = {}  # control → resolved preset id
        self._keys_noted = False
        # The device keeps its own colour/B&W mode (clr/bw flips it; HUE/SAT/LUM pick colour).
        # None until something tells us which it is.
        self._device_bw: Optional[bool] = None

    def _track_device_mode(self, event: Event) -> None:
        if isinstance(event, Turn):
            bank = event.control.split("_", 1)[0]
            if bank == "bw":
                self._device_bw = True
            elif bank in ("hue", "sat", "lum"):
                self._device_bw = False
        elif isinstance(event, Press):
            if event.control in ("hue", "sat", "lum"):
                self._device_bw = False
            elif event.control == "clr_bw" and self._device_bw is not None:
                self._device_bw = not self._device_bw

    async def handle(self, event: Event) -> None:
        self._track_device_mode(event)  # the device changes mode even while Lightroom is away
        if not self.session.connected:
            log.debug("dropped %s: Lightroom isn't connected", event)
            return
        try:
            if isinstance(event, Turn):
                await self._turn(event)
            elif isinstance(event, Press):
                await self._press(event)
            # Release: nothing until keyboard keys arrive (milestone 2)
        except _ERRORS as e:
            log.warning("%s failed: %s", event, e)

    async def _turn(self, event: Turn) -> None:
        action = self.mapping.turn_action(event.control)
        if action["type"] == "adjust":
            self.dials.add(action["param"], event.detents)
        elif action["type"] == "step":
            call = action["cw"] if event.detents > 0 else action["ccw"]
            for _ in range(abs(event.detents)):
                await self.session.call(call["message"], *call["args"])

    async def _press(self, event: Press) -> None:
        action = self.mapping.press_action(event.control)
        kind = action["type"]
        if kind == "call" and action["message"] == "toggleBlackAndWhite" and event.control == "clr_bw" \
                and self._device_bw is not None:
            # Make the photo match the device's new mode instead of toggling blindly, so the
            # lights and the photo can't end up opposite each other.
            photo_bw = bool((await self.session.call("isBlackAndWhiteOn"))[0])
            if photo_bw != self._device_bw:
                await self.session.call("toggleBlackAndWhite")
        elif kind == "call":
            await self.session.call(action["message"], *action["args"])
        elif kind == "preset":
            preset_id = self._presets.get(event.control)
            if preset_id is not None:
                await self.session.call("applyPreset", preset_id)
            elif action.get("id") or action.get("name"):
                log.warning("%s: its preset couldn't be found in Lightroom; nothing applied", event.control)
        elif kind in ("key", "shortcut") and not self._keys_noted:
            self._keys_noted = True
            log.info("keyboard keys and shortcuts arrive in milestone 2; ignoring %s for now", event.control)

    async def resolve_presets(self) -> None:
        """Match each preset slot to a Lightroom preset: by id, else by an exact, unique name."""
        self._presets, self.preset_warnings = {}, []
        slots = [(c, a) for c, a in self.mapping.press_items()
                 if a["type"] == "preset" and (a.get("id") or a.get("name"))]
        if not slots:
            return
        try:
            ids = (await self.session.call("getPresetIDs"))[0]
            names: Optional[Dict[str, str]] = None
            for control, action in slots:
                if action.get("id") in ids:
                    self._presets[control] = action["id"]
                    continue
                name = action.get("name")
                if not name:
                    self._warn(f"{control}: preset id {action.get('id')!r} no longer exists in Lightroom")
                    continue
                if names is None:  # only fetched when an id didn't match (1,500+ calls)
                    names = {i: (await self.session.call("getPresetName", i))[0] for i in ids}
                matches = [i for i, n in names.items() if n == name]
                if len(matches) == 1:
                    self._presets[control] = matches[0]
                elif matches:
                    self._warn(f"{control}: {len(matches)} presets named {name!r}; assign it again in the settings")
                else:
                    self._warn(f"{control}: no preset named {name!r} in Lightroom")
        except _ERRORS as e:
            log.warning("couldn't resolve presets: %s", e)

    def _warn(self, message: str) -> None:
        self.preset_warnings.append(message)
        log.warning(message)
