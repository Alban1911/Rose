#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Party Injection Hook
Integrates party mode skin collection with injection flow
"""

from pathlib import Path
from typing import List, Optional

from state import SharedState
from utils.core.junction import is_junction, link_or_extract, safe_remove_entry
from utils.core.logging import get_logger
from utils.core.paths import get_injection_dir

from ..core.party_manager import PartyManager
from ..discovery.custom_mods import get_mods_root
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
        """Check if party injection is enabled (any peer, including ones whose
        room is reconnecting: their last known skins are still used)"""
        return (
            self.party_manager is not None
            and self.party_manager.enabled
            and len(self.party_manager.party_state.peers) > 0
        )

    def has_party_skins(self) -> bool:
        """Check if any party member has a skin to inject for this game"""
        return bool(self.get_party_skins_for_injection())

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
                    + (f" (chroma {skin.chroma_id})" if skin.chroma_id else "")
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
        source = None

        if skin_data.custom_mod_path:
            # Our own copy of the party member's custom mod (folder or archive)
            local_mod = get_mods_root() / skin_data.custom_mod_path
            if local_mod.exists():
                log.info(
                    f"[PARTY_INJECT] {skin_data.summoner_name} has custom mod, "
                    f"using local match: {skin_data.custom_mod_path}"
                )
                source = local_mod
            else:
                log.warning(
                    f"[PARTY_INJECT] Custom mod path not found: {skin_data.custom_mod_path}"
                )

        if source is None:
            source = self._resolve_skin_zip(skin_data, injector)
        if source is None:
            return None

        # Prefixed so it never collides with our own mod folder
        mod_folder_name = f"party_{skin_data.summoner_id}"
        mod_dest = injector.mods_dir / mod_folder_name
        if mod_dest.exists() or is_junction(mod_dest):
            safe_remove_entry(mod_dest)

        # Cached extraction: the same skin is instant in later games
        link_or_extract(source, mod_dest, cache_dir=get_injection_dir() / ".extract_cache")
        if not (mod_dest.exists() or is_junction(mod_dest)):
            log.warning(f"[PARTY_INJECT] Mod folder missing after extraction: {mod_dest}")
            return None

        log.info(
            f"[PARTY_INJECT] Prepared {skin_data.summoner_name}'s skin: {source.name}"
        )
        return mod_folder_name

    @staticmethod
    def _resolve_skin_zip(skin_data: PartySkinData, injector) -> Optional[Path]:
        """Find the skin (or chroma) file of a party member's official skin"""
        skin_name = f"skin_{skin_data.skin_id}"

        if skin_data.chroma_id:
            zip_path = injector._resolve_zip(
                skin_name,
                chroma_id=skin_data.chroma_id,
                skin_name=skin_name,
                champion_name=None,
                champion_id=skin_data.champion_id,
            )
            if zip_path and zip_path.exists():
                return zip_path
            log.info(
                f"[PARTY_INJECT] Chroma {skin_data.chroma_id} not found, "
                f"using base skin {skin_data.skin_id}"
            )

        zip_path = injector._resolve_zip(
            skin_name,
            skin_name=skin_name,
            champion_name=None,
            champion_id=skin_data.champion_id,
        )
        if not zip_path or not zip_path.exists():
            log.warning(f"[PARTY_INJECT] Could not find skin ZIP for {skin_name}")
            return None
        return zip_path

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
