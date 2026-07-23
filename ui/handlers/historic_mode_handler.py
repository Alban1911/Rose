#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Historic Mode Handler
Handles historic mode activation and deactivation
"""

from typing import Optional
from state import SharedState
from utils.core.logging import get_logger

log = get_logger()


def historic_custom_mod_affects_skin(state: SharedState, *skin_ids: object) -> bool:
    """Return whether the saved custom-mod history applies to any skin ID."""
    try:
        champion_id = getattr(state, "locked_champ_id", None)
        if champion_id is None:
            return False

        from utils.core.historic import (
            get_custom_mod_path,
            get_historic_skin_for_champion,
            is_custom_mod_path,
        )

        historic_value = get_historic_skin_for_champion(int(champion_id))
        if not is_custom_mod_path(historic_value):
            return False

        requested_ids = set()
        for skin_id in skin_ids:
            try:
                value = int(skin_id)
            except (TypeError, ValueError):
                continue
            if value > 0:
                requested_ids.add(value)
        if not requested_ids:
            return False

        custom_path = get_custom_mod_path(historic_value)
        if not custom_path:
            return False
        normalized_path = custom_path.replace(chr(92), "/").casefold()

        # Reuse the monitor's storage service. Constructing a new service here
        # would reconcile the entire mods library during a skin transition.
        storage = getattr(
            getattr(state, "ui_skin_thread", None),
            "mod_storage_service",
            None,
        )
        path_parts = custom_path.replace(chr(92), "/").split("/")
        storage_skin_id = None
        if len(path_parts) >= 2 and path_parts[0].casefold() == "skins":
            try:
                storage_skin_id = int(path_parts[1])
            except (TypeError, ValueError):
                storage_skin_id = None

        if storage is not None and storage_skin_id is not None:
            for entry in storage.list_mods_for_skin(storage_skin_id):
                try:
                    relative_path = str(entry.path.relative_to(storage.mods_root))
                except (ValueError, AttributeError):
                    continue
                if relative_path.replace(chr(92), "/").casefold() != normalized_path:
                    continue

                try:
                    affected_ids = {int(value) for value in (entry.affected_skin_ids or ())}
                except (AttributeError, TypeError, ValueError):
                    affected_ids = set()
                if not affected_ids:
                    try:
                        affected_ids.add(int(entry.skin_id))
                    except (AttributeError, TypeError, ValueError):
                        pass
                return bool(requested_ids & affected_ids)

        # Legacy fallback: at least recognize the storage skin encoded in the
        # saved path when the mod is temporarily unavailable.
        path_parts = custom_path.replace(chr(92), "/").split("/")
        if len(path_parts) >= 2 and path_parts[0].casefold() == "skins":
            try:
                return int(path_parts[1]) in requested_ids
            except (TypeError, ValueError):
                pass
    except Exception as exc:
        log.debug("[HISTORIC] Failed to resolve saved custom-mod targets: %s", exc)
    return False


class HistoricModeHandler:
    """Handles historic mode activation and deactivation"""
    
    def __init__(self, state: SharedState):
        """Initialize historic mode handler
        
        Args:
            state: Shared application state
        """
        self.state = state
    
    def check_and_activate(self, skin_id: int) -> None:
        """Check and activate historic mode if conditions are met"""
        if self.state.historic_first_detection_done or self.state.locked_champ_id is None:
            return
        
        # History may be restored while the client is already showing an
        # affected skin/chroma; do not require a default-skin spawn first.
        base_skin_id = self.state.locked_champ_id * 1000
        try:
            from utils.core.historic import (
                get_historic_skin_for_champion,
                is_custom_mod_path,
            )
            historic_value = get_historic_skin_for_champion(self.state.locked_champ_id)
            custom_mod_applies = historic_custom_mod_affects_skin(self.state, skin_id)

            if historic_value is not None and (
                skin_id == base_skin_id or custom_mod_applies
            ):
                self.state.historic_mode_active = True
                self.state.historic_skin_id = historic_value

                if is_custom_mod_path(historic_value):
                    log.info(f"[HISTORIC] Historic mode ACTIVATED for champion {self.state.locked_champ_id} (custom mod path: {historic_value})")
                else:
                    log.info(f"[HISTORIC] Historic mode ACTIVATED for champion {self.state.locked_champ_id} (historic skin ID: {historic_value})")

                try:
                    if self.state and hasattr(self.state, "ui_skin_thread") and self.state.ui_skin_thread:
                        self.state.ui_skin_thread._broadcast_historic_state()
                        log.debug("[HISTORIC] Broadcasted state to JavaScript")
                except Exception as e:
                    log.debug(f"[UI] Failed to broadcast historic state on activation: {e}")
            elif historic_value is None:
                log.debug(f"[HISTORIC] No historic entry found for champion {self.state.locked_champ_id}")
            else:
                log.debug(f"[HISTORIC] First detected skin is not the default or saved custom-mod target (skin_id={skin_id}, base={base_skin_id}) - historic mode not activated")
        except Exception as e:
            log.debug(f"[HISTORIC] Failed to check historic entry: {e}")

        # Mark first detection as done AFTER processing
        self.state.historic_first_detection_done = True
    
    def check_and_deactivate(self, skin_id: int, new_base_skin_id: Optional[int]) -> None:
        """Check and deactivate historic mode if skin changed from default"""
        if not self.state.historic_mode_active or self.state.locked_champ_id is None:
            return
        
        base_skin_id = self.state.locked_champ_id * 1000
        # Keep custom-mod history active when the selected skin/chroma is one
        # of the saved mod targets. The client is allowed to remain on that
        # real skin; history is only tracking the mod, not forcing base skin.
        if new_base_skin_id != base_skin_id and historic_custom_mod_affects_skin(
            self.state, skin_id, new_base_skin_id
        ):
            log.debug(
                "[HISTORIC] Keeping custom-mod history active for selected "
                "skin/chroma %s (base: %s)",
                skin_id,
                new_base_skin_id,
            )
            return

        if new_base_skin_id != base_skin_id:

            # Skin changed to a different base skin - deactivate historic mode
            self.state.historic_mode_active = False
            self.state.historic_skin_id = None
            log.info(f"[HISTORIC] Historic mode DEACTIVATED - skin changed from default to {skin_id} (base: {new_base_skin_id})")
            
            # Broadcast state to JavaScript
            try:
                if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                    self.state.ui_skin_thread._broadcast_historic_state()
            except Exception as e:
                log.debug(f"[UI] Failed to broadcast historic state on deactivation: {e}")

