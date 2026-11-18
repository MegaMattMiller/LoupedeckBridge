"""tools/bridgectl acts on the installed release, or with --dev on the dev build (milestone 6).
Runs the real script with stand-in pgrep/pkill/open/sleep that record what they're asked to do."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAKES = {
    # "running" holds the executable paths of apps the fake `open` started.
    "open": '#!/bin/bash\necho "open $*" >> "$FAKE_LOG"\n'
            'for a in "$@"; do case "$a" in *.app) echo "$a/Contents/MacOS/LoupedeckBridge" >> "$FAKE_RUNNING";; esac; done\n',
    "pgrep": '#!/bin/bash\necho "pgrep $*" >> "$FAKE_LOG"\npat="${@: -1}"\n'
             'grep -qF -- "$pat" "$FAKE_RUNNING" 2>/dev/null\n',
    "pkill": '#!/bin/bash\necho "pkill $*" >> "$FAKE_LOG"\npat="${@: -1}"\n'
             'grep -vF -- "$pat" "$FAKE_RUNNING" > "$FAKE_RUNNING.new" 2>/dev/null; mv "$FAKE_RUNNING.new" "$FAKE_RUNNING"\n',
    "sleep": "#!/bin/bash\nexit 0\n",
}


def rig(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in FAKES.items():
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    release = tmp_path / "Applications" / "LoupedeckBridge.app"
    dev = tmp_path / "build" / "LoupedeckBridge Dev.app"
    for app in (release, dev):
        (app / "Contents" / "MacOS").mkdir(parents=True)
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path / "home"),
           "LB_BRIDGECTL_RELEASE_APP": str(release), "LB_BRIDGECTL_DEV_APP": str(dev),
           "FAKE_LOG": str(tmp_path / "log"), "FAKE_RUNNING": str(tmp_path / "running")}
    (tmp_path / "running").write_text("")
    return env, release, dev


def run(env, *args):
    return subprocess.run([str(REPO / "tools" / "bridgectl"), *args], env=env, capture_output=True, text=True,
                          timeout=30)


def test_bridgectl_targets(tmp_path):
    # Review Focus 3: the release is the default, --dev the dev build; never two bridges.
    env, release, dev = rig(tmp_path)
    log, running = Path(env["FAKE_LOG"]), Path(env["FAKE_RUNNING"])
    marker = Path(env["HOME"]) / "Library/Application Support/loupedeck-lr-bridge/release-paused"

    run(env, "status")
    assert f"{release}/Contents/MacOS/LoupedeckBridge" in log.read_text()
    log.write_text("")
    run(env, "status", "--dev")
    assert f"{dev}/Contents/MacOS/LoupedeckBridge" in log.read_text()

    # the release is running; starting the dev build pauses it
    running.write_text(f"{release}/Contents/MacOS/LoupedeckBridge\n")
    log.write_text("")
    result = run(env, "start", "--dev")
    assert result.returncode == 0, result.stderr
    calls = log.read_text()
    assert f"pkill -TERM -f {release}/Contents/MacOS/LoupedeckBridge" in calls
    assert f"open -g {dev}" in calls and marker.exists()
    assert f"{release}/" not in running.read_text()

    # stopping the dev build brings the release back
    log.write_text("")
    result = run(env, "stop", "--dev")
    assert result.returncode == 0, result.stderr
    calls = log.read_text()
    assert f"pkill -TERM -f {dev}/Contents/MacOS/LoupedeckBridge" in calls
    assert f"open -g {release}" in calls and not marker.exists()


def test_stop_dev_without_marker_leaves_release_alone(tmp_path):
    env, release, dev = rig(tmp_path)
    Path(env["FAKE_RUNNING"]).write_text(f"{dev}/Contents/MacOS/LoupedeckBridge\n")
    run(env, "stop", "--dev")
    assert f"open -g {release}" not in Path(env["FAKE_LOG"]).read_text()
