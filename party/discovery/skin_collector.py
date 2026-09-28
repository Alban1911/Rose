#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin Collector
Collects and manages skin selections from party members
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from state import SharedState
from utils.core.historic import get_custom_mod_path, is_custom_mod_path
from utils.core.logging import get_logger

from ..protocol.message_types import SkinSelection
from ..network.peer_connection import PeerConnection
from .custom_mods import find_local_mod

log = get_logger()


def _to_int(value) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


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
        # (ChampSelect generation, our selection) kept from when our injection started
        self._frozen: Optional[tuple] = None

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

    def freeze_my_selection(self, summoner_id: int, summoner_name: str) -> None:
        """Keep our selection as it is when our injection starts, for the rest of
        this champ select. The injection then forces the base skin, and Rift
        Classic's skin pane shows that as a skin of its own (Morgana Classic),
        which friends would otherwise get instead of the injected one."""
        generation = getattr(self.state, "champ_select_generation", 0)
        self._frozen = (generation, self._current_selection(summoner_id, summoner_name))

    def is_frozen(self) -> bool:
        """Our injection started in this champ select: our selection is final."""
        return bool(self._frozen) and self._frozen[0] == getattr(self.state, "champ_select_generation", 0)

    def get_my_selection(
        self, summoner_id: int, summoner_name: str
    ) -> Optional[SkinSelection]:
        """Get our own skin selection from state, as it will be injected
        (HistoricMode and random skins, chromas and custom mods included)

        Args:
            summoner_id: Our summoner ID
            summoner_name: Our summoner name

        Returns:
            Our skin selection or None
        """
        if self.is_frozen():
            return self._frozen[1]
        return self._current_selection(summoner_id, summoner_name)

    def _current_selection(
        self, summoner_id: int, summoner_name: str
    ) -> Optional[SkinSelection]:
        state = self.state
        champion_id = state.locked_champ_id or state.hovered_champ_id
        if not champion_id:
            return None

        skin_id = None
        chroma_id = None
        custom_mod_path = None

        # Same priority as the injection: HistoricMode, random skin, then the hovered skin
        if getattr(state, "historic_mode_active", False):
            historic_skin_id = getattr(state, "historic_skin_id", None)
            if is_custom_mod_path(historic_skin_id):
                custom_mod_path = get_custom_mod_path(historic_skin_id)
            else:
                skin_id = _to_int(historic_skin_id)

        if skin_id is None and not custom_mod_path and getattr(state, "random_mode_active", False):
            skin_id = _to_int(getattr(state, "random_skin_id", None))

        if skin_id is None:
            skin_id = state.last_hovered_skin_id
            if not custom_mod_path and skin_id:
                selected_chroma_id = getattr(state, "selected_chroma_id", None)
                if selected_chroma_id and skin_id < selected_chroma_id < skin_id + 100:
                    chroma_id = selected_chroma_id

                selected_custom_mod = getattr(state, "selected_custom_mod", None)
                if selected_custom_mod and selected_custom_mod.get("skin_id") == skin_id:
                    custom_mod_path = selected_custom_mod.get("relative_path")

        if not skin_id:
            if not custom_mod_path:
                return None
            skin_id = champion_id * 1000  # custom mod on the default skin

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
        team_champion_ids: Optional[Set[int]] = None,
        my_champion_id: Optional[int] = None,
    ) -> List[PartySkinData]:
        """Collect skins from relay room members for injection.

        When champion select data is available, members whose champion isn't
        on our team are skipped. A champion never gets a second skin (ours
        included): two mods for the same champion conflict.

        Args:
            members: List of member dicts from the relay (each has summoner_id, skin, etc.)
            my_summoner_id: Our summoner ID (to exclude ourselves)
            team_champions: Mapping of summoner_id -> champion_id
            team_champion_ids: Every champion picked on our team
            my_champion_id: Our own champion

        Returns:
            List of PartySkinData for party members
        """
        skins = []
        taken_champions = {my_champion_id} if my_champion_id else set()

        for member in members:
            sid = _to_int(member.get("summoner_id"))
            if not sid or sid == my_summoner_id:
                continue

            name = member.get("summoner_name") or "Unknown"
            skin = member.get("skin")
            if not isinstance(skin, dict):
                continue
            champion_id = _to_int(skin.get("champion_id"))
            skin_id = _to_int(skin.get("skin_id"))
            if not champion_id or not skin_id:
                continue

            if team_champion_ids and champion_id not in team_champion_ids:
                log.info(f"[SKIN_COLLECT] Skipping {name}: champion {champion_id} is not on our team")
                continue
            expected = team_champions.get(sid)
            if expected and expected != champion_id:
                log.warning(
                    f"[SKIN_COLLECT] Champion mismatch for {name}: "
                    f"expected {expected}, got {champion_id}"
                )
                continue
            if champion_id in taken_champions:
                log.info(f"[SKIN_COLLECT] Skipping {name}: champion {champion_id} already has a skin")
                continue

            # For custom mods, use our own copy of the same mod (matched by content)
            custom_mod_path = None
            if skin.get("is_custom"):
                custom_mod_path = find_local_mod(
                    champion_id,
                    content_hash=skin.get("custom_mod_content_hash"),
                    legacy_hash=skin.get("custom_mod_hash"),
                )
                if custom_mod_path:
                    log.info(f"[SKIN_COLLECT] Matched {name}'s custom mod: {custom_mod_path}")
                else:
                    log.info(f"[SKIN_COLLECT] {name} uses a custom mod we don't have, using the official skin")

            if not custom_mod_path and skin_id == champion_id * 1000:
                continue  # default skin: nothing to inject

            taken_champions.add(champion_id)
            skins.append(PartySkinData(
                summoner_id=sid,
                summoner_name=name,
                champion_id=champion_id,
                skin_id=skin_id,
                chroma_id=_to_int(skin.get("chroma_id")),
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
