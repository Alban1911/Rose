#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU Game Mode Detection
Handles game mode and map detection
"""

from typing import Optional

from ..core.lockfile import SWIFTPLAY_MODES


class LCUGameMode:
    """Handles game mode detection"""
    
    def __init__(self, properties):
        """Initialize game mode handler
        
        Args:
            properties: LCUProperties instance
        """
        self.properties = properties
    
    @property
    def game_mode(self) -> Optional[str]:
        """Get current game mode (e.g., 'ARAM', 'CLASSIC')"""
        session = self.properties.game_session
        if session and isinstance(session, dict):
            return session.get("gameData", {}).get("gameMode")
        return None
    
    @property
    def map_id(self) -> Optional[int]:
        """Get current map ID (12 = Howling Abyss, 11 = Summoner's Rift)"""
        session = self.properties.game_session
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

