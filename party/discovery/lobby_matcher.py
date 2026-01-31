#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lobby Matcher
Matches connected peers to lobby/champion select members
"""

from typing import Dict, List, Optional, Set

from lcu import LCU
from state import SharedState
from utils.core.logging import get_logger

from ..network.peer_connection import PeerConnection

log = get_logger()


class LobbyMatcher:
    """Matches connected peers to current lobby members"""

    def __init__(self, lcu: LCU, state: SharedState):
        """Initialize lobby matcher

        Args:
            lcu: LCU client instance
            state: Shared application state
        """
        self.lcu = lcu
        self.state = state

    def get_lobby_summoner_ids(self) -> Set[int]:
        """Get summoner IDs from current lobby

        Returns:
            Set of summoner IDs in the lobby
        """
        summoner_ids = set()

        try:
            # Try lobby endpoint first (pre-game lobby)
            lobby_data = self.lcu.get("/lol-lobby/v2/lobby")
            if lobby_data and isinstance(lobby_data, dict):
                members = lobby_data.get("members", [])
                if isinstance(members, list):
                    for member in members:
                        if isinstance(member, dict):
                            summoner_id = member.get("summonerId")
                            if summoner_id:
                                summoner_ids.add(int(summoner_id))

                # Also check localMember
                local_member = lobby_data.get("localMember")
                if isinstance(local_member, dict):
                    summoner_id = local_member.get("summonerId")
                    if summoner_id:
                        summoner_ids.add(int(summoner_id))

        except Exception as e:
            log.debug(f"[LOBBY] Error getting lobby members: {e}")

        return summoner_ids

    def get_champ_select_summoner_ids(self) -> Set[int]:
        """Get summoner IDs from champion select

        Returns:
            Set of summoner IDs in champion select
        """
        summoner_ids = set()

        try:
            session = self.lcu.session
            if not session or not isinstance(session, dict):
                return summoner_ids

            # Get myTeam members
            my_team = session.get("myTeam", [])
            if isinstance(my_team, list):
                for player in my_team:
                    if isinstance(player, dict):
                        summoner_id = player.get("summonerId")
                        if summoner_id:
                            summoner_ids.add(int(summoner_id))

        except Exception as e:
            log.debug(f"[LOBBY] Error getting champ select members: {e}")

        return summoner_ids

    def get_all_summoner_ids(self) -> Set[int]:
        """Get summoner IDs from lobby or champion select

        Returns:
            Set of summoner IDs from current lobby/game
        """
        phase = self.state.phase

        if phase == "ChampSelect":
            return self.get_champ_select_summoner_ids()
        elif phase in ("Lobby", "Matchmaking", "ReadyCheck"):
            return self.get_lobby_summoner_ids()
        else:
            # Try both
            ids = self.get_lobby_summoner_ids()
            if not ids:
                ids = self.get_champ_select_summoner_ids()
            return ids

    def get_my_summoner_id(self) -> Optional[int]:
        """Get our own summoner ID

        Returns:
            Our summoner ID or None
        """
        try:
            summoner = self.lcu.current_summoner
            if summoner and isinstance(summoner, dict):
                summoner_id = summoner.get("summonerId")
                if summoner_id:
                    return int(summoner_id)
        except Exception as e:
            log.debug(f"[LOBBY] Error getting own summoner ID: {e}")

        return None

    def get_my_summoner_name(self) -> str:
        """Get our own summoner name

        Returns:
            Our summoner name or "Unknown"
        """
        try:
            summoner = self.lcu.current_summoner
            if summoner and isinstance(summoner, dict):
                # Try different name fields
                name = summoner.get("displayName")
                if not name:
                    name = summoner.get("gameName")
                if not name:
                    name = summoner.get("internalName")
                if name:
                    return str(name)
        except Exception as e:
            log.debug(f"[LOBBY] Error getting own summoner name: {e}")

        return "Unknown"

    def match_peers_to_lobby(
        self, peers: List[PeerConnection]
    ) -> Dict[int, PeerConnection]:
        """Match connected peers to lobby members

        Args:
            peers: List of connected peer connections

        Returns:
            Dict mapping summoner_id to PeerConnection for peers in lobby
        """
        lobby_ids = self.get_all_summoner_ids()

        if not lobby_ids:
            log.debug("[LOBBY] No lobby members found")
            return {}

        matched = {}
        for peer in peers:
            if peer.is_connected and peer.summoner_id in lobby_ids:
                matched[peer.summoner_id] = peer
                peer.peer_info.in_lobby = True
            else:
                peer.peer_info.in_lobby = False

        if matched:
            log.info(f"[LOBBY] Matched {len(matched)} peers to lobby members")

        return matched

    def get_team_champion_mapping(self) -> Dict[int, int]:
        """Get mapping of summoner ID to champion ID for our team

        Returns:
            Dict mapping summoner_id to champion_id
        """
        mapping = {}

        try:
            session = self.lcu.session
            if not session or not isinstance(session, dict):
                return mapping

            my_team = session.get("myTeam", [])
            if isinstance(my_team, list):
                for player in my_team:
                    if isinstance(player, dict):
                        summoner_id = player.get("summonerId")
                        champion_id = player.get("championId")
                        if summoner_id and champion_id:
                            mapping[int(summoner_id)] = int(champion_id)

        except Exception as e:
            log.debug(f"[LOBBY] Error getting team champions: {e}")

        return mapping

    def is_in_same_lobby(self, peer_summoner_ids: List[int]) -> bool:
        """Check if given peers are in our lobby

        Args:
            peer_summoner_ids: List of peer summoner IDs to check

        Returns:
            True if at least one peer is in our lobby
        """
        lobby_ids = self.get_all_summoner_ids()
        return bool(lobby_ids.intersection(peer_summoner_ids))
