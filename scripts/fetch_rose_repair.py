#!/usr/bin/env python3
"""
Download rose-repair.exe into injection/tools before a build

rose-repair is LTK Manager's mod repair engine (ltk-manager-core, GPL-3.0)
behind a small headless CLI. Its source and CI builds live at
https://github.com/kebaps123/ltk-manager/tree/rose-repair/crates/rose-repair
The Marketplace works without it; downloaded mods are just not repaired.
"""

import sys
from pathlib import Path

VERSION = "rose-repair-v0.1.0"
URL = f"https://github.com/kebaps123/ltk-manager/releases/download/{VERSION}/rose-repair.exe"
TARGET = Path(__file__).resolve().parent.parent / "injection" / "tools" / "rose-repair.exe"


def fetch_rose_repair(force: bool = False) -> bool:
    if TARGET.is_file() and not force:
        print(f"[OK] rose-repair.exe already present: {TARGET}")
        return True
    try:
        import requests

        response = requests.get(URL, timeout=120)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"[WARNING] Could not download rose-repair.exe ({exc}); Marketplace repair stays off")
        return False
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(response.content)
    print(f"[OK] rose-repair.exe downloaded ({len(response.content) / 1024 / 1024:.1f} MB)")
    return True


if __name__ == "__main__":
    fetch_rose_repair(force="--force" in sys.argv)
