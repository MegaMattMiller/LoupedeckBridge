"""tools/install.sh, the standalone installer (milestone 6). Runs the real script with stand-in curl, codesign,
open, pgrep, pkill and sleep; ditto, plutil and shasum are the real system tools."""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUNDLE_ID = "io.github.megamattmiller.loupedeckbridge"
CERT = b"fake DER certificate"
PINNED = hashlib.sha256(CERT).hexdigest()

FAKES = {
    # curl -fL -o OUT URL (or -fsSL URL for the API): serves files from $FAKE_SERVER by URL basename.
    "curl": r'''#!/bin/bash
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
for a in "$@"; do case "$a" in
  --verify) exit "${FAKE_VERIFY:-0}";;
  --extract-certificates=*) [ -n "${FAKE_NO_CERT:-}" ] || printf '%s' "$FAKE_CERT" > "${a#--extract-certificates=}0";;
esac; done
exit 0
''',
    "open": '#!/bin/bash\necho "open $*" >> "$FAKE_LOG"\n',
    "pgrep": "#!/bin/bash\nexit 1\n",
    "pkill": "#!/bin/bash\nexit 0\n",
    "sleep": "#!/bin/bash\nexit 0\n",
}


def make_app(parent: Path, version: str, bundle_id: str = BUNDLE_ID) -> Path:
    app = parent / "LoupedeckBridge.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
        f"<key>CFBundleIdentifier</key><string>{bundle_id}</string>"
        f"<key>LBVersion</key><string>{version}</string></dict></plist>")
    return app


def publish(server: Path, tmp: Path, version: str, bundle_id: str = BUNDLE_ID) -> None:
    """A fake GitHub release: the zip, its .sha256, and the 'latest' API answer."""
    src = tmp / f"src-{version}"
    app = make_app(src, version, bundle_id)
    name = f"LoupedeckBridge-v{version}-macos-arm64.zip"
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
