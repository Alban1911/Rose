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
from utils.logging import get_logger, log_section, log_success
from constants import LCU_API_TIMEOUT_S

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
            self._disable("LCU lockfile not found")
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
            log_section(log, "LCU Connected", "🔗", {"Port": self.port, "Status": "Ready"})
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
        self.s = requests.Session()
        self.s.verify = False

    def refresh_if_needed(self, force: bool = False):
        """Refresh connection if needed"""
        lf = _find_lockfile(self._explicit_lockfile)
        if not lf or not os.path.isfile(lf):
            self._disable("lockfile not found")
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
                log_success(log, f"LCU reloaded (port={self.port})", "🔄")

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

    def owned_skins(self) -> Optional[list]:
        """Get owned skins (returns list of skin IDs)"""
        # This endpoint returns all skins the player owns
        data = self.get("/lol-inventory/v2/inventory/CHAMPION_SKIN")
        if isinstance(data, list):
            # Extract skin IDs from the inventory items
            skin_ids = []
            for item in data:
                if isinstance(item, dict):
                    item_id = item.get("itemId")
                    if item_id is not None:
                        try:
                            skin_ids.append(int(item_id))
                        except (ValueError, TypeError):
                            pass
            return skin_ids
        return None
    
    def get_current_summoner(self) -> Optional[dict]:
        """Get current summoner info"""
        return self.get("/lol-summoner/v1/current-summoner")

    def get_region_locale(self) -> Optional[dict]:
        """Get client region and locale information"""
        return self.get("/riotclient/region-locale")

    def get_client_language(self) -> Optional[str]:
        """Get client language from LCU API"""
        locale_info = self.get_region_locale()
        if locale_info and isinstance(locale_info, dict):
            return locale_info.get("locale")
        return None
    
    def set_selected_skin(self, action_id: int, skin_id: int) -> bool:
        """Set the selected skin for a champion select action"""
        if not self.ok:
            self.refresh_if_needed()
            if not self.ok:
                log.warning("LCU set_selected_skin failed: LCU not connected")
                return False
        
        try:
            response = self.s.patch(
                f"{self.base}/lol-champ-select/v1/session/actions/{action_id}",
                json={"selectedSkinId": skin_id},
                timeout=LCU_API_TIMEOUT_S
            )
            if response.status_code in (200, 204):
                return True
            else:
                log.warning(f"LCU set_selected_skin failed: status={response.status_code}, response={response.text[:200]}")
                return False
        except Exception as e:
            log.warning(f"LCU set_selected_skin exception: {e}")
            return False
    
    def set_my_selection_skin(self, skin_id: int) -> bool:
        """Set the selected skin using my-selection endpoint (works after champion lock)"""
        if not self.ok:
            self.refresh_if_needed()
            if not self.ok:
                log.warning("LCU set_my_selection_skin failed: LCU not connected")
                return False
        
        try:
            response = self.s.patch(
                f"{self.base}/lol-champ-select/v1/session/my-selection",
                json={"selectedSkinId": skin_id},
                timeout=LCU_API_TIMEOUT_S
            )
            if response.status_code in (200, 204):
                return True
            else:
                log.warning(f"LCU set_my_selection_skin failed: status={response.status_code}, response={response.text[:200]}")
                return False
        except Exception as e:
            log.warning(f"LCU set_my_selection_skin exception: {e}")
            return False