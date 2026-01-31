#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Party State
State management for party mode
"""

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..protocol.message_types import SkinSelection


@dataclass
class PartyPeerState:
    """State for a single party peer"""
    summoner_id: int
    summoner_name: str = "Unknown"
    connected: bool = False
    connection_state: str = "disconnected"  # connecting, handshaking, connected, disconnected, dead
    in_lobby: bool = False
    skin_selection: Optional[SkinSelection] = None


@dataclass
class PartyState:
    """Party mode state container"""

    # Party mode status
    enabled: bool = False
    my_token: Optional[str] = None
    my_summoner_id: Optional[int] = None
    my_summoner_name: str = "Unknown"

    # Connected peers
    peers: Dict[int, PartyPeerState] = field(default_factory=dict)

    # Skin selections from peers (champion_id -> skin_data)
    party_skins: Dict[int, dict] = field(default_factory=dict)

    # Thread safety
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add_peer(
        self,
        summoner_id: int,
        summoner_name: str = "Unknown",
        connected: bool = False,
        connection_state: str = "disconnected",
    ):
        """Add or update a peer"""
        with self._lock:
            if summoner_id in self.peers:
                self.peers[summoner_id].summoner_name = summoner_name
                self.peers[summoner_id].connected = connected
                self.peers[summoner_id].connection_state = connection_state
            else:
                self.peers[summoner_id] = PartyPeerState(
                    summoner_id=summoner_id,
                    summoner_name=summoner_name,
                    connected=connected,
                    connection_state=connection_state,
                )

    def remove_peer(self, summoner_id: int):
        """Remove a peer"""
        with self._lock:
            if summoner_id in self.peers:
                del self.peers[summoner_id]

    def update_peer_connection(self, summoner_id: int, connected: bool):
        """Update peer connection status"""
        with self._lock:
            if summoner_id in self.peers:
                self.peers[summoner_id].connected = connected

    def update_peer_connection_state(self, summoner_id: int, connection_state: str):
        """Update peer connection state (connecting, handshaking, connected, disconnected, dead)"""
        with self._lock:
            if summoner_id in self.peers:
                self.peers[summoner_id].connection_state = connection_state

    def update_peer_lobby_status(self, summoner_id: int, in_lobby: bool):
        """Update peer lobby status"""
        with self._lock:
            if summoner_id in self.peers:
                self.peers[summoner_id].in_lobby = in_lobby

    def update_peer_skin(self, summoner_id: int, selection: SkinSelection):
        """Update peer skin selection"""
        with self._lock:
            if summoner_id in self.peers:
                self.peers[summoner_id].skin_selection = selection
                # Also update party_skins for easy lookup by champion
                self.party_skins[selection.champion_id] = {
                    "summoner_id": selection.summoner_id,
                    "summoner_name": selection.summoner_name,
                    "skin_id": selection.skin_id,
                    "chroma_id": selection.chroma_id,
                    "custom_mod_path": selection.custom_mod_path,
                }

    def clear_peer_skin(self, summoner_id: int):
        """Clear peer skin selection"""
        with self._lock:
            if summoner_id in self.peers:
                old_selection = self.peers[summoner_id].skin_selection
                self.peers[summoner_id].skin_selection = None
                # Remove from party_skins
                if old_selection:
                    self.party_skins.pop(old_selection.champion_id, None)

    def get_connected_peers(self) -> List[PartyPeerState]:
        """Get list of connected peers"""
        with self._lock:
            return [p for p in self.peers.values() if p.connected]

    def get_lobby_peers(self) -> List[PartyPeerState]:
        """Get list of peers in the current lobby"""
        with self._lock:
            return [p for p in self.peers.values() if p.connected and p.in_lobby]

    def get_all_skin_selections(self) -> Dict[int, SkinSelection]:
        """Get all skin selections from peers (summoner_id -> selection)"""
        with self._lock:
            return {
                p.summoner_id: p.skin_selection
                for p in self.peers.values()
                if p.connected and p.skin_selection
            }

    def clear_all(self):
        """Clear all party state"""
        with self._lock:
            self.enabled = False
            self.my_token = None
            self.peers.clear()
            self.party_skins.clear()

    def to_dict(self) -> dict:
        """Convert to dictionary for UI broadcast"""
        with self._lock:
            return {
                "enabled": self.enabled,
                "my_token": self.my_token,
                "my_summoner_id": self.my_summoner_id,
                "my_summoner_name": self.my_summoner_name,
                "peers": [
                    {
                        "summoner_id": p.summoner_id,
                        "summoner_name": p.summoner_name,
                        "connected": p.connected,
                        "connection_state": p.connection_state,
                        "in_lobby": p.in_lobby,
                        "skin_selection": (
                            p.skin_selection.to_dict() if p.skin_selection else None
                        ),
                    }
                    for p in self.peers.values()
                ],
            }
