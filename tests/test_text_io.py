"""Every text file the bridge and its tools read or write names its encoding (milestone 7).

Without one, Python uses the system's locale encoding: UTF-8 on the Mac, but cp1252 on Windows, which misreads
the ★ in config/commands.json and broke the settings page (app.js answered 500). JSON reads use "utf-8-sig", so
a file saved by Notepad with a BOM still loads; everything else uses "utf-8"."""
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEXT_CALLS = {"read_text", "write_text", "fdopen", "RotatingFileHandler"}
NOT_FILES = {"os", "webbrowser"}          # os.open is low-level; webbrowser.open opens a page


def _mode(call: ast.Call, position: int):
    for kw in call.keywords:
        if kw.arg == "mode":
            return kw.value
    return call.args[position] if len(call.args) > position else None


def _problems(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
        owner = func.value.id if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) else None
        if name == "open":
            if owner in NOT_FILES:
                continue
            # open(path, mode) vs path.open(mode)
            mode = _mode(node, 1 if isinstance(func, ast.Name) else 0)
        elif name in TEXT_CALLS:
            mode = _mode(node, 1) if name == "fdopen" else None
        else:
            continue
        if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value:
            continue
        if any(kw.arg == "encoding" for kw in node.keywords):
            continue
        yield f"{path.relative_to(REPO).as_posix()}:{node.lineno}: {name}() without encoding="


def test_text_io_names_utf8():
    files = sorted((REPO / "bridge").rglob("*.py")) + sorted((REPO / "tools").glob("*.py"))
    problems = [p for f in files for p in _problems(f)]
    assert not problems, "\n".join(problems)
