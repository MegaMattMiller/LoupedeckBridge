"""Security properties of the release workflow that must not regress (milestone 6 review, Critical 1):
- nothing unpinned from PyPI runs before the tested build is saved, and the test tools are hash-pinned
- the publish job signs exactly the saved build
- the signing key exists during one step only, and no code from the build runs while it does
- the key can't be exported from the temporary keychain
The workflows are read as text: each check names the property it protects."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RELEASE = (REPO / ".github" / "workflows" / "release.yml").read_text()
CI = (REPO / ".github" / "workflows" / "ci.yml").read_text()


def job(text: str, name: str) -> str:
    start = text.index(f"\n  {name}:\n")
    following = re.search(r"\n  [A-Za-z_-]+:\n", text[start + 1:])
    return text[start: start + 1 + following.start()] if following else text[start:]


def steps(job_text: str) -> "list[str]":
    return job_text.split("\n      - ")[1:]


def test_build_is_saved_before_any_test_code_runs():
    build = job(RELEASE, "build")
    assert build.index("actions/upload-artifact") < build.index("pip install"), \
        "the tested build must be uploaded before any downloaded test tool runs"


def test_publish_signs_exactly_the_saved_build():
    build, publish = job(RELEASE, "build"), job(RELEASE, "publish")
    assert "zip_sha256: ${{ steps.save.outputs.zip_sha256 }}" in build
    unpack = next(s for s in steps(publish) if "ditto -x -k unsigned.zip" in s)
    assert "needs.build.outputs.zip_sha256" in unpack and "shasum -a 256 unsigned.zip" in unpack


def test_signing_key_exists_in_one_step_only():
    publish = steps(job(RELEASE, "publish"))
    signing = [s for s in publish if "import_signing_identity.sh" in s]
    assert len(signing) == 1
    step = signing[0]
    assert "security delete-keychain" in step and "trap" in step, "the keychain must go at the end of the same step"
    assert "Contents/MacOS/LoupedeckBridge" not in step, "no code from the build may run while the key can sign"
    after = publish[publish.index(step) + 1:]
    assert any("--check-signature" in s for s in after)
    assert not any("keychain" in s and "delete" not in s for s in after)


def test_test_tools_are_hash_pinned():
    for name, text in (("release.yml", job(RELEASE, "build")), ("ci.yml", job(CI, "release-build"))):
        assert "requirements-dev.txt" not in text, f"{name}: unpinned test tools in the release build's job"
        assert "--require-hashes" in text and "tools/release-test-requirements.txt" in text, name


def test_signing_key_is_not_extractable():
    script = (REPO / "tools" / "import_signing_identity.sh").read_text()
    line = next(l for l in script.splitlines() if l.startswith("security import"))
    assert " -x " in line
