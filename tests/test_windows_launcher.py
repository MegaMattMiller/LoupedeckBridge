"""The Windows tray app's rules (windows/launcher/Policies.cs, BuildInfo.cs; milestone 7), checked by building and
running windows/launcher/tests/PolicyTests.csproj, as tests/test_launcher_policies.py does for the Mac's Swift.
Windows with the .NET SDK only."""
from __future__ import annotations

import subprocess

import pytest

from tests.windows_build import CAN_BUILD, LAUNCHER, build

# Ported from macos/launcher/tests/PolicyTests.swift (same names, same rules), then the Windows ones.
CHECKS = ["never_connected_never_alerts", "drop_alerts_after_debounce", "quick_replug_is_silent", "wake_grace",
          "flapping_is_rate_limited", "rate_limited_alert_fires_later", "restart_disarms", "restart_budget",
          "already_running_is_not_a_crash", "parse_rejects_garbage", "bridge_exit_drops_pending_disconnect",
          "quit_after_forced_kill_releases_keys", "quit_after_clean_stop_just_exits",
          "crash_releases_alerts_and_schedules_once", "manual_restart_during_wait_spawns_once",
          "stale_restart_click_does_nothing", "status_ignored_once_the_bridge_is_gone",
          "already_running_quits_the_app", "version_compare", "update_stops_the_bridge_without_quitting",
          "update_after_a_forced_stop_releases_keys", "update_when_stopped_swaps_at_once",
          "update_cancels_a_pending_restart", "failed_update_restarts_the_bridge", "second_update_request_is_ignored",
          "quit_during_an_update_just_quits",
          # Windows
          "parse_reads_busy", "runtime_paths_bundled_and_repo", "bridge_arguments", "build_info_names",
          "build_info_rejects_garbage", "problem_text_names_busy", "tooltips_fit", "command_line_quotes_paths",
          "kill_ends_the_bridge_and_its_python", "kill_leaves_other_children_alone",
          "orphaned_python_is_ended_after_the_launcher_exits"]

pytestmark = pytest.mark.skipif(not CAN_BUILD, reason="needs Windows and the .NET SDK")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    out = tmp_path_factory.mktemp("policies")
    built = build(LAUNCHER / "tests" / "PolicyTests.csproj", out)
    if built.returncode != 0:
        pytest.fail("the C# checks don't build:\n" + built.stdout[-3000:] + built.stderr[-1000:])
    run = subprocess.run([str(out / "PolicyTests.exe")], capture_output=True, text=True, timeout=60)
    found = {}
    for line in run.stdout.splitlines():
        status, _, rest = line.partition(" ")
        name, _, why = rest.partition(":")
        found[name] = (status, why.strip())
    return found


@pytest.mark.parametrize("name", CHECKS)
def test_policy(results, name):
    assert name in results, f"the C# check {name} didn't run"
    status, why = results[name]
    assert status == "ok", why
