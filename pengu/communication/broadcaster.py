#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Message Broadcaster
Handles broadcasting messages to WebSocket clients
"""

import asyncio
import json
import logging
import time
from typing import Optional

from utils.core.utilities import get_champion_id_from_skin_id

log = logging.getLogger(__name__)

# Special skin IDs that have chromas
SPECIAL_BASE_SKIN_IDS = {
    99007,  # Elementalist Lux
    145070,  # Risen Legend Kai'Sa
    103085,  # Risen Legend Ahri
}
SPECIAL_CHROMA_SKIN_IDS = {
    145071,  # Immortalized Legend Kai'Sa
    100001,  # Kai'Sa HOL chroma
    103086,  # Immortalized Legend Ahri
    103087,  # Form 2 Ahri
    88888,  # Ahri HOL chroma
}


class Broadcaster:
    """Broadcasts messages to WebSocket clients"""
    
    def __init__(self, websocket_server, shared_state, skin_mapping, skin_scraper=None):
        """Initialize broadcaster
        
        Args:
            websocket_server: WebSocket server instance
            shared_state: Shared application state
            skin_scraper: LCU skin scraper instance
        """
        self.websocket_server = websocket_server
        self.shared_state = shared_state
        self.skin_scraper = skin_scraper
        self.skin_mapping = skin_mapping;
    
    def broadcast_skin_state(self, skin_name: str, skin_id: Optional[int]) -> None:
        """Broadcast skin state to clients"""
        if not self.websocket_server.loop or not self.websocket_server.connections:
            return
        
        champion_id = (
            get_champion_id_from_skin_id(skin_id)
            if skin_id is not None
            else None
        )
        has_chromas = self._skin_has_chromas(skin_id)
        payload = {
            "type": "skin-state",
            "skinName": skin_name,
            "skinId": skin_id,
            "championId": champion_id,
            "hasChromas": has_chromas,
        }
        log.info(
            "[SkinMonitor] Skin state → name='%s' id=%s champion=%s hasChromas=%s",
            skin_name,
            skin_id,
            champion_id,
            has_chromas,
        )
        self._send_message(json.dumps(payload))
    
    def broadcast_chroma_state(self) -> None:
        """Broadcast current chroma selection state to JavaScript"""
        if not self.websocket_server.loop or not self.websocket_server.connections:
            return
        
        # Get chroma state from ChromaPanelManager
        from ui.chroma.panel import get_chroma_panel
        panel = get_chroma_panel(state=self.shared_state)
        
        if panel:
            with panel.lock:
                selected_chroma_id = panel.current_selected_chroma_id
                chroma_color = panel.current_chroma_color
                chroma_colors = panel.current_chroma_colors
                current_skin_id = panel.current_skin_id
        else:
            selected_chroma_id = self.shared_state.selected_chroma_id
            chroma_color = None
            chroma_colors = None
            current_skin_id = None
        
        payload = {
            "type": "chroma-state",
            "selectedChromaId": selected_chroma_id,
            "chromaColor": chroma_color,
            "chromaColors": chroma_colors,
            "currentSkinId": current_skin_id,
            "timestamp": int(time.time() * 1000),
        }
        
        log.debug(
            "[SkinMonitor] Broadcasting chroma state → selectedChromaId=%s chromaColor=%s",
            selected_chroma_id,
            chroma_color,
        )
        
        self._send_message(json.dumps(payload))
    
    def broadcast_historic_state(self) -> None:
        """Broadcast current historic mode state to JavaScript"""
        if not self.websocket_server.loop or not self.websocket_server.connections:
            return
        
        historic_mode_active = getattr(self.shared_state, 'historic_mode_active', False)
        historic_skin_id = getattr(self.shared_state, 'historic_skin_id', None)
        skin_name = self.skin_mapping.find_skin_name_by_skin_id(historic_skin_id)
        payload = {
            "type": "historic-state",
            "active": historic_mode_active,
            "historicSkinId": historic_skin_id,
            "historicSkinName": skin_name,
            "timestamp": int(time.time() * 1000),
        }
        
        log.debug(
            "[SkinMonitor] Broadcasting historic state → active=%s historicSkinId=%s",
            historic_mode_active,
            historic_skin_id,
        )
        
        self._send_message(json.dumps(payload))
    
    def broadcast_phase_change(self, phase: str) -> None:
        """Broadcast phase change to JavaScript plugins"""
        if not self.websocket_server.loop or not self.websocket_server.connections:
            return
        
        game_mode = getattr(self.shared_state, "current_game_mode", None)
        map_id = getattr(self.shared_state, "current_map_id", None)
        queue_id = getattr(self.shared_state, "current_queue_id", None)
        
        payload = {
            "type": "phase-change",
            "phase": phase,
            "gameMode": game_mode,
            "mapId": map_id,
            "queueId": queue_id,
            "timestamp": int(time.time() * 1000),
        }
        
        log.debug(
            "[SkinMonitor] Broadcasting phase change → phase=%s, gameMode=%s, mapId=%s, queueId=%s",
            phase,
            game_mode,
            map_id,
            queue_id,
        )
        
        self._send_message(json.dumps(payload))
    
    def broadcast_champion_locked(self, locked: bool) -> None:
        """Broadcast champion lock state to JavaScript plugins"""
        if not self.websocket_server.loop or not self.websocket_server.connections:
            return
        
        payload = {
            "type": "champion-locked",
            "locked": locked,
            "timestamp": int(time.time() * 1000),
        }
        
        log.debug(
            "[SkinMonitor] Broadcasting champion lock state → locked=%s",
            locked,
        )
        
        self._send_message(json.dumps(payload))
    
    def broadcast_random_mode_state(self) -> None:
        """Broadcast random mode state to JavaScript plugins"""
        if not self.websocket_server.loop or not self.websocket_server.connections:
            return
        
        random_mode_active = getattr(self.shared_state, 'random_mode_active', False)
        random_skin_id = getattr(self.shared_state, 'random_skin_id', None)
        dice_state = 'enabled' if random_mode_active else 'disabled'
        
        payload = {
            "type": "random-mode-state",
            "active": random_mode_active,
            "randomSkinId": random_skin_id,
            "diceState": dice_state,
            "timestamp": int(time.time() * 1000),
        }
        
        log.debug(
            "[SkinMonitor] Broadcasting random mode state → active=%s diceState=%s randomSkinId=%s",
            random_mode_active,
            dice_state,
            random_skin_id,
        )
        
        self._send_message(json.dumps(payload))
    
    def _send_message(self, message: str) -> None:
        """Send message to all connected clients"""
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        
        if running_loop is self.websocket_server.loop:
            self.websocket_server.loop.create_task(self.websocket_server.broadcast(message))
        else:
            asyncio.run_coroutine_threadsafe(
                self.websocket_server.broadcast(message), self.websocket_server.loop
            )
    
    def _skin_has_chromas(self, skin_id: Optional[int]) -> bool:
        """Check if skin has chromas"""
        if skin_id is None:
            return False
        
        if skin_id == 99007:
            return True
        
        if 99991 <= skin_id <= 99999:
            return True
        
        if skin_id in SPECIAL_BASE_SKIN_IDS:
            return True
        
        if skin_id in SPECIAL_CHROMA_SKIN_IDS:
            return True
        
        if self.skin_scraper and self.skin_scraper.cache:
            chroma_id_map = getattr(
                self.skin_scraper.cache, "chroma_id_map", None
            )
            if chroma_id_map and skin_id in chroma_id_map:
                return True
            
            try:
                chromas = self.skin_scraper.get_chromas_for_skin(skin_id)
                if chromas:
                    return True
            except Exception:
                return False
        
        return False

