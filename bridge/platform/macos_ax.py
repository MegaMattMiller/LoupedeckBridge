"""macOS Accessibility permission: check it, and ask macOS to prompt for it.

macOS grants this permission to the *app* that launched the process (the "responsible"
app): Terminal, the Claude app, or LoupedeckBridge.app. The bridge can't grant it, only
detect it's missing and trigger macOS's own prompt.
"""
from __future__ import annotations

import ctypes
import ctypes.util

_ax = ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices"))
_cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))

_ax.AXIsProcessTrusted.restype = ctypes.c_bool
_ax.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
_ax.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
_cf.CFDictionaryCreate.restype = ctypes.c_void_p
_cf.CFDictionaryCreate.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long,
                                   ctypes.c_void_p, ctypes.c_void_p]
_cf.CFRelease.argtypes = [ctypes.c_void_p]


def is_trusted() -> bool:
    return bool(_ax.AXIsProcessTrusted())


def request_permission(prompt: bool = True) -> bool:
    """Return whether the permission is granted; with prompt=True macOS shows its
    "would like to control this computer" dialog if it isn't."""
    key = ctypes.c_void_p.in_dll(_ax, "kAXTrustedCheckOptionPrompt")
    value = ctypes.c_void_p.in_dll(_cf, "kCFBooleanTrue" if prompt else "kCFBooleanFalse")
    keys = (ctypes.c_void_p * 1)(key.value)
    values = (ctypes.c_void_p * 1)(value.value)
    options = _cf.CFDictionaryCreate(
        None, keys, values, 1,
        ctypes.addressof(ctypes.c_void_p.in_dll(_cf, "kCFTypeDictionaryKeyCallBacks")),
        ctypes.addressof(ctypes.c_void_p.in_dll(_cf, "kCFTypeDictionaryValueCallBacks")))
    try:
        return bool(_ax.AXIsProcessTrustedWithOptions(options))
    finally:
        _cf.CFRelease(options)
