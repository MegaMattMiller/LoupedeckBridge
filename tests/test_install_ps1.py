"""tools/install.ps1 (milestone 7): installs or updates LoupedeckBridge on Windows from its GitHub releases, after
checking the download's SHA-256, its signature (the pinned release key), its layout and version. Run here with Windows
PowerShell 5.1 against a fake release served on 127.0.0.1, signed with throwaway identities, with the install folder,
the Start menu and the registry keys in temporary places; a stand-in exe (FakeApp) logs what it's asked to do."""
from __future__ import annotations

import functools
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path

import pytest

from tests.signing_fixtures import CAN_SIGN, make_identity, sign
from tests.windows_build import CAN_BUILD, LAUNCHER, REPO, build

SCRIPT = REPO / "tools" / "install.ps1"
POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(sys.platform != "win32" or POWERSHELL is None or not CAN_BUILD or not CAN_SIGN,
                                reason="needs Windows PowerShell, the .NET SDK, bash and openssl")


@pytest.fixture(scope="module")
def fake_exe(tmp_path_factory):
    out = tmp_path_factory.mktemp("fakeapp")
    built = build(LAUNCHER / "tests" / "FakeApp" / "FakeApp.csproj", out)
    if built.returncode != 0:
        pytest.fail("FakeApp doesn't build:\n" + built.stdout[-3000:])
    return out / "LoupedeckBridge.exe"


@pytest.fixture(scope="module")
def keys(tmp_path_factory):
    folder = tmp_path_factory.mktemp("keys")
    return make_identity(folder, "A"), make_identity(folder, "B")


class Server:
    """Files under root, on http://127.0.0.1:<port>/ (local only), as GitHub's API and downloads would serve them."""

    def __init__(self, root: Path):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
        handler.log_message = lambda *args: None
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Rig:
    def __init__(self, tmp_path: Path, fake_exe: Path, keys):
        self.tmp, self.fake_exe = tmp_path, fake_exe
        self.a, self.b = keys
        self.root = tmp_path / "server"
        (self.root / "api").mkdir(parents=True)
        self.server = Server(self.root)
        self.install = tmp_path / "Programs" / "LoupedeckBridge"
        self.start_menu = tmp_path / "Start Menu"
        self.log = tmp_path / "fake.log"
        self.key = f"HKCU:\\Software\\LoupedeckBridgeTests\\{uuid.uuid4().hex}"
        self.env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}   # 5.1 can't use 7's
        self.env.update({"LB_PINNED_SIGNER_SHA256": self.a.sha256, "LB_RELEASES_API": self.server.url + "/api",
                         "LB_DOWNLOAD_BASE": self.server.url + "/download", "LB_INSTALL_DIR": str(self.install),
                         "LB_START_MENU_DIR": str(self.start_menu), "LB_RUN_KEY": self.key + "\\Run",
                         "LB_UNINSTALL_KEY": self.key + "\\Uninstall\\LoupedeckBridge",
                         "LB_PREFS_KEY": self.key + "\\Prefs", "LB_FAKE_LOG": str(self.log)})

    def release(self, version: str, *, signer=None, extra=(), drop=(), bad_sha=False, info=None, latest=True,
                padding: int = 0) -> Path:
        """A release folder on the server: the zip (LoupedeckBridge\\ with FakeApp, its JSON, install.ps1 and a
        marker), its .sha256 and .p7s."""
        folder = self.root / "download" / f"v{version}"
        folder.mkdir(parents=True)
        name = f"LoupedeckBridge-v{version}-windows-x64.zip"
        zip_path = folder / name
        info = info or {"runtime": "bundled", "version": version, "is_dev": False, "signer_sha256": self.a.sha256}
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            files = {"LoupedeckBridge/LoupedeckBridge.exe": self.fake_exe.read_bytes(),
                     "LoupedeckBridge/LoupedeckBridge.json": json.dumps(info).encode(),
                     "LoupedeckBridge/install.ps1": SCRIPT.read_bytes(),
                     "LoupedeckBridge/app/version.txt": version.encode()}
            if padding:
                files["LoupedeckBridge/app/padding.bin"] = os.urandom(padding)
            for entry, data in files.items():
                if entry not in drop:
                    z.writestr(entry, data)
            for entry, data in extra:
                z.writestr(entry, data)
        digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        if bad_sha:
            digest = "0" * 64
        (folder / f"{name}.sha256").write_text(f"{digest}  {name}\n", encoding="utf-8")
        result = sign(zip_path, signer or self.a)
        assert result.returncode == 0, result.stdout + result.stderr
        if latest:
            (self.root / "api" / "latest").write_text(json.dumps({"tag_name": f"v{version}", "draft": False}),
                                                      encoding="utf-8")
        return zip_path

    def run(self, *args: str, script: Path = SCRIPT, cwd: "Path | None" = None) -> subprocess.CompletedProcess:
        return subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                               str(script), *args], capture_output=True, text=True, env=self.env, timeout=180, cwd=cwd)

    def installed(self) -> "str | None":
        marker = self.install / "app" / "version.txt"
        return marker.read_text(encoding="utf-8") if marker.exists() else None

    def logged(self) -> "list[str]":
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def starts(self, count: int, timeout: float = 15.0) -> "list[str]":
        """The installed app's start lines, once there are `count` of them: install.ps1 starts the app and exits
        without waiting, so its line can come a moment later."""
        exe = str(self.install / "LoupedeckBridge.exe").lower()
        deadline = time.monotonic() + timeout
        while True:
            found = [line for line in self.logged() if line.strip().lower() == exe]
            if len(found) >= count or time.monotonic() > deadline:
                return found
            time.sleep(0.1)

    def registry(self, name: str) -> "str | None":
        result = subprocess.run([POWERSHELL, "-NoProfile", "-Command",
                                 f"(Get-ItemProperty -Path '{self.key}\\Uninstall\\LoupedeckBridge' -ErrorAction "
                                 f"SilentlyContinue).{name}"], capture_output=True, text=True, env=self.env)
        return result.stdout.strip() or None

    def close(self):
        self.server.close()
        subprocess.run([POWERSHELL, "-NoProfile", "-Command", f"Remove-Item -Recurse -Force '{self.key}' -ErrorAction "
                        "SilentlyContinue; Remove-Item -Force 'HKCU:\\Software\\LoupedeckBridgeTests' -ErrorAction "
                        "SilentlyContinue"], capture_output=True, env=self.env)
        subprocess.run([POWERSHELL, "-NoProfile", "-Command",
                        f"Get-Process | Where-Object {{ $_.Path -like '{self.tmp}*' }} | Stop-Process -Force"],
                       capture_output=True, env=self.env)


@pytest.fixture
def rig(tmp_path, fake_exe, keys):
    r = Rig(tmp_path, fake_exe, keys)
    yield r
    r.close()


def output(result) -> str:
    return result.stdout + result.stderr


def test_rig_keeps_every_install_ps1_place_away_from_this_pc(rig):
    # Each place install.ps1 changes (folders, registry keys, GitHub) is a setting the tests point somewhere temporary.
    # One left out reaches this PC's real install: before this test, LB_PREFS_KEY was, and every uninstall test
    # deleted the real tray app's update preferences.
    import re
    settings = set(re.findall(r"Setting '(LB_\w+)'", SCRIPT.read_text(encoding="utf-8")))
    not_places = {"LB_MAX_DOWNLOAD_BYTES"}
    assert settings - not_places - set(rig.env) == set()
    assert all(rig.env[name].startswith(rig.key) for name in settings if name.endswith("_KEY"))


def test_install_into_empty_dir(rig):
    rig.env["LB_FAKE_SLOW_START"] = "1.5"      # install.ps1 starts the app and exits without waiting
    rig.release("0.6.0")
    result = rig.run()
    assert result.returncode == 0, output(result)
    assert rig.installed() == "0.6.0"
    assert rig.starts(1), "the installed app wasn't started"


def test_install_a_named_version(rig):
    rig.release("0.6.0")
    rig.release("0.6.1")
    result = rig.run("-Version", "v0.6.0")
    assert result.returncode == 0, output(result)
    assert rig.installed() == "0.6.0"


def test_install_refuses_wrong_signature(rig):
    # Review Focus 4: a release signed with someone else's key.
    rig.release("0.6.0", signer=rig.b)
    result = rig.run()
    assert result.returncode == 1 and "another key" in output(result), output(result)
    assert rig.installed() is None and not rig.install.exists()


def test_install_refuses_bad_sha256(rig):
    rig.release("0.6.0", bad_sha=True)
    result = rig.run()
    assert result.returncode == 1 and "SHA-256" in output(result), output(result)
    assert rig.installed() is None


def test_install_refuses_a_changed_byte(rig):
    zip_path = rig.release("0.6.0")
    data = bytearray(zip_path.read_bytes())
    data[len(data) // 2] ^= 1
    zip_path.write_bytes(bytes(data))
    digest = hashlib.sha256(bytes(data)).hexdigest()                 # the .sha256 updated too: only the signature catches it
    zip_path.with_name(zip_path.name + ".sha256").write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    result = rig.run()
    assert result.returncode == 1 and "doesn't match" in output(result), output(result)
    assert rig.installed() is None


def test_install_refuses_unsafe_zip_paths(rig):
    # Review Focus 4: an entry that would land outside the install folder.
    rig.release("0.6.0", extra=[("LoupedeckBridge/../evil.txt", b"x")])
    result = rig.run()
    assert result.returncode == 1 and "unsafe path" in output(result), output(result)
    assert not list(rig.tmp.rglob("evil.txt")) and rig.installed() is None


def test_install_refuses_a_release_without_its_exe(rig):
    rig.release("0.6.0", drop=("LoupedeckBridge/LoupedeckBridge.exe",))
    result = rig.run()
    assert result.returncode == 1 and "LoupedeckBridge.exe" in output(result), output(result)


def test_install_refuses_a_dev_build(rig):
    rig.release("0.6.0", info={"runtime": "repo", "repo": "C:\\x", "version": "0.6.0", "is_dev": True})
    result = rig.run()
    assert result.returncode == 1 and "isn't a LoupedeckBridge release" in output(result), output(result)


def test_install_failure_leaves_app_in_place(rig):
    # Review Focus 5: a failed download or a corrupt zip leaves the installed app alone.
    rig.release("0.6.0")
    assert rig.run().returncode == 0
    (rig.root / "api" / "latest").write_text(json.dumps({"tag_name": "v0.6.1"}), encoding="utf-8")   # no files: 404
    result = rig.run()
    assert result.returncode == 1 and "couldn't download" in output(result), output(result)
    assert rig.installed() == "0.6.0"
    folder = rig.root / "download" / "v0.6.2"
    folder.mkdir(parents=True)
    name = "LoupedeckBridge-v0.6.2-windows-x64.zip"
    (folder / name).write_bytes(b"not a zip")
    (folder / f"{name}.sha256").write_text(hashlib.sha256(b"not a zip").hexdigest() + f"  {name}\n", encoding="utf-8")
    assert sign(folder / name, rig.a).returncode == 0
    result = rig.run("-Version", "0.6.2")
    assert result.returncode == 1 and rig.installed() == "0.6.0", output(result)


def test_older_needs_flag(rig):
    rig.release("0.6.1")
    assert rig.run().returncode == 0
    rig.release("0.6.0", latest=False)
    result = rig.run("-Version", "0.6.0")
    assert result.returncode == 1 and "isn't newer" in output(result), output(result)
    assert rig.installed() == "0.6.1"
    result = rig.run("-Version", "0.6.0", "-AllowOlder")
    assert result.returncode == 0 and rig.installed() == "0.6.0", output(result)


def test_old_app_kept_as_previous(rig):
    rig.release("0.6.0")
    assert rig.run().returncode == 0
    rig.release("0.6.1")
    assert rig.run().returncode == 0
    assert rig.installed() == "0.6.1"
    assert (rig.install.parent / "LoupedeckBridge.previous" / "app" / "version.txt").read_text(encoding="utf-8") == "0.6.0"


def test_no_pinned_key_refuses(rig):
    rig.release("0.6.0")
    rig.env["LB_PINNED_SIGNER_SHA256"] = "none"      # (Windows reads an empty variable as unset)
    result = rig.run()
    assert result.returncode == 1 and "no release key" in output(result), output(result)
    assert rig.installed() is None


def test_install_prints_the_release_key(rig):
    rig.release("0.6.0")
    rig.env.pop("LB_PINNED_SIGNER_SHA256")
    result = rig.run()           # the real key: this throwaway release is refused, after the fingerprint is shown
    assert "4927ccbb8cc8c7e3c32afa79d58f11f2129b84b3c7638cb530cb2ced0faa2cf4" in output(result)
    assert result.returncode == 1 and rig.installed() is None


def test_install_says_when_the_key_is_overridden(rig):
    rig.release("0.6.0")
    result = rig.run()
    assert rig.a.sha256 in output(result) and "LB_PINNED_SIGNER_SHA256" in output(result)


def test_running_app_is_stopped_before_the_swap(rig):
    rig.release("0.6.0")
    assert rig.run().returncode == 0
    rig.release("0.6.1")
    assert rig.run().returncode == 0
    lines = rig.logged()
    old_exe = str(rig.install / "LoupedeckBridge.exe").lower()
    assert any(line.lower().startswith(old_exe) and line.endswith("--quit") for line in lines), lines


def test_app_that_wont_quit_is_left_alone(rig):
    rig.release("0.6.0")
    assert rig.run().returncode == 0
    rig.release("0.6.1")
    rig.env["LB_FAKE_WONT_QUIT"] = "1"
    result = rig.run()
    assert result.returncode == 1 and "won't quit" in output(result), output(result)
    assert rig.installed() == "0.6.0"


def test_failed_copy_puts_back_and_restarts_the_old_app(rig):
    # Review Focus 5: the swap fails after the old version was moved aside (here: the new folder can't be renamed into
    # place, because a file in it is held open), so the old one is put back and started again.
    rig.env["LB_FAKE_SLOW_START"] = "1.5"      # install.ps1 starts the app and exits without waiting
    rig.release("0.6.0")
    assert rig.run().returncode == 0
    assert rig.starts(1), rig.logged()
    rig.release("0.6.1")
    rig.env["LB_INSTALL_HOLD_FILE"] = "app/version.txt"         # see install.ps1: a file in .new held open, for tests
    result = rig.run()
    assert result.returncode == 1 and "put back" in output(result), output(result)
    assert rig.installed() == "0.6.0"
    assert not (rig.install.parent / "LoupedeckBridge.previous").exists()
    assert len(rig.starts(2)) == 2, rig.logged()           # started after the first install, and again after the put-back


def test_downloads_are_size_capped(rig):
    rig.release("0.6.0", padding=300_000)
    rig.env["LB_MAX_DOWNLOAD_BYTES"] = "100000"
    result = rig.run()
    assert result.returncode == 1 and "bigger than" in output(result), output(result)
    assert rig.installed() is None


def test_start_menu_and_apps_entry(rig):
    rig.release("0.6.0")
    assert rig.run().returncode == 0
    assert (rig.start_menu / "LoupedeckBridge.lnk").exists()
    assert rig.registry("DisplayName") == "LoupedeckBridge"
    assert rig.registry("DisplayVersion") == "0.6.0"
    uninstall = rig.registry("UninstallString")
    assert uninstall and str(rig.install / "install.ps1") in uninstall and "-Uninstall" in uninstall


def test_uninstall_keeps_user_settings(rig, tmp_path):
    rig.release("0.6.0")
    assert rig.run().returncode == 0
    settings = tmp_path / "Roaming" / "loupedeck-lr-bridge" / "mapping.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}", encoding="utf-8")
    rig.env["APPDATA"] = str(tmp_path / "Roaming")
    result = rig.run("-Uninstall")
    assert result.returncode == 0, output(result)
    assert not rig.install.exists() and not (rig.start_menu / "LoupedeckBridge.lnk").exists()
    assert rig.registry("DisplayName") is None
    assert settings.exists() and "loupedeck-lr-bridge" in output(result)
    assert any(line.endswith("--quit") for line in rig.logged())


# ---- final review: the swap waits for a folder held a moment longer, and keeps the older .previous until it works ----

HOLDER = """import pathlib, sys, time
log, then = pathlib.Path(sys.argv[1]), float(sys.argv[2])
deadline = time.time() + 170
while time.time() < deadline and not (log.exists() and "--quit" in log.read_text(encoding="utf-8", errors="replace")):
    time.sleep(0.05)
time.sleep(then)
"""


def hold(rig, then: float) -> subprocess.Popen:
    """A process standing in <install>\\app until `then` seconds after install.ps1 asks the app to quit: as the old
    app does for a moment after its `--quit` returns, or a browser it opened would."""
    return subprocess.Popen([sys.executable, "-c", HOLDER, str(rig.log), str(then)], cwd=rig.install / "app")


def previous(rig) -> "str | None":
    marker = rig.install.parent / "LoupedeckBridge.previous" / "app" / "version.txt"
    return marker.read_text(encoding="utf-8") if marker.exists() else None


def test_install_waits_for_a_folder_held_a_moment_longer(rig):
    rig.release("0.6.0")
    assert rig.run().returncode == 0
    rig.release("0.6.1")
    holder = hold(rig, then=1.0)
    try:
        result = rig.run()
    finally:
        holder.kill()
        holder.wait(timeout=10)
    assert result.returncode == 0 and rig.installed() == "0.6.1", output(result)
    assert previous(rig) == "0.6.0"


def test_failed_move_keeps_the_older_previous(rig):
    rig.release("0.6.0")
    assert rig.run().returncode == 0
    rig.release("0.6.1")
    assert rig.run().returncode == 0
    rig.release("0.6.2")
    holder = hold(rig, then=170)                          # for the whole run
    try:
        result = rig.run()
    finally:
        holder.kill()
        holder.wait(timeout=10)
    assert result.returncode == 1 and "couldn't move the old version aside" in output(result), output(result)
    assert rig.installed() == "0.6.1" and previous(rig) == "0.6.0"


def test_failed_copy_keeps_the_older_previous(rig):
    rig.release("0.6.0")
    assert rig.run().returncode == 0
    rig.release("0.6.1")
    assert rig.run().returncode == 0
    rig.release("0.6.2")
    rig.env["LB_INSTALL_HOLD_FILE"] = "app/version.txt"
    result = rig.run()
    assert result.returncode == 1 and "put back" in output(result), output(result)
    assert rig.installed() == "0.6.1" and previous(rig) == "0.6.0"


def test_uninstall_removes_a_leftover_older_copy(rig):
    rig.release("0.6.0")
    assert rig.run().returncode == 0
    leftover = rig.install.parent / "LoupedeckBridge.older"            # an install cut short mid-swap
    (leftover / "app").mkdir(parents=True)
    result = rig.run("-Uninstall")
    assert result.returncode == 0 and not leftover.exists(), output(result)


# ---- final review, minors 7 and 8 -------------------------------------------------------------------------------

@pytest.fixture
def other_drive(tmp_path):
    """A folder on another drive: on GitHub's runner, its second disk (RUNNER_TEMP is on D:); elsewhere a drive letter
    for a folder of this test's own (subst, for this login session only, removed afterwards; the same disk underneath),
    so no real drive of the user's is written to."""
    runner = os.environ.get("RUNNER_TEMP")
    if runner and Path(runner).drive.upper() != tmp_path.drive.upper():
        folder = Path(runner) / f"lb-other-drive-{uuid.uuid4().hex}"
        folder.mkdir()
        try:
            yield folder
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        return
    folder = tmp_path / "other-drive"
    folder.mkdir()
    taken = {d[0] for d in os.listdrives()} if hasattr(os, "listdrives") else set()
    for letter in "QRSTUVWXYZ":
        if letter in taken or os.path.exists(f"{letter}:\\"):
            continue
        if subprocess.run(["subst", f"{letter}:", str(folder)], capture_output=True).returncode == 0:
            try:
                yield Path(f"{letter}:\\")
            finally:
                subprocess.run(["subst", f"{letter}:", "/D"], capture_output=True)
            return
    pytest.skip("no free drive letter for subst")


def test_install_with_temp_on_another_drive(rig, other_drive):
    # Minor 7: a folder can't be moved to another drive, so the download is unpacked next to the install folder, not
    # in %TEMP% (which some people move to another drive).
    temp = other_drive / "temp"
    temp.mkdir()
    rig.env["TEMP"] = rig.env["TMP"] = str(temp)
    rig.release("0.6.0")
    result = rig.run()
    assert result.returncode == 0 and rig.installed() == "0.6.0", output(result)


def test_uninstall_keeps_its_apps_entry_until_the_app_is_gone(rig):
    # Minor 8: a folder that can't be removed (a program stands in it) keeps the Settings > Apps entry, so uninstalling
    # can be tried again from there.
    rig.release("0.6.0")
    assert rig.run().returncode == 0
    holder = hold(rig, then=170)
    try:
        result = rig.run("-Uninstall")
    finally:
        holder.kill()
        holder.wait(timeout=10)
    assert result.returncode == 1 and "try again" in output(result), output(result)
    assert rig.registry("DisplayName") == "LoupedeckBridge"
    result = rig.run("-Uninstall")
    assert result.returncode == 0 and rig.registry("DisplayName") is None, output(result)


def test_uninstall_removes_the_update_preferences(rig):
    # Minor 8: the tray app's update preferences (HKCU\Software\LoupedeckBridge) go too; the layout and presets stay.
    prefs = rig.env["LB_PREFS_KEY"]
    rig.release("0.6.0")
    assert rig.run().returncode == 0
    subprocess.run([POWERSHELL, "-NoProfile", "-Command", f"New-Item -Force -Path '{prefs}' | Out-Null; "
                    f"New-ItemProperty -Force -Path '{prefs}' -Name AutoUpdateCheck -Value 0 -PropertyType DWord | Out-Null"],
                   env=rig.env, check=True, capture_output=True)
    assert rig.run("-Uninstall").returncode == 0
    left = subprocess.run([POWERSHELL, "-NoProfile", "-Command", f"Test-Path '{prefs}'"], env=rig.env,
                          capture_output=True, text=True)
    assert left.stdout.strip() == "False"


def test_uninstall_started_inside_the_install_folder(rig):
    # Minor 8: Settings > Apps runs the installed copy of install.ps1; started with the install folder as its current
    # folder, its process must step out before removing it (Set-Location alone moves only PowerShell's own location).
    rig.release("0.6.0")
    assert rig.run().returncode == 0
    result = rig.run("-Uninstall", script=rig.install / "install.ps1", cwd=rig.install)
    assert result.returncode == 0 and not rig.install.exists(), output(result)
