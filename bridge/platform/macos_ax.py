"""macOS Accessibility permission: check it, and ask macOS to prompt for it.

macOS grants this permission to the *app* that launched the process (the "responsible"
app): Terminal, the Claude app, or LoupedeckBridge.app. The bridge can't grant it, only
detect it's missing and trigger macOS's own prompt.

The frameworks load on first use, so importing this module (via macos_keys) works on any system, e.g. for
the tests on Windows.
"""
from __future__ import annotations

import ctypes
import ctypes.util

_libs = None


def _load():
    global _libs
    if _libs is None:
        ax = ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices"))
        cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
        ax.AXIsProcessTrusted.restype = ctypes.c_bool
        ax.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
        ax.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
        cf.CFDictionaryCreate.restype = ctypes.c_void_p
        cf.CFDictionaryCreate.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long,
                                          ctypes.c_void_p, ctypes.c_void_p]
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        _libs = (ax, cf)
    return _libs


def is_trusted() -> bool:
    ax, _ = _load()
    return bool(ax.AXIsProcessTrusted())


def request_permission(prompt: bool = True) -> bool:
    """Return whether the permission is granted; with prompt=True macOS shows its
    "would like to control this computer" dialog if it isn't."""
    ax, cf = _load()
    key = ctypes.c_void_p.in_dll(ax, "kAXTrustedCheckOptionPrompt")
    value = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue" if prompt else "kCFBooleanFalse")
    keys = (ctypes.c_void_p * 1)(key.value)
    values = (ctypes.c_void_p * 1)(value.value)
    options = cf.CFDictionaryCreate(
        None, keys, values, 1,
        ctypes.addressof(ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")),
        ctypes.addressof(ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryValueCallBacks")))
    try:
        return bool(ax.AXIsProcessTrustedWithOptions(options))
    finally:
        cf.CFRelease(options)
