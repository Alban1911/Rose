#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Party Injection Hook
Integrates party mode skin collection with injection flow
"""

from dataclasses import replace
from pathlib import Path
from typing import List, Optional

from injection.classic import is_classic_game_mode
from injection.mods.manifest import find_saved_mod
from injection.mods.mod_source import ModSource, RoseFile
from state import SharedState
from utils.core.logging import get_logger

from ..core.party_manager import PartyManager
from ..discovery.custom_mods import get_mods_root
from ..discovery.skin_collector import PartySkinData

log = get_logger()

PARTY_FOLDER_PREFIX = "party_"


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
        # Rift Classic plays Jade_<Champion> characters: friends' skins come
        # from the Classic library
        classic = is_classic_game_mode(getattr(self.state, "current_game_mode", None))

        for skin_data in party_skins:
            try:
                mod_name = self._prepare_single_skin(
                    skin_data=skin_data,
                    injector=injector,
                    classic=classic,
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
        classic: bool = False,
    ) -> Optional[str]:
        """Prepare a single party member's skin for injection

        Args:
            skin_data: Party member's skin data
            injector: Injector instance
            classic: Rift Classic game (skins from the Classic library)

        Returns:
            Mod folder name or None if preparation failed
        """
        return prepare_peer_skin(skin_data, injector, classic=classic)

    @staticmethod
    def _resolve_skin_zip(skin_data: PartySkinData, injector, classic: bool = False) -> Optional[Path]:
        return _resolve_skin_zip(skin_data, injector, classic)

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


def prepare_peer_skin(
    skin_data: PartySkinData,
    injector,
    classic: bool = False,
    mods_dir: Optional[Path] = None,
) -> Optional[str]:
    """Prepare a party member's skin in *mods_dir* (the injector's by default)

    The loadout countdown stages it in a folder of its own
    (injection.core.stage_plan), the same way the injection prepares it. Our
    copy of a friend's custom mod that LTK Manager holds is named by its LTK
    reference, with nothing linked: the injection switches it on.

    Args:
        skin_data: Party member's skin data
        injector: Injector instance
        classic: Rift Classic game (skins from the Classic library)
        mods_dir: Where the mod folder goes

    Returns:
        Mod folder name or None if preparation failed
    """
    mods_dir = Path(mods_dir) if mods_dir is not None else injector.mods_dir
    mod_folder_name = f"{PARTY_FOLDER_PREFIX}{skin_data.summoner_id}"
    mod = None
    label = skin_data.custom_mod_path

    if skin_data.custom_mod_path and classic:
        # Custom mods target the regular characters, which Classic doesn't load
        log.info(
            f"[PARTY_INJECT] Rift Classic: {skin_data.summoner_name}'s custom mod "
            f"does not apply, using the Classic skin"
        )
    elif skin_data.custom_mod_path:
        mod = _local_custom_mod(skin_data.custom_mod_path, mod_folder_name)
        if mod is not None:
            log.info(
                f"[PARTY_INJECT] {skin_data.summoner_name} has custom mod, "
                f"using local match: {skin_data.custom_mod_path}"
            )
        else:
            log.warning(
                f"[PARTY_INJECT] Custom mod path not found: {skin_data.custom_mod_path}"
            )

    if mod is None:
        skin_zip = _resolve_skin_zip(skin_data, injector, classic)
        if skin_zip is None:
            return None
        mod, label = RoseFile(skin_zip, mod_folder_name), skin_zip.name

    name = mod.put(mods_dir)
    if name is None:
        log.warning(f"[PARTY_INJECT] Mod folder missing after extraction: {mods_dir / mod_folder_name}")
        return None

    log.info(f"[PARTY_INJECT] Prepared {skin_data.summoner_name}'s skin: {label}")
    return name


def _local_custom_mod(relative_path: str, folder_name: str) -> Optional[ModSource]:
    """Our own copy of a friend's custom mod: a saved mod (LTK Manager's
    entry, or Rose's copy while it is pending), or a file nobody registered,
    linked as *folder_name* beside our own pick of it. None when it cannot be
    injected."""
    mods_root = get_mods_root()
    saved = find_saved_mod(mods_root, relative_path)
    if saved is not None:
        if not saved.available:
            return None
        source = saved.source
        return replace(source, name=folder_name) if isinstance(source, RoseFile) else source
    local_mod = mods_root / relative_path
    return RoseFile(local_mod, folder_name) if local_mod.exists() else None


def _resolve_skin_zip(skin_data: PartySkinData, injector, classic: bool = False) -> Optional[Path]:
    """Find the skin (or chroma) file of a party member's official skin"""
    skin_name = f"skin_{skin_data.skin_id}"

    if skin_data.chroma_id:
        zip_path = injector._resolve_zip(
            skin_name,
            chroma_id=skin_data.chroma_id,
            skin_name=skin_name,
            champion_name=None,
            champion_id=skin_data.champion_id,
            classic=classic,
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
        classic=classic,
    )
    if not zip_path or not zip_path.exists():
        log.warning(f"[PARTY_INJECT] Could not find skin ZIP for {skin_name}")
        return None
    return zip_path
