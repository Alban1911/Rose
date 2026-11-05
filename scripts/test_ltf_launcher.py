#!/usr/bin/env python3
"""Build and run the Windows launcher token/policy integration tests."""

from pathlib import Path
import subprocess
import sys
import tempfile

from build_ltf import COMMON_FLAGS, ROOT, _find_vcvars


def main() -> int:
    vcvars = _find_vcvars()
    if not vcvars:
        print("MSVC x64 build tools were not found.")
        return 1
    source = ROOT / "native" / "ltf" / "tests" / "launcher_token_test.cpp"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        work = Path(directory)
        executable = work / "launcher_token_test.exe"
        batch = work / "build.cmd"
        batch.write_text(
            '@echo off\n'
            f'call "{vcvars}" >nul || exit /b 1\n'
            f'cl {COMMON_FLAGS} "{source}" /Fe:"{executable}" || exit /b 1\n',
            encoding="utf-8",
        )
        built = subprocess.run(["cmd", "/d", "/c", str(batch)], cwd=work, check=False)
        if built.returncode:
            return built.returncode
        return subprocess.run([str(executable)], cwd=work, check=False, timeout=30).returncode


if __name__ == "__main__":
    sys.exit(main())
