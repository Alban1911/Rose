#!/usr/bin/env python3
"""Build Rose's stand-in cslol-dll.dll (see native/cslol_stub/cslol_stub.c)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "native" / "cslol_stub" / "cslol_stub.c"
OUTPUT = ROOT / "injection" / "tools" / "cslol-dll.dll"
# Second copy under a name older updaters do not skip; Rose restores cslol-dll.dll from it
OUTPUT_COPY = OUTPUT.with_suffix(".stub")


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


def build_stub() -> int:
    vcvars = _find_vcvars()
    if not vcvars:
        print("[ERROR] MSVC x64 build tools were not found.")
        print("        Install the Visual Studio C++ build tools.")
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # MSVC helper processes can briefly keep the work directory busy
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as work_dir:
        # No CRT and no entry point: the DLL has no dependencies beyond itself
        implib = Path(work_dir) / "cslol_stub.lib"
        script = Path(work_dir) / "build.bat"
        script.write_text(
            "@echo off\r\n"
            f'call "{vcvars}" >nul || exit /b 1\r\n'
            f'cl /nologo /LD /O1 /GS- "{SOURCE}" /link /NOENTRY /NODEFAULTLIB '
            f'/OUT:"{OUTPUT}" /IMPLIB:"{implib}"\r\n',
            encoding="utf-8",
        )
        result = subprocess.run(["cmd", "/d", "/c", str(script)], cwd=work_dir, check=False)
    if result.returncode != 0:
        print(f"[ERROR] cslol-dll stub build failed with exit code {result.returncode}.")
        return result.returncode

    shutil.copy2(OUTPUT, OUTPUT_COPY)
    print(f"[OK] Built {OUTPUT} (+ {OUTPUT_COPY.name})")
    return 0


if __name__ == "__main__":
    sys.exit(build_stub())
