#!/usr/bin/env python3
"""Build the LeagueToolFlop (LTF) bridge from the sources vendored in native/ltf.

Produces injection/tools/ltk_launcher.exe and injection/tools/LeagueToolFlop.dll,
which replace the LTK patcher binaries users had to copy in themselves.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "native" / "ltf"
TOOLS_DIR = ROOT / "injection" / "tools"
LAUNCHER = TOOLS_DIR / "ltk_launcher.exe"
BRIDGE_DLL = TOOLS_DIR / "LeagueToolFlop.dll"

# /utf-8 keeps the sources' em-dashes intact; /MT keeps the injected DLL free
# of a CRT install
COMMON_FLAGS = "/nologo /std:c++20 /O2 /EHsc /MT /utf-8"
LAUNCHER_SOURCES = ["LeagueToolFlop-inj.cpp"]
DLL_SOURCES = ["LeagueToolFlop_dll.cpp"]
DLL_LIBS = "ws2_32.lib psapi.lib user32.lib advapi32.lib shell32.lib bcrypt.lib"


def _find_vcvars() -> Path | None:
    vswhere = Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.exists():
        return None
    result = subprocess.run(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        candidate = Path(line.strip()) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
        if candidate.exists():
            return candidate
    return None


def build() -> int:
    vcvars = _find_vcvars()
    if not vcvars:
        print("[ERROR] MSVC x64 build tools were not found.")
        print("        Install the Visual Studio C++ build tools.")
        return 1
    missing = [name for name in DLL_SOURCES + LAUNCHER_SOURCES if not (SOURCE_DIR / name).exists()]
    if missing:
        print(f"[ERROR] Missing vendored sources in {SOURCE_DIR}: {', '.join(missing)}")
        return 1

    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    # MSVC helper processes can briefly keep the work directory busy
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as work_dir:
        script = Path(work_dir) / "build.bat"
        # Objects go to the work directory, not next to the vendored sources
        objects = f'/Fo"{Path(work_dir)}\\\\"'
        lines = [
            "@echo off\r\n",
            f'call "{vcvars}" >nul || exit /b 1\r\n',
            f'cd /d "{SOURCE_DIR}"\r\n',
            f"cl {COMMON_FLAGS} {objects} {' '.join(LAUNCHER_SOURCES)} /link "
            f'/OUT:"{LAUNCHER}" || exit /b 1\r\n',
            f"cl {COMMON_FLAGS} /LD {objects} {' '.join(DLL_SOURCES)} /link "
            f'/OUT:"{BRIDGE_DLL}" {DLL_LIBS} || exit /b 1\r\n',
        ]
        script.write_text("".join(lines), encoding="utf-8")
        result = subprocess.run(["cmd", "/d", "/c", str(script)], cwd=work_dir, check=False)

    if result.returncode != 0:
        print(f"[ERROR] LTF bridge build failed with exit code {result.returncode}.")
        return result.returncode

    print(f"[OK] Built {LAUNCHER}")
    print(f"[OK] Built {BRIDGE_DLL}")
    return 0


if __name__ == "__main__":
    sys.exit(build())
