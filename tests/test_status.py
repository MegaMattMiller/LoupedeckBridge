"""The bridge's status lines for LoupedeckBridge.app's menu-bar icon (milestone 5)."""
from __future__ import annotations

import asyncio
import json
import logging
import os

from bridge.status import STATUS_FD_ENV, StatusReporter


class Keyboard:
    def __init__(self, trusted: bool):
        self.trusted = trusted

    def is_trusted(self) -> bool:
        return self.trusted


def test_writes_only_changes():
    lines = []
    s = StatusReporter(lines.append)
    s.set(loupedeck=True)
    s.set(loupedeck=True)
    s.set(lightroom=True)
    assert [json.loads(line)["loupedeck"] for line in lines] == [True, True]
    assert json.loads(lines[-1]) == {**s.state, "loupedeck": True, "lightroom": True}
    assert all(line.endswith("\n") and line.count("\n") == 1 for line in lines)


def test_initial_state():
    s = StatusReporter(lambda line: None, keyboard=Keyboard(True))
    assert s.state == {"loupedeck": False, "lightroom": False, "keys": "allowed", "five_mode": "ratings",
                       "settings_url": None, "loupedeck_busy": False}
    assert StatusReporter(lambda line: None, keyboard=Keyboard(False)).state["keys"] == "missing"


def test_keys_unavailable_without_keyboard():
    assert StatusReporter(lambda line: None, keyboard=None).state["keys"] == "unavailable"


def test_no_fd_means_no_output():
    # Review Focus 3: `python -m bridge` in a terminal has no launcher listening.
    for environ in ({}, {STATUS_FD_ENV: "nope"}, {STATUS_FD_ENV: "987654"}):
        s = StatusReporter.from_env(environ=environ)
        s.set(loupedeck=True)          # nothing written, nothing raised
        asyncio.run(asyncio.wait_for(s.run(interval=0.01), 1))


def test_from_env_writes_lines_to_the_fd():
    r, w = os.pipe()
    s = StatusReporter.from_env(environ={STATUS_FD_ENV: str(w)})
    s.set(loupedeck=True)
    data = os.read(r, 4096).decode()
    assert data.endswith("\n") and json.loads(data)["loupedeck"] is True
    s.close()
    os.close(r)


def test_write_failure_disables_quietly(caplog):
    # Review Focus 3: the app was force-quit; the bridge must keep working.
    r, w = os.pipe()
    s = StatusReporter.from_env(environ={STATUS_FD_ENV: str(w)})
    os.close(r)
    with caplog.at_level(logging.INFO, logger="status"):
        s.set(loupedeck=True)
        s.set(lightroom=True)
        s.close()
    records = [rec for rec in caplog.records if rec.name == "status"]
    assert len(records) == 1 and records[0].levelno == logging.INFO


def test_keys_polled_until_allowed():
    # Review Focus 4: granting the permission while the bridge runs shows within seconds.
    lines = []
    kb = Keyboard(False)
    s = StatusReporter(lines.append, keyboard=kb)

    async def main():
        task = asyncio.ensure_future(s.run(interval=0.01))
        await asyncio.sleep(0.05)
        assert json.loads(lines[-1])["keys"] == "missing"
        kb.trusted = True
        for _ in range(20):
            await asyncio.sleep(0.01)
            if json.loads(lines[-1])["keys"] == "allowed":
                break
        assert json.loads(lines[-1])["keys"] == "allowed"
        settled = len(lines)
        await asyncio.sleep(0.05)
        assert len(lines) == settled                    # polling stopped once allowed
        await asyncio.wait_for(task, 1)                 # and run() returned
    asyncio.run(main())


def test_status_starts_not_busy():
    # Milestone 7: "the Loupedeck is in use by another program" (Windows opens a MIDI input for one program).
    assert StatusReporter(None).state["loupedeck_busy"] is False
