"""Lightroom's presets: ids, and (only when needed) their names, cached until invalidated."""
from __future__ import annotations

import asyncio
from typing import List, Optional, Tuple


class PresetCatalog:
    def __init__(self, session, chunk: int = 50):
        self.session, self.chunk = session, chunk
        self._ids: Optional[List[str]] = None
        self._items: Optional[List[Tuple[str, str]]] = None

    async def ids(self) -> List[str]:
        if self._ids is None:
            self._ids = list((await self.session.call("getPresetIDs"))[0])
        return self._ids

    async def items(self) -> List[Tuple[str, str]]:
        """(id, name) for every preset. One getPresetName call per preset (1,500+), sent in
        concurrent chunks so the list is ready in a second or two."""
        if self._items is None:
            ids = await self.ids()
            items: List[Tuple[str, str]] = []
            for start in range(0, len(ids), self.chunk):
                part = ids[start:start + self.chunk]
                names = await asyncio.gather(*(self.session.call("getPresetName", pid) for pid in part))
                items.extend((pid, reply[0]) for pid, reply in zip(part, names))
            self._items = items
        return self._items

    def invalidate(self) -> None:
        """Forget everything (e.g. after a reconnect: presets may have been added or removed)."""
        self._ids = None
        self._items = None
