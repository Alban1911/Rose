#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin Processor
Handles processing skin names and mapping to IDs
"""

import logging
import time
import unicodedata
from typing import Optional

from config import SKIN_NAME_MIN_SIMILARITY
from utils.core.utilities import (
    get_base_skin_id_for_chroma,
    get_champion_id_from_skin_id,
)

log = logging.getLogger(__name__)


class SkinProcessor:
    """Processes skin names and updates shared state"""
    
    def __init__(self, shared_state, skin_scraper=None, skin_mapping=None):
        """Initialize skin processor
        
        Args:
            shared_state: Shared application state
            skin_scraper: LCU skin scraper instance
            skin_mapping: Skin mapping instance
        """
        self.shared_state = shared_state
        self.skin_scraper = skin_scraper
        self.skin_mapping = skin_mapping
        self.last_skin_name: Optional[str] = None
    
    def process_skin_name(self, skin_name: str, broadcaster=None) -> None:
        """Process a skin name and update shared state
        
        Args:
            skin_name: Skin name to process
            broadcaster: Optional broadcaster for sending updates
        """
        try:
            log.info("[SkinMonitor] Skin detected: '%s'", skin_name)
            self.shared_state.ui_last_text = skin_name
            self.shared_state.ui_last_text_champion_id = (
                getattr(self.shared_state, "locked_champ_id", None)
                or getattr(self.shared_state, "hovered_champ_id", None)
            )
            self.shared_state.ui_last_text_generation = getattr(
                self.shared_state, "champ_select_generation", 0
            )
            self.shared_state.ui_last_text_timestamp = time.monotonic()
            
            if getattr(self.shared_state, "is_swiftplay_mode", False):
                self._process_swiftplay_skin_name(skin_name, broadcaster)
            else:
                self._process_regular_skin_name(skin_name, broadcaster)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "[SkinMonitor] Error processing skin '%s': %s",
                skin_name,
                exc,
            )
    
    def _process_swiftplay_skin_name(self, skin_name: str, broadcaster=None) -> None:
        """Process skin name for Swiftplay mode"""
        if not self.skin_mapping:
            log.warning("[SkinMonitor] No skin mapping available for Swiftplay")
            return
        
        skin_id = self.skin_mapping.find_skin_id_by_name(skin_name)
        if skin_id is None:
            log.warning(
                "[SkinMonitor] Unable to map Swiftplay skin '%s' to ID",
                skin_name,
            )
            return
        
        champion_id = get_champion_id_from_skin_id(skin_id)
        if not champion_id:
            log.warning(
                "[SkinMonitor] Could not derive champion ID from skin %s — skipping tracking",
                skin_id,
            )
            return

        with self.shared_state.swiftplay_lock:
            self.shared_state.swiftplay_skin_tracking[champion_id] = skin_id
            tracking_snapshot = dict(self.shared_state.swiftplay_skin_tracking)
        self.shared_state.ui_skin_id = skin_id
        self.shared_state.last_hovered_skin_id = skin_id

        # Mark this champion as explicitly changed so the restore logic
        # won't override the user's choice on re-queue
        swiftplay_handler = getattr(self.shared_state, "swiftplay_handler", None)
        if swiftplay_handler is not None:
            swiftplay_handler.mark_champion_changed(champion_id)

        log.info(
            "[SkinMonitor] Swiftplay skin '%s' → champion %s (skin_id=%s) | tracking: %s",
            skin_name,
            champion_id,
            skin_id,
            tracking_snapshot,
        )
        
        if broadcaster:
            broadcaster.broadcast_skin_state(skin_name, skin_id)
    
    def _process_regular_skin_name(self, skin_name: str, broadcaster=None) -> None:
        """Process skin name for regular champion select"""
        if not self.skin_scraper:
            log.warning("[SkinMonitor] No skin scraper available")
            return
        
        result = self._find_skin_id(skin_name)
        if result is None:
            log.debug(
                "[SkinMonitor] No skin ID found for '%s' with current data",
                skin_name,
            )
            return
        
        skin_id, matched_name = result

        # The normal matcher maps localized chroma labels to their base skin.
        # Keep the explicitly selected chroma ID when the reported label is
        # that same chroma, otherwise the UI immediately falls back to the
        # base skin and the custom-mod wheel refreshes for the wrong target.
        selected_chroma_id = self._match_selected_chroma_id(skin_name)
        if selected_chroma_id is not None:
            chroma_data = self.skin_scraper.cache.chroma_id_map.get(selected_chroma_id, {})
            skin_id = selected_chroma_id
            matched_name = chroma_data.get("name") or matched_name
            log.debug(
                "[SkinMonitor] Preserving selected chroma %s from UI label '%s'",
                selected_chroma_id,
                skin_name,
            )


        # Reset chroma selection when switching to a different BASE skin.
        # Skin IDs are not numerically contiguous: 161002 and 161004 are
        # separate Vel'Koz skins, not chromas of one another.
        old_skin_id = self.shared_state.last_hovered_skin_id
        if old_skin_id is not None and old_skin_id != skin_id:
            chroma_id_map = None
            if self.skin_scraper and getattr(self.skin_scraper, "cache", None):
                chroma_id_map = getattr(self.skin_scraper.cache, "chroma_id_map", None)

            def base_skin_id(value: int) -> int:
                if chroma_id_map and value in chroma_id_map:
                    return get_base_skin_id_for_chroma(value, chroma_id_map) or value
                return value

            old_base_skin_id = base_skin_id(int(old_skin_id))
            new_base_skin_id = base_skin_id(int(skin_id))
            old_is_chroma = old_base_skin_id != int(old_skin_id)
            new_is_chroma = new_base_skin_id != int(skin_id)
            selected_chroma_is_current_skin = False
            try:
                selected_chroma_is_current_skin = (
                    int(self.shared_state.selected_chroma_id) == int(skin_id)
                )
            except (TypeError, ValueError):
                pass

            if (
                (
                    old_base_skin_id != new_base_skin_id
                    or (old_is_chroma and not new_is_chroma)
                )
                and not selected_chroma_is_current_skin
            ):
                # Different base skin - reset chroma selection. A chroma
                # selected through the Rose wheel is also reported as a skin
                # change, so preserve it when it is the newly detected skin.
                if self.shared_state.selected_chroma_id is not None:
                    log.debug(f"[CHROMA] Resetting selected_chroma_id on skin change ({old_skin_id} -> {skin_id})")
                    self.shared_state.selected_chroma_id = None

        self.shared_state.ui_skin_id = skin_id
        self.shared_state.last_hovered_skin_id = skin_id

        # Use the matched name from the matcher instead of the input
        self.shared_state.last_hovered_skin_key = matched_name
        log.info(
            "[SkinMonitor] Skin '%s' mapped to ID %s (key=%s)",
            skin_name,
            skin_id,
            self.shared_state.last_hovered_skin_key,
        )
        
        if broadcaster:
            # Broadcast the matched name, not the input name
            broadcaster.broadcast_skin_state(matched_name, skin_id)
    
    @staticmethod
    def _normalize_skin_label(value: object) -> str:
        """Normalize labels before comparing a selected chroma with UI text."""
        return " ".join(
            unicodedata.normalize("NFKC", str(value or "")).casefold().split()
        )

    def _match_selected_chroma_id(self, skin_name: str) -> Optional[int]:
        """Return the selected chroma when the UI reports that chroma label.

        The LCU skin matcher intentionally resolves chroma labels to their base
        skin. That is useful for normal skin tracking, but it must not erase an
        explicit chroma selection immediately after the chroma wheel reports it.
        """
        try:
            selected_chroma_id = int(self.shared_state.selected_chroma_id)
        except (TypeError, ValueError):
            return None

        cache = getattr(self.skin_scraper, "cache", None)
        chroma_id_map = getattr(cache, "chroma_id_map", None) if cache else None
        chroma_data = chroma_id_map.get(selected_chroma_id) if chroma_id_map else None
        if not isinstance(chroma_data, dict):
            return None

        incoming_label = self._normalize_skin_label(skin_name)
        known_labels = {
            self._normalize_skin_label(chroma_data.get("name")),
            self._normalize_skin_label(chroma_data.get("skinName")),
        }
        known_labels.discard("")
        if incoming_label in known_labels:
            return selected_chroma_id
        return None

    def _find_skin_id(self, skin_name: str) -> Optional[tuple[int, str]]:
        """Find skin ID and matched name using skin scraper
        
        Returns:
            Tuple of (skin_id, matched_name) if found, None otherwise
        """
        champ_id = getattr(self.shared_state, "locked_champ_id", None)
        if not champ_id:
            return None
        
        if not self.skin_scraper:
            return None
        
        try:
            if not self.skin_scraper.scrape_champion_skins(champ_id):
                return None
        except Exception:
            return None
        
        try:
            result = self.skin_scraper.find_skin_by_text(skin_name)
        except Exception:
            return None
        
        if result:
            skin_id, matched_name, similarity = result
            if similarity < SKIN_NAME_MIN_SIMILARITY:
                log.warning(
                    "[SkinMonitor] Rejecting weak match '%s' -> '%s' "
                    "(ID=%s, similarity=%.4f < %.4f)",
                    skin_name,
                    matched_name,
                    skin_id,
                    similarity,
                    SKIN_NAME_MIN_SIMILARITY,
                )
                return None
            log.info(
                "[SkinMonitor] Matched '%s' -> '%s' (ID=%s, similarity=%.4f)",
                skin_name,
                matched_name,
                skin_id,
                similarity,
            )
            return (skin_id, matched_name)
        else:
            log.warning(
                "[SkinMonitor] No match found for '%s'",
                skin_name
            )
        
        return None
    
    def clear_cache(self) -> None:
        """Clear cached state"""
        self.last_skin_name = None
        self.shared_state.ui_skin_id = None
        self.shared_state.ui_last_text = None
        self.shared_state.ui_last_text_champion_id = None
        self.shared_state.ui_last_text_generation = -1
        self.shared_state.ui_last_text_timestamp = 0.0

