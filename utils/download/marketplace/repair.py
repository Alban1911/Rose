"""Repair outdated mods with LTK Manager's repair engine before import

rose-repair.exe is a small headless wrapper around ltk-manager-core (GPL-3,
github.com/LeagueToolkit/ltk-manager). It fixes what game patches break in a
mod (bin fields, audio banks, textures...), the same "Repair" LTK Manager
offers. Missing tool or a failed repair never blocks an import.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

REPAIR_EXE = "rose-repair.exe"
TIMEOUT_SECONDS = 600


@dataclass
class RepairResult:
    status: str  # "repaired" | "unchanged" | "failed" | "unavailable"
    path: Path
    applied: int = 0
    error: str = ""


def find_repair_tool() -> Optional[Path]:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent / "_internal"))
    else:
        base = Path(__file__).resolve().parents[3]
    tool = base / "injection" / "tools" / REPAIR_EXE
    return tool if tool.is_file() else None


def league_root() -> Optional[str]:
    """LTK wants the League install root; Rose stores the Game folder"""
    try:
        from injection.config.config_manager import ConfigManager

        path = ConfigManager().load_league_path()
    except Exception:  # noqa: BLE001
        return None
    if not path:
        return None
    game = Path(path)
    return str(game.parent if game.name.lower() == "game" else game)


def repair_archive(archive: Path) -> RepairResult:
    """Repair *archive*; returns the file to import (the original when nothing changed)"""
    tool = find_repair_tool()
    if tool is None:
        return RepairResult("unavailable", archive)

    # Same file name in a sibling folder, so the imported mod keeps its name
    output = archive.parent / "repaired" / archive.name
    output.parent.mkdir(exist_ok=True)
    command = [str(tool), str(archive), str(output)]
    root = league_root()
    if root:
        command += ["--league", root]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        lines = [line for line in completed.stdout.splitlines() if line.strip().startswith("{")]
        report = json.loads(lines[-1]) if lines else {}
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        log.warning("[Repair] %s could not run: %s", tool.name, exc)
        return RepairResult("failed", archive, error=str(exc))

    status = report.get("status", "failed")
    if status == "repaired" and output.is_file():
        suffix = report.get("extension") or archive.suffix.lstrip(".")
        repaired = output.with_suffix(f".{suffix}")
        if repaired != output:
            output.replace(repaired)
        log.info("[Repair] %s: %s fixes applied", archive.name, report.get("applied"))
        return RepairResult("repaired", repaired, applied=int(report.get("applied") or 0))
    if status == "unchanged":
        return RepairResult("unchanged", archive)
    error = report.get("error") or completed.stderr.strip()[-300:]
    log.warning("[Repair] %s not repaired: %s", archive.name, error)
    return RepairResult("failed", archive, error=error)
