#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tools Manager
Handles CSLOL tools detection and validation
"""

from pathlib import Path
from typing import Dict, Optional

from utils.core.logging import get_logger

log = get_logger()

from .patcher import LTK_PATCHER_DLL, LTK_PATCHER_HOST, resolve_ltk_dll, resolve_ltk_host


class ToolsManager:
    """Manages CSLOL tools detection and validation"""
    
    def __init__(self, tools_dir: Path):
        self.tools_dir = tools_dir
    
    def check_tools_available(self) -> bool:
        """Check if the runtime injection tool is present."""
        # cslol-dll.dll is Rose's stand-in; mod-tools.exe will not start without it
        missing_tools = [
            tool for tool in ("mod-tools.exe", "cslol-dll.dll")
            if not (self.tools_dir / tool).exists()
        ]

        # The patcher pair is matched by content too, so a copy a download
        # manager renamed is still found.
        if resolve_ltk_host(self.tools_dir) is None:
            missing_tools.append(LTK_PATCHER_HOST)
        if resolve_ltk_dll(self.tools_dir) is None:
            missing_tools.append(LTK_PATCHER_DLL)
        
        if missing_tools:
            log.warning(f"Missing runtime injection dependencies: {missing_tools}")
            log.warning("Please place the missing files in injection/tools/")
            return False
        
        return True
    
    def detect_tools(self) -> Dict[str, Path]:
        """Detect runtime injection tools."""
        tools = {
            "modtools": self.tools_dir / "mod-tools.exe",
        }
        for name, exe in tools.items():
            if not exe.exists():
                log.error(f"[INJECTOR] Missing tool: {exe}")
        return tools

    def detect_ltk_patcher(self) -> Optional[Path]:
        """Return the LTK patcher host if it is installed next to its hook DLL.

        The LTK Manager patcher (ltk_patcher_host.exe + ltk_patcher_dll.dll)
        serves the overlay built by mkoverlay. Users provide their own copy,
        under whatever name their download manager left it.
        """
        host = resolve_ltk_host(self.tools_dir)
        if host is not None and resolve_ltk_dll(self.tools_dir) is not None:
            return host
        return None

