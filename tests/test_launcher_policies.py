"""The menu-bar app's alert and restart rules (macos/launcher/Policies.swift) and its status pipe
(BridgeProcess.swift) and its signature check (Signature.swift), checked by compiling and running macos/launcher/tests/PolicyTests.swift. macOS with swiftc only."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parent.parent / "macos" / "launcher"
CHECKS = ["never_connected_never_alerts", "drop_alerts_after_debounce", "quick_replug_is_silent", "wake_grace",
          "flapping_is_rate_limited", "rate_limited_alert_fires_later", "keys_missing_once_per_run",
          "restart_disarms", "restart_budget", "already_running_is_not_a_crash", "parse_rejects_garbage", "parse_ignores_new_fields",
          "status_pipe_reaches_the_app", "bridge_exit_drops_pending_disconnect", "quit_after_forced_kill_releases_keys",
          "quit_after_clean_stop_just_exits", "crash_releases_alerts_and_schedules_once",
          "manual_restart_during_wait_spawns_once", "stale_restart_click_does_nothing",
          "status_ignored_once_the_bridge_is_gone", "already_running_quits_the_app", "runtime_paths_bundled_and_repo",
          "version_compare", "release_parse_accepts_a_real_shape", "release_parse_rejects_garbage", "check_schedule",
          "notice_once_per_version", "notice_survives_a_relaunch", "found_update_survives_a_relaunch",
          "install_plan_order", "install_plan_refuses_wrong_bundle",
          "install_plan_refuses_bad_signature", "install_plan_refuses_two_apps", "install_plan_refuses_not_newer",
          "install_plan_accepts_valid", "download_is_capped_and_hashed", "unzip_problem_says_why",
          "bridge_python_runs_only_its_own_code", "update_stops_the_bridge_without_quitting",
          "update_after_a_forced_stop_releases_keys", "update_when_stopped_swaps_at_once",
          "update_cancels_a_pending_restart", "failed_update_restarts_the_bridge", "second_update_request_is_ignored",
          "quit_during_an_update_just_quits", "signature_accepts_the_pinned_certificate",
          "signature_refuses_another_certificate", "signature_refuses_another_identifier", "signature_needs_a_pinned_key",
          "signature_refuses_unsigned_ad_hoc_and_changed_apps",
          # milestone 8: each Mac updates from its own download
          "release_parse_picks_the_running_arch", "release_parse_needs_its_own_arch",
          "release_parse_still_needs_the_sha256", "asset_name_per_arch", "running_arch_is_one_of_two",
          "saved_update_for_the_other_arch_is_not_restored"]

pytestmark = pytest.mark.skipif(sys.platform != "darwin" or shutil.which("swiftc") is None,
                                reason="needs macOS and swiftc")


@pytest.fixture(scope="module")
def policy_run(tmp_path_factory):
    binary = tmp_path_factory.mktemp("policies") / "policy-tests"
    build = subprocess.run(["swiftc", "-parse-as-library", str(LAUNCHER / "Policies.swift"),
                            str(LAUNCHER / "BridgeProcess.swift"), str(LAUNCHER / "Signature.swift"), str(LAUNCHER / "Download.swift"),
                            str(LAUNCHER / "tests" / "PolicyTests.swift"),
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
    return found, run.returncode


@pytest.fixture(scope="module")
def results(policy_run):
    return policy_run[0]


def test_every_swift_check_is_asserted(policy_run):
    """A check missing from CHECKS runs but is never looked at, so it could never fail the suite.

    Milestone 8 review: five new checks in PolicyTests.swift were invisible this way, and one of them had
    taken over a case that CHECKS did cover.
    """
    found, returncode = policy_run
    missing = [name for name in found if name not in CHECKS]
    assert not missing, f"add these to CHECKS, or they can never fail: {missing}"
    assert returncode == 0, "the Swift test binary itself reported failure"


@pytest.mark.parametrize("name", CHECKS)
def test_policy(results, name):
    assert name in results, f"the Swift check {name} didn't run"
    status, why = results[name]
    assert status == "ok", why
