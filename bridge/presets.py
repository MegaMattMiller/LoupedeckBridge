"""Lightroom's presets: ids, and (only when needed) their names.

Lightroom answers getPresetName in ~17–26 ms, so all 1,572 names take ~27 s (measured, milestone 3
live check). Names are therefore remembered on disk: a load asks Lightroom for the id list (fast)
and looks up names only for presets it hasn't seen. A refresh re-reads every name (renames keep
their id, so only a refresh notices them).

Callers share one load: a second tab, or a reconnect while the page is loading, waits for the
running load instead of starting its own (which would double both the wait and the queue a dial
turn waits behind).
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("presets")

Progress = Callable[[int, int], Any]  # (done, total); may be async
UNNAMED = "(unnamed preset)"


def _name(reply) -> str:
    """getPresetName's answer is [name]; anything else (e.g. [] or [None]) gets a placeholder."""
    name = reply[0] if isinstance(reply, list) and reply else None
    return name if isinstance(name, str) and name else UNNAMED


class PresetCatalog:
    def __init__(self, session, chunk: int = 16, cache_path: Optional[Path] = None):
        # Small chunks: while names load, a dial turn queues behind at most `chunk` requests.
        self.session, self.chunk, self.cache_path = session, chunk, cache_path
        self._ids: Optional[List[str]] = None
        self._items: Optional[List[Tuple[str, str]]] = None
        self._names: Dict[str, str] = self._load_cache()
        self._loading: Optional[asyncio.Future] = None  # the load every caller shares
        self._loading_refresh = False

    async def ids(self) -> List[str]:
        if self._ids is None:
            self._ids = list((await self.session.call("getPresetIDs"))[0])
        return self._ids

    async def items(self, refresh: bool = False, progress: Optional[Progress] = None) -> List[Tuple[str, str]]:
        """(id, name) for every preset, in Lightroom's order. refresh re-reads the id list and every name.

        progress is called by the load this call starts; a call that joins a running load gets no progress."""
        while True:
            task = self._loading if self._loading is not None and not self._loading.done() else None
            if task is None:
                if self._items is not None and not refresh:
                    return self._items
                task = self._loading = asyncio.ensure_future(self._load(refresh, progress))
                self._loading_refresh = refresh
                task.add_done_callback(self._load_done)
                covers = True
            else:
                covers = self._loading_refresh or not refresh  # a plain load can't stand in for a refresh
            # shield: a caller that goes away (a closed tab) mustn't stop the load the others wait for
            result = await asyncio.shield(task)
            if covers:
                return result

    async def _load(self, refresh: bool, progress: Optional[Progress]) -> List[Tuple[str, str]]:
        if refresh:
            self._ids = None  # presets may have been added or removed too
        ids = await self.ids()
        todo = list(ids) if refresh else [i for i in ids if i not in self._names]
        for start in range(0, len(todo), self.chunk):
            part = todo[start:start + self.chunk]
            replies = await asyncio.gather(*(self.session.call("getPresetName", pid) for pid in part))
            self._names.update((pid, _name(reply)) for pid, reply in zip(part, replies))
            if progress is not None:
                result = progress(min(start + self.chunk, len(todo)), len(todo))
                if inspect.isawaitable(result):
                    await result  # e.g. sending it to the page: keeps progress ahead of the list
        known = set(ids)
        self._names = {i: n for i, n in self._names.items() if i in known}
        self._items = [(i, self._names[i]) for i in ids]
        if todo or len(self._names) != len(ids):
            self._save_cache()
        return self._items

    def _load_done(self, task: "asyncio.Future") -> None:
        if self._loading is task:
            self._loading = None
        if not task.cancelled():
            task.exception()  # retrieved here, so a load nobody waits for anymore doesn't log a warning

    def invalidate(self) -> None:
        """Forget the id list (e.g. after a reconnect); remembered names are kept."""
        self._ids = None
        self._items = None

    def _load_cache(self) -> Dict[str, str]:
        if self.cache_path is None:
            return {}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8-sig"))
            return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
        except (OSError, ValueError, AttributeError):
            return {}

    def _save_cache(self) -> None:
        if self.cache_path is None:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_name(self.cache_path.name + ".tmp")
            tmp.write_text(json.dumps(self._names), encoding="utf-8")
            os.replace(tmp, self.cache_path)
        except OSError as e:  # a cache is a convenience: never fail a load over it
            log.warning("couldn't save the preset name cache: %s", e)
