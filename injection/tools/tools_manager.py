#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tools Manager
Detects the injection runtime Rose ships (the LTF bridge, built from
native/ltf/) and the LTK Manager install it drives.
"""

from pathlib import Path
from typing import Dict, Optional

from utils.core.logging import get_logger

log = get_logger()

# Built from native/ltf/ by scripts/build_ltf.py and shipped with Rose
LTF_LAUNCHER = "ltk_launcher.exe"
LTF_BRIDGE_DLL = "LeagueToolFlop.dll"

# Where LTK Manager installs itself unless Rose is told otherwise
LTK_MANAGER_DEFAULT_DIR = "LTK Manager"
LTK_MANAGER_EXECUTABLES = ("ltk-manager.exe", "LTK Manager.exe")


def ltk_manager_install_dirs() -> list[Path]:
    """The directories LTK Manager installs itself to, most likely first."""
    import os

    dirs: list[Path] = []
    for variable in ("ProgramW6432", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if not base:
            continue
        candidate = Path(base) / LTK_MANAGER_DEFAULT_DIR
        if candidate not in dirs:
            dirs.append(candidate)
    return dirs


class ToolsManager:
    """Manages injection runtime detection and validation"""

    def __init__(self, tools_dir: Path):
        self.tools_dir = tools_dir

    def check_tools_available(self) -> bool:
        """Check if the injection runtime Rose ships is present."""
        if self.detect_ltf_launcher() is None:
            log.warning(f"Missing injection runtime in {self.tools_dir}: {LTF_LAUNCHER} + {LTF_BRIDGE_DLL}")
            log.warning("Reinstall Rose, or allow its files through your antivirus.")
            return False
        return True

    def detect_tools(self) -> Dict[str, Path]:
        """Detect runtime injection tools."""
        tools: Dict[str, Path] = {"ltf_launcher": self.tools_dir / LTF_LAUNCHER}
        for name, exe in tools.items():
            if not exe.exists():
                log.error(f"[INJECTOR] Missing tool: {exe}")
        return tools

    def detect_ltf_launcher(self) -> Optional[Path]:
        """The LTF launcher, if it and its bridge DLL are both in the tools folder.

        The launcher refuses to start without LeagueToolFlop.dll next to it,
        so both files are checked together.
        """
        launcher = self.tools_dir / LTF_LAUNCHER
        if launcher.exists() and (self.tools_dir / LTF_BRIDGE_DLL).exists():
            return launcher
        return None

    def detect_ltk_manager(self) -> Optional[Path]:
        """The ltk-manager.exe the LTF launcher should start.

        Order: the config's ltkManagerPath, a running LTK Manager, the known
        install locations. Returns None when LTK Manager is not installed.
        """
        configured = self._configured_ltk_manager()
        if configured is not None:
            return configured

        running = self._running_ltk_manager()
        if running is not None:
            return running

        for directory in ltk_manager_install_dirs():
            for name in LTK_MANAGER_EXECUTABLES:
                candidate = directory / name
                if candidate.exists():
                    log.info(f"[INJECT] LTK Manager found at {candidate}")
                    return candidate
        return None

    @staticmethod
    def _configured_ltk_manager() -> Optional[Path]:
        """The LTK Manager path from config.ini, when it points at a real file."""
        from config import get_config_option

        configured = (get_config_option("General", "ltkManagerPath") or "").strip().strip('"')
        if not configured:
            return None
        candidate = Path(configured)
        if candidate.is_file():
            log.info(f"[INJECT] LTK Manager taken from config.ini: {candidate}")
            return candidate
        log.warning(f"[INJECT] ltkManagerPath in config.ini does not exist: {configured}")

    @staticmethod
    def _running_ltk_manager() -> Optional[Path]:
        """The executable of a running LTK Manager, if there is one."""
        try:
            import psutil
        except ImportError:
            return None
        for name in LTK_MANAGER_EXECUTABLES:
            try:
                for proc in psutil.process_iter(["name"]):
                    if (proc.info.get("name") or "").lower() == name.lower():
                        return Path(proc.exe())
            except (psutil.Error, OSError):
                continue
        return None
