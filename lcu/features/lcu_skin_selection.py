#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU Skin Selection
Handles skin selection via LCU API
"""

from config import LCU_API_TIMEOUT_S
from utils.core.classic_mode_ids import (
    is_classic_mode,
    is_classic_skin_id,
    resource_skin_id,
)
from utils.core.logging import get_logger

log = get_logger()


class LCUSkinSelection:
    """Handles skin selection operations"""
    
    def __init__(self, api, connection, shared_state=None):
        """Initialize skin selection handler
        
        Args:
            api: LCUAPI instance
            connection: LCUConnection instance
        """
        self.api = api
        self.connection = connection
        self.shared_state = shared_state

    def bind_shared_state(self, shared_state) -> None:
        self.shared_state = shared_state

    def _classic_write_allowed(self, skin_id: object) -> bool:
        state = self.shared_state
        if state is None or not is_classic_mode(state.current_game_mode):
            return True
        try:
            value = int(skin_id)
        except (TypeError, ValueError):
            return False
        if not is_classic_skin_id(value):
            return False
        canonical_skin_id = resource_skin_id(value)
        if canonical_skin_id // 1000 != state.classic_champion_id:
            return False
        owned = {resource_skin_id(item) for item in (state.owned_skin_ids or ())}
        return (
            canonical_skin_id == state.classic_default_skin_id
            or canonical_skin_id in owned
        )
    
    def set_selected_skin(self, action_id: int, skin_id: int) -> bool:
        """Set the selected skin for a champion select action
        
        Args:
            action_id: Action ID in champion select
            skin_id: Skin ID to select
            
        Returns:
            True if successful, False otherwise
        """
        if not self._classic_write_allowed(skin_id):
            log.error("Refused unsafe Classic Mode LCU skin write: %s", skin_id)
            return False

        if not self.connection.ok:
            self.connection.refresh_if_needed()
            if not self.connection.ok:
                log.warning("LCU set_selected_skin failed: LCU not connected")
                return False
        
        try:
            response = self.api.patch(
                f"/lol-champ-select/v1/session/actions/{action_id}",
                {"selectedSkinId": skin_id},
                LCU_API_TIMEOUT_S
            )
            if response and response.status_code in (200, 204):
                return True
            else:
                status_code = response.status_code if response else "None"
                response_text = response.text[:200] if response else "No response"
                log.warning(f"LCU set_selected_skin failed: status={status_code}, response={response_text}")
                return False
        except Exception as e:
            log.warning(f"LCU set_selected_skin exception: {e}")
            return False
    
    def set_my_selection_skin(self, skin_id: int) -> bool:
        """Set the selected skin using my-selection endpoint (works after champion lock)
        
        Args:
            skin_id: Skin ID to select
            
        Returns:
            True if successful, False otherwise
        """
        if not self._classic_write_allowed(skin_id):
            log.error("Refused unsafe Classic Mode LCU skin write: %s", skin_id)
            return False

        if not self.connection.ok:
            self.connection.refresh_if_needed()
            if not self.connection.ok:
                log.warning("LCU set_my_selection_skin failed: LCU not connected")
                return False
        
        try:
            response = self.api.patch(
                f"/lol-champ-select/v1/session/my-selection",
                {"selectedSkinId": skin_id},
                LCU_API_TIMEOUT_S
            )
            if response and response.status_code in (200, 204):
                return True
            else:
                status_code = response.status_code if response else "None"
                response_text = response.text[:200] if response else "No response"
                log.warning(f"LCU set_my_selection_skin failed: status={status_code}, response={response_text}")
                return False
        except Exception as e:
            log.warning(f"LCU set_my_selection_skin exception: {e}")
            return False
