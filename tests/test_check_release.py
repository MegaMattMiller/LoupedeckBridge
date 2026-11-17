"""tools/check_release.py: a release tag must match bridge.__version__ and have a CHANGELOG.md section
(milestone 6, Review Focus 4). The release workflow runs it before building, and uses its output as the notes."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import bridge

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "check_release.py"
CHANGELOG = """# Changelog

## v0.5.1 — 2026-11-20

- Small fixes.

## v0.5.0 — 2026-11-17

- First release.
- The menu bar app.

## v0.4.0

- Older.
"""


def check(tmp_path, *args, version="0.5.0", changelog=CHANGELOG):
    (tmp_path / "bridge").mkdir(exist_ok=True)
    (tmp_path / "bridge" / "__init__.py").write_text(f'"""x"""\n__version__ = "{version}"\n')
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    return subprocess.run([sys.executable, str(SCRIPT), *args, "--root", str(tmp_path)],
                          capture_output=True, text=True, timeout=30)


def test_check_release_ok(tmp_path):
    result = check(tmp_path, "0.5.0")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "- First release.\n- The menu bar app."


def test_check_release_accepts_a_tag_name(tmp_path):
    assert check(tmp_path, "v0.5.0").returncode == 0


def test_check_release_version_mismatch(tmp_path):
    result = check(tmp_path, "0.5.0", version="0.5.1")
    assert result.returncode == 1 and "0.5.1" in result.stderr


def test_check_release_missing_section(tmp_path):
    result = check(tmp_path, "0.5.0", changelog=CHANGELOG.replace("## v0.5.0 — 2026-11-17", "## v0.4.9"))
    assert result.returncode == 1 and "CHANGELOG" in result.stderr


def test_check_release_no_prefix_match(tmp_path):
    # "## v0.5.10" is not a section for v0.5.1
    result = check(tmp_path, "0.5.1", version="0.5.1", changelog="# Changelog\n\n## v0.5.10\n\n- Later.\n")
    assert result.returncode == 1


def test_check_release_empty_section(tmp_path):
    result = check(tmp_path, "0.5.0", changelog="# Changelog\n\n## v0.5.0\n\n## v0.4.0\n\n- Older.\n")
    assert result.returncode == 1 and "empty" in result.stderr


def test_check_release_rejects_a_non_version(tmp_path):
    assert check(tmp_path, "latest").returncode == 1


def test_the_repo_is_releasable():
    # The committed version always has its changelog section, so a release is one tag away.
    result = subprocess.run([sys.executable, str(SCRIPT), bridge.__version__], capture_output=True, text=True,
                            timeout=30)
    assert result.returncode == 0, result.stderr
