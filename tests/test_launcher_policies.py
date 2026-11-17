"""The menu-bar app's alert and restart rules (macos/launcher/Policies.swift), checked by compiling and
running macos/launcher/tests/PolicyTests.swift. macOS with swiftc only."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parent.parent / "macos" / "launcher"
CHECKS = ["never_connected_never_alerts", "drop_alerts_after_debounce", "quick_replug_is_silent", "wake_grace",
          "flapping_is_rate_limited", "rate_limited_alert_fires_later", "keys_missing_once_per_run",
          "restart_disarms", "restart_budget", "already_running_is_not_a_crash", "parse_rejects_garbage"]

pytestmark = pytest.mark.skipif(sys.platform != "darwin" or shutil.which("swiftc") is None,
                                reason="needs macOS and swiftc")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    binary = tmp_path_factory.mktemp("policies") / "policy-tests"
    build = subprocess.run(["swiftc", "-parse-as-library", str(LAUNCHER / "Policies.swift"),
                            str(LAUNCHER / "tests" / "PolicyTests.swift"), "-o", str(binary)],
                           capture_output=True, text=True)
    if build.returncode != 0:
        pytest.fail("Policies.swift doesn't compile:\n" + build.stderr[-3000:])
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    found = {}
    for line in run.stdout.splitlines():
        status, _, rest = line.partition(" ")
        name, _, why = rest.partition(":")
        found[name] = (status, why.strip())
    return found


@pytest.mark.parametrize("name", CHECKS)
def test_policy(results, name):
    assert name in results, f"the Swift check {name} didn't run"
    status, why = results[name]
    assert status == "ok", why
