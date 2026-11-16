"""A stand-in Lightroom controller server for tests: records every request and answers from a table."""
from __future__ import annotations

import json
from typing import Dict, List, Set, Tuple

from websockets.asyncio.server import serve


class FakeLightroom:
    def __init__(self) -> None:
        self.calls: List[Tuple[str, list]] = []
        self.responses: Dict[str, list] = {"register": ["FAKE-GUID", "10.0"]}
        self.failing: Set[str] = set()
        self._server = None
        self._conns: set = set()

    async def start(self, port: int = 0) -> int:
        self._server = await serve(self._handle, "127.0.0.1", port)
        return self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def drop_clients(self) -> None:
        for conn in list(self._conns):
            await conn.close()

    async def push(self, frame: dict) -> None:
        """Send an unsolicited frame to every client (e.g. a late reply)."""
        for conn in list(self._conns):
            await conn.send(json.dumps(frame))

    async def _handle(self, conn) -> None:
        self._conns.add(conn)
        try:
            async for raw in conn:
                req = json.loads(raw)
                msg, params = req["message"], req.get("params", [])
                self.calls.append((msg, params))
                ok = msg not in self.failing
                reply = {"requestId": req["requestId"], "success": ok,
                         "response": self.responses.get(msg, []) if ok else ["invalid_request"]}
                await conn.send(json.dumps(reply))
        finally:
            self._conns.discard(conn)
