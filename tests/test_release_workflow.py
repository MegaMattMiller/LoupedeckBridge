"""Security properties of the release workflow that must not regress (milestone 6 review, Critical 1):
- nothing unpinned from PyPI runs before the tested build is saved, and the test tools are hash-pinned
- the publish job signs exactly the saved build
- the signing key exists during one step only, and no code from the build runs while it does
- the key can't be exported from the temporary keychain
Milestone 7: the Windows build is saved and checked the same way, signed in the same key step, verified on Windows
before anything is published, and nothing is published unless both platforms' downloads are there.
The workflows are read as text: each check names the property it protects. outline() checks the layout GitHub reads
(the test tools have no YAML parser), so a broken layout fails here instead of every check passing vacuously."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RELEASE = (REPO / ".github" / "workflows" / "release.yml").read_text()
CI = (REPO / ".github" / "workflows" / "ci.yml").read_text()


def outline(text: str) -> "dict[str, list[str]]":
    """A workflow's top-level keys, each with its keys one level in (two spaces), in order."""
    keys: "dict[str, list[str]]" = {}
    current = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        top = re.match(r"([A-Za-z_-]+):", line)
        child = re.match(r"  ([A-Za-z_-]+):", line)
        if top:
            current = keys.setdefault(top.group(1), [])
        elif child and current is not None:
            current.append(child.group(1))
    return keys


def job(text: str, name: str) -> str:
    start = text.index(f"\n  {name}:\n", text.index("\njobs:\n"))
    following = re.search(r"\n  [A-Za-z_-]+:\n", text[start + 1:])
    return text[start: start + 1 + following.start()] if following else text[start:]


def steps(job_text: str) -> "list[str]":
    return job_text.split("\n      - ")[1:]


def compares_commits(sign_steps: "list[str]", env_var: str) -> bool:
    """A step that both receives the other build's commit AND compares it with this one's.

    Asserting only on the `env:` entry passes even if the comparison line is deleted (found while
    mutation-testing the milestone 8 guards), so the `[ "$X" = "$COMMIT" ]` line must be there too.
    """
    for step in sign_steps:
        if f"{env_var}: ${{{{ needs." not in step or "needs.build.outputs.commit" not in step:
            continue
        if any(f'"${env_var}"' in line and '"$COMMIT"' in line and "[" in line for line in step.splitlines()):
            return True
    return False


def test_build_is_saved_before_any_test_code_runs():
    build = job(RELEASE, "build")
    assert build.index("actions/upload-artifact") < build.index("pip install"), \
        "the tested build must be uploaded before any downloaded test tool runs"


def test_publish_signs_exactly_the_saved_build():
    build, sign = job(RELEASE, "build"), job(RELEASE, "sign")
    assert "zip_sha256: ${{ steps.save.outputs.zip_sha256 }}" in build
    unpack = next(s for s in steps(sign) if "ditto -x -k unsigned.zip" in s)
    assert "needs.build.outputs.zip_sha256" in unpack and "shasum -a 256 unsigned.zip" in unpack


def test_signing_key_exists_in_one_step_only():
    sign = steps(job(RELEASE, "sign"))
    signing = [s for s in sign if "import_signing_identity.sh" in s]
    assert len(signing) == 1
    step = signing[0]
    assert "security delete-keychain" in step and "trap" in step, "the keychain must go at the end of the same step"
    assert "Contents/MacOS/LoupedeckBridge" not in step, "no code from the build may run while the key can sign"
    after = sign[sign.index(step) + 1:]
    assert any("--check-signature" in s for s in after)
    assert not any("keychain" in s and "delete" not in s for s in after)


def test_test_tools_are_hash_pinned():
    for name, text in (("release.yml", job(RELEASE, "build")), ("ci.yml", job(CI, "release-build")),
                       ("release.yml", job(RELEASE, "build-intel")), ("ci.yml", job(CI, "release-build-intel")),
                       ("release.yml", job(RELEASE, "build-windows")), ("ci.yml", job(CI, "release-build-windows"))):
        assert "requirements-dev.txt" not in text, f"{name}: unpinned test tools in the release build's job"
        assert "--require-hashes" in text and "tools/release-test-requirements.txt" in text, name


def test_signing_key_is_not_extractable():
    script = (REPO / "tools" / "import_signing_identity.sh").read_text()
    line = next(l for l in script.splitlines() if l.startswith("security import"))
    assert " -x " in line


# ---- v0.5.1: the review's deferred workflow fixes --------------------------------------------------------

def test_publish_signs_the_commit_the_build_job_built():
    # Both jobs resolved the tag by name, hours apart across the approval wait.
    build, sign = job(RELEASE, "build"), job(RELEASE, "sign")
    assert "commit: ${{ steps.commit.outputs.sha }}" in build
    assert "ref: ${{ needs.build.outputs.commit }}" in sign
    signing = next(i for i, s in enumerate(steps(sign)) if "import_signing_identity.sh" in s)
    check = next(i for i, s in enumerate(steps(sign)) if "ls-remote" in s)
    assert check < signing, "the tag must be checked unmoved before the key is used"
    assert "needs.build.outputs.commit" in steps(sign)[check]


def test_run_workflow_needs_the_matching_tag():
    which = next(s for s in steps(job(RELEASE, "build")) if s.startswith("name: Which version"))
    assert "github.ref }}" in which and "refs/tags/v" in which


def test_publish_checks_the_signing_identifier_like_the_app():
    # Across the sign job, not within one step: milestone 8 split the launcher's own check away from the
    # certificate checks, so that a step which runs a launcher need never mention the Intel build.
    sign = job(RELEASE, "sign")
    assert "--check-signature" in sign
    assert '-R="identifier \\"io.github.megamattmiller.loupedeckbridge\\""' in sign
    # Each verify job's own check is covered by its own test (verify-windows reaches it through
    # check_windows_release.ps1, not inline).


def test_rehearsal_proves_tampering_and_another_key_are_refused():
    rehearsal = job(CI, "release-build")
    # `if …; then fail` rather than `! …`: under bash -e, a `!` line never fails the step
    assert "tampered" in rehearsal and "if dist/LoupedeckBridge.app/Contents/MacOS/LoupedeckBridge --check-signature" in rehearsal
    assert "another key" in rehearsal and 'LB_PINNED_SIGNER_SHA256="$(printf' in rehearsal
    assert "\n          ! " not in rehearsal


# ---- milestone 7: Windows -------------------------------------------------------------------------------------------
CHECK_SCRIPT = (REPO / "tools" / "check_windows_release.ps1").read_text(encoding="utf-8")


def test_windows_build_is_saved_before_any_test_code_runs():
    build = job(RELEASE, "build-windows")
    assert build.index("actions/upload-artifact") < build.index("pip install"),         "the tested Windows build must be uploaded before any downloaded test tool runs"
    assert "zip_sha256: ${{ steps.save.outputs.zip_sha256 }}" in build


def test_sign_signs_exactly_the_saved_windows_build():
    sign = steps(job(RELEASE, "sign"))
    check = next(i for i, s in enumerate(sign) if "needs.build-windows.outputs.zip_sha256" in s)
    signing = next(i for i, s in enumerate(sign) if "import_signing_identity.sh" in s)
    assert check < signing, "the Windows zip must be checked byte for byte before the key is used"


def test_both_builds_are_the_same_commit():
    build_windows, sign = job(RELEASE, "build-windows"), steps(job(RELEASE, "sign"))
    assert "commit: ${{ steps.commit.outputs.sha }}" in build_windows
    assert compares_commits(sign, "WINDOWS_COMMIT"), "the Windows build's commit must be compared with the Mac's"


def test_windows_zip_is_signed_in_the_key_step():
    step = next(s for s in steps(job(RELEASE, "sign")) if "import_signing_identity.sh" in s)
    assert "tools/sign_windows_zip.sh" in step, "the Windows zip is signed while the key exists, in the same step"
    assert "LoupedeckBridge.exe" not in step and "Contents/MacOS/LoupedeckBridge" not in step
    assert 'rm -f "$RUNNER_TEMP/id.p12"' in step


def test_verify_windows_runs_the_app_check_and_install_ps1():
    verify = job(RELEASE, "verify-windows")
    assert "tools/check_windows_release.ps1" in verify and "secrets." not in verify
    assert "--check-signature" in CHECK_SCRIPT and "install.ps1" in CHECK_SCRIPT


def test_publish_needs_both_platforms():
    publish = job(RELEASE, "publish")
    needs = re.search(r"needs: \[([^\]]*)\]", publish).group(1)
    assert {"build", "build-intel", "build-windows", "sign", "verify-intel",
            "verify-windows"} <= {n.strip() for n in needs.split(",")}
    for name in ("macos-arm64.zip", "macos-arm64.zip.sha256", "macos-x86_64.zip", "macos-x86_64.zip.sha256",
                 "windows-x64.zip", "windows-x64.zip.sha256", "windows-x64.zip.p7s"):
        assert name in publish, name
    assert "contents: write" in publish and "secrets." not in publish


# ---- milestone 8: the Intel Mac release ---------------------------------------------------------------------

def test_intel_build_runs_on_an_intel_runner():
    build = job(RELEASE, "build-intel")
    assert "runs-on: macos-15-intel" in build
    assert "unsigned-app-intel" in build
    # the same discipline as the other builds: saved before any test code, and unchanged by the tests
    saved = [i for i, s in enumerate(steps(build)) if "upload-artifact" in s]
    tested = [i for i, s in enumerate(steps(build)) if "pytest" in s]
    assert saved and tested and max(saved) < min(tested), "the Intel build must be saved before any test code runs"


def test_sign_needs_every_build_and_signs_both_macs():
    sign = job(RELEASE, "sign")
    needs = re.search(r"needs: \[([^\]]*)\]", sign).group(1)
    assert {"build", "build-intel", "build-windows"} <= {n.strip() for n in needs.split(",")}
    assert "unsigned-app-intel" in sign
    key_step = next(s for s in steps(sign) if "import_signing_identity.sh" in s)
    assert "dist/LoupedeckBridge.app" in key_step and "dist-intel/LoupedeckBridge.app" in key_step, \
        "both Macs are signed in the one approved key step"


def test_the_intel_app_is_only_executed_on_an_intel_runner():
    # An Intel binary can't be run on the arm64 signing runner at all, so running one anywhere but an Intel
    # runner is a broken release. codesign and plutil read a bundle without executing it; what matters is
    # invoking the launcher.
    #
    # Checked per STEP, not per line: `for app in dist/… dist-intel/…` on one line and
    # `"$app/Contents/MacOS/LoupedeckBridge"` on the next would slip past a per-line check, and that idiom is
    # already in the sign job. So a step that invokes a launcher may not mention the Intel build at all.
    for name, text in (("release.yml", RELEASE), ("ci.yml", CI)):
        for each in outline(text)["jobs"]:
            body = job(text, each)
            if "runs-on: macos-15-intel" in body:
                continue
            for step in steps(body):
                if "Contents/MacOS/LoupedeckBridge" in step:
                    assert "dist-intel" not in step, (
                        f"{name}: {each} isn't on an Intel runner, and a step that runs a launcher mentions "
                        f"the Intel build: {step.splitlines()[0]}")
    verify = job(RELEASE, "verify-intel")
    assert "runs-on: macos-15-intel" in verify
    # and it really does run that app, on what it unzipped from the Intel download
    assert "macos-x86_64.zip" in verify
    assert any("Contents/MacOS/LoupedeckBridge" in line and "--check-signature" in line
               for line in verify.splitlines()), "verify-intel must run the Intel app's own check"
    needs = re.search(r"needs: \[([^\]]*)\]", verify).group(1)
    assert {"build-intel", "sign"} <= {n.strip() for n in needs.split(",")}
    assert "secrets." not in verify


def test_sign_checks_both_macs_against_the_pinned_key():
    accept = next(s for s in steps(job(RELEASE, "sign")) if "PINNED_SIGNER_SHA256_DEFAULT" in s)
    assert "extract-certificates" in accept
    for app in ("dist/LoupedeckBridge.app", "dist-intel/LoupedeckBridge.app"):
        assert app in accept, f"{app} isn't compared with the pinned key"


def test_sign_signs_exactly_the_saved_intel_build():
    # The Windows and Apple Silicon builds each have this guard; the third build needs it too.
    sign = steps(job(RELEASE, "sign"))
    check = next(i for i, s in enumerate(sign) if "needs.build-intel.outputs.zip_sha256" in s)
    signing = next(i for i, s in enumerate(sign) if "import_signing_identity.sh" in s)
    assert check < signing, "the Intel build must be checked byte for byte before the key is used"


def test_every_build_is_the_same_commit():
    intel, sign = job(RELEASE, "build-intel"), steps(job(RELEASE, "sign"))
    assert "commit: ${{ steps.commit.outputs.sha }}" in intel
    assert compares_commits(sign, "INTEL_COMMIT"), \
        "the Intel build's commit must be compared with the Apple Silicon one's"


def test_the_publish_gate_counts_exactly_the_files_it_lists():
    # The list and the count are written separately, so they can drift: -eq 5 with seven names would publish
    # a release missing two downloads.
    publish = job(RELEASE, "publish")
    listed = re.findall(r'"LoupedeckBridge-v\$VERSION-[a-z0-9_.-]+"', publish)
    count = re.search(r'wc -l\)" -eq (\d+)', publish)
    assert count, "the publish gate must count the downloads"
    assert len(set(listed)) == int(count.group(1)), \
        f"the gate lists {len(set(listed))} downloads but demands {count.group(1)}"


def test_ci_builds_the_intel_release_too():
    intel = job(CI, "release-build-intel")
    assert "runs-on: macos-15-intel" in intel
    assert "tools/build_release_app.sh" in intel and "pytest" in intel
    assert "tests/test_release_bundle.py" in intel


def test_only_sign_uses_the_release_environment():
    assert RELEASE.count("environment: release") == 1
    assert "environment: release" in job(RELEASE, "sign")


def test_windows_rehearsal_proves_tampering_and_another_key_are_refused():
    rehearsal = job(CI, "release-build-windows")
    assert "tools/check_windows_release.ps1" in rehearsal and "-Pinned" in rehearsal
    assert "tampered" in CHECK_SCRIPT and "'0' * 64" in CHECK_SCRIPT


def test_libressl_signatures_are_checked_on_windows():
    # The release signs the Windows zip with macOS's LibreSSL; CI proves Windows' SignedCms accepts what it makes.
    assert "libressl-sample" in job(CI, "release-build") and "tools/sign_windows_zip.sh" in job(CI, "release-build")
    assert "libressl-sample" in job(CI, "release-build-windows")


def test_workflows_are_laid_out_as_github_reads_them():
    release, ci = outline(RELEASE), outline(CI)
    assert list(release) == ["name", "on", "permissions", "concurrency", "jobs"], list(release)
    assert release["concurrency"] == ["group", "cancel-in-progress"], "a job outside `jobs:` is no job at all"
    assert release["jobs"] == ["build", "build-intel", "build-windows", "sign", "verify-intel",
                               "verify-windows", "publish"]
    assert list(ci) == ["name", "on", "permissions", "jobs"], list(ci)
    assert ci["jobs"] == ["suite", "suite-windows", "release-build", "release-build-intel",
                          "release-build-windows"]


def test_windows_jobs_use_no_macos_only_tools():
    # tools/make_signing_identity.sh needs shasum and macOS's /usr/bin/openssl; Git Bash on Windows has neither.
    mac_only = ("make_signing_identity.sh", "shasum", "/usr/bin/openssl", "ditto", "codesign", "security ")
    for name, text in (("release.yml", RELEASE), ("ci.yml", CI)):
        for each in outline(text)["jobs"]:
            body = job(text, each)
            if "runs-on: windows" in body:
                used = [tool for tool in mac_only if tool in body]
                assert not used, f"{name}: {each} runs on Windows but uses {used}"


def test_artifacts_download_into_folders_the_checkout_doesnt_have():
    # The v0.6.0 release run: the sign job downloaded the Windows zip into windows/, which the checkout already has
    # (the tray app's source), so "only the zip is there" failed before signing (and `cp windows/*` would have).
    tracked = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    taken = {line.split("/")[0] for line in tracked.splitlines()}
    for name, text in (("release.yml", RELEASE), ("ci.yml", CI)):
        for each in outline(text)["jobs"]:
            for step in steps(job(text, each)):
                path = re.search(r"\n\s+path: (\S+)", step)
                if "actions/download-artifact" in step and path:
                    first = path.group(1).split("/")[0]
                    assert first not in taken, f"{name}: {each} downloads into {first}/, which the checkout already has"


def test_jobs_need_only_jobs_that_exist():
    for name, text in (("release.yml", RELEASE), ("ci.yml", CI)):
        jobs = outline(text)["jobs"]
        for each in jobs:
            needs = re.search(r"\n    needs: (.+)\n", job(text, each))
            needed = set(re.findall(r"[A-Za-z_-]+", needs.group(1))) if needs else set()
            assert needed <= set(jobs) - {each}, f"{name}: {each} needs {sorted(needed - set(jobs))}"
