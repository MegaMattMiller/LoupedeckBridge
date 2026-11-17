"""Route control events to their mapped actions: dial adjustments, API calls, presets and keys."""
from __future__ import annotations

import asyncio
import logging
import sys
import webbrowser
from typing import Callable, Dict, List, Optional

from bridge.hardware import COL, FIVE, Event, Press, Release, Turn, five_id
from bridge.lightroom import LightroomError
from bridge.mapping import FN_KEY, Mapping
from bridge.presets import PresetCatalog

log = logging.getLogger("actions")

_ERRORS = (LightroomError, ConnectionError, asyncio.TimeoutError)
STEP_CAP = 3  # most calls one step event may trigger (the device sends ±1 per message anyway)
MODIFIERS = {"shift", "ctrl", "cmd", "alt"}  # held without repeating
CLR_BW = "clr_bw"  # fixed: always keeps the photo's black & white in step with the device
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
        self._generation = 0  # counts reload_presets runs; only the newest one commits
        self._settings_noted = False
        self._held: Dict[str, str] = {}     # control → key name it's holding down
        self._repeats: Dict[str, asyncio.Task] = {}
        self._keys_noted = False
        # The device keeps its own colour/B&W mode (clr/bw flips it; HUE/SAT/LUM pick colour).
        # None until something tells us which it is.
        self._device_bw: Optional[bool] = None
        self._stepping: Dict[str, asyncio.Task] = {}  # control → its in-flight step call
        self._fn = False  # the Fn button is held: controls use their Fn layer
        # The five buttons next to --/Col: "ratings", "colours" or "keys". Always starts in Ratings.
        self._five = self._five_last = "ratings"  # _five_last: the last of Ratings/Colours
        self.on_mode_change: Optional[Callable[[], None]] = None

    @property
    def fn_held(self) -> bool:
        return self._fn

    @property
    def five_mode(self) -> str:
        return self._five

    def banked(self, control: str) -> str:
        """The control id a physical control has right now (the five buttons depend on the mode)."""
        return five_id(control, self._five) if control in FIVE else control

    def _switch_five(self, fn: bool) -> None:
        """--/Col: Ratings ↔ Colours (from Keys: back to the last of them); Fn + --/Col: Keys on / off."""
        if fn:
            self._five = self._five_last if self._five == "keys" else "keys"
        elif self._five == "keys":
            self._five = self._five_last
        else:
            self._five = "colours" if self._five == "ratings" else "ratings"
        if self._five != "keys":
            self._five_last = self._five
        log.info("five buttons: %s", self._five.capitalize())
        if self.on_mode_change is not None:
            try:
                self.on_mode_change()
            except Exception:  # telling the page mustn't break the device
                log.exception("on_mode_change failed")

    def device_reconnected(self) -> None:
        """The device was (re)plugged: it may have powered up in a different mode."""
        self._device_bw = None
        self._fn = False

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
        if event.control == FN_KEY:
            # Fn is the layer key: it only switches layers. The device sends the same numbers for
            # every control with or without it (captured 2026-11-16), so the layer is ours to track.
            if isinstance(event, (Press, Release)):
                self._fn = isinstance(event, Press)
            return
        self._track_device_mode(event)  # the device changes mode even while Lightroom is away
        # Keys are keyboard input, not Lightroom calls: they work whether or not Lightroom is there.
        # A held key remembers what it pressed, so its release ends it even if Fn changed meanwhile.
        if isinstance(event, Release):
            self._release_key(event.control)
            return
        fn = self._fn  # the layer is chosen when a press starts, and per turn message
        if isinstance(event, Press) and event.control == COL:
            self._switch_five(fn)  # fixed: whatever --/Col maps to, in either layer; works without Lightroom
            return
        if isinstance(event, Press) and event.control != CLR_BW:
            # Held keys are remembered by the physical control, so a release after a mode switch
            # still lets go of the key this press started.
            action = self.mapping.press_action(self.banked(event.control), fn=fn)
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
                await self._turn(event, fn)
            elif isinstance(event, Press) and event.control == CLR_BW:
                await self._sync_bw()  # whatever clr/bw maps to, in either layer
            elif isinstance(event, Press):
                await self._press(event, fn)
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
        """Let go of every key the Loupedeck is holding (unplug, shutdown): never leave a stuck key,
        or a stuck Fn layer."""
        self._fn = False
        for control in list(self._held):
            self._release_key(control)

    async def _turn(self, event: Turn, fn: bool = False) -> None:
        action = self.mapping.turn_action(event.control, fn=fn)
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

    async def _press(self, event: Press, fn: bool = False) -> None:
        control = self.banked(event.control)
        action = self.mapping.press_action(control, fn=fn)
        kind = action["type"]
        if kind == "reset_dial":
            # A dial click resets whatever its turn adjusts, in the layer this press is in.
            turn = self.mapping.turn_action(control, fn=fn)
            if turn["type"] != "adjust":
                return
            action, kind = {"type": "call", "message": "resetToDefault", "args": [turn["param"]]}, "call"
        if kind == "call" and action["message"] == "resetToDefault" and action["args"] \
                and str(action["args"][0]).startswith("GrayMixer"):
            # Spec: B&W mix sliders do nothing unless the photo is black & white — resets included,
            # or a click would quietly reset a B&W mix saved on a colour photo.
            if not bool((await self.session.call("isBlackAndWhiteOn"))[0]):
                log.info("%s click ignored: the photo isn't black & white", event.control)
                return
        if kind == "call" and action["message"] == "exportWithPrevious":
            reply = await self.session.call("canExportWithPrevious")
            if not (isinstance(reply, list) and reply and reply[0]):
                log.info("Fn + Export: Lightroom has no previous export settings yet; nothing exported")
                return
        if kind == "call":
            await self.session.call(action["message"], *action["args"])
        elif kind == "preset":
            preset_id = self._presets.get(event.control)
            if preset_id is not None:
                await self.session.call("applyPreset", preset_id)
            elif action.get("id") or action.get("name"):
                log.warning("%s: its preset couldn't be found in Lightroom; nothing applied", event.control)

    async def _sync_bw(self) -> None:
        """Make the photo match the device's new colour/B&W mode instead of toggling blindly, so the
        lights and the photo can't end up opposite each other. Unknown mode: a plain toggle."""
        if self._device_bw is None:
            await self.session.call("toggleBlackAndWhite")
            return
        photo_bw = bool((await self.session.call("isBlackAndWhiteOn"))[0])
        if photo_bw != self._device_bw:
            await self.session.call("toggleBlackAndWhite")

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
        """Re-match the slots (e.g. after a slot was changed in the settings page).

        Only the newest run keeps its result: an older, slower one (say the check after a reconnect,
        waiting on 1,500 names) saw the slots as they were before a later change."""
        self._generation += 1
        mine = self._generation
        presets: Dict[str, str] = {}
        problems: Dict[str, str] = {}
        warnings: List[str] = []

        def problem(control: str, kind: str, message: str) -> None:
            problems[control] = kind
            warnings.append(message)

        slots = [(c, a) for c, a in self.mapping.press_items()
                 if a["type"] == "preset" and (a.get("id") or a.get("name"))]
        try:
            ids = await self.catalog.ids() if slots else []
            for control, action in slots:
                if action.get("id") in ids:
                    presets[control] = action["id"]
                    continue
                name = action.get("name")
                if not name:
                    problem(control, "missing", f"{control}: preset id {action.get('id')!r} no longer exists "
                                                "in Lightroom")
                    continue
                names = await self.catalog.items()  # only when an id didn't match (1,500+ calls)
                matches = [i for i, n in names if n == name]
                if len(matches) == 1:
                    presets[control] = matches[0]
                elif matches:
                    problem(control, "ambiguous", f"{control}: {len(matches)} presets named {name!r}; "
                                                  "assign it again in the settings")
                else:
                    problem(control, "missing", f"{control}: no preset named {name!r} in Lightroom")
        except _ERRORS as e:
            log.warning("couldn't resolve presets: %s", e)
        if mine != self._generation:
            return  # a newer run started meanwhile; its result stands
        self._presets, self._preset_problems, self.preset_warnings = presets, problems, warnings
        for message in warnings:
            log.warning(message)

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

