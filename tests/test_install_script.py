"""tools/install.sh, the standalone installer (milestone 6). Runs the real script with stand-in curl, codesign,
open, pgrep, pkill, sleep, uname and sysctl; ditto, plutil and shasum are the real system tools.
Milestone 8: uname and sysctl are faked so the arch tests run the same on either Mac, and default to an Apple
Silicon Mac so the milestone 6 and 7 cases keep testing exactly what they did."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS tools: bash, ditto, codesign, open")

REPO = Path(__file__).resolve().parent.parent
BUNDLE_ID = "io.github.megamattmiller.loupedeckbridge"
CERT = b"fake DER certificate"
PINNED = hashlib.sha256(CERT).hexdigest()

FAKES = {
    # curl -fL -o OUT URL (or -fsSL URL for the API): serves files from $FAKE_SERVER by URL basename.
    "curl": r'''#!/bin/bash
echo "curl $*" >> "$FAKE_LOG"
[ -n "${FAKE_CURL_FAIL:-}" ] && exit 22
out=""; url=""
while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift 2;; -*) shift;; *) url="$1"; shift;; esac; done
name="${url##*/}"
[ -f "$FAKE_SERVER/$name" ] || exit 22
if [ -n "$out" ]; then cp "$FAKE_SERVER/$name" "$out"; else cat "$FAKE_SERVER/$name"; fi
''',
    # codesign --verify … APP: exit $FAKE_VERIFY; codesign -d --extract-certificates=PREFIX APP: writes PREFIX0
    # (nothing with FAKE_NO_CERT: an ad hoc signature has no certificate)
    "codesign": r'''#!/bin/bash
echo "codesign $*" >> "$FAKE_LOG"
for a in "$@"; do case "$a" in
  --verify) exit "${FAKE_VERIFY:-0}";;
  --extract-certificates=*) [ -n "${FAKE_NO_CERT:-}" ] || printf '%s' "$FAKE_CERT" > "${a#--extract-certificates=}0";;
esac; done
exit 0
''',
    "open": '#!/bin/bash\necho "open $*" >> "$FAKE_LOG"\n',
    # a running app is the file $FAKE_RUNNING; pkill makes it quit, unless FAKE_STUCK
    "pgrep": '#!/bin/bash\n[ -f "${FAKE_RUNNING:-/nonexistent}" ]\n',
    "pkill": '#!/bin/bash\necho "pkill $*" >> "$FAKE_LOG"\n[ -n "${FAKE_STUCK:-}" ] || rm -f "${FAKE_RUNNING:-/nonexistent}"\n',
    # the real ditto, except: FAKE_DITTO_FULL fails unzipping, FAKE_DITTO_COPY_FAIL fails the copy into place
    "ditto": r'''#!/bin/bash
if [ "$1" = "-x" ]; then
  [ -n "${FAKE_DITTO_FULL:-}" ] && { echo "ditto: Couldn't write: No space left on device" >&2; exit 1; }
else
  [ -n "${FAKE_DITTO_COPY_FAIL:-}" ] && { echo "ditto: Couldn't copy: No space left on device" >&2; exit 1; }
fi
exec /usr/bin/ditto "$@"
''',
    "sleep": "#!/bin/bash\nexit 0\n",
    # which Mac this is: FAKE_UNAME_M (default arm64), and FAKE_TRANSLATED=1 for a Rosetta shell
    "uname": '#!/bin/bash\n[ "$1" = -m ] && { echo "${FAKE_UNAME_M:-arm64}"; exit 0; }\nexec /usr/bin/uname "$@"\n',
    "sysctl": r"""#!/bin/bash
for a in "$@"; do [ "$a" = sysctl.proc_translated ] && { echo "${FAKE_TRANSLATED:-0}"; exit 0; }; done
exec /usr/sbin/sysctl "$@"
""",
}


def make_app(parent: Path, version: str, bundle_id: str = BUNDLE_ID, arch: "str | None" = "arm64") -> Path:
    """arch=None leaves LBArch out, as every release before v0.7.0 does."""
    app = parent / "LoupedeckBridge.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
        f"<key>CFBundleIdentifier</key><string>{bundle_id}</string>"
        f"<key>LBVersion</key><string>{version}</string>"
        + (f"<key>LBArch</key><string>{arch}</string>" if arch is not None else "")
        + "</dict></plist>")
    return app


OMIT = "omit"          # publish(says_arch=OMIT): a pre-v0.7.0 bundle, with no LBArch


def publish(server: Path, tmp: Path, version: str, bundle_id: str = BUNDLE_ID, arch: str = "arm64",
            says_arch: "str | None" = None) -> None:
    """A fake GitHub release: the zip, its .sha256, and the 'latest' API answer.

    `arch` names the download; `says_arch` is what the app inside claims (default: the same), so a release
    serving one Mac's app under the other's name can be tested.
    """
    src = tmp / f"src-{version}-{arch}"
    app = make_app(src, version, bundle_id, arch=None if says_arch == OMIT else (says_arch or arch))
    name = f"LoupedeckBridge-v{version}-macos-{arch}.zip"
    subprocess.run(["ditto", "-c", "-k", "--keepParent", str(app), str(server / name)], check=True)
    digest = hashlib.sha256((server / name).read_bytes()).hexdigest()
    (server / f"{name}.sha256").write_text(f"{digest}  {name}\n")
    (server / "latest").write_text(f'{{"tag_name": "v{version}", "draft": false, "prerelease": false}}')


def rig(tmp_path):
    bin_dir, server, home, apps = (tmp_path / d for d in ("bin", "server", "home", "Applications"))
    for d in (bin_dir, server, home / ".Trash", apps):
        d.mkdir(parents=True)
    for name, body in FAKES.items():
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/sbin", "HOME": str(home),
           "LB_INSTALL_DIR": str(apps), "LB_PINNED_SIGNER_SHA256": PINNED, "FAKE_CERT": CERT.decode(),
           "FAKE_SERVER": str(server), "FAKE_LOG": str(tmp_path / "log")}
    return env, server, apps, home


def install(env, *args):
    return subprocess.run([str(REPO / "tools" / "install.sh"), *args], env=env, capture_output=True, text=True,
                          timeout=60)


def installed_version(apps: Path) -> str:
    return subprocess.run(["plutil", "-extract", "LBVersion", "raw", str(apps / "LoupedeckBridge.app/Contents/Info.plist")],
                          capture_output=True, text=True).stdout.strip()


def test_install_into_empty_dir(tmp_path):
    env, server, apps, _ = rig(tmp_path)
    publish(server, tmp_path, "0.5.0")
    result = install(env)
    assert result.returncode == 0, result.stderr
    assert installed_version(apps) == "0.5.0"
    assert f"open {apps}/LoupedeckBridge.app" in Path(env["FAKE_LOG"]).read_text()


def test_install_a_named_version(tmp_path):
    env, server, apps, _ = rig(tmp_path)
    publish(server, tmp_path, "0.5.0")
    (server / "latest").unlink()                       # a named version needs no API call
    assert install(env, "v0.5.0").returncode == 0 and installed_version(apps) == "0.5.0"


def test_install_refuses_wrong_signature(tmp_path):
    # Review Focus 1: not signed with the release key → nothing replaced.
    env, server, apps, home = rig(tmp_path)
    make_app(apps, "0.4.0")
    publish(server, tmp_path, "0.5.0")
    for bad in ({"FAKE_VERIFY": "1"}, {"FAKE_CERT": "someone else's certificate"}):
        result = install({**env, **bad})
        assert result.returncode == 1, (bad, result.stdout, result.stderr)
        assert installed_version(apps) == "0.4.0" and not list((home / ".Trash").iterdir())


def test_install_refuses_ad_hoc_signature_and_says_why(tmp_path):
    # Live check, 2026-11-17: an ad hoc build (valid signature, no certificate) was refused, but silently.
    env, server, apps, home = rig(tmp_path)
    make_app(apps, "0.4.0")
    publish(server, tmp_path, "0.5.0")
    result = install({**env, "FAKE_NO_CERT": "1"})
    assert result.returncode == 1 and "release key" in result.stderr, result.stderr
    assert installed_version(apps) == "0.4.0" and not list((home / ".Trash").iterdir())


def test_install_refuses_bad_sha256(tmp_path):
    env, server, apps, home = rig(tmp_path)
    make_app(apps, "0.4.0")
    publish(server, tmp_path, "0.5.0")
    sha = server / "LoupedeckBridge-v0.5.0-macos-arm64.zip.sha256"
    sha.write_text("0" * 64 + "  LoupedeckBridge-v0.5.0-macos-arm64.zip\n")
    assert install(env).returncode == 1 and installed_version(apps) == "0.4.0"


def test_install_refuses_other_apps(tmp_path):
    env, server, apps, _ = rig(tmp_path)
    publish(server, tmp_path, "0.5.0", bundle_id=BUNDLE_ID + ".dev")
    assert install(env).returncode == 1 and not (apps / "LoupedeckBridge.app").exists()


def test_install_failure_leaves_app_in_place(tmp_path):
    # Review Focus 2: a failed download or a corrupt zip leaves the installed app alone.
    env, server, apps, home = rig(tmp_path)
    make_app(apps, "0.4.0")
    publish(server, tmp_path, "0.5.0")
    assert install({**env, "FAKE_CURL_FAIL": "1"}).returncode == 1
    zip_path = server / "LoupedeckBridge-v0.5.0-macos-arm64.zip"
    zip_path.write_bytes(b"not a zip")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (server / f"{zip_path.name}.sha256").write_text(f"{digest}  {zip_path.name}\n")
    assert install(env).returncode == 1
    assert installed_version(apps) == "0.4.0" and not list((home / ".Trash").iterdir())


def test_older_needs_flag(tmp_path):
    env, server, apps, _ = rig(tmp_path)
    make_app(apps, "0.6.0")
    publish(server, tmp_path, "0.5.0")
    assert install(env).returncode == 1 and installed_version(apps) == "0.6.0"
    assert install(env, "--allow-older").returncode == 0 and installed_version(apps) == "0.5.0"


def test_old_app_goes_to_trash(tmp_path):
    env, server, apps, home = rig(tmp_path)
    make_app(apps, "0.4.0")
    publish(server, tmp_path, "0.5.0")
    assert install(env).returncode == 0 and installed_version(apps) == "0.5.0"
    trashed = list((home / ".Trash").iterdir())
    assert len(trashed) == 1 and trashed[0].name.endswith(".app") and "0.4.0" in trashed[0].name


def test_no_pinned_key_refuses(tmp_path):
    env, server, apps, _ = rig(tmp_path)
    publish(server, tmp_path, "0.5.0")
    result = install({**env, "LB_PINNED_SIGNER_SHA256": ""})
    assert result.returncode == 1 and "pinned" in (result.stdout + result.stderr)


def test_usage(tmp_path):
    env, *_ = rig(tmp_path)
    assert install(env, "--nope").returncode == 2


def test_release_key_is_pinned():
    # The release certificate's SHA-256 (made by tools/make_signing_identity.sh, 2026-11-17). Every release app
    # copies it into its Info.plist at build time, so clearing or changing it strands installed apps.
    text = (REPO / "tools" / "install.sh").read_text()
    assert 'PINNED_SIGNER_SHA256_DEFAULT="4927ccbb8cc8c7e3c32afa79d58f11f2129b84b3c7638cb530cb2ced0faa2cf4"' in text


REAL_KEY = "4927ccbb8cc8c7e3c32afa79d58f11f2129b84b3c7638cb530cb2ced0faa2cf4"


def test_install_prints_the_release_key(tmp_path):
    # So a first install on a new Mac can be checked against a fingerprint noted elsewhere (milestone 6 review).
    env, server, apps, _ = rig(tmp_path)
    publish(server, tmp_path, "0.5.0")
    result = install({**env, "LB_PINNED_SIGNER_SHA256": REAL_KEY, "FAKE_CERT": "x"})   # refused: wrong certificate
    assert result.returncode == 1
    assert f"release key (certificate SHA-256): {REAL_KEY}" in result.stdout
    assert "LB_PINNED_SIGNER_SHA256" not in result.stdout                               # the built-in key


def test_install_says_when_the_key_is_overridden(tmp_path):
    env, server, apps, _ = rig(tmp_path)                    # the rig pins a test key through the environment
    publish(server, tmp_path, "0.5.0")
    result = install(env)
    assert result.returncode == 0 and PINNED in result.stdout
    assert "not the built-in key (LB_PINNED_SIGNER_SHA256)" in result.stdout


# ---- v0.5.1: the review's deferred installer fixes -------------------------------------------------------

def test_install_checks_the_signing_identifier(tmp_path):
    env, server, apps, _ = rig(tmp_path)
    publish(server, tmp_path, "0.5.0")
    assert install(env).returncode == 0
    log = Path(env["FAKE_LOG"]).read_text()
    assert 'codesign --verify --strict -R=identifier "io.github.megamattmiller.loupedeckbridge"' in log, log


def test_unzip_failure_says_why(tmp_path):
    # A full disk was reported as "it isn't a valid zip".
    env, server, apps, _ = rig(tmp_path)
    make_app(apps, "0.4.0")
    publish(server, tmp_path, "0.5.0")
    result = install({**env, "FAKE_DITTO_FULL": "1"})
    assert result.returncode == 1 and "No space left on device" in result.stderr, result.stderr
    assert installed_version(apps) == "0.4.0"


def test_running_app_is_stopped_before_the_swap(tmp_path):
    env, server, apps, _ = rig(tmp_path)
    make_app(apps, "0.4.0")
    publish(server, tmp_path, "0.5.0")
    running = tmp_path / "running"
    running.touch()
    assert install({**env, "FAKE_RUNNING": str(running)}).returncode == 0
    assert not running.exists() and installed_version(apps) == "0.5.0"


def test_app_that_wont_quit_is_left_alone(tmp_path):
    # It carried on, and its `open` then just brought the old (trashed) copy to the front.
    env, server, apps, home = rig(tmp_path)
    make_app(apps, "0.4.0")
    publish(server, tmp_path, "0.5.0")
    running = tmp_path / "running"
    running.touch()
    result = install({**env, "FAKE_RUNNING": str(running), "FAKE_STUCK": "1"})
    assert result.returncode == 1 and "still running" in result.stderr, result.stderr
    assert installed_version(apps) == "0.4.0" and not list((home / ".Trash").iterdir())


def test_failed_copy_puts_back_and_restarts_the_old_app(tmp_path):
    env, server, apps, home = rig(tmp_path)
    make_app(apps, "0.4.0")
    publish(server, tmp_path, "0.5.0")
    running = tmp_path / "running"
    running.touch()
    result = install({**env, "FAKE_RUNNING": str(running), "FAKE_DITTO_COPY_FAIL": "1"})
    assert result.returncode == 1 and "No space left on device" in result.stderr, result.stderr
    assert installed_version(apps) == "0.4.0" and not list((home / ".Trash").iterdir())
    assert f"open {apps}/LoupedeckBridge.app" in Path(env["FAKE_LOG"]).read_text(), "the old app wasn't restarted"


def test_downloads_are_size_capped(tmp_path):
    env, server, apps, _ = rig(tmp_path)
    publish(server, tmp_path, "0.5.0")
    assert install(env).returncode == 0
    zip_fetch = [l for l in Path(env["FAKE_LOG"]).read_text().splitlines()
                 if l.startswith("curl") and l.endswith("macos-arm64.zip")]
    assert zip_fetch and "--max-filesize" in zip_fetch[0], zip_fetch


# ---- milestone 8: which Mac's download ---------------------------------------------------------------------

@pytest.mark.parametrize("arch", ["arm64", "x86_64"])
def test_installs_the_arch_it_is_running_on(tmp_path, arch):
    env, server, apps, _ = rig(tmp_path)
    publish(server, tmp_path, "0.7.0", arch=arch)
    result = install({**env, "FAKE_UNAME_M": arch})
    assert result.returncode == 0, result.stderr
    assert installed_version(apps) == "0.7.0"
    assert f"macos-{arch}.zip" in Path(env["FAKE_LOG"]).read_text()


def test_refuses_a_bundle_built_for_the_other_arch(tmp_path):
    # The download is named for this Mac but holds the other Mac's app: nothing is replaced.
    env, server, apps, home = rig(tmp_path)
    make_app(apps, "0.6.2", arch="x86_64")
    publish(server, tmp_path, "0.7.0", arch="x86_64", says_arch="arm64")
    result = install({**env, "FAKE_UNAME_M": "x86_64"})
    assert result.returncode == 1, result.stdout
    assert "arm64" in result.stderr and "x86_64" in result.stderr, result.stderr
    assert installed_version(apps) == "0.6.2" and not list((home / ".Trash").iterdir())


def test_rosetta_gets_the_apple_silicon_build(tmp_path):
    # uname -m says x86_64 in a translated shell on an Apple Silicon Mac; that Mac wants the arm64 build.
    env, server, apps, _ = rig(tmp_path)
    publish(server, tmp_path, "0.7.0", arch="arm64")
    result = install({**env, "FAKE_UNAME_M": "x86_64", "FAKE_TRANSLATED": "1"})
    assert result.returncode == 0, result.stderr
    assert installed_version(apps) == "0.7.0"
    assert "macos-arm64.zip" in Path(env["FAKE_LOG"]).read_text()


def test_lb_arch_overrides_detection(tmp_path):
    env, server, apps, _ = rig(tmp_path)
    publish(server, tmp_path, "0.7.0", arch="arm64")
    result = install({**env, "FAKE_UNAME_M": "x86_64", "LB_ARCH": "arm64"})
    assert result.returncode == 0, result.stderr
    assert installed_version(apps) == "0.7.0"


def test_unknown_arch_is_refused(tmp_path):
    env, server, apps, _ = rig(tmp_path)
    publish(server, tmp_path, "0.7.0")
    result = install({**env, "LB_ARCH": "ppc64"})
    assert result.returncode == 1, result.stdout
    assert "ppc64" in result.stderr, result.stderr
    assert not (apps / "LoupedeckBridge.app").exists()
    log = Path(env["FAKE_LOG"])
    # refused before any download: the fakes never ran, so there may be no log at all
    assert "curl" not in (log.read_text() if log.exists() else "")


def test_installs_a_release_from_before_LBArch(tmp_path):
    # Every release before v0.7.0 is Apple Silicon and has no LBArch. README documents `install.sh v0.5.0`,
    # and --allow-older going back, so those must stay installable.
    env, server, apps, _ = rig(tmp_path)
    publish(server, tmp_path, "0.6.2", arch="arm64", says_arch=OMIT)
    result = install({**env, "FAKE_UNAME_M": "arm64"}, "v0.6.2")
    assert result.returncode == 0, result.stderr
    assert installed_version(apps) == "0.6.2"


def test_an_intel_mac_refuses_a_release_from_before_LBArch(tmp_path):
    # There is no Intel build before v0.7.0, so a nameless-arch bundle must not be installed on an Intel Mac.
    env, server, apps, _ = rig(tmp_path)
    publish(server, tmp_path, "0.6.2", arch="x86_64", says_arch=OMIT)
    result = install({**env, "FAKE_UNAME_M": "x86_64"}, "v0.6.2")
    assert result.returncode == 1, result.stdout
    assert not (apps / "LoupedeckBridge.app").exists()


def test_the_refusal_names_the_arch_it_found(tmp_path):
    # plutil writes "Could not extract value" to stdout, so a naive capture puts that text in the message.
    env, server, apps, _ = rig(tmp_path)
    make_app(apps, "0.6.2", arch="x86_64")
    publish(server, tmp_path, "0.7.0", arch="x86_64", says_arch="arm64")
    result = install({**env, "FAKE_UNAME_M": "x86_64"})
    assert result.returncode == 1
    assert "Could not extract" not in result.stderr, result.stderr
    assert "arm64" in result.stderr and "x86_64" in result.stderr, result.stderr
