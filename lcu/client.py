#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
League Client API client
"""

# Standard library imports
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

# Third-party imports
import psutil
import requests

# Local imports
from config import LCU_API_TIMEOUT_S
from utils.logging import get_logger, log_section, log_success

log = get_logger()

SWIFTPLAY_MODES = {"SWIFTPLAY", "BRAWL"}


@dataclass
class Lockfile:
    name: str
    pid: int
    port: int
    password: str
    protocol: str


def _find_lockfile(explicit: Optional[str]) -> Optional[str]:
    """Find League Client lockfile using pathlib"""
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
        
        if not lf:
            self._disable("LCU lockfile not found")
            return
        
        lockfile_path = Path(lf)
        if not lockfile_path.is_file():
            self._disable("LCU lockfile not found")
            return
        
        try:
            # Use context manager for file handling
            with open(lockfile_path, "r", encoding="utf-8") as f:
                content = f.read()
            name, pid, port, pw, proto = content.split(":")[:5]
            self.port = int(port)
            self.pw = pw
            self.base = f"https://127.0.0.1:{self.port}"
            self.s = requests.Session()
            self.s.verify = False
            self.s.auth = ("riot", pw)
            self.s.headers.update({"Content-Type": "application/json"})
            self.ok = True
            try: 
                self.lf_mtime = lockfile_path.stat().st_mtime
            except (OSError, IOError) as e:
                log.debug(f"Failed to get lockfile mtime: {e}")
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
            except (ValueError, requests.exceptions.JSONDecodeError) as e:
                log.debug(f"Failed to decode JSON response: {e}")
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

    @property
    def phase(self) -> Optional[str]:
        """Get current gameflow phase"""
        ph = self.get("/lol-gameflow/v1/gameflow-phase")
        return ph if isinstance(ph, str) else None

    @property
    def session(self) -> Optional[dict]:
        """Get current session"""
        return self.get("/lol-champ-select/v1/session")

    @property
    def hovered_champion_id(self) -> Optional[int]:
        """Get hovered champion ID"""
        v = self.get("/lol-champ-select/v1/hovered-champion-id")
        try: 
            return int(v) if v is not None else None
        except (ValueError, TypeError) as e:
            log.debug(f"Failed to parse hovered champion ID: {e}")
            return None

    @property
    def my_selection(self) -> Optional[dict]:
        """Get my selection"""
        return self.get("/lol-champ-select/v1/session/my-selection") or self.get("/lol-champ-select/v1/selection")

    @property
    def unlocked_skins(self) -> Optional[dict]:
        """Get unlocked skins"""
        return self.get("/lol-champions/v1/owned-champions-minimal")

    def owned_skins(self) -> Optional[List[int]]:
        """
        Get owned skins (returns list of skin IDs)
        
        Note: This is a method (not property) because it's expensive and
        should be called explicitly when needed, not accessed frequently.
        """
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
    
    @property
    def current_summoner(self) -> Optional[dict]:
        """Get current summoner info"""
        return self.get("/lol-summoner/v1/current-summoner")

    @property
    def region_locale(self) -> Optional[dict]:
        """Get client region and locale information"""
        return self.get("/riotclient/region-locale")

    @property
    def client_language(self) -> Optional[str]:
        """Get client language from LCU API"""
        locale_info = self.region_locale
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

    @property
    def game_session(self) -> Optional[dict]:
        """Get current game session with mode and map info"""
        return self.get("/lol-gameflow/v1/session")

    @property
    def game_mode(self) -> Optional[str]:
        """Get current game mode (e.g., 'ARAM', 'CLASSIC')"""
        session = self.game_session
        if session and isinstance(session, dict):
            return session.get("gameData", {}).get("gameMode")
        return None

    @property
    def map_id(self) -> Optional[int]:
        """Get current map ID (12 = Howling Abyss, 11 = Summoner's Rift)"""
        session = self.game_session
        if session and isinstance(session, dict):
            return session.get("gameData", {}).get("mapId")
        return None

    @property
    def is_aram(self) -> bool:
        """Check if currently in ARAM (Howling Abyss)"""
        return self.map_id == 12 or self.game_mode == "ARAM"

    @property
    def is_sr(self) -> bool:
        """Check if currently in Summoner's Rift"""
        return self.map_id == 11 or self.game_mode == "CLASSIC"
    
    @property
    def is_swiftplay(self) -> bool:
        """Check if currently in Swiftplay mode"""
        game_mode = self.game_mode
        return isinstance(game_mode, str) and game_mode.upper() in SWIFTPLAY_MODES
    
    def get_swiftplay_lobby_data(self) -> Optional[dict]:
        """Get Swiftplay lobby data with champion selection"""
        try:
            # Try different endpoints that might contain Swiftplay lobby data
            endpoints = [
                "/lol-lobby/v2/lobby",
                "/lol-lobby/v2/lobby/matchmaking/search-state",
                "/lol-lobby/v1/parties/me"
            ]
            
            for endpoint in endpoints:
                try:
                    data = self.get(endpoint)
                    if data and isinstance(data, dict):
                        # Check if this looks like Swiftplay lobby data
                        if self._is_swiftplay_lobby_data(data):
                            return data
                except Exception as e:
                    log.debug(f"Failed to get Swiftplay data from {endpoint}: {e}")
                    continue
            
            return None
        except Exception as e:
            log.warning(f"Error getting Swiftplay lobby data: {e}")
            return None
    
    def _is_swiftplay_lobby_data(self, data: dict) -> bool:
        """Check if the data looks like Swiftplay lobby data"""
        try:
            # Look for indicators that this is Swiftplay lobby data
            # This might include specific fields or structures
            if "gameMode" in data and isinstance(data.get("gameMode"), str) and data.get("gameMode").upper() in SWIFTPLAY_MODES:
                log.debug("Found Swiftplay-like game mode in lobby data")
                return True
            
            # Check for other Swiftplay-specific indicators
            if "queueId" in data:
                # Swiftplay might have a specific queue ID
                queue_id = data.get("queueId")
                log.debug(f"Found queue ID: {queue_id}")
                if queue_id is not None and any(tag in str(queue_id).lower() for tag in ("swift", "brawl")):
                    log.debug("Queue ID indicates Swiftplay-like mode")
                    return True
            
            # If we're already detected as Swiftplay mode, any lobby data is likely Swiftplay
            if self.is_swiftplay:
                log.debug("Already in Swiftplay mode, treating lobby data as Swiftplay")
                return True
            
            return False
        except Exception as e:
            log.debug(f"Error checking Swiftplay lobby data: {e}")
            return False
    
    def get_swiftplay_champion_selection(self) -> Optional[dict]:
        """Get champion selection data from Swiftplay lobby (single champion - for backward compatibility)"""
        try:
            # Try multiple endpoints to get champion selection
            endpoints_to_try = [
                "/lol-lobby/v2/lobby",
                "/lol-lobby/v2/lobby/matchmaking/search-state",
                "/lol-lobby/v1/parties/me"
            ]
            
            for endpoint in endpoints_to_try:
                try:
                    data = self.get(endpoint)
                    if not data or not isinstance(data, dict):
                        continue
                    
                    # Look for champion selection in different possible locations
                    champion_selection = self._extract_champion_selection_from_data(data)
                    if champion_selection:
                        return champion_selection
                        
                except Exception as e:
                    log.debug(f"Error checking {endpoint} for champion selection: {e}")
                    continue
            
            return None
            
        except Exception as e:
            log.warning(f"Error getting Swiftplay champion selection: {e}")
            return None
    
    def get_swiftplay_dual_champion_selection(self) -> Optional[dict]:
        """Get both champion selections from Swiftplay lobby"""
        try:
            # Try multiple endpoints to get champion selection
            endpoints_to_try = [
                "/lol-lobby/v2/lobby",
                "/lol-lobby/v2/lobby/matchmaking/search-state",
                "/lol-lobby/v1/parties/me"
            ]
            
            for endpoint in endpoints_to_try:
                try:
                    data = self.get(endpoint)
                    if not data or not isinstance(data, dict):
                        continue
                    
                    # Look for both champion selections
                    champion_selections = self._extract_dual_champion_selection_from_data(data)
                    if champion_selections:
                        return champion_selections
                        
                except Exception as e:
                    log.debug(f"Error checking {endpoint} for dual champion selection: {e}")
                    continue
            
            return None
            
        except Exception as e:
            log.warning(f"Error getting Swiftplay dual champion selection: {e}")
            return None
    
    def _extract_champion_selection_from_data(self, data: dict) -> Optional[dict]:
        """Extract champion selection from lobby data"""
        try:
            from utils.utilities import get_champion_id_from_skin_id

            # Helper to build champion selection dict when we have IDs
            def _build_selection(champ_id: int, skin_id: int, slot: Optional[dict] = None) -> Optional[dict]:
                if champ_id <= 0 and skin_id > 0:
                    try:
                        derived_id = get_champion_id_from_skin_id(skin_id)
                        if derived_id:
                            champ_id = derived_id
                    except Exception:
                        pass

                if champ_id <= 0 and skin_id <= 0:
                    return None

                slot = slot or {}
                selection = {
                    "championId": champ_id,
                    "skinId": skin_id,
                    "position": slot.get("positionPreference", ""),
                    "spell1": slot.get("spell1", 0),
                    "spell2": slot.get("spell2", 0)
                }
                log.debug(f"Resolved Swiftplay champion selection: {selection}")
                return selection

            # Method 1: Check localMember in lobby data
            local_member = data.get("localMember") if isinstance(data, dict) else None
            if isinstance(local_member, dict):
                player_slots = local_member.get("playerSlots", []) or []
                if player_slots:
                    slot = player_slots[0] or {}
                    champ_id = int(slot.get("championId") or 0)
                    skin_id = int(slot.get("skinId") or 0)
                    selection = _build_selection(champ_id, skin_id, slot)
                    if selection:
                        return selection

                # Fallback: look for selectedSkinId/primaryChampionId even without playerSlots
                skin_id = int(local_member.get("selectedSkinId") or 0)
                if skin_id <= 0:
                    skin_id = int(local_member.get("primarySkinId") or 0)
                champ_id = int(local_member.get("primaryChampionId") or 0)
                if champ_id <= 0:
                    champ_id = int(local_member.get("secondaryChampionId") or 0)
                selection = _build_selection(champ_id, skin_id, local_member)
                if selection:
                    return selection

            # Method 2: Check members array for local player entry
            members = data.get("members") if isinstance(data, dict) else None
            if isinstance(members, list):
                for member in members:
                    if not isinstance(member, dict):
                        continue
                    if not (member.get("isLeader", False) or member.get("isLocalPlayer", False) or member.get("summonerId") == data.get("localMember", {}).get("summonerId")):
                        continue
                    player_slots = member.get("playerSlots", []) or []
                    if player_slots:
                        slot = player_slots[0] or {}
                        champ_id = int(slot.get("championId") or 0)
                        skin_id = int(slot.get("skinId") or 0)
                        selection = _build_selection(champ_id, skin_id, slot)
                        if selection:
                            return selection

                    skin_id = int(member.get("selectedSkinId") or 0)
                    if skin_id <= 0:
                        skin_id = int(member.get("primarySkinId") or 0)
                    champ_id = int(member.get("primaryChampionId") or 0)
                    if champ_id <= 0:
                        champ_id = int(member.get("secondaryChampionId") or 0)
                    selection = _build_selection(champ_id, skin_id, member)
                    if selection:
                        return selection

            # Method 3: Check gameConfig and fallback on map info (informational only)
            if isinstance(data, dict) and "gameConfig" in data:
                game_config = data.get("gameConfig", {})
                log.debug(f"Game config data: {game_config}")

            return None

        except Exception as e:
            log.debug(f"Error extracting champion selection from data: {e}")
            return None
    
    def _extract_dual_champion_selection_from_data(self, data: dict) -> Optional[dict]:
        """Extract both champion selections from local player data only"""
        try:
            champions = []
            
            # Check localMember for primary and secondary champions
            local_member = data.get("localMember")
            if local_member and isinstance(local_member, dict):
                log.debug("Checking localMember for champion selections...")
                
                # Check for primaryChampionId and secondaryChampionId
                primary_champion_id = local_member.get("primaryChampionId")
                secondary_champion_id = local_member.get("secondaryChampionId")
                
                log.debug(f"Primary champion ID: {primary_champion_id}")
                log.debug(f"Secondary champion ID: {secondary_champion_id}")
                
                # Add primary champion if exists
                if primary_champion_id and primary_champion_id > 0:
                    # Try to get skin ID from playerSlots or use default
                    primary_skin_id = 0
                    primary_position = ""
                    primary_spell1 = 0
                    primary_spell2 = 0
                    
                    player_slots = local_member.get("playerSlots", [])
                    if isinstance(player_slots, list) and len(player_slots) > 0:
                        first_slot = player_slots[0]
                        if isinstance(first_slot, dict):
                            primary_skin_id = first_slot.get("skinId", 0)
                            primary_position = first_slot.get("positionPreference", "")
                            primary_spell1 = first_slot.get("spell1", 0)
                            primary_spell2 = first_slot.get("spell2", 0)
                    
                    champion_data = {
                        "championId": primary_champion_id,
                        "skinId": primary_skin_id,
                        "position": primary_position,
                        "spell1": primary_spell1,
                        "spell2": primary_spell2
                    }
                    champions.append(champion_data)
                    log.info(f"Found PRIMARY champion: ID {primary_champion_id}, Skin {primary_skin_id}, Position {primary_position}")
                
                # Add secondary champion if exists
                if secondary_champion_id and secondary_champion_id > 0:
                    # Try to get skin ID from playerSlots or use default
                    secondary_skin_id = 0
                    secondary_position = ""
                    secondary_spell1 = 0
                    secondary_spell2 = 0
                    
                    player_slots = local_member.get("playerSlots", [])
                    if isinstance(player_slots, list) and len(player_slots) > 1:
                        second_slot = player_slots[1]
                        if isinstance(second_slot, dict):
                            secondary_skin_id = second_slot.get("skinId", 0)
                            secondary_position = second_slot.get("positionPreference", "")
                            secondary_spell1 = second_slot.get("spell1", 0)
                            secondary_spell2 = second_slot.get("spell2", 0)
                    
                    champion_data = {
                        "championId": secondary_champion_id,
                        "skinId": secondary_skin_id,
                        "position": secondary_position,
                        "spell1": secondary_spell1,
                        "spell2": secondary_spell2
                    }
                    champions.append(champion_data)
                    log.info(f"Found SECONDARY champion: ID {secondary_champion_id}, Skin {secondary_skin_id}, Position {secondary_position}")
                
                # Fallback: Check playerSlots if primary/secondary not found
                if not champions:
                    player_slots = local_member.get("playerSlots", [])
                    if isinstance(player_slots, list):
                        log.debug(f"Fallback: Checking {len(player_slots)} player slots in localMember")
                        for i, slot in enumerate(player_slots):
                            if isinstance(slot, dict):
                                champion_id = slot.get("championId")
                                skin_id = slot.get("skinId")
                                position = slot.get("positionPreference", "")
                                spell1 = slot.get("spell1", 0)
                                spell2 = slot.get("spell2", 0)
                                
                                log.debug(f"Player slot {i}: championId={champion_id}, skinId={skin_id}, position={position}")
                                
                                if champion_id and champion_id > 0:
                                    champion_data = {
                                        "championId": champion_id,
                                        "skinId": skin_id or 0,
                                        "position": position,
                                        "spell1": spell1,
                                        "spell2": spell2
                                    }
                                    champions.append(champion_data)
                                    log.info(f"Found champion in slot {i}: ID {champion_id}, Skin {skin_id}, Position {position}")
            else:
                log.debug("No localMember found in lobby data")
            
            if champions:
                log.info(f"Extracted {len(champions)} local champions from Swiftplay lobby data")
                for i, champ in enumerate(champions):
                    log.info(f"  Champion {i+1}: ID {champ['championId']}, Skin {champ['skinId']}, Position {champ['position']}")
                
                return {
                    "champions": champions,
                    "champion_1": champions[0] if len(champions) > 0 else None,
                    "champion_2": champions[1] if len(champions) > 1 else None
                }
            
            log.warning("No local champions found in lobby data")
            return None
            
        except Exception as e:
            log.debug(f"Error extracting dual champion selection from data: {e}")
            return None
    
    def get_champion_name_by_id(self, champion_id: int) -> Optional[str]:
        """Get champion name by champion ID"""
        try:
            # Try to get champion data from LCU
            champion_data = self.get(f"/lol-game-data/assets/v1/champions/{champion_id}.json")
            if champion_data and isinstance(champion_data, dict):
                return champion_data.get("name")
            
            # Fallback: try inventory endpoint
            inventory_data = self.get(f"/lol-champions/v1/inventories/scouting/champions/{champion_id}")
            if inventory_data and isinstance(inventory_data, dict):
                return inventory_data.get("name")
            
            return None
            
        except Exception as e:
            log.debug(f"Error getting champion name for ID {champion_id}: {e}")
            return None
