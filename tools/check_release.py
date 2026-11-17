#!/usr/bin/env python3
"""Is this version ready to release?  tools/check_release.py VERSION [--root DIR]

VERSION is "0.5.0" or a tag name, "v0.5.0". Exit 0 and print that version's CHANGELOG.md section (the
release notes) if bridge/__init__.py's __version__ is VERSION and CHANGELOG.md has a "## vVERSION" section
with something in it. Otherwise exit 1 and say why. Run by tools/release.sh and the release workflow.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def section(changelog: str, version: str) -> "str | None":
    """The text under "## v<version>" (anything may follow the heading, e.g. a date) up to the next "## "."""
    heading = re.compile(r"^## v" + re.escape(version) + r"(?![\w.])")
    lines, found = [], False
    for line in changelog.splitlines():
        if found and line.startswith("## "):
            break
        if found:
            lines.append(line)
        elif heading.match(line):
            found = True
    return "\n".join(lines).strip() if found else None


def problem(root: Path, version: str) -> "tuple[str | None, str]":
    """(why it isn't releasable, or None; the notes)."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        return f"'{version}' isn't a version like 0.5.0", ""
    init = (root / "bridge" / "__init__.py").read_text()
    match = re.search(r'^__version__ = "([^"]*)"', init, re.M)
    if not match:
        return "bridge/__init__.py has no __version__", ""
    if match.group(1) != version:
        return f"bridge/__init__.py says {match.group(1)}, not {version}", ""
    changelog = root / "CHANGELOG.md"
    notes = section(changelog.read_text(), version) if changelog.exists() else None
    if notes is None:
        return f"CHANGELOG.md has no '## v{version}' section", ""
    if not notes:
        return f"CHANGELOG.md's v{version} section is empty", ""
    return None, notes


def main(argv: "list[str]") -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    version = args.version[1:] if args.version.startswith("v") else args.version
    why, notes = problem(args.root, version)
    if why:
        print(f"check_release: {why}", file=sys.stderr)
        return 1
    print(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
