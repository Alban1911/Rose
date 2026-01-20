#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin Name Resolver
Resolves skin name for injection based on state (historic, random, or hovered)
"""

import logging
import time
from typing import Optional

from state import SharedState
from utils.core.logging import get_logger

log = get_logger()


class SkinNameResolver:
    """Resolves skin name for injection"""
    
    def __init__(self, state: SharedState, skin_scraper=None):
        """Initialize skin name resolver
        
        Args:
            state: Shared application state
            skin_scraper: Skin scraper instance
        """
        self.state = state
        self.skin_scraper = skin_scraper
        # Prevent log spam when UI state is not ready yet (this resolver can be polled frequently).
        self._no_skin_id_last_log_ts: float = 0.0
        self._no_skin_id_last_payload = None
        self._no_skin_id_suppressed: int = 0

    def _log_no_skin_id_available(self) -> None:
        """Rate-limit 'no skin id' logs to avoid spam in tight polling loops."""
        # Keep payload small but useful for diagnosis.
        payload = (
            getattr(self.state, "last_hovered_skin_id", None),
            getattr(self.state, "last_hovered_skin_key", None),
            getattr(self.state, "phase", None),
        )

        now = time.monotonic()
        interval_s = 2.0

        # If state changed, log immediately (and flush suppressed count).
        if payload != self._no_skin_id_last_payload:
            if self._no_skin_id_suppressed:
                log.debug(f"[INJECT] (suppressed {self._no_skin_id_suppressed} repeated 'no skin id' messages)")
            self._no_skin_id_last_payload = payload
            self._no_skin_id_last_log_ts = now
            self._no_skin_id_suppressed = 0
            log.debug(
                "[INJECT] No skin ID available yet "
                f"(last_hovered_skin_id={payload[0]}, last_hovered_skin_key={payload[1]}, phase={payload[2]})"
            )
            return

        # Same payload: rate limit.
        if (now - self._no_skin_id_last_log_ts) >= interval_s:
            suffix = f" (suppressed {self._no_skin_id_suppressed} repeats)" if self._no_skin_id_suppressed else ""
            self._no_skin_id_last_log_ts = now
            self._no_skin_id_suppressed = 0
            log.debug(
                "[INJECT] No skin ID available yet "
                f"(last_hovered_skin_id={payload[0]}, last_hovered_skin_key={payload[1]}, phase={payload[2]}){suffix}"
            )
        else:
            self._no_skin_id_suppressed += 1
    
    def resolve_injection_name(self) -> Optional[str]:
        """Resolve injection name based on current state
        
        Returns:
            Injection name (e.g., "skin_1234" or "chroma_5678") or None
        """
        # Historic mode override
        if getattr(self.state, 'historic_mode_active', False) and getattr(self.state, 'historic_skin_id', None):
            from utils.core.historic import is_custom_mod_path, get_custom_mod_path
            
            hist_value = self.state.historic_skin_id
            
            # Check if it's a custom mod path
            if is_custom_mod_path(hist_value):
                custom_mod_path = get_custom_mod_path(hist_value)
                log.info(f"[HISTORIC] Using historic custom mod path for injection: {custom_mod_path}")
                # Extract skin ID from mod path (format: skins/{skin_id}/{mod_name})
                # For example: "skins/887030/gwen-battle-queen-edited-chroma_2.1.0.fantome" -> 887030
                try:
                    path_parts = custom_mod_path.replace("\\", "/").split("/")
                    if len(path_parts) >= 2 and path_parts[0] == "skins":
                        skin_id_str = path_parts[1]
                        base_skin_id = int(skin_id_str)
                        base_skin_name = f"skin_{base_skin_id}"
                        log.info(f"[HISTORIC] Extracted base skin ID {base_skin_id} from mod path, returning: {base_skin_name}")
                        return base_skin_name
                    else:
                        log.warning(f"[HISTORIC] Invalid mod path format, expected 'skins/{{skin_id}}/...': {custom_mod_path}")
                except (ValueError, IndexError) as e:
                    log.warning(f"[HISTORIC] Failed to extract skin ID from mod path '{custom_mod_path}': {e}")
                # Fallback: try to use champion ID to get default skin
                champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
                if champ_id:
                    base_skin_id = champ_id * 1000
                    base_skin_name = f"skin_{base_skin_id}"
                    log.info(f"[HISTORIC] Fallback: Returning default skin for custom mod injection: {base_skin_name}")
                    return base_skin_name
                else:
                    log.warning(f"[HISTORIC] No champion ID available for custom mod path")
                    return None
            else:
                # It's a skin/chroma ID
                try:
                    hist_id = int(hist_value)
                    chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else None
                    if chroma_id_map and hist_id in chroma_id_map:
                        name = f"chroma_{hist_id}"
                        log.info(f"[HISTORIC] Using historic chroma ID for injection: {hist_id}")
                    else:
                        name = f"skin_{hist_id}"
                        log.info(f"[HISTORIC] Using historic skin ID for injection: {hist_id}")
                    return name
                except (ValueError, TypeError):
                    log.warning(f"[HISTORIC] Invalid historic value: {hist_value}")
                    return None
        
        # Random mode
        random_mode_active = getattr(self.state, 'random_mode_active', False)
        random_skin_name = getattr(self.state, 'random_skin_name', None)
        if random_mode_active and random_skin_name:
            random_skin_id = getattr(self.state, 'random_skin_id', None)
            if random_skin_id:
                if self.skin_scraper and self.skin_scraper.cache and random_skin_id in self.skin_scraper.cache.chroma_id_map:
                    name = f"chroma_{random_skin_id}"
                    log.info(f"[RANDOM] Injecting random chroma: {random_skin_name} (ID: {random_skin_id})")
                else:
                    name = f"skin_{random_skin_id}"
                    log.info(f"[RANDOM] Injecting random skin: {random_skin_name} (ID: {random_skin_id})")
                return name
            else:
                log.error(f"[RANDOM] No random skin ID available for injection")
                return None
        
        # Normal hovered skin
        skin_id = getattr(self.state, 'last_hovered_skin_id', None)
        if skin_id:
            from utils.core.utilities import is_base_skin
            chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else None
            
            if is_base_skin(skin_id, chroma_id_map):
                name = f"skin_{skin_id}"
                log.debug(f"[INJECT] Using base skin ID from state: '{name}' (ID: {skin_id})")
            else:
                name = f"chroma_{skin_id}"
                log.debug(f"[INJECT] Using chroma ID from state: '{name}' (chroma: {skin_id})")
            return name
        else:
            self._log_no_skin_id_available()
            return None
    
    def build_skin_label(self) -> Optional[str]:
        """Build clean skin label for logging
        
        Returns:
            Clean skin label or None
        """
        raw = self.state.last_hovered_skin_key or self.state.last_hovered_skin_slug \
            or (str(self.state.last_hovered_skin_id) if self.state.last_hovered_skin_id else None)
        
        if not raw:
            return None
        
        try:
            champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
            cname = ""
            if champ_id and self.skin_scraper and self.skin_scraper.cache.is_loaded_for_champion(champ_id):
                cname = self.skin_scraper.cache.champion_name or ""

            # Get skin name from LCU
            base = ""
            if self.state.last_hovered_skin_id and self.skin_scraper and self.skin_scraper.cache.is_loaded_for_champion(champ_id):
                skin_data = self.skin_scraper.cache.get_skin_by_id(self.state.last_hovered_skin_id)
                if skin_data:
                    base = skin_data.get('skinName', '').strip()
            
            if not base:
                base = (raw or "").strip()

            # Normalize spaces and apostrophes
            base_clean = base.replace(" ", " ").replace("'", "'")
            c_clean = (cname or "").replace(" ", " ").replace("'", "'")

            # Remove champion prefix if present
            if c_clean and base_clean.lower().startswith(c_clean.lower() + " "):
                base_clean = base_clean[len(c_clean) + 1:].lstrip()
            elif c_clean and base_clean.lower().endswith(" " + c_clean.lower()):
                base_clean = base_clean[:-(len(c_clean) + 1)].rstrip()

            # Check if champion name is already included
            nb = base_clean.lower().strip() if base_clean else ""
            nc = c_clean.lower().strip() if c_clean else ""
            if nc and (nc in nb.split()):
                final_label = base_clean
            else:
                final_label = (base_clean + (" " + c_clean if c_clean else "")).strip()
            
            return final_label
        except Exception:
            return raw or ""

