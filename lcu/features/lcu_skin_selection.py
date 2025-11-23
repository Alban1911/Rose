#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU Skin Selection
Handles skin selection via LCU API
"""

from config import LCU_API_TIMEOUT_S
from utils.core.logging import get_logger

log = get_logger()


class LCUSkinSelection:
    """Handles skin selection operations"""
    
    def __init__(self, api, connection):
        """Initialize skin selection handler
        
        Args:
            api: LCUAPI instance
            connection: LCUConnection instance
        """
        self.api = api
        self.connection = connection
    
    def set_selected_skin(self, action_id: int, skin_id: int) -> bool:
        """Set the selected skin for a champion select action
        
        Args:
            action_id: Action ID in champion select
            skin_id: Skin ID to select
            
        Returns:
            True if successful, False otherwise
        """
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

