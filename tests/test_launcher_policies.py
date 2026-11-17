"""The menu-bar app's alert and restart rules (macos/launcher/Policies.swift) and its status pipe
(BridgeProcess.swift), checked by compiling and running macos/launcher/tests/PolicyTests.swift. macOS with swiftc only."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parent.parent / "macos" / "launcher"
CHECKS = ["never_connected_never_alerts", "drop_alerts_after_debounce", "quick_replug_is_silent", "wake_grace",
          "flapping_is_rate_limited", "rate_limited_alert_fires_later", "keys_missing_once_per_run",
          "restart_disarms", "restart_budget", "already_running_is_not_a_crash", "parse_rejects_garbage",
          "status_pipe_reaches_the_app", "bridge_exit_drops_pending_disconnect", "quit_after_forced_kill_releases_keys",
          "quit_after_clean_stop_just_exits", "crash_releases_alerts_and_schedules_once",
          "manual_restart_during_wait_spawns_once", "stale_restart_click_does_nothing",
          "status_ignored_once_the_bridge_is_gone", "already_running_quits_the_app", "runtime_paths_bundled_and_repo",
          "version_compare", "release_parse_accepts_a_real_shape", "release_parse_rejects_garbage", "check_schedule",
          "notice_once_per_version", "install_plan_order", "install_plan_refuses_wrong_bundle",
          "install_plan_refuses_bad_signature", "install_plan_refuses_two_apps", "install_plan_refuses_not_newer",
          "install_plan_accepts_valid"]

pytestmark = pytest.mark.skipif(sys.platform != "darwin" or shutil.which("swiftc") is None,
                                reason="needs macOS and swiftc")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    binary = tmp_path_factory.mktemp("policies") / "policy-tests"
    build = subprocess.run(["swiftc", "-parse-as-library", str(LAUNCHER / "Policies.swift"),
                            str(LAUNCHER / "BridgeProcess.swift"), str(LAUNCHER / "tests" / "PolicyTests.swift"),
                            "-o", str(binary)],
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
