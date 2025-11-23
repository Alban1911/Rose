#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU Swiftplay Support
Handles Swiftplay-specific lobby data and champion selection
"""

from typing import Optional

from utils.core.logging import get_logger

from ..core.lockfile import SWIFTPLAY_MODES

log = get_logger()


class LCUSwiftplay:
    """Handles Swiftplay-specific operations"""
    
    def __init__(self, api, game_mode):
        """Initialize Swiftplay handler
        
        Args:
            api: LCUAPI instance
            game_mode: LCUGameMode instance
        """
        self.api = api
        self.game_mode = game_mode
    
    def get_swiftplay_lobby_data(self) -> Optional[dict]:
        """Get Swiftplay lobby data with champion selection
        
        Returns:
            Lobby data dict or None if not found
        """
        try:
            # Try different endpoints that might contain Swiftplay lobby data
            endpoints = [
                "/lol-lobby/v2/lobby",
                "/lol-lobby/v2/lobby/matchmaking/search-state",
                "/lol-lobby/v1/parties/me"
            ]
            
            for endpoint in endpoints:
                try:
                    data = self.api.get(endpoint)
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
            if "gameMode" in data and isinstance(data.get("gameMode"), str) and data.get("gameMode").upper() in SWIFTPLAY_MODES:
                log.debug("Found Swiftplay-like game mode in lobby data")
                return True
            
            # Check for other Swiftplay-specific indicators
            if "queueId" in data:
                queue_id = data.get("queueId")
                log.debug(f"Found queue ID: {queue_id}")
                if queue_id is not None and any(tag in str(queue_id).lower() for tag in ("swift", "brawl")):
                    log.debug("Queue ID indicates Swiftplay-like mode")
                    return True
            
            # If we're already detected as Swiftplay mode, any lobby data is likely Swiftplay
            if self.game_mode.is_swiftplay:
                log.debug("Already in Swiftplay mode, treating lobby data as Swiftplay")
                return True
            
            return False
        except Exception as e:
            log.debug(f"Error checking Swiftplay lobby data: {e}")
            return False
    
    def get_swiftplay_champion_selection(self) -> Optional[dict]:
        """Get champion selection data from Swiftplay lobby (single champion - for backward compatibility)"""
        try:
            endpoints_to_try = [
                "/lol-lobby/v2/lobby",
                "/lol-lobby/v2/lobby/matchmaking/search-state",
                "/lol-lobby/v1/parties/me"
            ]
            
            for endpoint in endpoints_to_try:
                try:
                    data = self.api.get(endpoint)
                    if not data or not isinstance(data, dict):
                        continue
                    
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
            endpoints_to_try = [
                "/lol-lobby/v2/lobby",
                "/lol-lobby/v2/lobby/matchmaking/search-state",
                "/lol-lobby/v1/parties/me"
            ]
            
            for endpoint in endpoints_to_try:
                try:
                    data = self.api.get(endpoint)
                    if not data or not isinstance(data, dict):
                        continue
                    
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
            from utils.core.utilities import get_champion_id_from_skin_id

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

