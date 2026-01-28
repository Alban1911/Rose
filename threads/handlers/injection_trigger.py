#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Injection Trigger
Handles triggering skin injection based on countdown timer
"""

import logging
import threading
import time
from typing import Optional

from config import BASE_SKIN_VERIFICATION_WAIT_S, LOG_SEPARATOR_WIDTH
from lcu import LCU
from state import SharedState
from utils.core.issue_reporter import report_issue
from utils.core.logging import get_logger, log_action
from utils.core.safe_extract import safe_extractall

log = get_logger()


class InjectionTrigger:
    """Handles triggering skin injection"""
    
    def __init__(
        self,
        lcu: LCU,
        state: SharedState,
        injection_manager=None,
        skin_scraper=None,
    ):
        """Initialize injection trigger
        
        Args:
            lcu: LCU client instance
            state: Shared application state
            injection_manager: Injection manager instance
            skin_scraper: Skin scraper instance
        """
        self.lcu = lcu
        self.state = state
        self.injection_manager = injection_manager
        self.skin_scraper = skin_scraper
    
    def trigger_injection(self, name: str, ticker_id: int, cname: str = ""):
        """Trigger injection for a skin/chroma
        
        Args:
            name: Injection name (e.g., "skin_1234" or "chroma_5678")
            ticker_id: Ticker ID for logging
            cname: Champion name (optional)
        """
        if not name:
            log.error("=" * LOG_SEPARATOR_WIDTH)
            log.error(f"INJECTION FAILED - NO SKIN ID AVAILABLE")
            log.error(f"   Loadout Timer: #{ticker_id}")
            log.error("=" * LOG_SEPARATOR_WIDTH)
            return
        
        # Mark that we've processed the last hovered skin
        self.state.last_hover_written = True
        
        # Check if custom mod is selected for this skin (before logging)
        ui_skin_id = self.state.last_hovered_skin_id
        selected_custom_mod = getattr(self.state, 'selected_custom_mod', None)
        mod_name = None
        if selected_custom_mod and selected_custom_mod.get("skin_id") == ui_skin_id:
            mod_name = selected_custom_mod.get("mod_name") or selected_custom_mod.get("mod_folder_name")
        
        # Collect all selected mods for log message
        mod_labels = []
        if mod_name:
            mod_labels.append(f"{mod_name} (SKIN_{ui_skin_id})")
        else:
            mod_labels.append(name.upper())
        
        # Add map/font/announcer/other mods if selected
        selected_map_mod = getattr(self.state, 'selected_map_mod', None)
        if selected_map_mod:
            map_name = selected_map_mod.get("mod_name", "Map")
            mod_labels.append(f"MAP: {map_name}")
        
        selected_font_mod = getattr(self.state, 'selected_font_mod', None)
        if selected_font_mod:
            font_name = selected_font_mod.get("mod_name", "Font")
            mod_labels.append(f"FONT: {font_name}")
        
        selected_announcer_mod = getattr(self.state, 'selected_announcer_mod', None)
        if selected_announcer_mod:
            announcer_name = selected_announcer_mod.get("mod_name", "Announcer")
            mod_labels.append(f"ANNOUNCER: {announcer_name}")
        
        selected_other_mods = getattr(self.state, 'selected_other_mods', None)
        if not selected_other_mods:
            # Fallback to legacy single mod
            selected_other_mod = getattr(self.state, 'selected_other_mod', None)
            if selected_other_mod:
                selected_other_mods = [selected_other_mod]
        
        if selected_other_mods:
            other_names = [mod.get("mod_name", "Other") for mod in selected_other_mods]
            mod_labels.append(f"OTHER: {', '.join(other_names)}")
        
        # Build injection log message with all mods
        injection_label = " + ".join(mod_labels)
        
        log.info("=" * LOG_SEPARATOR_WIDTH)
        log.info(f"PREPARING INJECTION >>> {injection_label} <<<")
        log.info(f"   Loadout Timer: #{ticker_id}")
        log.info("=" * LOG_SEPARATOR_WIDTH)
        
        try:
            lcu_skin_id = self.state.selected_skin_id
            owned_skin_ids = self.state.owned_skin_ids
            
            # Auto-select previously used custom mods (so users don't need to open the Custom Mods UI)
            # - Skin custom mod: stored per champion in utils.core.historic as a "path:..."
            # - Map/font/announcer/other: stored globally in utils.core.mod_historic (mod_historic.json)
            historic_custom_mod_path = None
            if not selected_custom_mod:
                try:
                    from pathlib import Path
                    from utils.core.historic import get_historic_skin_for_champion, is_custom_mod_path, get_custom_mod_path

                    champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
                    historic_value = get_historic_skin_for_champion(champ_id) if champ_id else None
                    if historic_value and is_custom_mod_path(historic_value):
                        historic_custom_mod_path = get_custom_mod_path(historic_value)

                    # Only auto-select if the stored custom-mod path matches the skin we're injecting.
                    # This avoids injecting a random mod from another skin.
                    if historic_custom_mod_path:
                        path_parts = historic_custom_mod_path.replace("\\", "/").split("/")
                        if len(path_parts) >= 2 and path_parts[0] == "skins":
                            historic_skin_id = int(path_parts[1])
                            if ui_skin_id and historic_skin_id != int(ui_skin_id):
                                historic_custom_mod_path = None
                except Exception:
                    historic_custom_mod_path = None

            if not selected_custom_mod and historic_custom_mod_path:
                try:
                    from pathlib import Path
                    from injection.mods.storage import ModStorageService
                    mod_storage = ModStorageService()

                    # Extract skin ID from mod path (format: skins/{skin_id}/{mod_name})
                    path_parts = historic_custom_mod_path.replace("\\", "/").split("/")
                    if len(path_parts) >= 2 and path_parts[0] == "skins":
                        historic_skin_id = int(path_parts[1])

                        # Find the mod in storage
                        entries = mod_storage.list_mods_for_skin(historic_skin_id)
                        selected_mod_entry = None
                        for entry in entries:
                            # Match by relative path
                            relative_path = str(entry.path.relative_to(mod_storage.mods_root)).replace("\\", "/")
                            if relative_path == historic_custom_mod_path:
                                selected_mod_entry = entry
                                break

                        if selected_mod_entry:
                            # Determine mod folder name
                            mod_source = Path(selected_mod_entry.path)
                            if mod_source.is_dir():
                                mod_folder_name = mod_source.name
                            elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                                mod_folder_name = mod_source.stem
                            else:
                                mod_folder_name = mod_source.stem

                            # Get champion ID from skin ID
                            from utils.core.utilities import get_champion_id_from_skin_id
                            champion_id = get_champion_id_from_skin_id(historic_skin_id)

                            # Create selected_custom_mod dict (similar to _handle_select_skin_mod)
                            self.state.selected_custom_mod = {
                                "skin_id": historic_skin_id,
                                "champion_id": champion_id,
                                "mod_name": selected_mod_entry.mod_name,
                                "mod_path": str(selected_mod_entry.path),
                                "mod_folder_name": mod_folder_name,
                                "relative_path": historic_custom_mod_path,
                            }

                            # Update selected_custom_mod reference for this function
                            selected_custom_mod = self.state.selected_custom_mod

                            log.info(f"[HISTORIC] Auto-selected saved custom mod: {selected_mod_entry.mod_name} (skin {historic_skin_id})")
                        else:
                            log.warning(f"[HISTORIC] Saved custom mod not found in storage: {historic_custom_mod_path}")
                    else:
                        log.warning(f"[HISTORIC] Invalid saved custom mod path format: {historic_custom_mod_path}")
                except Exception as e:
                    log.warning(f"[HISTORIC] Failed to auto-select saved custom mod: {e}")
                    import traceback
                    log.debug(f"[HISTORIC] Traceback: {traceback.format_exc()}")
            
            # Auto-select saved mods (map, font, announcer, other) if not already selected
            # (These were previously only initialized when the Custom Mods UI was opened.)
            if self.injection_manager:
                try:
                    from utils.core.mod_historic import load_mod_historic
                    from injection.mods.storage import ModStorageService
                    import shutil
                    
                    mod_storage = ModStorageService()
                    historic_mods = load_mod_historic()
                    
                    # Helper function to auto-select a historic mod
                    def auto_select_historic_mod(mod_type: str, category_attr: str):
                        """Auto-select a historic mod by type"""
                        if not self.injection_manager:
                            return
                        
                        injector = self.injection_manager.injector
                        if not injector:
                            return
                        
                        historic_path = historic_mods.get(mod_type)
                        if not historic_path:
                            return

                        # For category-mods selection, historic data is stored per category key
                        # (ui/voiceover/loading_screen/vfx/sfx/others). We treat them together here.
                        if mod_type == "other":
                            historic_paths = []
                            for cat in ("ui", "voiceover", "loading_screen", "vfx", "sfx", "others"):
                                v = historic_mods.get(cat)
                                if isinstance(v, list):
                                    historic_paths.extend(v)
                                elif isinstance(v, str):
                                    historic_paths.append(v)
                            if not historic_paths:
                                return
                            
                            # Check if already selected
                            selected_other_mods = getattr(self.state, 'selected_other_mods', None)
                            if selected_other_mods and len(selected_other_mods) > 0:
                                return
                            
                            valid_other_mods = []
                            for historic_path_item in historic_paths:
                                try:
                                    # Category mods are stored as relative paths like "vfx/...", "ui/...", etc.
                                    # Infer category from the first path segment so ALL categories work.
                                    hp = str(historic_path_item).replace("\\", "/").lstrip("/")
                                    category_id = (hp.split("/", 1)[0] if "/" in hp else hp).strip().lower()
                                    allowed_categories = {
                                        mod_storage.CATEGORY_UI,
                                        mod_storage.CATEGORY_VOICEOVER,
                                        mod_storage.CATEGORY_LOADING_SCREEN,
                                        mod_storage.CATEGORY_VFX,
                                        mod_storage.CATEGORY_SFX,
                                        mod_storage.CATEGORY_OTHERS,
                                    }
                                    if category_id not in allowed_categories:
                                        category_id = mod_storage.CATEGORY_OTHERS

                                    entries = mod_storage.list_mods_for_category(category_id)

                                    # Find the mod by matching relative path
                                    selected_mod_entry = None
                                    for entry_dict in entries:
                                        entry_id = entry_dict.get("id") or ""
                                        if entry_id.replace("\\", "/") == str(historic_path_item).replace("\\", "/"):
                                            # Found the mod - construct full path
                                            entry_path_str = entry_dict.get("path", "").replace("/", "\\")
                                            mod_path = mod_storage.mods_root / entry_path_str
                                            selected_mod_entry = type('ModEntry', (), {
                                                'mod_name': entry_dict.get("name", ""),
                                                'path': mod_path
                                            })()
                                            break
                                    
                                    if not selected_mod_entry:
                                        log.debug(f"[HISTORIC] Historic other mod not found in storage: {historic_path_item}")
                                        continue
                                    
                                    mod_source = Path(selected_mod_entry.path)
                                    if not mod_source.exists():
                                        log.info(f"[HISTORIC] Historic other mod file not found (mod may have been deleted), ignoring: {mod_source}")
                                        continue
                                    
                                    # Determine mod folder name
                                    if mod_source.is_dir():
                                        mod_folder_name = mod_source.name
                                    elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                                        mod_folder_name = mod_source.stem
                                    else:
                                        mod_folder_name = mod_source.stem
                                    
                                    # Extract/copy mod to injection mods directory
                                    if mod_source.is_dir():
                                        mod_dest = injector.mods_dir / mod_source.name
                                        if mod_dest.exists():
                                            shutil.rmtree(mod_dest, ignore_errors=True)
                                        shutil.copytree(mod_source, mod_dest, dirs_exist_ok=True)
                                        log.info(f"[HISTORIC] Copied other mod directory to: {mod_dest}")
                                    elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                                        mod_dest = injector.mods_dir / mod_source.stem
                                        if mod_dest.exists():
                                            shutil.rmtree(mod_dest, ignore_errors=True)
                                        mod_dest.mkdir(parents=True, exist_ok=True)
                                        # Security: Use safe extraction to prevent path traversal attacks
                                        safe_extractall(mod_source, mod_dest)
                                        file_type = "ZIP" if mod_source.suffix.lower() == ".zip" else "FANTOME"
                                        log.info(f"[HISTORIC] Extracted {file_type} other mod to: {mod_dest}")
                                    else:
                                        mod_dest = injector.mods_dir / mod_folder_name
                                        if mod_dest.exists():
                                            shutil.rmtree(mod_dest, ignore_errors=True)
                                        mod_dest.mkdir(parents=True, exist_ok=True)
                                        shutil.copy2(mod_source, mod_dest / mod_source.name)
                                        log.info(f"[HISTORIC] Copied other mod file to folder: {mod_dest}")
                                    
                                    # Add to valid mods list
                                    valid_other_mods.append({
                                        "mod_name": selected_mod_entry.mod_name,
                                        "mod_path": str(selected_mod_entry.path),
                                        "mod_folder_name": mod_folder_name,
                                        "relative_path": str(historic_path_item),
                                    })
                                    
                                    log.info(f"[HISTORIC] Auto-selected historic other mod: {selected_mod_entry.mod_name}")
                                except Exception as e:
                                    log.warning(f"[HISTORIC] Failed to auto-select historic other mod {historic_path_item}: {e}")
                                    import traceback
                                    log.debug(f"[HISTORIC] Traceback: {traceback.format_exc()}")
                            
                            # Store all valid other mods in shared state
                            if valid_other_mods:
                                self.state.selected_other_mods = valid_other_mods
                                log.info(f"[HISTORIC] Auto-selected {len(valid_other_mods)} historic other mod(s)")
                            
                            # Update historic if some mods were missing
                            if len(valid_other_mods) != len(historic_paths):
                                try:
                                    from utils.core.mod_historic import write_historic_mod
                                    if valid_other_mods:
                                        valid_paths = [mod["relative_path"] for mod in valid_other_mods]
                                        write_historic_mod("other", valid_paths)
                                    else:
                                        from utils.core.mod_historic import clear_historic_mod
                                        clear_historic_mod("other")
                                except Exception as e:
                                    log.debug(f"[HISTORIC] Failed to update historic other mods: {e}")
                            
                            return
                        
                        # For other mod types (map, font, announcer), handle single mod
                        # Check if already selected
                        selected_attr = f'selected_{mod_type}_mod'
                        if getattr(self.state, selected_attr, None):
                            return
                        
                        try:
                            # Get mods for this category
                            category = getattr(mod_storage, category_attr)
                            entries = mod_storage.list_mods_for_category(category)
                            
                            # Find the mod by matching relative path
                            selected_mod_entry = None
                            for entry_dict in entries:
                                entry_id = entry_dict.get("id") or ""
                                if entry_id.replace("\\", "/") == str(historic_path).replace("\\", "/"):
                                    # Found the mod - construct full path
                                    entry_path_str = entry_dict.get("path", "").replace("/", "\\")
                                    mod_path = mod_storage.mods_root / entry_path_str
                                    selected_mod_entry = type('ModEntry', (), {
                                        'mod_name': entry_dict.get("name", ""),
                                        'path': mod_path
                                    })()
                                    break
                            
                            if not selected_mod_entry:
                                log.debug(f"[HISTORIC] Historic {mod_type} mod not found in storage: {historic_path}")
                                return
                            
                            mod_source = Path(selected_mod_entry.path)
                            if not mod_source.exists():
                                log.info(f"[HISTORIC] Historic {mod_type} mod file not found (mod may have been deleted), ignoring: {mod_source}")
                                # Clear the historic mod entry since the mod no longer exists
                                try:
                                    from utils.core.mod_historic import clear_historic_mod
                                    clear_historic_mod(mod_type)
                                    log.debug(f"[HISTORIC] Cleared historic {mod_type} mod entry")
                                except Exception as e:
                                    log.debug(f"[HISTORIC] Failed to clear historic {mod_type} mod entry: {e}")
                                return
                            
                            # Determine mod folder name
                            if mod_source.is_dir():
                                mod_folder_name = mod_source.name
                            elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                                mod_folder_name = mod_source.stem
                            else:
                                mod_folder_name = mod_source.stem
                            
                            # Extract/copy mod to injection mods directory
                            if mod_source.is_dir():
                                mod_dest = injector.mods_dir / mod_source.name
                                if mod_dest.exists():
                                    shutil.rmtree(mod_dest, ignore_errors=True)
                                shutil.copytree(mod_source, mod_dest, dirs_exist_ok=True)
                                log.info(f"[HISTORIC] Copied {mod_type} mod directory to: {mod_dest}")
                            elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                                mod_dest = injector.mods_dir / mod_source.stem
                                if mod_dest.exists():
                                    shutil.rmtree(mod_dest, ignore_errors=True)
                                mod_dest.mkdir(parents=True, exist_ok=True)
                                # Security: Use safe extraction to prevent path traversal attacks
                                safe_extractall(mod_source, mod_dest)
                                file_type = "ZIP" if mod_source.suffix.lower() == ".zip" else "FANTOME"
                                log.info(f"[HISTORIC] Extracted {file_type} {mod_type} mod to: {mod_dest}")
                            else:
                                mod_dest = injector.mods_dir / mod_folder_name
                                if mod_dest.exists():
                                    shutil.rmtree(mod_dest, ignore_errors=True)
                                mod_dest.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(mod_source, mod_dest / mod_source.name)
                                log.info(f"[HISTORIC] Copied {mod_type} mod file to folder: {mod_dest}")
                            
                            # Store selected mod in shared state
                            setattr(self.state, selected_attr, {
                                "mod_name": selected_mod_entry.mod_name,
                                "mod_path": str(selected_mod_entry.path),
                                "mod_folder_name": mod_folder_name,
                                "relative_path": str(historic_path),
                            })
                            
                            log.info(f"[HISTORIC] Auto-selected historic {mod_type} mod: {selected_mod_entry.mod_name}")
                        except Exception as e:
                            log.warning(f"[HISTORIC] Failed to auto-select historic {mod_type} mod: {e}")
                            import traceback
                            log.debug(f"[HISTORIC] Traceback: {traceback.format_exc()}")
                    
                    # Auto-select each historic mod type
                    auto_select_historic_mod("map", "CATEGORY_MAPS")
                    auto_select_historic_mod("font", "CATEGORY_FONTS")
                    auto_select_historic_mod("announcer", "CATEGORY_ANNOUNCERS")
                    auto_select_historic_mod("other", "CATEGORY_OTHERS")
                except Exception as e:
                    log.warning(f"[HISTORIC] Failed to auto-select historic mods: {e}")
                    import traceback
                    log.debug(f"[HISTORIC] Traceback: {traceback.format_exc()}")
            
            # Check if any mods are selected (skin, map, font, announcer, or other)
            selected_map_mod = getattr(self.state, 'selected_map_mod', None)
            selected_font_mod = getattr(self.state, 'selected_font_mod', None)
            selected_announcer_mod = getattr(self.state, 'selected_announcer_mod', None)
            selected_other_mods = getattr(self.state, 'selected_other_mods', None)
            if not selected_other_mods:
                # Fallback to legacy single mod
                selected_other_mod = getattr(self.state, 'selected_other_mod', None)
                if selected_other_mod:
                    selected_other_mods = [selected_other_mod]
            
            # Check if custom skin mod is selected
            # In historic mode, use the historic skin ID; otherwise use hovered skin ID
            target_skin_id = ui_skin_id
            if getattr(self.state, 'historic_mode_active', False) and selected_custom_mod:
                # Use the skin ID from the selected custom mod (which is the historic skin ID)
                target_skin_id = selected_custom_mod.get("skin_id", ui_skin_id)
            
            has_custom_skin_mod = selected_custom_mod and selected_custom_mod.get("skin_id") == target_skin_id
            has_other_mods = selected_map_mod or selected_font_mod or selected_announcer_mod or (selected_other_mods and len(selected_other_mods) > 0)
            has_any_mods = has_custom_skin_mod or has_other_mods
            
            # If custom skin mod is selected, inject it
            if has_custom_skin_mod:
                # Check if skin is owned (use target_skin_id which is the historic skin ID in historic mode)
                is_skin_owned = target_skin_id in owned_skin_ids
                
                if not is_skin_owned:
                    # Skin not owned: need to inject base skin ZIP + custom mod
                    log.info(f"[INJECT] Custom mod selected for unowned skin {target_skin_id}, injecting base skin ZIP + custom mod")
                    self._inject_custom_mod(selected_custom_mod, base_skin_name=name, champion_name=cname)
                else:
                    # Skin owned: just inject custom mod (base files already in game)
                    log.info(f"[INJECT] Custom mod selected for owned skin {target_skin_id}, injecting custom mod only")
                    self._inject_custom_mod(selected_custom_mod)
                return
            
            # If only map/font/announcer/other mods are selected (no custom skin mod), inject them
            if has_other_mods and not has_custom_skin_mod:
                # Create a dummy custom mod dict to use the injection path
                dummy_custom_mod = {
                    "skin_id": ui_skin_id,
                    "champion_id": self.state.locked_champ_id or self.state.hovered_champ_id,
                    "mod_name": name.upper(),
                    "mod_folder_name": None,  # No custom skin mod, only map/font/announcer/other
                }
                # Build list of selected mod types for logging
                selected_mod_types = []
                if selected_map_mod:
                    selected_mod_types.append("Map")
                if selected_font_mod:
                    selected_mod_types.append("Font")
                if selected_announcer_mod:
                    selected_mod_types.append("Announcer")
                selected_other_mods = getattr(self.state, 'selected_other_mods', None)
                if not selected_other_mods:
                    # Fallback to legacy single mod
                    selected_other_mod = getattr(self.state, 'selected_other_mod', None)
                    if selected_other_mod:
                        selected_other_mods = [selected_other_mod]
                if selected_other_mods and len(selected_other_mods) > 0:
                    selected_mod_types.append("Other")
                mod_types_str = "/".join(selected_mod_types) if selected_mod_types else "Map/Font/Announcer/Other"
                
                # Check if skin needs to be injected (if unowned, inject base skin ZIP along with map/font/announcer/other mods)
                is_skin_owned = ui_skin_id in owned_skin_ids
                base_skin_name_for_injection = None
                if not is_skin_owned and ui_skin_id != 0:
                    # Skin is unowned, need to inject base skin ZIP along with map/font/announcer/other mods
                    base_skin_name_for_injection = name
                    log.info(f"[INJECT] {mod_types_str} mod(s) selected + unowned skin {ui_skin_id}, injecting base skin ZIP + {mod_types_str.lower()} mod(s)")
                else:
                    # Skin is owned - user can select it normally, just inject the mods
                    log.info(f"[INJECT] {mod_types_str} mod(s) selected, injecting them (skin: {name})")
                
                self._inject_custom_mod(dummy_custom_mod, base_skin_name=base_skin_name_for_injection, champion_name=cname)
                return
            
            # Skip injection for base skins (only if no mods are selected)
            if ui_skin_id == 0:
                log.info("[INJECT] skipping base skin injection (skinId=0) - no mods-only flow available")
                if self.injection_manager:
                    self.injection_manager.resume_if_suspended()
            
            # Force owned skins/chromas via LCU
            elif ui_skin_id in owned_skin_ids:
                self._force_owned_skin(ui_skin_id)
            
            # Inject if user doesn't own the hovered skin
            elif self.injection_manager:
                self._inject_unowned_skin(name, cname)
        
        except Exception as e:
            log.warning(f"[loadout #{ticker_id}] injection setup failed: {e}")
    
    def _force_owned_skin(self, skin_id: int):
        """Force owned skin/chroma selection via LCU"""
        log.info(f"[INJECT] User owns this skin/chroma (skinId={skin_id}), forcing selection via LCU")
        
        champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
        if champ_id and self.lcu:
            target_skin_id = skin_id
            log.info(f"[INJECT] Forcing owned skin/chroma (skinId={target_skin_id})")
            
            forced_successfully = False
            
            # Find the user's action ID to update
            try:
                sess = self.lcu.session or {}
                actions = sess.get("actions") or []
                my_cell = self.state.local_cell_id
                
                action_found = False
                is_action_completed = False
                
                for rnd in actions:
                    for act in rnd:
                        if act.get("actorCellId") == my_cell and act.get("type") == "pick":
                            action_id = act.get("id")
                            is_action_completed = act.get("completed", False)
                            action_found = True
                            
                            if not is_action_completed:
                                if action_id is not None:
                                    if self.lcu.set_selected_skin(action_id, target_skin_id):
                                        log.info(f"[INJECT] Owned skin/chroma forced via action")
                                        forced_successfully = True
                                    else:
                                        log.debug(f"[INJECT] Action-based approach failed")
                            break
                    if action_found:
                        break
                
                # Try my-selection endpoint if action-based failed
                if not forced_successfully:
                    if self.lcu.set_my_selection_skin(target_skin_id):
                        log.info(f"[INJECT] Owned skin/chroma forced via my-selection")
                        forced_successfully = True
                    else:
                        log.warning(f"[INJECT] Failed to force owned skin/chroma")
                
                # Verify the change
                if forced_successfully:
                    if not getattr(self.state, 'random_mode_active', False):
                        time.sleep(BASE_SKIN_VERIFICATION_WAIT_S)
                        verify_sess = self.lcu.session or {}
                        verify_team = verify_sess.get("myTeam") or []
                        for player in verify_team:
                            if player.get("cellId") == my_cell:
                                current_skin = player.get("selectedSkinId")
                                if current_skin == target_skin_id:
                                    log.info(f"[INJECT] Owned skin/chroma verified: {current_skin}")
                                else:
                                    log.warning(f"[INJECT] Verification failed: {current_skin} != {target_skin_id}")
                                break
                    else:
                        log.info(f"[INJECT] Skipping verification wait in random mode")
            
            except Exception as e:
                log.warning(f"[INJECT] Error forcing owned skin/chroma: {e}")
            
            # Resume game if suspended
            if self.injection_manager:
                try:
                    self.injection_manager.resume_if_suspended()
                except Exception as e:
                    log.warning(f"[INJECT] Failed to resume game after forcing owned skin: {e}")
    
    def _inject_unowned_skin(self, name: str, cname: str):
        """Inject unowned skin/chroma"""
        try:
            # Force base skin selection via LCU before injecting
            champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
            if champ_id:
                base_skin_id = champ_id * 1000
                
                # Read actual current selection from LCU session
                actual_lcu_skin_id = None
                try:
                    sess = self.lcu.session or {}
                    my_team = sess.get("myTeam") or []
                    my_cell = self.state.local_cell_id
                    for player in my_team:
                        if player.get("cellId") == my_cell:
                            actual_lcu_skin_id = player.get("selectedSkinId")
                            if actual_lcu_skin_id is not None:
                                actual_lcu_skin_id = int(actual_lcu_skin_id)
                            break
                except Exception as e:
                    log.debug(f"[INJECT] Failed to read actual LCU skin ID: {e}")
                
                # Only force base skin if current selection is not already base skin
                if actual_lcu_skin_id is None or actual_lcu_skin_id != base_skin_id:
                    self._force_base_skin(base_skin_id)
            
            # Create callback to check if game ended
            has_been_in_progress = False

            def game_ended_callback():
                nonlocal has_been_in_progress
                phase = self.state.phase
                if phase == "InProgress":
                    has_been_in_progress = True
                    return False
                if phase in ("Reconnect", "GameStart"):
                    return False
                return has_been_in_progress and phase not in ("InProgress", "Reconnect", "GameStart")
            
            # Inject skin in a separate thread
            log.info(f"[INJECT] Starting injection: {name}")
            
            champ_id_for_history = self.state.locked_champ_id

            def run_injection():
                try:
                    if not self.lcu.ok:
                        log.warning(f"[INJECT] LCU not available, skipping injection")
                        return
                    
                    success = self.injection_manager.inject_skin_immediately(
                        name,
                        stop_callback=game_ended_callback,
                        champion_name=cname,
                        champion_id=self.state.locked_champ_id
                    )
                    
                    # Clear random state after injection
                    if getattr(self.state, 'random_mode_active', False):
                        self.state.random_skin_name = None
                        self.state.random_skin_id = None
                        self.state.random_mode_active = False
                        log.info("[RANDOM] Random mode cleared after injection")
                    
                    if success:
                        # Persist historic entry
                        try:
                            injected_id = None
                            if isinstance(name, str) and '_' in name:
                                parts = name.split('_', 1)
                                if len(parts) == 2 and parts[1].isdigit():
                                    injected_id = int(parts[1])
                            champ_id = champ_id_for_history
                            if champ_id is not None and injected_id is not None:
                                from utils.core.historic import write_historic_entry
                                write_historic_entry(int(champ_id), int(injected_id))
                                log.info(f"[HISTORIC] Stored last injected ID {injected_id} for champion {champ_id}")
                        except Exception as e:
                            log.debug(f"[HISTORIC] Failed to store historic entry: {e}")
                        
                        # Clean up missing mods from historic after injection completes
                        try:
                            from utils.core.mod_historic import get_historic_mod, clear_historic_mod
                            from injection.mods.storage import ModStorageService
                            
                            mod_storage = ModStorageService()
                            mods_root = mod_storage.mods_root
                            
                            # Helper to check if a mod file exists
                            def mod_file_exists(relative_path: str) -> bool:
                                try:
                                    full_path = mods_root / relative_path.replace("/", "\\")
                                    return full_path.exists()
                                except Exception:
                                    return False
                            
                            # Check and clean map mod
                            historic_map_path = get_historic_mod("map")
                            if historic_map_path and not mod_file_exists(historic_map_path):
                                clear_historic_mod("map")
                                log.info(f"[MOD_HISTORIC] Cleaned missing map mod from historic: {historic_map_path}")
                            
                            # Check and clean font mod
                            historic_font_path = get_historic_mod("font")
                            if historic_font_path and not mod_file_exists(historic_font_path):
                                clear_historic_mod("font")
                                log.info(f"[MOD_HISTORIC] Cleaned missing font mod from historic: {historic_font_path}")
                            
                            # Check and clean announcer mod
                            historic_announcer_path = get_historic_mod("announcer")
                            if historic_announcer_path and not mod_file_exists(historic_announcer_path):
                                clear_historic_mod("announcer")
                                log.info(f"[MOD_HISTORIC] Cleaned missing announcer mod from historic: {historic_announcer_path}")
                            
                            # Check and clean other mods
                            historic_other_paths = get_historic_mod("other")
                            if historic_other_paths:
                                if isinstance(historic_other_paths, str):
                                    historic_other_paths = [historic_other_paths]
                                elif not isinstance(historic_other_paths, list):
                                    historic_other_paths = []
                                
                                cleaned_paths = [path for path in historic_other_paths if mod_file_exists(path)]
                                
                                if len(cleaned_paths) != len(historic_other_paths):
                                    from utils.core.mod_historic import write_historic_mod
                                    if cleaned_paths:
                                        write_historic_mod("other", cleaned_paths)
                                        removed_count = len(historic_other_paths) - len(cleaned_paths)
                                        log.info(f"[MOD_HISTORIC] Cleaned {removed_count} missing other mod(s) from historic")
                                    else:
                                        clear_historic_mod("other")
                                        log.info(f"[MOD_HISTORIC] Cleared historic other mods (all were missing)")
                        except Exception as e:
                            log.debug(f"[MOD_HISTORIC] Failed to clean up missing mods from historic: {e}")
                        
                        log.info("=" * LOG_SEPARATOR_WIDTH)
                        log.info(f"INJECTION COMPLETED >>> {name.upper()} <<<")
                        log.info(f"   Verify in-game - timing determines if skin appears")
                        log.info("=" * LOG_SEPARATOR_WIDTH)
                    else:
                        log.error("=" * LOG_SEPARATOR_WIDTH)
                        log.error(f"INJECTION FAILED >>> {name.upper()} <<<")
                        log.error("=" * LOG_SEPARATOR_WIDTH)
                        log.error(f"[INJECT] Skin will likely NOT appear in-game")
                    
                    # Request UI destruction after injection
                    try:
                        from ui.core.user_interface import get_user_interface
                        user_interface = get_user_interface(self.state, self.skin_scraper)
                        user_interface.request_ui_destruction()
                        log_action(log, "UI destruction requested after injection completion", "")
                    except Exception as e:
                        log.warning(f"[INJECT] Failed to request UI destruction after injection: {e}")
                except Exception as e:
                    log.error(f"[INJECT] injection thread error: {e}")
            
            injection_thread = threading.Thread(target=run_injection, daemon=True, name="InjectionThread")
            injection_thread.start()
        
        except Exception as e:
            log.error(f"[INJECT] injection error: {e}")
    
    def _force_base_skin(self, base_skin_id: int):
        """Force base skin selection via LCU"""
        log.info(f"[INJECT] Forcing base skin (skinId={base_skin_id})")
        
        # Hide chroma border/wheel immediately
        try:
            from ui.core.user_interface import get_user_interface
            user_interface = get_user_interface(self.state, self.skin_scraper)
            if user_interface.is_ui_initialized():
                user_interface._schedule_hide_all_on_main_thread()
                log.info("[INJECT] UI hiding scheduled - base skin forced for injection")
        except Exception as e:
            log.warning(f"[INJECT] Failed to schedule UI hide: {e}")
            import traceback
            log.warning(f"[INJECT] UI hide traceback: {traceback.format_exc()}")
        
        base_skin_set_successfully = False
        # Measure just the "force base skin" operation time (LCU PATCH + champ-select action selection),
        # not the later verification sleep.
        t_force0 = time.perf_counter()
        
        try:
            sess = self.lcu.session or {}
            actions = sess.get("actions") or []
            my_cell = self.state.local_cell_id
            
            action_found = False
            is_action_completed = False
            
            for rnd in actions:
                for act in rnd:
                    if act.get("actorCellId") == my_cell and act.get("type") == "pick":
                        action_id = act.get("id")
                        is_action_completed = act.get("completed", False)
                        action_found = True
                        
                        if not is_action_completed:
                            if action_id is not None:
                                if self.lcu.set_selected_skin(action_id, base_skin_id):
                                    log.info(f"[INJECT] Base skin forced via action")
                                    base_skin_set_successfully = True
                                else:
                                    log.debug(f"[INJECT] Action-based approach failed")
                        break
                if action_found:
                    break
            
            # Try my-selection endpoint if action-based failed
            if not base_skin_set_successfully:
                if self.lcu.set_my_selection_skin(base_skin_id):
                    log.info(f"[INJECT] Base skin forced via my-selection")
                    base_skin_set_successfully = True
                else:
                    log.warning(f"[INJECT] Failed to force base skin")

            # Emit timing info (INFO so it shows up in normal customer logs).
            # Also, if forcing base skin was slow compared to injection threshold, write an issue entry.
            # This helps diagnose cases where LCU is laggy and skin injection timing gets tight.
            dt_force_s = None
            threshold_s = None
            if base_skin_set_successfully:
                try:
                    if self.injection_manager is not None:
                        threshold_s = float(getattr(self.injection_manager, "injection_threshold", 0.0))
                    else:
                        from config import get_config_float
                        threshold_s = float(get_config_float("General", "injection_threshold", 0.5))

                    dt_force_s = float(time.perf_counter() - t_force0)
                    log.info(f"[INJECT] Base skin force time: {dt_force_s:.3f}s (threshold: {threshold_s:.3f}s)")

                    if dt_force_s > threshold_s:
                        report_issue(
                            "BASE_SKIN_FORCE_SLOW",
                            "error",
                            "Base skin forcing took longer than your injection threshold.",
                            hint=f"Base skin force time: {dt_force_s:.3f}s, injection threshold: {threshold_s:.3f}s. Consider increasing Injection Threshold.",
                            dedupe_window_s=60.0,
                        )
                except Exception:
                    pass
            
            # Verify the change
            if base_skin_set_successfully:
                if not getattr(self.state, 'random_mode_active', False):
                    time.sleep(BASE_SKIN_VERIFICATION_WAIT_S)
                    verify_sess = self.lcu.session or {}
                    verify_team = verify_sess.get("myTeam") or []
                    for player in verify_team:
                        if player.get("cellId") == my_cell:
                            current_skin = player.get("selectedSkinId")
                            if current_skin != base_skin_id:
                                log.warning(f"[INJECT] Base skin verification failed: {current_skin} != {base_skin_id}")
                                try:
                                    # Reuse the same "recommended threshold" logic (based on observed base-skin force time)
                                    # by emitting a hint line that includes both values in the same format as BASE_SKIN_FORCE_SLOW.
                                    hint = "Retry your skin selection. If the warning persists, increase Injection Threshold."
                                    if isinstance(dt_force_s, (int, float)) and isinstance(threshold_s, (int, float)):
                                        hint = (
                                            f"Base skin force time: {float(dt_force_s):.3f}s, "
                                            f"injection threshold: {float(threshold_s):.3f}s. "
                                            f"Increase Injection Threshold until the warning is gone, then retry."
                                        )
                                    report_issue(
                                        "BASE_SKIN_VERIFY_FAILED",
                                        "warning",
                                        "Base skin verification failed (selected skin may not apply).",
                                        hint=hint,
                                        details={
                                            "expected_skin_id": str(base_skin_id),
                                            "actual_skin_id": str(current_skin),
                                        },
                                        dedupe_window_s=60.0,
                                    )
                                except Exception:
                                    pass
                            else:
                                log.info(f"[INJECT] Base skin verified: {current_skin}")
                            break
                else:
                    log.info(f"[INJECT] Skipping base skin verification wait in random mode")
            else:
                log.warning(f"[INJECT] Failed to force base skin - injection may fail")
        
        except Exception as e:
            log.error(f"[INJECT] Error forcing base skin: {e}")
            import traceback
            log.error(f"[INJECT] Traceback: {traceback.format_exc()}")
    
    def _inject_custom_mod(self, custom_mod: dict, base_skin_name: Optional[str] = None, champion_name: str = ""):
        """Inject custom mod from mods storage (mod should already be extracted)
        
        Args:
            custom_mod: Custom mod dictionary
            base_skin_name: Optional base skin name to extract and inject (for unowned skins)
            champion_name: Optional champion name for base skin extraction
        
        Note: custom_mod can have mod_folder_name=None if only map/font/announcer mods are selected
        """
        try:
            from pathlib import Path
            
            if not self.injection_manager:
                log.error("[INJECT] Cannot inject custom mod - injection manager not available")
                return
            
            injector = self.injection_manager.injector
            if not injector:
                log.error("[INJECT] Cannot inject custom mod - injector not available")
                return
            
            mod_name = custom_mod.get("mod_name")
            mod_folder_name = custom_mod.get("mod_folder_name")
            mod_path = custom_mod.get("mod_path")
            skin_id = custom_mod.get("skin_id")
            champion_id = custom_mod.get("champion_id")
            
            # Clean mods directory first (before extracting base skin and custom mod)
            injector._clean_mods_dir()
            injector._clean_overlay_dir()
            
            # Collect all mods to inject (base skin + custom skin mod + map + font + announcer + other)
            mod_folder_names = []
            mod_names_list = []
            # Track missing mods to clean up from historic
            missing_map_mod_path = None
            missing_font_mod_path = None
            missing_announcer_mod_path = None
            missing_other_mod_paths = []
            
            # Extract and add base skin ZIP if provided (for unowned skins)
            if base_skin_name:
                log.info(f"[INJECT] Extracting base skin ZIP: {base_skin_name}")
                try:
                    # Resolve the base skin ZIP
                    zp = injector._resolve_zip(
                        base_skin_name,
                        skin_name=base_skin_name,
                        champion_name=champion_name,
                        champion_id=champion_id
                    )
                    if zp and zp.exists():
                        # Extract base skin ZIP to mods directory
                        base_mod_folder = injector._extract_zip_to_mod(zp)
                        if base_mod_folder:
                            mod_folder_names.append(base_mod_folder.name)
                            mod_names_list.append(f"Base Skin ({base_skin_name})")
                            log.info(f"[INJECT] Base skin ZIP extracted: {base_mod_folder.name}")
                        else:
                            log.warning(f"[INJECT] Failed to extract base skin ZIP: {base_skin_name}")
                    else:
                        log.warning(f"[INJECT] Base skin ZIP not found: {base_skin_name}")
                except Exception as e:
                    log.error(f"[INJECT] Error extracting base skin ZIP: {e}")
                    import traceback
                    log.debug(f"[INJECT] Traceback: {traceback.format_exc()}")
            
            # Re-extract custom skin mod if available (after cleaning mods directory)
            if mod_folder_name and mod_path:
                log.info(f"[INJECT] Re-extracting custom mod from: {mod_path}")
                try:
                    import shutil
                    mod_source = Path(mod_path)
                    if not mod_source.exists():
                        log.warning(f"[INJECT] Custom mod source not found: {mod_source}")
                    else:
                        mod_dest = injector.mods_dir / mod_folder_name
                        if mod_dest.exists():
                            shutil.rmtree(mod_dest, ignore_errors=True)
                        mod_dest.mkdir(parents=True, exist_ok=True)
                        
                        if mod_source.is_dir():
                            shutil.copytree(mod_source, mod_dest, dirs_exist_ok=True)
                            log.info(f"[INJECT] Custom mod directory copied: {mod_folder_name}")
                        elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                            # Security: Use safe extraction to prevent path traversal attacks
                            safe_extractall(mod_source, mod_dest)
                            log.info(f"[INJECT] Custom mod ZIP extracted: {mod_folder_name}")
                        else:
                            shutil.copy2(mod_source, mod_dest / mod_source.name)
                            log.info(f"[INJECT] Custom mod file copied: {mod_folder_name}")
                        
                        # Verify mod folder exists after extraction
                        if mod_dest.exists():
                            mod_folder_names.append(mod_folder_name)
                            mod_names_list.append(mod_name or "Custom Mod")
                            log.info(f"[INJECT] Custom skin mod ready: {mod_folder_name}")
                        else:
                            log.warning(f"[INJECT] Custom mod folder not found after extraction: {mod_dest}")
                except Exception as e:
                    log.error(f"[INJECT] Error re-extracting custom mod: {e}")
                    import traceback
                    log.debug(f"[INJECT] Traceback: {traceback.format_exc()}")
            elif mod_folder_name:
                log.warning(f"[INJECT] Custom mod folder name provided but no mod_path - cannot re-extract")
            else:
                log.info(f"[INJECT] No custom skin mod selected, injecting base skin + map/font/announcer/other mods only")
            
            # Helper function to re-extract a mod from its source path
            def re_extract_mod(mod_dict, mod_type_name):
                """Re-extract a mod from its source path after cleaning"""
                if not mod_dict or not mod_dict.get("mod_folder_name"):
                    return None
                
                mod_folder_name = mod_dict.get("mod_folder_name")
                mod_path = mod_dict.get("mod_path")
                
                if not mod_path:
                    log.warning(f"[INJECT] {mod_type_name} mod folder name provided but no mod_path - cannot re-extract")
                    return None
                
                try:
                    import shutil
                    mod_source = Path(mod_path)
                    if not mod_source.exists():
                        log.info(f"[INJECT] {mod_type_name} mod source not found (mod may have been deleted), ignoring: {mod_source}")
                        return None
                    
                    mod_dest = injector.mods_dir / mod_folder_name
                    if mod_dest.exists():
                        shutil.rmtree(mod_dest, ignore_errors=True)
                    mod_dest.mkdir(parents=True, exist_ok=True)
                    
                    if mod_source.is_dir():
                        shutil.copytree(mod_source, mod_dest, dirs_exist_ok=True)
                        log.info(f"[INJECT] {mod_type_name} mod directory copied: {mod_folder_name}")
                    elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                        # Security: Use safe extraction to prevent path traversal attacks
                        safe_extractall(mod_source, mod_dest)
                        log.info(f"[INJECT] {mod_type_name} mod ZIP extracted: {mod_folder_name}")
                    else:
                        shutil.copy2(mod_source, mod_dest / mod_source.name)
                        log.info(f"[INJECT] {mod_type_name} mod file copied: {mod_folder_name}")
                    
                    if mod_dest.exists():
                        return mod_folder_name
                    else:
                        log.warning(f"[INJECT] {mod_type_name} mod folder not found after extraction: {mod_dest}")
                        return None
                except Exception as e:
                    log.error(f"[INJECT] Error re-extracting {mod_type_name} mod: {e}")
                    import traceback
                    log.debug(f"[INJECT] Traceback: {traceback.format_exc()}")
                    return None
            
            # Add map mod if selected
            selected_map_mod = getattr(self.state, 'selected_map_mod', None)
            if selected_map_mod:
                map_mod_folder = re_extract_mod(selected_map_mod, "Map")
                if map_mod_folder:
                    mod_folder_names.append(map_mod_folder)
                    mod_names_list.append(selected_map_mod.get("mod_name", "Map"))
                    log.info(f"[INJECT] Including map mod: {selected_map_mod.get('mod_name')}")
                else:
                    # Track missing mod's relative path for cleanup
                    relative_path = selected_map_mod.get("relative_path")
                    if relative_path:
                        missing_map_mod_path = relative_path
                    log.info(f"[INJECT] Map mod not found (may have been deleted), ignoring: {selected_map_mod.get('mod_name', 'Unknown')}")
                    # Clear missing mod from state
                    self.state.selected_map_mod = None
            
            # Add font mod if selected
            selected_font_mod = getattr(self.state, 'selected_font_mod', None)
            if selected_font_mod:
                font_mod_folder = re_extract_mod(selected_font_mod, "Font")
                if font_mod_folder:
                    mod_folder_names.append(font_mod_folder)
                    mod_names_list.append(selected_font_mod.get("mod_name", "Font"))
                    log.info(f"[INJECT] Including font mod: {selected_font_mod.get('mod_name')}")
                else:
                    # Track missing mod's relative path for cleanup
                    relative_path = selected_font_mod.get("relative_path")
                    if relative_path:
                        missing_font_mod_path = relative_path
                    log.info(f"[INJECT] Font mod not found (may have been deleted), ignoring: {selected_font_mod.get('mod_name', 'Unknown')}")
                    # Clear missing mod from state
                    self.state.selected_font_mod = None
            
            # Add announcer mod if selected
            selected_announcer_mod = getattr(self.state, 'selected_announcer_mod', None)
            if selected_announcer_mod:
                announcer_mod_folder = re_extract_mod(selected_announcer_mod, "Announcer")
                if announcer_mod_folder:
                    mod_folder_names.append(announcer_mod_folder)
                    mod_names_list.append(selected_announcer_mod.get("mod_name", "Announcer"))
                    log.info(f"[INJECT] Including announcer mod: {selected_announcer_mod.get('mod_name')}")
                else:
                    # Track missing mod's relative path for cleanup
                    relative_path = selected_announcer_mod.get("relative_path")
                    if relative_path:
                        missing_announcer_mod_path = relative_path
                    log.info(f"[INJECT] Announcer mod not found (may have been deleted), ignoring: {selected_announcer_mod.get('mod_name', 'Unknown')}")
                    # Clear missing mod from state
                    self.state.selected_announcer_mod = None
            
            # Add other mods if selected (support multiple selections)
            selected_other_mods = getattr(self.state, 'selected_other_mods', None)
            if not selected_other_mods:
                # Fallback to legacy single mod for backward compatibility
                selected_other_mod = getattr(self.state, 'selected_other_mod', None)
                if selected_other_mod:
                    selected_other_mods = [selected_other_mod]
            
            if selected_other_mods:
                # Filter out missing mods and keep track of valid ones
                valid_other_mods = []
                for selected_other_mod in selected_other_mods:
                    other_mod_folder = re_extract_mod(selected_other_mod, "Other")
                    if other_mod_folder:
                        mod_folder_names.append(other_mod_folder)
                        mod_names_list.append(selected_other_mod.get("mod_name", "Other"))
                        valid_other_mods.append(selected_other_mod)
                        log.info(f"[INJECT] Including other mod: {selected_other_mod.get('mod_name')}")
                    else:
                        # Track missing mod's relative path for cleanup
                        relative_path = selected_other_mod.get("relative_path")
                        if relative_path:
                            missing_other_mod_paths.append(relative_path)
                        log.info(f"[INJECT] Other mod not found (may have been deleted), ignoring: {selected_other_mod.get('mod_name', 'Unknown')}")
                
                # Update state to only include valid mods
                if len(valid_other_mods) != len(selected_other_mods):
                    if valid_other_mods:
                        self.state.selected_other_mods = valid_other_mods
                    else:
                        self.state.selected_other_mods = []
                        if hasattr(self.state, 'selected_other_mod'):
                            self.state.selected_other_mod = None
            
            # Check if we have any mods to inject
            if not mod_folder_names:
                log.warning("[INJECT] No mods available to inject (skin, map, font, announcer, or other)")
                return
            
            log.info(f"[INJECT] Injecting mods: {', '.join(mod_names_list)}" + (f" for skin {skin_id}" if skin_id else ""))
            
            # Start game monitor to freeze game during overlay creation
            # This prevents file locks and ensures clean injection
            if self.injection_manager and not self.injection_manager._monitor_active:
                log.info("[INJECT] Starting game monitor for custom mod injection")
                self.injection_manager._start_monitor()
            
            # Force base skin selection via LCU before injecting (only if injecting base skin ZIP)
            # For owned skins, user can select them normally - no need to force
            champion_id = self.state.locked_champ_id or self.state.hovered_champ_id
            if champion_id and base_skin_name:
                # Injecting base skin ZIP for unowned skin - force base skin
                base_skin_id = champion_id * 1000
                self._force_base_skin(base_skin_id)
            
            # Create callback to check if game ended
            has_been_in_progress = False

            def game_ended_callback():
                nonlocal has_been_in_progress
                phase = self.state.phase
                if phase == "InProgress":
                    has_been_in_progress = True
                    return False
                if phase in ("Reconnect", "GameStart"):
                    return False
                return has_been_in_progress and phase not in ("InProgress", "Reconnect", "GameStart")
            
            # All mods are already extracted, create and run overlay with all mods
            result = injector.overlay_manager.mk_run_overlay(
                mod_folder_names,
                timeout=120,
                stop_callback=game_ended_callback,
                injection_manager=self.injection_manager
            )
            
            # Clean up missing mods from historic after overlay starts
            try:
                from utils.core.mod_historic import get_historic_mod, write_historic_mod, clear_historic_mod
                
                # Normalize paths for comparison (handle both forward and backslashes)
                def normalize_path(p):
                    return str(p).replace("\\", "/").lower()
                
                # Clean up map mod if it was missing
                if missing_map_mod_path:
                    historic_map_path = get_historic_mod("map")
                    if historic_map_path and normalize_path(historic_map_path) == normalize_path(missing_map_mod_path):
                        clear_historic_mod("map")
                        log.info(f"[MOD_HISTORIC] Cleaned missing map mod from historic: {missing_map_mod_path}")
                
                # Clean up font mod if it was missing
                if missing_font_mod_path:
                    historic_font_path = get_historic_mod("font")
                    if historic_font_path and normalize_path(historic_font_path) == normalize_path(missing_font_mod_path):
                        clear_historic_mod("font")
                        log.info(f"[MOD_HISTORIC] Cleaned missing font mod from historic: {missing_font_mod_path}")
                
                # Clean up announcer mod if it was missing
                if missing_announcer_mod_path:
                    historic_announcer_path = get_historic_mod("announcer")
                    if historic_announcer_path and normalize_path(historic_announcer_path) == normalize_path(missing_announcer_mod_path):
                        clear_historic_mod("announcer")
                        log.info(f"[MOD_HISTORIC] Cleaned missing announcer mod from historic: {missing_announcer_mod_path}")
                
                # Clean up other mods (can be multiple) - same pattern as above
                if missing_other_mod_paths:
                    historic_other_paths = get_historic_mod("other")
                    if historic_other_paths:
                        # Convert to list if needed
                        if isinstance(historic_other_paths, str):
                            historic_other_paths = [historic_other_paths]
                        elif not isinstance(historic_other_paths, list):
                            historic_other_paths = []
                        
                        normalized_missing = [normalize_path(p) for p in missing_other_mod_paths]
                        
                        # Remove missing mod paths from historic
                        cleaned_paths = [
                            path for path in historic_other_paths
                            if normalize_path(path) not in normalized_missing
                        ]
                        
                        # Update historic if paths were removed
                        if len(cleaned_paths) != len(historic_other_paths):
                            if cleaned_paths:
                                write_historic_mod("other", cleaned_paths)
                                removed_count = len(historic_other_paths) - len(cleaned_paths)
                                log.info(f"[MOD_HISTORIC] Cleaned {removed_count} missing other mod(s) from historic")
                            else:
                                clear_historic_mod("other")
                                log.info(f"[MOD_HISTORIC] Cleared historic other mods (all were missing)")
            except Exception as e:
                log.debug(f"[MOD_HISTORIC] Failed to clean up missing mods from historic: {e}")
                import traceback
                log.debug(f"[MOD_HISTORIC] Traceback: {traceback.format_exc()}")
            
            # Stop monitor after injection completes
            if self.injection_manager:
                self.injection_manager._stop_monitor()
            
            if result == 0:
                log.info("=" * LOG_SEPARATOR_WIDTH)
                injection_label = " + ".join([m.upper() for m in mod_names_list])
                log.info(f"CUSTOM MOD INJECTION COMPLETED >>> {injection_label} <<<")
                log.info(f"   Verify in-game - timing determines if mod appears")
                log.info("=" * LOG_SEPARATOR_WIDTH)
                
                # Store mod selections in historic before clearing
                try:
                    from utils.core.mod_historic import write_historic_mod
                    from utils.core.historic import write_historic_entry
                    
                    # Store custom skin mod in historic if selected
                    selected_custom_mod = getattr(self.state, 'selected_custom_mod', None)
                    if selected_custom_mod and selected_custom_mod.get("relative_path"):
                        champion_id = selected_custom_mod.get("champion_id") or self.state.locked_champ_id or self.state.hovered_champ_id
                        if champion_id:
                            # Store custom mod path with "path:" prefix
                            custom_mod_path = f"path:{selected_custom_mod['relative_path']}"
                            write_historic_entry(int(champion_id), custom_mod_path)
                            log.debug(f"[HISTORIC] Stored custom mod path for champion {champion_id}: {selected_custom_mod['relative_path']}")
                    elif base_skin_name:
                        # Store base skin ID in historic if injecting base skin with mods (no custom mod)
                        try:
                            # Extract skin ID from base_skin_name (e.g., "skin_84002" -> 84002)
                            injected_id = None
                            if isinstance(base_skin_name, str) and '_' in base_skin_name:
                                parts = base_skin_name.split('_', 1)
                                if len(parts) == 2 and parts[1].isdigit():
                                    injected_id = int(parts[1])
                            
                            champion_id = self.state.locked_champ_id or self.state.hovered_champ_id
                            if champion_id is not None and injected_id is not None:
                                write_historic_entry(int(champion_id), int(injected_id))
                                log.info(f"[HISTORIC] Stored last injected ID {injected_id} for champion {champion_id}")
                        except Exception as e:
                            log.debug(f"[HISTORIC] Failed to store base skin entry: {e}")
                    
                    # Store map mod if selected
                    selected_map_mod = getattr(self.state, 'selected_map_mod', None)
                    if selected_map_mod and selected_map_mod.get("relative_path"):
                        write_historic_mod("map", selected_map_mod["relative_path"])
                        log.debug(f"[MOD_HISTORIC] Stored map mod: {selected_map_mod['relative_path']}")
                    
                    # Store font mod if selected
                    selected_font_mod = getattr(self.state, 'selected_font_mod', None)
                    if selected_font_mod and selected_font_mod.get("relative_path"):
                        write_historic_mod("font", selected_font_mod["relative_path"])
                        log.debug(f"[MOD_HISTORIC] Stored font mod: {selected_font_mod['relative_path']}")
                    
                    # Store announcer mod if selected
                    selected_announcer_mod = getattr(self.state, 'selected_announcer_mod', None)
                    if selected_announcer_mod and selected_announcer_mod.get("relative_path"):
                        write_historic_mod("announcer", selected_announcer_mod["relative_path"])
                        log.debug(f"[MOD_HISTORIC] Stored announcer mod: {selected_announcer_mod['relative_path']}")
                    
                    # Store other mods if selected (store all for historic)
                    selected_other_mods = getattr(self.state, 'selected_other_mods', None)
                    if not selected_other_mods:
                        # Fallback to legacy single mod
                        selected_other_mod = getattr(self.state, 'selected_other_mod', None)
                        if selected_other_mod:
                            selected_other_mods = [selected_other_mod]
                    if selected_other_mods and len(selected_other_mods) > 0:
                        # Store all mods for historic (list format)
                        other_mod_paths = [mod.get("relative_path") for mod in selected_other_mods if mod.get("relative_path")]
                        if other_mod_paths:
                            write_historic_mod("other", other_mod_paths)
                            log.debug(f"[MOD_HISTORIC] Stored {len(other_mod_paths)} other mod(s): {', '.join(other_mod_paths)}")
                except Exception as e:
                    log.debug(f"[MOD_HISTORIC] Failed to store mod selections: {e}")
                
                # Clear all selected mods after successful injection
                self.state.selected_custom_mod = None
                if hasattr(self.state, 'selected_map_mod'):
                    self.state.selected_map_mod = None
                if hasattr(self.state, 'selected_font_mod'):
                    self.state.selected_font_mod = None
                if hasattr(self.state, 'selected_announcer_mod'):
                    self.state.selected_announcer_mod = None
                if hasattr(self.state, 'selected_other_mod'):
                    self.state.selected_other_mod = None
                if hasattr(self.state, 'selected_other_mods'):
                    self.state.selected_other_mods = []
            else:
                log.error("=" * LOG_SEPARATOR_WIDTH)
                injection_label = " + ".join([m.upper() for m in mod_names_list])
                log.error(f"CUSTOM MOD INJECTION FAILED >>> {injection_label} <<<")
                log.error("=" * LOG_SEPARATOR_WIDTH)
                log.error(f"[INJECT] Mods will likely NOT appear in-game")
        
        except Exception as e:
            log.error(f"[INJECT] Error injecting custom mod: {e}")
            import traceback
            log.error(f"[INJECT] Traceback: {traceback.format_exc()}")

