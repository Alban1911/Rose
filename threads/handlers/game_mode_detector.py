#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Game Mode Detector
Detects game mode and map information from LCU
"""

import logging
import traceback
from lcu import LCU
from state import SharedState
from utils.core.logging import get_logger

log = get_logger()

SWIFTPLAY_MODES = {"SWIFTPLAY", "BRAWL"}


class GameModeDetector:
    """Detects game mode and map information"""
    
    def __init__(self, lcu: LCU, state: SharedState):
        """Initialize game mode detector
        
        Args:
            lcu: LCU client instance
            state: Shared application state
        """
        self.lcu = lcu
        self.state = state
    
    def detect_game_mode(self):
        """Detect game mode once when entering champion select"""
        old_swiftplay_mode = self.state.is_swiftplay_mode
        new_swiftplay_mode = False  # Compute locally first, assign once at the end

        try:
            if not self.lcu.ok:
                log.info("[WS] LCU not connected - cannot detect game mode, defaulting to non-swiftplay")
                if old_swiftplay_mode:
                    log.info(f"[WS] Swiftplay mode flag reset: {old_swiftplay_mode} → False")
                self.state.is_swiftplay_mode = False
                return

            # Get game session data
            session = self.lcu.get("/lol-gameflow/v1/session")
            if not session:
                log.info("[WS] No game session data available, defaulting to non-swiftplay")
                if old_swiftplay_mode:
                    log.info(f"[WS] Swiftplay mode flag reset: {old_swiftplay_mode} → False")
                self.state.is_swiftplay_mode = False
                return

            # Extract game mode and map ID
            game_mode = None
            map_id = None
            queue_id = None

            # Try multiple locations for queue ID
            if "gameData" in session:
                game_data = session.get("gameData", {})
                if "queue" in game_data:
                    queue = game_data.get("queue", {})
                    game_mode = queue.get("gameMode")
                    map_id = queue.get("mapId")
                    queue_id = queue.get("queueId")

            # Second try: session.queueId
            if queue_id is None:
                queue_id = session.get("queueId")

            # Third try: Check champ select session
            if queue_id is None:
                champ_session = self.lcu.get("/lol-champ-select/v1/session")
                if champ_session and isinstance(champ_session, dict):
                    queue_id = champ_session.get("queueId")

            # Store in shared state
            self.state.current_game_mode = game_mode
            self.state.current_map_id = map_id
            self.state.current_queue_id = queue_id

            # Compute is_swiftplay_mode without intermediate False visible to other threads
            if isinstance(game_mode, str) and game_mode.upper() in SWIFTPLAY_MODES:
                new_swiftplay_mode = True

            # Single atomic-style assignment
            self.state.is_swiftplay_mode = new_swiftplay_mode

            if old_swiftplay_mode != new_swiftplay_mode:
                log.info(f"[WS] Swiftplay mode flag updated: {old_swiftplay_mode} → {new_swiftplay_mode}")

            # Log queue ID
            log.info(f"[WS] Queue ID: {queue_id}")

            # Log detection result
            if map_id == 12 or game_mode == "ARAM":
                log.info("[WS] ARAM mode detected - chroma panel will use ARAM background")
            elif map_id == 11 or game_mode == "CLASSIC":
                log.info("[WS] Summoner's Rift mode detected - chroma panel will use SR background")
            elif new_swiftplay_mode:
                log.info(f"[WS] {game_mode} mode detected - will trigger early skin detection in lobby")
                log.info("[WS] Swiftplay-like mode: Champion selection and skin detection will happen in lobby phase")
            else:
                log.info(f"[WS] Unknown game mode ({game_mode}, Map ID: {map_id}) - defaulting to SR background")

        except Exception as e:
            log.warning(f"[WS] Error detecting game mode: {e}")
            log.warning(f"[WS] Traceback: {traceback.format_exc()}")

