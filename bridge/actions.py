"""Route control events to their mapped actions: dial adjustments, API calls, presets and keys."""
from __future__ import annotations

import asyncio
import logging
import sys
import webbrowser
from typing import Callable, Dict, List, Optional

from bridge.hardware import Event, Press, Release, Turn
from bridge.lightroom import LightroomError
from bridge.mapping import Mapping
from bridge.presets import PresetCatalog

log = logging.getLogger("actions")

_ERRORS = (LightroomError, ConnectionError, asyncio.TimeoutError)
STEP_CAP = 3  # most calls one step event may trigger (the device sends ±1 per message anyway)
MODIFIERS = {"shift", "ctrl", "cmd", "alt"}  # held without repeating
PERMISSION_HELP = ("Keyboard keys need macOS's Accessibility permission: System Settings → Privacy & Security → "
                   "Accessibility → turn on LoupedeckBridge (run the bridge from LoupedeckBridge.app; "
                   "see the README).")


class Dispatcher:
    def __init__(self, mapping: Mapping, session, dials, keyboard=None,
                 repeat_delay: float = 0.4, repeat_interval: float = 0.05,
                 catalog: Optional[PresetCatalog] = None,
                 opener: Callable[[str], object] = webbrowser.open, settings_url: Optional[str] = None):
        self.mapping, self.session, self.dials, self.keyboard = mapping, session, dials, keyboard
        # Synthetic key-downs don't auto-repeat on macOS, so held non-modifier keys repeat here.
        self.repeat_delay, self.repeat_interval = repeat_delay, repeat_interval
        self.catalog = catalog or PresetCatalog(session)
        self.opener, self.settings_url = opener, settings_url
        self.preset_warnings: List[str] = []
        self._presets: Dict[str, str] = {}  # control → resolved preset id
        self._preset_problems: Dict[str, str] = {}  # control → "missing" | "ambiguous"
        self._settings_noted = False
        self._held: Dict[str, str] = {}     # control → key name it's holding down
        self._repeats: Dict[str, asyncio.Task] = {}
        self._keys_noted = False
        # The device keeps its own colour/B&W mode (clr/bw flips it; HUE/SAT/LUM pick colour).
        # None until something tells us which it is.
        self._device_bw: Optional[bool] = None
        self._stepping: Dict[str, asyncio.Task] = {}  # control → its in-flight step call

    def device_reconnected(self) -> None:
        """The device was (re)plugged: it may have powered up in a different mode."""
        self._device_bw = None

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
        # Keys are keyboard input, not Lightroom calls: they work whether or not Lightroom is there.
        if isinstance(event, Release):
            self._release_key(event.control)
            return
        if isinstance(event, Press):
            action = self.mapping.press_action(event.control)
            if action["type"] in ("key", "shortcut"):
                self._press_key(event.control, action)
                return
            if action["type"] == "open_settings":  # also works while Lightroom is away
                self._open_settings()
                return
        if not self.session.connected:
            log.debug("dropped %s: Lightroom isn't connected", event)
            return
        try:
            if isinstance(event, Turn):
                await self._turn(event)
            elif isinstance(event, Press):
                await self._press(event)
        except _ERRORS as e:
            log.warning("%s failed: %s", event, e)

    # ---- keyboard keys -------------------------------------------------------
    def _press_key(self, control: str, action: dict) -> None:
        kb = self.keyboard
        if kb is None:
            if not self._keys_noted:
                self._keys_noted = True
                log.info("keyboard keys aren't available on this system yet; ignoring %s", control)
            return
        if not kb.is_trusted():
            if not self._keys_noted:
                self._keys_noted = True
                log.warning(PERMISSION_HELP)
            return
        try:
            if action["type"] == "shortcut":
                kb.tap(action["mac"] if sys.platform == "darwin" else action["windows"])
            elif control not in self._held:
                name = action["key"]
                kb.key_down(name)
                self._held[control] = name
                if name not in MODIFIERS:
                    self._repeats[control] = asyncio.get_running_loop().create_task(self._repeat(name))
        except ValueError as e:
            log.warning("%s: %s; nothing sent", control, e)

    async def _repeat(self, name: str) -> None:
        await asyncio.sleep(self.repeat_delay)
        while True:
            self.keyboard.key_repeat(name)
            await asyncio.sleep(self.repeat_interval)

    def _release_key(self, control: str) -> None:
        name = self._held.pop(control, None)
        if name is None:
            return
        task = self._repeats.pop(control, None)
        if task is not None:
            task.cancel()
        self.keyboard.key_up(name)

    def release_all_keys(self) -> None:
        """Let go of every key the Loupedeck is holding (unplug, shutdown): never leave a stuck key."""
        for control in list(self._held):
            self._release_key(control)

    async def _turn(self, event: Turn) -> None:
        action = self.mapping.turn_action(event.control)
        if action["type"] == "adjust":
            self.dials.add(action["param"], event.detents)
        elif action["type"] == "step":
            # Never queue steps: while one is in flight, further detents are dropped, so a fast
            # spin can't keep changing photos after you stop or hold up the other controls.
            if event.control in self._stepping:
                log.debug("%s: step dropped, the previous one is still running", event.control)
                return
            call = action["cw"] if event.detents > 0 else action["ccw"]
            task = asyncio.create_task(self._step(event.control, call, min(abs(event.detents), STEP_CAP)))
            self._stepping[event.control] = task
            task.add_done_callback(lambda _t, control=event.control: self._stepping.pop(control, None))

    async def _step(self, control: str, call: dict, count: int) -> None:
        for _ in range(count):
            try:
                await self.session.call(call["message"], *call["args"])
            except Exception as e:  # runs on its own; nothing above it would see the error
                log.warning("%s: %s failed: %s", control, call["message"], e)
                return

    async def _press(self, event: Press) -> None:
        action = self.mapping.press_action(event.control)
        kind = action["type"]
        if event.control.startswith("bw_") and kind != "none":
            # Spec: B&W-bank dials do nothing unless the photo is black & white — clicks included,
            # or a click would quietly reset a B&W mix saved on a colour photo.
            if not bool((await self.session.call("isBlackAndWhiteOn"))[0]):
                log.info("%s click ignored: the photo isn't black & white", event.control)
                return
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

    def _open_settings(self) -> None:
        if self.settings_url is None:
            if not self._settings_noted:
                self._settings_noted = True
                log.info("the settings page isn't running, so there's nothing to open")
            return
        try:
            self.opener(self.settings_url)
        except Exception as e:  # a browser problem mustn't affect the bridge
            log.warning("couldn't open %s: %s", self.settings_url, e)

    async def resolve_presets(self) -> None:
        """Match each preset slot to a Lightroom preset: by id, else by an exact, unique name.
        Called after each connect; Lightroom's presets may have changed, so the catalog is refreshed."""
        self.catalog.invalidate()
        await self.reload_presets()

    async def reload_presets(self) -> None:
        """Re-match the slots (e.g. after a slot was changed in the settings page)."""
        self._presets, self._preset_problems, self.preset_warnings = {}, {}, []
        slots = [(c, a) for c, a in self.mapping.press_items()
                 if a["type"] == "preset" and (a.get("id") or a.get("name"))]
        try:
            ids = await self.catalog.ids() if slots else []
            for control, action in slots:
                if action.get("id") in ids:
                    self._presets[control] = action["id"]
                    continue
                name = action.get("name")
                if not name:
                    self._problem(control, "missing", f"{control}: preset id {action.get('id')!r} no longer exists "
                                                      "in Lightroom")
                    continue
                names = await self.catalog.items()  # only when an id didn't match (1,500+ calls)
                matches = [i for i, n in names if n == name]
                if len(matches) == 1:
                    self._presets[control] = matches[0]
                elif matches:
                    self._problem(control, "ambiguous", f"{control}: {len(matches)} presets named {name!r}; "
                                                        "assign it again in the settings")
                else:
                    self._problem(control, "missing", f"{control}: no preset named {name!r} in Lightroom")
        except _ERRORS as e:
            log.warning("couldn't resolve presets: %s", e)

    def slot_status(self, control: str) -> dict:
        """What the settings page shows for a preset slot."""
        action = self.mapping.press_action(control)
        pid = action.get("id") if action["type"] == "preset" else None
        name = action.get("name") if action["type"] == "preset" else None
        if not pid and not name:
            status = "empty"
        elif control in self._presets:
            status = "ok"
        elif control in self._preset_problems:
            status = self._preset_problems[control]
        else:
            status = "unknown"  # Lightroom hasn't been asked yet (e.g. not connected)
        return {"slot": control, "id": pid, "name": name, "status": status}

    def _problem(self, control: str, kind: str, message: str) -> None:
        self._preset_problems[control] = kind
        self._warn(message)

    def _warn(self, message: str) -> None:
        self.preset_warnings.append(message)
        log.warning(message)
