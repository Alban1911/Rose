#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin Collector
Collects and manages skin selections from party members
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from state import SharedState
from utils.core.logging import get_logger

from ..protocol.message_types import SkinSelection
from ..network.peer_connection import PeerConnection

log = get_logger()


@dataclass
class PartySkinData:
    """Aggregated skin data from party members"""
    summoner_id: int
    summoner_name: str
    champion_id: int
    skin_id: int
    chroma_id: Optional[int] = None
    custom_mod_path: Optional[str] = None
    is_local: bool = False  # True if this is our own selection


class SkinCollector:
    """Collects skin selections from party members for injection"""

    def __init__(self, state: SharedState):
        """Initialize skin collector

        Args:
            state: Shared application state
        """
        self.state = state

        # Cached skin selections by summoner ID
        self._selections: Dict[int, SkinSelection] = {}

    def update_from_peer(self, selection: SkinSelection):
        """Update skin selection from peer

        Args:
            selection: Peer's skin selection
        """
        self._selections[selection.summoner_id] = selection
        log.debug(
            f"[SKIN_COLLECT] Updated selection from {selection.summoner_name}: "
            f"champion {selection.champion_id} -> skin {selection.skin_id}"
        )

    def clear_peer(self, summoner_id: int):
        """Clear skin selection for a peer

        Args:
            summoner_id: Peer's summoner ID to clear
        """
        if summoner_id in self._selections:
            del self._selections[summoner_id]
            log.debug(f"[SKIN_COLLECT] Cleared selection for summoner {summoner_id}")

    def clear_all(self):
        """Clear all peer skin selections"""
        self._selections.clear()
        log.debug("[SKIN_COLLECT] Cleared all peer selections")

    def get_my_selection(
        self, summoner_id: int, summoner_name: str
    ) -> Optional[SkinSelection]:
        """Get our own skin selection from state

        Args:
            summoner_id: Our summoner ID
            summoner_name: Our summoner name

        Returns:
            Our skin selection or None
        """
        champion_id = self.state.locked_champ_id or self.state.hovered_champ_id

        # Check random mode (regular dice or favorites dice)
        random_mode_active = getattr(self.state, "random_mode_active", False)
        random_skin_id = getattr(self.state, "random_skin_id", None)
        if random_mode_active and random_skin_id:
            skin_id = random_skin_id
            chroma_id = getattr(self.state, "random_chroma_id", None)
        # Check historic mode
        elif getattr(self.state, "historic_mode_active", False) and getattr(self.state, "historic_skin_id", None):
            skin_id = self.state.historic_skin_id
            chroma_id = None
        # Standard hovered / locked skin
        else:
            skin_id = self.state.last_hovered_skin_id
            chroma_id = getattr(self.state, "selected_chroma_id", None)

        if not champion_id or not skin_id:
            return None

        # Check for custom mod
        custom_mod_path = None
        selected_custom_mod = getattr(self.state, "selected_custom_mod", None)
        if selected_custom_mod and selected_custom_mod.get("skin_id") == skin_id:
            custom_mod_path = selected_custom_mod.get("relative_path")

        return SkinSelection(
            summoner_id=summoner_id,
            summoner_name=summoner_name,
            champion_id=champion_id,
            skin_id=skin_id,
            chroma_id=chroma_id,
            custom_mod_path=custom_mod_path,
        )

    def collect_all_skins(
        self,
        peers: List[PeerConnection],
        my_summoner_id: int,
        my_summoner_name: str,
        team_champions: Dict[int, int],
    ) -> List[PartySkinData]:
        """Collect all skin selections for injection

        Args:
            peers: List of connected peers in lobby
            my_summoner_id: Our summoner ID
            my_summoner_name: Our summoner name
            team_champions: Mapping of summoner_id -> champion_id

        Returns:
            List of PartySkinData for all party members
        """
        skins = []

        # Add our own selection first
        my_selection = self.get_my_selection(my_summoner_id, my_summoner_name)
        if my_selection:
            skins.append(
                PartySkinData(
                    summoner_id=my_summoner_id,
                    summoner_name=my_summoner_name,
                    champion_id=my_selection.champion_id,
                    skin_id=my_selection.skin_id,
                    chroma_id=my_selection.chroma_id,
                    custom_mod_path=my_selection.custom_mod_path,
                    is_local=True,
                )
            )

        # Add peer selections (require connected; in_lobby may be cleared at injection time when phase changes)
        for peer in peers:
            if not peer.is_connected:
                continue

            selection = peer.skin_selection
            if not selection:
                # Use cached selection
                selection = self._selections.get(peer.summoner_id)

            if selection:
                # Verify champion matches team champion
                expected_champion = team_champions.get(selection.summoner_id)
                if expected_champion and expected_champion != selection.champion_id:
                    log.warning(
                        f"[SKIN_COLLECT] Champion mismatch for {selection.summoner_name}: "
                        f"expected {expected_champion}, got {selection.champion_id}"
                    )
                    continue

                skins.append(
                    PartySkinData(
                        summoner_id=selection.summoner_id,
                        summoner_name=selection.summoner_name,
                        champion_id=selection.champion_id,
                        skin_id=selection.skin_id,
                        chroma_id=selection.chroma_id,
                        custom_mod_path=selection.custom_mod_path,
                        is_local=False,
                    )
                )

        log.info(
            f"[SKIN_COLLECT] Collected {len(skins)} skin selections "
            f"({sum(1 for s in skins if s.is_local)} local, "
            f"{sum(1 for s in skins if not s.is_local)} from peers)"
        )

        return skins

    def collect_relay_skins(
        self,
        members: list,
        my_summoner_id: int,
        team_champions: Dict[int, int],
    ) -> List[PartySkinData]:
        """Collect skins from relay room members for injection.

        Args:
            members: List of member dicts from the relay (each has summoner_id, skin, etc.)
            my_summoner_id: Our summoner ID (to exclude ourselves)
            team_champions: Mapping of summoner_id -> champion_id

        Returns:
            List of PartySkinData for party members
        """
        skins = []

        for member in members:
            sid = member.get("summoner_id", 0)
            if sid == my_summoner_id or not sid:
                continue

            skin = member.get("skin")
            if not skin:
                # Try cached selection
                cached = self._selections.get(sid)
                if cached:
                    skin = {
                        "champion_id": cached.champion_id,
                        "skin_id": cached.skin_id,
                        "chroma_id": cached.chroma_id,
                    }

            if not skin or not skin.get("skin_id"):
                continue

            champion_id = skin.get("champion_id", 0)
            expected = team_champions.get(sid)
            if expected and expected != champion_id:
                log.warning(f"[SKIN_COLLECT] Champion mismatch for {sid}")
                continue

            # For custom mods, try to find a local match by content hash
            custom_mod_path = None
            if skin.get("is_custom") and skin.get("custom_mod_hash"):
                from ..core.party_manager import PartyManager
                local_path = PartyManager.find_local_mod_by_hash(
                    skin["custom_mod_hash"], champion_id
                )
                if local_path:
                    custom_mod_path = local_path
                    log.info(f"[SKIN_COLLECT] Matched custom mod for peer {sid}: {local_path}")
                else:
                    log.info(f"[SKIN_COLLECT] No local match for peer {sid}'s custom mod, skipping")
                    continue

            skins.append(PartySkinData(
                summoner_id=sid,
                summoner_name=member.get("summoner_name", "Unknown"),
                champion_id=champion_id,
                skin_id=skin.get("skin_id", 0),
                chroma_id=skin.get("chroma_id"),
                custom_mod_path=custom_mod_path,
                is_local=False,
            ))

        log.info(f"[SKIN_COLLECT] Collected {len(skins)} relay skin selections")
        return skins

    def get_peer_selections(self) -> Dict[int, SkinSelection]:
        """Get all cached peer selections

        Returns:
            Dict mapping summoner_id to SkinSelection
        """
        return dict(self._selections)
