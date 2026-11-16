from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


def test_trust_check_agrees_with_and_without_options():
    # request_permission(prompt=False) goes through AXIsProcessTrustedWithOptions (the same
    # options dictionary the real prompt uses) without showing a dialog; it must agree with
    # the plain AXIsProcessTrusted check.
    from bridge.platform import macos_ax
    trusted = macos_ax.is_trusted()
    assert isinstance(trusted, bool)
    assert macos_ax.request_permission(prompt=False) is trusted
