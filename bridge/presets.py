"""Lightroom's presets: ids, and (only when needed) their names.

Lightroom answers getPresetName in ~17–26 ms, so all 1,572 names take ~27 s (measured, milestone 3
live check). Names are therefore remembered on disk: a load asks Lightroom for the id list (fast)
and looks up names only for presets it hasn't seen. A refresh re-reads every name (renames keep
their id, so only a refresh notices them).
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


class PresetCatalog:
    def __init__(self, session, chunk: int = 16, cache_path: Optional[Path] = None):
        # Small chunks: while names load, a dial turn queues behind at most `chunk` requests.
        self.session, self.chunk, self.cache_path = session, chunk, cache_path
        self._ids: Optional[List[str]] = None
        self._items: Optional[List[Tuple[str, str]]] = None
        self._names: Dict[str, str] = self._load_cache()

    async def ids(self) -> List[str]:
        if self._ids is None:
            self._ids = list((await self.session.call("getPresetIDs"))[0])
        return self._ids

    async def items(self, refresh: bool = False, progress: Optional[Progress] = None) -> List[Tuple[str, str]]:
        """(id, name) for every preset, in Lightroom's order."""
        if self._items is None or refresh:
            ids = await self.ids()
            todo = list(ids) if refresh else [i for i in ids if i not in self._names]
            for start in range(0, len(todo), self.chunk):
                part = todo[start:start + self.chunk]
                replies = await asyncio.gather(*(self.session.call("getPresetName", pid) for pid in part))
                self._names.update((pid, reply[0]) for pid, reply in zip(part, replies))
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

    def invalidate(self) -> None:
        """Forget the id list (e.g. after a reconnect); remembered names are kept."""
        self._ids = None
        self._items = None

    def _load_cache(self) -> Dict[str, str]:
        if self.cache_path is None:
            return {}
        try:
            data = json.loads(self.cache_path.read_text())
            return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
        except (OSError, ValueError, AttributeError):
            return {}

    def _save_cache(self) -> None:
        if self.cache_path is None:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_name(self.cache_path.name + ".tmp")
            tmp.write_text(json.dumps(self._names))
            os.replace(tmp, self.cache_path)
        except OSError as e:  # a cache is a convenience: never fail a load over it
            log.warning("couldn't save the preset name cache: %s", e)
