#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Create the update package the launcher downloads from a GitHub release

Zips dist/Rose (Rose.exe and _internal/ at the root of the archive, as the
updater extracts it) into installer/update_package_<version>.zip. Run it on
the signed build, next to the installer.
"""

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "Rose"
OUTPUT_DIR = ROOT / "installer"
# Downloaded by the launcher from the release on its own (see update_sequence),
# and left out of the installer too
EXCLUDED_NAMES = {"hashes.game.txt"}


def app_version() -> str:
    """The version in config.py, which must match installer.iss."""
    config = (ROOT / "config.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', config, re.MULTILINE)
    if not match:
        raise SystemExit("APP_VERSION not found in config.py")
    version = match.group(1)
    iss = (ROOT / "installer.iss").read_text(encoding="utf-8")
    iss_match = re.search(r'^#define MyAppVersion "([^"]+)"', iss, re.MULTILINE)
    if not iss_match or iss_match.group(1) != version:
        raise SystemExit(
            f"config.py says {version} but installer.iss says "
            f"{iss_match.group(1) if iss_match else 'nothing'}: bump both"
        )
    return version


def packaged_files():
    for path in sorted(DIST.rglob("*")):
        if not path.is_file() or path.name.lower() in EXCLUDED_NAMES:
            continue
        # A package left in dist/Rose by hand isn't part of the build
        if path.parent == DIST and path.suffix.lower() == ".zip":
            continue
        yield path


def create_update_package() -> Path:
    if not (DIST / "Rose.exe").is_file():
        raise SystemExit(f"{DIST / 'Rose.exe'} not found: build Rose first")

    version = app_version()
    OUTPUT_DIR.mkdir(exist_ok=True)
    target = OUTPUT_DIR / f"update_package_{version}.zip"
    partial = target.with_suffix(".zip.partial")

    count = 0
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in packaged_files():
            archive.write(path, path.relative_to(DIST).as_posix())
            count += 1
    partial.replace(target)

    size_mb = target.stat().st_size / (1024 * 1024)
    print(f"Update package: {target} ({count} files, {size_mb:.1f} MB)")
    return target


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    create_update_package()
