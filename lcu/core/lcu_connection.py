#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU Connection Management
Handles connection initialization, refresh, and lifecycle
"""

import time
from pathlib import Path
from typing import Optional

import requests

from utils.core.logging import get_logger, log_section, log_success

from .lockfile import find_lockfile, parse_lockfile

log = get_logger()


class LCUConnection:
    """Manages LCU connection lifecycle"""
    
    def __init__(self, lockfile_path: Optional[str] = None):
        """Initialize LCU connection
        
        Args:
            lockfile_path: Optional explicit path to lockfile
        """
        self.ok = False
        self.port = None
        self.pw = None
        self.base = None
        self.session = None
        self._explicit_lockfile = lockfile_path
        self.lf_path = None
        self.lf_mtime = 0.0
        self._init_from_lockfile()
    
    def _init_from_lockfile(self):
        """Initialize from lockfile"""
        lf = find_lockfile(self._explicit_lockfile)
        self.lf_path = lf
        
        if not lf:
            self._disable("LCU lockfile not found")
            return
        
        lockfile_path = Path(lf)
        if not lockfile_path.is_file():
            self._disable("LCU lockfile not found")
            return
        
        try:
            # Parse lockfile
            lockfile_data = parse_lockfile(lf)
            if not lockfile_data:
                self._disable("LCU lockfile parsing failed")
                return
            
            self.port = lockfile_data.port
            self.pw = lockfile_data.password
            self.base = f"https://127.0.0.1:{self.port}"
            self.session = requests.Session()
            self.session.verify = False
            self.session.auth = ("riot", self.pw)
            self.session.headers.update({"Content-Type": "application/json"})
            self.ok = True
            try: 
                self.lf_mtime = lockfile_path.stat().st_mtime
            except (OSError, IOError) as e:
                log.debug(f"Failed to get lockfile mtime: {e}")
                self.lf_mtime = time.time()
            log_section(log, "LCU Connected", "", {"Port": self.port, "Status": "Ready"})
        except Exception as e:
            self._disable(f"LCU unavailable: {e}")
    
    def _disable(self, reason: str):
        """Disable LCU connection"""
        if self.ok: 
            log.debug(f"LCU disabled: {reason}")
        self.ok = False
        self.base = None
        self.port = None
        self.pw = None
        self.session = requests.Session()
        self.session.verify = False
    
    def refresh_if_needed(self, force: bool = False):
        """Refresh connection if needed"""
        lf = find_lockfile(self._explicit_lockfile)
        
        if not lf:
            self._disable("lockfile not found")
            self.lf_path = None
            self.lf_mtime = 0.0
            return
        
        lockfile_path = Path(lf)
        if not lockfile_path.is_file():
            self._disable("lockfile not found")
            self.lf_path = None
            self.lf_mtime = 0.0
            return
        
        try: 
            mt = lockfile_path.stat().st_mtime
        except (OSError, IOError) as e:
            log.debug(f"Failed to get lockfile mtime during refresh: {e}")
            mt = 0.0
        
        if force or lf != self.lf_path or (mt and mt != self.lf_mtime) or not self.ok:
            old = (self.port, self.pw)
            self.lf_path = lf
            self._init_from_lockfile()
            new = (self.port, self.pw)
            if self.ok and old != new: 
                log_success(log, f"LCU reloaded (port={self.port})", "")

