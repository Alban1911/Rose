#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Party Injection Hook
Integrates party mode skin collection with injection flow
"""

from pathlib import Path
from typing import List, Optional

from state import SharedState
from utils.core.logging import get_logger

from ..core.party_manager import PartyManager
from ..discovery.skin_collector import PartySkinData

log = get_logger()


class PartyInjectionHook:
    """Hooks into the injection flow to add party member skins"""

    def __init__(
        self,
        party_manager: PartyManager,
        state: SharedState,
        injection_manager=None,
    ):
        """Initialize injection hook

        Args:
            party_manager: PartyManager instance
            state: Shared application state
            injection_manager: InjectionManager instance
        """
        self.party_manager = party_manager
        self.state = state
        self.injection_manager = injection_manager

    def is_enabled(self) -> bool:
        """Check if party injection is enabled"""
        return (
            self.party_manager is not None
            and self.party_manager.enabled
            and len(self.party_manager.party_state.get_lobby_peers()) > 0
        )

    def get_party_skins_for_injection(self) -> List[PartySkinData]:
        """Get party member skins for injection

        Returns:
            List of PartySkinData from party members (excluding our own)
        """
        if not self.is_enabled():
            return []

        all_skins = self.party_manager.get_party_skins()

        # Filter out our own skin (we handle that separately)
        peer_skins = [s for s in all_skins if not s.is_local]

        if peer_skins:
            log.info(
                f"[PARTY_INJECT] Found {len(peer_skins)} party member skin(s) to inject"
            )
            for skin in peer_skins:
                log.info(
                    f"  - {skin.summoner_name}: Champion {skin.champion_id} -> Skin {skin.skin_id}"
                )

        return peer_skins

    def prepare_party_mods(self, injector) -> List[str]:
        """Prepare party member skin mods for injection

        Args:
            injector: Injector instance with mods_dir

        Returns:
            List of mod folder names that were prepared
        """
        if not self.is_enabled():
            return []

        party_skins = self.get_party_skins_for_injection()
        if not party_skins:
            return []

        mod_folder_names = []

        for skin_data in party_skins:
            try:
                mod_name = self._prepare_single_skin(
                    skin_data=skin_data,
                    injector=injector,
                )
                if mod_name:
                    mod_folder_names.append(mod_name)
            except Exception as e:
                log.warning(
                    f"[PARTY_INJECT] Failed to prepare skin for {skin_data.summoner_name}: {e}"
                )

        return mod_folder_names

    def _prepare_single_skin(
        self,
        skin_data: PartySkinData,
        injector,
    ) -> Optional[str]:
        """Prepare a single party member's skin for injection

        Args:
            skin_data: Party member's skin data
            injector: Injector instance

        Returns:
            Mod folder name or None if preparation failed
        """
        skin_id = skin_data.skin_id
        champion_id = skin_data.champion_id
        chroma_id = skin_data.chroma_id
        custom_mod_path = skin_data.custom_mod_path

        # Determine skin name for ZIP resolution
        skin_name = f"skin_{skin_id}"

        if custom_mod_path:
            # Party member has a custom mod - we can't inject that
            # (custom mods are local to each user's machine)
            log.info(
                f"[PARTY_INJECT] {skin_data.summoner_name} has custom mod - "
                f"using base skin {skin_name} instead"
            )

        # Resolve the skin ZIP
        try:
            zip_path = injector._resolve_zip(
                skin_name,
                skin_name=skin_name,
                champion_name=None,
                champion_id=champion_id,
            )

            if not zip_path or not zip_path.exists():
                log.warning(
                    f"[PARTY_INJECT] Could not find skin ZIP for {skin_name}"
                )
                return None

            # Extract to mods directory
            mod_folder = injector._extract_zip_to_mod(zip_path)

            if mod_folder:
                log.info(
                    f"[PARTY_INJECT] Prepared {skin_data.summoner_name}'s skin: "
                    f"{mod_folder.name}"
                )
                return mod_folder.name

        except Exception as e:
            log.warning(f"[PARTY_INJECT] Failed to resolve/extract skin: {e}")

        return None

    def get_injection_summary(self) -> dict:
        """Get summary of party injection status

        Returns:
            Dict with injection summary info
        """
        if not self.is_enabled():
            return {
                "party_enabled": False,
                "peers_in_lobby": 0,
                "skins_to_inject": 0,
            }

        party_skins = self.get_party_skins_for_injection()

        return {
            "party_enabled": True,
            "peers_in_lobby": len(self.party_manager.party_state.get_lobby_peers()),
            "skins_to_inject": len(party_skins),
            "skins": [
                {
                    "summoner_name": s.summoner_name,
                    "champion_id": s.champion_id,
                    "skin_id": s.skin_id,
                }
                for s in party_skins
            ],
        }
