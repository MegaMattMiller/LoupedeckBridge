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
                         "LB_UNINSTALL_KEY": self.key + "\\Uninstall\\LoupedeckBridge", "LB_FAKE_LOG": str(self.log)})

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

    def run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                               str(SCRIPT), *args], capture_output=True, text=True, env=self.env, timeout=180)

    def installed(self) -> "str | None":
        marker = self.install / "app" / "version.txt"
        return marker.read_text(encoding="utf-8") if marker.exists() else None

    def logged(self) -> "list[str]":
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

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


def test_install_into_empty_dir(rig):
    rig.release("0.6.0")
    result = rig.run()
    assert result.returncode == 0, output(result)
    assert rig.installed() == "0.6.0"
    assert any(line.strip().lower() == str(rig.install / "LoupedeckBridge.exe").lower() for line in rig.logged()), \
        "the installed app wasn't started"


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
    rig.release("0.6.0")
    assert rig.run().returncode == 0
    rig.release("0.6.1")
    rig.env["LB_INSTALL_HOLD_FILE"] = "app/version.txt"         # see install.ps1: a file in .new held open, for tests
    result = rig.run()
    assert result.returncode == 1 and "put back" in output(result), output(result)
    assert rig.installed() == "0.6.0"
    assert not (rig.install.parent / "LoupedeckBridge.previous").exists()
    starts = [line for line in rig.logged() if line.strip().lower() == str(rig.install / "LoupedeckBridge.exe").lower()]
    assert len(starts) == 2, rig.logged()           # started after the first install, and again after the put-back


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
