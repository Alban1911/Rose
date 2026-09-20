#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lockfile Detection and Parsing
Handles finding and parsing League Client lockfile
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import psutil

from utils.core.logging import get_logger

log = get_logger()

SWIFTPLAY_MODES = {"SWIFTPLAY", "BRAWL"}
SWIFTPLAY_QUEUE_ID = 480


@dataclass
class Lockfile:
    """Parsed lockfile data"""
    name: str
    pid: int
    port: int
    password: str
    protocol: str


def find_lockfile(explicit: Optional[str] = None) -> Optional[str]:
    """Find League Client lockfile using pathlib
    
    Args:
        explicit: Optional explicit path to lockfile
        
    Returns:
        Path to lockfile if found, None otherwise
    """
    # Check explicit path
    if explicit:
        explicit_path = Path(explicit)
        if explicit_path.is_file():
            return str(explicit_path)
    
    # Check environment variable
    env = os.environ.get("LCU_LOCKFILE")
    if env:
        env_path = Path(env)
        if env_path.is_file():
            return str(env_path)
    
    # Check common installation paths
    if os.name == "nt":
        common_paths = [
            Path("C:/Riot Games/League of Legends/lockfile"),
            Path("C:/Program Files/Riot Games/League of Legends/lockfile"),
            Path("C:/Program Files (x86)/Riot Games/League of Legends/lockfile"),
        ]
    else:
        common_paths = [
            Path("/Applications/League of Legends.app/Contents/LoL/lockfile"),
            Path.home() / ".local/share/League of Legends/lockfile",
        ]
    
    for p in common_paths:
        if p.is_file():
            return str(p)
    
    # Try to find via process scanning
    try:
        for proc in psutil.process_iter(attrs=["name", "exe"]):
            nm = (proc.info.get("name") or "").lower()
            if "leagueclient" in nm:
                exe = proc.info.get("exe") or ""
                if exe:
                    exe_path = Path(exe)
                    # Check in same directory and parent directory
                    for directory in [exe_path.parent, exe_path.parent.parent]:
                        lockfile = directory / "lockfile"
                        if lockfile.is_file():
                            return str(lockfile)
    except (psutil.Error, OSError, AttributeError) as e:
        log.debug(f"Failed to find lockfile via process iteration: {e}")
    
    return None


def parse_lockfile(lockfile_path: str) -> Optional[Lockfile]:
    """Parse lockfile and return Lockfile dataclass
    
    Args:
        lockfile_path: Path to lockfile
        
    Returns:
        Parsed Lockfile or None if failed
    """
    path = Path(lockfile_path)
    if not path.is_file():
        return None
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            return None
        name, pid, port, pw, proto = content.split(":")[:5]
        return Lockfile(
            name=name,
            pid=int(pid),
            port=int(port),
            password=pw,
            protocol=proto
        )
    except Exception as e:
        log.debug(f"Failed to parse lockfile: {e}")
        return None


def find_process_credentials() -> Optional[Lockfile]:
    """Read the local LCU endpoint when a regional client leaves lockfile empty.

    Only the main client / UX processes are eligible. Never log their command
    lines or authentication tokens and never persist these credentials.
    """
    try:
        for proc in psutil.process_iter(attrs=["name"]):
            try:
                name = proc.info.get("name") or ""
                if name.lower() not in {"leagueclientux.exe", "leagueclient.exe"}:
                    continue
                args = proc.cmdline()
                options = {}
                for index, arg in enumerate(args):
                    key, separator, value = arg.partition("=")
                    if key not in {"--app-port", "--remoting-auth-token"}:
                        continue
                    if not separator and index + 1 < len(args):
                        value = args[index + 1]
                    options[key] = value.strip('"')
                port_text = options.get("--app-port", "")
                password = options.get("--remoting-auth-token", "")
                if not port_text.isdecimal() or not password:
                    continue
                port = int(port_text)
                if 0 < port < 65536:
                    return Lockfile(name, proc.pid, port, password, "https")
            except (psutil.Error, OSError, ValueError):
                continue
    except (psutil.Error, OSError):
        pass
    return None

