"""Loupedeck+ → Lightroom bridge."""

# The release version: shown in the menu bar / tray app and on the settings page, written into the Mac
# app's Info.plist and the Windows app's LoupedeckBridge.json by the builds, and matched by release tags (vX.Y.Z) and CHANGELOG.md.
# (Lightroom is sent a fixed "0.1" on register instead: see bridge/app.py.)
__version__ = "0.6.2"
