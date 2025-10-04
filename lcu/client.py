#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
League Client API client
"""

import os
import time
import psutil
import requests
from dataclasses import dataclass
from typing import Optional
from utils.logging import get_logger

log = get_logger()


@dataclass
class Lockfile:
    name: str
    pid: int
    port: int
    password: str
    protocol: str


def _find_lockfile(explicit: Optional[str]) -> Optional[str]:
    """Find League Client lockfile"""
    if explicit and os.path.isfile(explicit): 
        return explicit
    
    env = os.environ.get("LCU_LOCKFILE")
    if env and os.path.isfile(env): 
        return env
    
    if os.name == "nt":
        for p in (r"C:\\Riot Games\\League of Legends\\lockfile",
                  r"C:\\Program Files\\Riot Games\\League of Legends\\lockfile",
                  r"C:\\Program Files (x86)\\Riot Games\\League of Legends\\lockfile"):
            if os.path.isfile(p): 
                return p
    else:
        for p in ("/Applications/League of Legends.app/Contents/LoL/lockfile",
                  os.path.expanduser("~/.local/share/League of Legends/lockfile")):
            if os.path.isfile(p): 
                return p
    
    try:
        for proc in psutil.process_iter(attrs=["name", "exe"]):
            nm = (proc.info.get("name") or "").lower()
            if "leagueclient" in nm:
                exe = proc.info.get("exe") or ""
                for d in (os.path.dirname(exe), os.path.dirname(os.path.dirname(exe))):
                    p = os.path.join(d, "lockfile")
                    if os.path.isfile(p): 
                        return p
    except Exception:
        pass
    return None


class LCU:
    """League Client API client"""
    
    def __init__(self, lockfile_path: Optional[str]):
        self.ok = False
        self.port = None
        self.pw = None
        self.base = None
        self.s = None
        self._explicit_lockfile = lockfile_path
        self.lf_path = None
        self.lf_mtime = 0.0
        self._init_from_lockfile()

    def _init_from_lockfile(self):
        """Initialize from lockfile"""
        lf = _find_lockfile(self._explicit_lockfile)
        self.lf_path = lf
        if not lf or not os.path.isfile(lf):
            self._disable("LCU lockfile introuvable")
            return
        
        try:
            name, pid, port, pw, proto = open(lf, "r", encoding="utf-8").read().split(":")[:5]
            self.port = int(port)
            self.pw = pw
            self.base = f"https://127.0.0.1:{self.port}"
            self.s = requests.Session()
            self.s.verify = False
            self.s.auth = ("riot", pw)
            self.s.headers.update({"Content-Type": "application/json"})
            self.ok = True
            try: 
                self.lf_mtime = os.path.getmtime(lf)
            except Exception: 
                self.lf_mtime = time.time()
            log.info(f"LCU prêt (port {self.port})")
        except Exception as e:
            self._disable(f"LCU indisponible: {e}")

    def _disable(self, reason: str):
        """Disable LCU connection"""
        if self.ok: 
            log.debug(f"LCU désactivé: {reason}")
        self.ok = False
        self.base = None
        self.port = None
        self.pw = None
        self.s = requests.Session()
        self.s.verify = False

    def refresh_if_needed(self, force: bool = False):
        """Refresh connection if needed"""
        lf = _find_lockfile(self._explicit_lockfile)
        if not lf or not os.path.isfile(lf):
            self._disable("lockfile absent")
            self.lf_path = None
            self.lf_mtime = 0.0
            return
        
        try: 
            mt = os.path.getmtime(lf)
        except Exception: 
            mt = 0.0
        
        if force or lf != self.lf_path or (mt and mt != self.lf_mtime) or not self.ok:
            old = (self.port, self.pw)
            self.lf_path = lf
            self._init_from_lockfile()
            new = (self.port, self.pw)
            if self.ok and old != new: 
                log.info(f"LCU relu (port={self.port})")

    def get(self, path: str, timeout: float = 1.0):
        """Make GET request to LCU API"""
        if not self.ok:
            self.refresh_if_needed()
            if not self.ok: 
                return None
        
        try:
            r = self.s.get((self.base or "") + path, timeout=timeout)
            if r.status_code in (404, 405): 
                return None
            r.raise_for_status()
            try: 
                return r.json()
            except Exception: 
                return None
        except requests.exceptions.RequestException:
            self.refresh_if_needed(force=True)
            if not self.ok: 
                return None
            try:
                r = self.s.get((self.base or "") + path, timeout=timeout)
                if r.status_code in (404, 405): 
                    return None
                r.raise_for_status()
                try: 
                    return r.json()
                except Exception: 
                    return None
            except requests.exceptions.RequestException:
                return None

    def phase(self) -> Optional[str]:
        """Get current gameflow phase"""
        ph = self.get("/lol-gameflow/v1/gameflow-phase")
        return ph if isinstance(ph, str) else None

    def session(self) -> Optional[dict]:
        """Get current session"""
        return self.get("/lol-champ-select/v1/session")

    def hovered_champion_id(self) -> Optional[int]:
        """Get hovered champion ID"""
        v = self.get("/lol-champ-select/v1/hovered-champion-id")
        try: 
            return int(v) if v is not None else None
        except Exception: 
            return None

    def my_selection(self) -> Optional[dict]:
        """Get my selection"""
        return self.get("/lol-champ-select/v1/session/my-selection") or self.get("/lol-champ-select/v1/selection")

    def unlocked_skins(self) -> Optional[dict]:
        """Get unlocked skins"""
        return self.get("/lol-champions/v1/owned-champions-minimal")

    def owned_skins(self) -> Optional[dict]:
        """Get owned skins"""
        return self.get("/lol-skins/v1/owned-skins")

    def get_region_locale(self) -> Optional[dict]:
        """Get client region and locale information"""
        return self.get("/riotclient/region-locale")

    def get_client_language(self) -> Optional[str]:
        """Get client language from LCU API"""
        locale_info = self.get_region_locale()
        if locale_info and isinstance(locale_info, dict):
            return locale_info.get("locale")
        return None