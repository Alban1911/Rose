#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Party UI Bridge
WebSocket communication bridge for party mode UI
"""

import asyncio
import json
from typing import Callable, Optional

from utils.core.logging import get_logger

from ..core.party_manager import PartyManager
from ..core.party_state import PartyState

log = get_logger()


class PartyUIBridge:
    """Handles WebSocket communication for party mode UI"""

    def __init__(self, party_manager: PartyManager, broadcaster):
        """Initialize UI bridge

        Args:
            party_manager: PartyManager instance
            broadcaster: Broadcaster instance for sending messages
        """
        self.party_manager = party_manager
        self.broadcaster = broadcaster

        # Register state change callback
        self.party_manager.set_callbacks(
            on_state_change=self._on_state_change,
        )

    async def handle_message(self, data: dict) -> Optional[dict]:
        """Handle incoming message from UI

        Args:
            data: Message data from WebSocket

        Returns:
            Response dict or None
        """
        msg_type = data.get("type", "")

        if msg_type == "party-enable":
            return await self._handle_enable()

        elif msg_type == "party-disable":
            return await self._handle_disable()

        elif msg_type == "party-add-peer":
            token = data.get("token", "")
            return await self._handle_add_peer(token)

        elif msg_type == "party-remove-peer":
            summoner_id = data.get("summoner_id")
            if summoner_id:
                return await self._handle_remove_peer(int(summoner_id))

        elif msg_type == "party-get-state":
            return self._handle_get_state()

        elif msg_type == "party-broadcast-skin":
            await self.party_manager.broadcast_skin_update()
            return {"type": "party-response", "success": True}

        return None

    async def _handle_enable(self) -> dict:
        """Handle party enable request"""
        try:
            token = await self.party_manager.enable()
            self._broadcast_state()
            return {
                "type": "party-enabled",
                "success": True,
                "token": token,
            }
        except Exception as e:
            log.error(f"[PARTY_UI] Failed to enable: {e}")
            return {
                "type": "party-enabled",
                "success": False,
                "error": str(e),
            }

    async def _handle_disable(self) -> dict:
        """Handle party disable request"""
        try:
            await self.party_manager.disable()
            self._broadcast_state()
            return {
                "type": "party-disabled",
                "success": True,
            }
        except Exception as e:
            log.error(f"[PARTY_UI] Failed to disable: {e}")
            return {
                "type": "party-disabled",
                "success": False,
                "error": str(e),
            }

    async def _handle_add_peer(self, token: str) -> dict:
        """Handle add peer request"""
        if not token:
            return {
                "type": "party-peer-added",
                "success": False,
                "error": "No token provided",
            }

        try:
            success = await self.party_manager.add_peer(token)
            self._broadcast_state()
            return {
                "type": "party-peer-added",
                "success": success,
                "error": None if success else "Failed to connect to peer",
            }
        except Exception as e:
            log.error(f"[PARTY_UI] Failed to add peer: {e}")
            return {
                "type": "party-peer-added",
                "success": False,
                "error": str(e),
            }

    async def _handle_remove_peer(self, summoner_id: int) -> dict:
        """Handle remove peer request"""
        try:
            await self.party_manager.remove_peer(summoner_id)
            self._broadcast_state()
            return {
                "type": "party-peer-removed",
                "success": True,
                "summoner_id": summoner_id,
            }
        except Exception as e:
            log.error(f"[PARTY_UI] Failed to remove peer: {e}")
            return {
                "type": "party-peer-removed",
                "success": False,
                "error": str(e),
            }

    def _handle_get_state(self) -> dict:
        """Handle get state request"""
        state = self.party_manager.get_state_dict()
        return {
            "type": "party-state",
            **state,
        }

    def _on_state_change(self, state: PartyState):
        """Callback when party state changes"""
        self._broadcast_state()

    def _broadcast_state(self):
        """Broadcast current party state to all clients"""
        state = self.party_manager.get_state_dict()
        message = {
            "type": "party-state",
            **state,
            "timestamp": __import__("time").time(),
        }

        if self.broadcaster:
            try:
                self.broadcaster.broadcast_raw(json.dumps(message))
            except Exception as e:
                log.debug(f"[PARTY_UI] Failed to broadcast state: {e}")


def broadcast_party_state(broadcaster, party_manager: PartyManager):
    """Utility function to broadcast party state

    Args:
        broadcaster: Broadcaster instance
        party_manager: PartyManager instance
    """
    if not party_manager or not broadcaster:
        return

    state = party_manager.get_state_dict()
    message = json.dumps({
        "type": "party-state",
        **state,
        "timestamp": __import__("time").time(),
    })

    try:
        broadcaster.broadcast_raw(message)
    except Exception as e:
        log.debug(f"[PARTY_UI] Failed to broadcast state: {e}")
