"""The Windows tray app's rules (windows/launcher/Policies.cs, BuildInfo.cs, ProcessTree.cs, Signature.cs, Download.cs;
milestone 7), checked by building and running windows/launcher/tests/PolicyTests.csproj, as
tests/test_launcher_policies.py does for the Mac's Swift. Windows with the .NET SDK, bash and openssl only."""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from tests.signing_fixtures import CAN_SIGN, make_identity, sign
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
          "orphaned_python_is_ended_after_the_launcher_exits",
          # signatures, releases and installs
          "signature_accepts_the_pinned_certificate", "signature_refuses_another_certificate",
          "signature_refuses_a_changed_byte", "signature_needs_a_pinned_key", "signature_refuses_garbage",
          "release_parse_accepts_a_real_shape", "release_parse_rejects_garbage", "check_schedule",
          "notice_once_per_version", "notice_survives_a_relaunch", "found_update_survives_a_relaunch",
          "install_plan_order", "install_plan_refuses_damaged", "install_plan_refuses_bad_signature",
          "install_plan_refuses_not_a_release", "install_plan_refuses_no_version", "install_plan_refuses_not_newer",
          "install_plan_accepts_valid", "zip_layout_refuses_unsafe_paths", "download_is_capped_and_hashed",
          # swapping a new version in, and going back
          "swap_moves_old_aside_and_copies_new", "swap_replaces_an_older_previous", "swap_failure_puts_the_old_back",
          "go_back_swaps_previous_in", "go_back_needs_a_complete_previous"]

pytestmark = pytest.mark.skipif(not CAN_BUILD or not CAN_SIGN, reason="needs Windows, the .NET SDK, bash and openssl")


@pytest.fixture(scope="module")
def signed(tmp_path_factory):
    """content.bin signed with throwaway identity A (content.bin.p7s) and with B (other.p7s), and A's SHA-256."""
    folder = tmp_path_factory.mktemp("signatures")
    a, b = make_identity(folder / "ids", "A"), make_identity(folder / "ids", "B")
    content = folder / "content.bin"
    content.write_bytes(os.urandom(8192))
    for identity, name in ((b, "other.p7s"), (a, "content.bin.p7s")):
        result = sign(content, identity)
        assert result.returncode == 0, result.stdout + result.stderr
        (folder / "content.bin.p7s").replace(folder / name)
    (folder / "a.sha256").write_text(a.sha256, encoding="utf-8")
    return folder


@pytest.fixture(scope="module")
def results(tmp_path_factory, signed):
    out = tmp_path_factory.mktemp("policies")
    built = build(LAUNCHER / "tests" / "PolicyTests.csproj", out)
    if built.returncode != 0:
        pytest.fail("the C# checks don't build:\n" + built.stdout[-3000:] + built.stderr[-1000:])
    run = subprocess.run([str(out / "PolicyTests.exe"), str(signed)], capture_output=True, text=True, timeout=120)
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


# ---- the real exe's --check-signature (the release workflow's and CI's last check) -------------------------------

@pytest.fixture(scope="module")
def tray_exe(tmp_path_factory, signed):
    out = tmp_path_factory.mktemp("tray")
    built = build(LAUNCHER / "LoupedeckBridge.csproj", out, "-p:Version=0.6.0")
    if built.returncode != 0:
        pytest.fail("LoupedeckBridge.exe doesn't build:\n" + built.stdout[-3000:])
    info = {"runtime": "bundled", "version": "0.6.0", "is_dev": False,
            "signer_sha256": (signed / "a.sha256").read_text(encoding="utf-8")}
    (out / "LoupedeckBridge.json").write_text(json.dumps(info), encoding="utf-8")
    return out / "LoupedeckBridge.exe"


def test_check_signature_accepts_the_pinned_key(tray_exe, signed):
    result = subprocess.run([str(tray_exe), "--check-signature", str(signed / "content.bin")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and result.stdout.startswith("ok:"), result.stdout + result.stderr


def test_check_signature_refuses_another_pin(tray_exe, signed):
    result = subprocess.run([str(tray_exe), "--check-signature", str(signed / "content.bin"), "--pinned", "0" * 64],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 1 and "another key" in result.stdout, result.stdout + result.stderr


def test_check_signature_refuses_a_missing_signature(tray_exe, tmp_path):
    lone = tmp_path / "lone.zip"
    lone.write_bytes(b"x")
    result = subprocess.run([str(tray_exe), "--check-signature", str(lone)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 1 and result.stdout.startswith("refused:"), result.stdout + result.stderr
