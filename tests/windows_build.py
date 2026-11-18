"""Building the Windows tray app's C# projects from the tests (milestone 7): `dotnet build` against .NET Framework
4.8's reference assemblies, with no NuGet packages and with the .NET CLI's telemetry off."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LAUNCHER = REPO / "windows" / "launcher"
DOTNET_ENV = {**os.environ, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1",
              "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1"}
CAN_BUILD = sys.platform == "win32" and shutil.which("dotnet") is not None


def build(project: Path, out: Path, *properties: str) -> subprocess.CompletedProcess:
    """`dotnet build PROJECT -c Release -o OUT [-p:…]`; check returncode, and stdout for the errors."""
    return subprocess.run(["dotnet", "build", str(project), "-c", "Release", "-nologo", "-v", "q", "-o", str(out),
                           *properties], capture_output=True, text=True, env=DOTNET_ENV, timeout=300)
