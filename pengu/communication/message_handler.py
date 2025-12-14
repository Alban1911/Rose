#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Message Handler
Routes and handles different WebSocket message types
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from config import get_config_float, get_config_option, set_config_option
from injection.mods.storage import ModStorageService
from utils.core.paths import get_user_data_dir, get_asset_path
from utils.system.admin_utils import (
    is_admin,
    is_registered_for_autostart,
    register_autostart,
    unregister_autostart,
)

log = logging.getLogger(__name__)


class MessageHandler:
    """Handles routing and processing of WebSocket messages"""
    
    def __init__(
        self,
        shared_state,
        websocket_server,
        broadcaster,
        skin_processor,
        flow_controller,
        skin_scraper=None,
        mod_storage: Optional[ModStorageService] = None,
        injection_manager=None,
        port: int = 50000,
    ):
        """Initialize message handler
        
        Args:
            shared_state: Shared application state
            websocket_server: WebSocket server instance
            broadcaster: Broadcaster instance
            skin_processor: Skin processor instance
            flow_controller: Flow controller instance
            skin_scraper: LCU skin scraper instance
            mod_storage: Mod storage service instance
            injection_manager: Injection manager instance
            port: Server port
        """
        self.shared_state = shared_state
        self.websocket_server = websocket_server
        self.broadcaster = broadcaster
        self.skin_processor = skin_processor
        self.flow_controller = flow_controller
        self.skin_scraper = skin_scraper
        self.port = port
        self.mod_storage = mod_storage or ModStorageService()
        self.injection_manager = injection_manager
    
    def handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message
        
        Args:
            message: JSON message string
        """
        try:
            payload = json.loads(message)
        except json.JSONDecodeError as exc:
            log.warning("[SkinMonitor] Invalid payload: %s (%s)", message, exc)
            return
        
        payload_type = payload.get("type")
        
        # Route to appropriate handler
        if payload_type == "chroma-log":
            self._handle_chroma_log(payload)
        elif payload_type == "request-local-preview":
            self._handle_request_local_preview(payload)
        elif payload_type == "request-local-asset":
            self._handle_request_local_asset(payload)
        elif payload_type == "chroma-selection":
            self._handle_chroma_selection(payload)
        elif payload_type == "dice-button-click":
            self._handle_dice_button_click(payload)
        elif payload_type == "settings-request":
            self._handle_settings_request(payload)
        elif payload_type == "path-validate":
            self._handle_path_validate(payload)
        elif payload_type == "open-mods-folder":
            self._handle_open_mods_folder(payload)
        elif payload_type == "request-skin-mods":
            self._handle_request_skin_mods(payload)
        elif payload_type == "request-maps":
            self._handle_request_maps(payload)
        elif payload_type == "request-fonts":
            self._handle_request_fonts(payload)
        elif payload_type == "request-announcers":
            self._handle_request_announcers(payload)
        elif payload_type == "request-category-mods":
            self._handle_request_category_mods(payload)
        elif payload_type == "request-others":
            # Backwards compatible: treat as a request for the "others" category only
            self._handle_request_category_mods({"category": self.mod_storage.CATEGORY_OTHERS})
        elif payload_type == "select-skin-mod":
            self._handle_select_skin_mod(payload)
        elif payload_type == "select-map":
            self._handle_select_map(payload)
        elif payload_type == "select-font":
            self._handle_select_font(payload)
        elif payload_type == "select-announcer":
            self._handle_select_announcer(payload)
        elif payload_type == "select-other":
            self._handle_select_other(payload)
        elif payload_type == "open-logs-folder":
            self._handle_open_logs_folder(payload)
        elif payload_type == "open-pengu-loader-ui":
            self._handle_open_pengu_loader_ui(payload)
        elif payload_type == "settings-save":
            self._handle_settings_save(payload)
        elif payload_type == "add-custom-mods-category-selected":
            self._handle_add_custom_mods_category_selected(payload)
        elif payload_type == "add-custom-mods-champion-selected":
            self._handle_add_custom_mods_champion_selected(payload)
        elif payload_type == "add-custom-mods-skin-selected":
            self._handle_add_custom_mods_skin_selected(payload)
        elif payload.get("skin"):
            # Handle skin detection message
            self._handle_skin_detection(payload)
    
    def _handle_chroma_log(self, payload: dict) -> None:
        """Handle chroma log message"""
        source = payload.get("source", "ChromaWheel")
        event = payload.get("event") or payload.get("message") or "unknown"
        details = payload.get("data") or payload
        log.info("[%s] %s | %s", source, event, details)
    
    def _handle_request_local_preview(self, payload: dict) -> None:
        """Handle request for local preview image"""
        champion_id = payload.get("championId")
        skin_id = payload.get("skinId")
        chroma_id = payload.get("chromaId")
        
        if champion_id and skin_id and chroma_id:
            try:
                from ui.chroma.preview_manager import get_preview_manager
                preview_manager = get_preview_manager()
                
                preview_path = preview_manager.get_preview_path(
                    champion_name="",
                    skin_name="",
                    chroma_id=chroma_id if chroma_id != skin_id else None,
                    skin_id=skin_id,
                    champion_id=champion_id
                )
                
                if preview_path and preview_path.exists():
                    http_url = f"http://localhost:{self.port}/preview/{champion_id}/{skin_id}/{chroma_id}/{chroma_id}.png"
                    log.debug(f"[SkinMonitor] Local preview found: {preview_path} -> {http_url}")
                    
                    response_payload = {
                        "type": "local-preview-url",
                        "championId": champion_id,
                        "skinId": skin_id,
                        "chromaId": chroma_id,
                        "url": http_url,
                        "timestamp": int(time.time() * 1000),
                    }
                    self._send_response(json.dumps(response_payload))
                else:
                    log.debug(f"[SkinMonitor] Local preview not found: champion={champion_id}, skin={skin_id}, chroma={chroma_id}")
            except Exception as e:
                log.debug(f"[SkinMonitor] Failed to get local preview: {e}")
    
    def _handle_request_local_asset(self, payload: dict) -> None:
        """Handle request for local asset"""
        asset_path = payload.get("assetPath")
        chroma_id = payload.get("chromaId")
        
        if asset_path:
            try:
                asset_file = get_asset_path(asset_path)
                
                if asset_file and asset_file.exists():
                    http_url = f"http://localhost:{self.port}/asset/{asset_path.replace(chr(92), '/')}"
                    log.debug(f"[SkinMonitor] Local asset found: {asset_file} -> {http_url}")
                    
                    response_payload = {
                        "type": "local-asset-url",
                        "assetPath": asset_path,
                        "chromaId": chroma_id,
                        "url": http_url,
                        "timestamp": int(time.time() * 1000),
                    }
                    self._send_response(json.dumps(response_payload))
                else:
                    log.debug(f"[SkinMonitor] Local asset not found: {asset_path}")
            except Exception as e:
                log.debug(f"[SkinMonitor] Failed to get local asset: {e}")
    
    def _handle_chroma_selection(self, payload: dict) -> None:
        """Handle chroma selection from JavaScript"""
        chroma_id = payload.get("chromaId") or payload.get("skinId")
        chroma_name = payload.get("chromaName") or "Unknown"
        
        if chroma_id is not None:
            from ui.chroma.selector import get_chroma_selector
            chroma_selector = get_chroma_selector()
            
            if chroma_selector:
                chroma_selector._on_chroma_selected(chroma_id, chroma_name)
                log.info(f"[SkinMonitor] Chroma selected via ChromaSelector: {chroma_name} (ID: {chroma_id})")
                
                if chroma_selector.panel:
                    try:
                        chroma_selector.panel._on_chroma_selected_wrapper(chroma_id, chroma_name)
                    except Exception as e:
                        log.debug(f"[SkinMonitor] Failed to call panel wrapper: {e}")
                        self.broadcaster.broadcast_chroma_state()
                else:
                    self.broadcaster.broadcast_chroma_state()
            else:
                # Fallback
                self.shared_state.selected_chroma_id = chroma_id if chroma_id != 0 else None
                self.shared_state.last_hovered_skin_id = chroma_id
                log.info(f"[SkinMonitor] Chroma selected (fallback): {chroma_name} (ID: {chroma_id})")
                
                try:
                    from ui.chroma.panel import get_chroma_panel
                    panel = get_chroma_panel(state=self.shared_state)
                    if panel:
                        panel._on_chroma_selected_wrapper(chroma_id, chroma_name)
                    else:
                        self.broadcaster.broadcast_chroma_state()
                except Exception as e:
                    log.debug(f"[SkinMonitor] Failed to call panel wrapper in fallback: {e}")
                    self.broadcaster.broadcast_chroma_state()
    
    def _handle_dice_button_click(self, payload: dict) -> None:
        """Handle dice button click"""
        button_state = payload.get("state", "disabled")
        log.info(f"[SkinMonitor] Dice button clicked from JavaScript: state={button_state}")
        
        try:
            from ui.core.user_interface import get_user_interface
            ui = get_user_interface(self.shared_state, self.skin_scraper)
            
            if button_state == "disabled":
                ui._handle_dice_click_disabled()
            elif button_state == "enabled":
                ui._handle_dice_click_enabled()
            else:
                log.warning(f"[SkinMonitor] Unknown dice button state: {button_state}")
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle dice button click: {e}")
    
    def _handle_settings_request(self, payload: dict) -> None:
        """Handle settings request"""
        try:
            threshold = get_config_float("General", "injection_threshold", 0.5)
            monitor_auto_resume_timeout = get_config_float("General", "monitor_auto_resume_timeout", 60.0)
            autostart = is_registered_for_autostart()
            game_path = get_config_option("General", "leaguePath") or ""
            
            path_valid = False
            if game_path:
                try:
                    game_dir = Path(game_path.strip())
                    if game_dir.exists() and game_dir.is_dir():
                        league_exe = game_dir / "League of Legends.exe"
                        path_valid = league_exe.exists() and league_exe.is_file()
                except Exception:
                    path_valid = False
            
            response_payload = {
                "type": "settings-data",
                "threshold": threshold,
                "monitorAutoResumeTimeout": int(monitor_auto_resume_timeout),
                "autostart": autostart,
                "gamePath": game_path,
                "gamePathValid": path_valid
            }
            self._send_response(json.dumps(response_payload))
            
            log.info(f"[SkinMonitor] Settings data sent: threshold={threshold}, monitor_auto_resume_timeout={monitor_auto_resume_timeout}, autostart={autostart}, gamePath={game_path}, valid={path_valid}")
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle settings request: {e}")
    
    def _handle_path_validate(self, payload: dict) -> None:
        """Handle path validation request"""
        try:
            game_path = payload.get("gamePath", "")
            path_valid = False
            
            if game_path and game_path.strip():
                try:
                    game_dir = Path(game_path.strip())
                    if game_dir.exists() and game_dir.is_dir():
                        league_exe = game_dir / "League of Legends.exe"
                        path_valid = league_exe.exists() and league_exe.is_file()
                except Exception:
                    path_valid = False
            
            validation_payload = {
                "type": "path-validation-result",
                "gamePath": game_path,
                "valid": path_valid
            }
            self._send_response(json.dumps(validation_payload))
            
            log.debug(f"[SkinMonitor] Path validation result: path={game_path}, valid={path_valid}")
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle path validation: {e}")
    
    def _handle_open_mods_folder(self, payload: dict) -> None:
        """Handle open mods folder request"""
        try:
            mods_folder = get_user_data_dir() / "mods"
            mods_folder.mkdir(parents=True, exist_ok=True)
            
            if sys.platform == "win32":
                os.startfile(str(mods_folder))
            else:
                subprocess.Popen(["xdg-open" if os.name != "nt" else "explorer", str(mods_folder)])
            log.info(f"[SkinMonitor] Opened mods folder: {mods_folder}")
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to open mods folder: {e}")
    
    def _handle_request_skin_mods(self, payload: dict) -> None:
        """Return the list of custom mods for a specific champion and skin"""
        if not self.mod_storage:
            return

        skin_id = payload.get("skinId")
        if skin_id is None:
            return

        try:
            entries = self.mod_storage.list_mods_for_skin(skin_id)
        except Exception as exc:
            log.error(f"[SkinMonitor] Failed to list skin mods: {exc}")
            entries = []

        champion_id = payload.get("championId")
        if entries:
            first_entry_champion = entries[0].champion_id
            if first_entry_champion is not None:
                champion_id = first_entry_champion

        mods_payload = []
        for entry in entries:
            try:
                relative_path = entry.path.relative_to(self.mod_storage.mods_root)
            except Exception:
                relative_path = entry.path

            mods_payload.append(
                {
                    "modName": entry.mod_name,
                    "description": entry.description,
                    "updatedAt": int(entry.updated_at * 1000),
                    "relativePath": str(relative_path).replace("\\", "/"),
                }
            )

        # Get historic custom mod path for this champion if available
        historic_mod_path = None
        try:
            from utils.core.historic import get_historic_skin_for_champion, is_custom_mod_path, get_custom_mod_path
            if champion_id:
                historic_value = get_historic_skin_for_champion(champion_id)
                if historic_value and is_custom_mod_path(historic_value):
                    historic_mod_path = get_custom_mod_path(historic_value)
        except Exception:
            pass

        response_payload = {
            "type": "skin-mods-response",
            "championId": champion_id,
            "skinId": skin_id,
            "mods": mods_payload,
            "historicMod": historic_mod_path,  # Add historic mod path if available
            "timestamp": int(time.time() * 1000),
        }
        self._send_response(json.dumps(response_payload))
    
    def _handle_request_maps(self, payload: dict) -> None:
        """Return the list of maps"""
        if not self.mod_storage:
            return
        
        try:
            maps = self.mod_storage.list_mods_for_category(self.mod_storage.CATEGORY_MAPS)
        except Exception as exc:
            log.error(f"[SkinMonitor] Failed to list maps: {exc}")
            maps = []
        
        # Get historic mod and add it to response
        historic_map_path = None
        try:
            from utils.core.mod_historic import get_historic_mod
            historic_map_path = get_historic_mod("map")
        except Exception:
            pass
        
        response_payload = {
            "type": "maps-response",
            "maps": maps,
            "historicMod": historic_map_path,  # Add historic mod identifier
            "timestamp": int(time.time() * 1000),
        }
        self._send_response(json.dumps(response_payload))
        
        # Auto-select historic mod if available and not already selected
        if historic_map_path and not getattr(self.shared_state, 'selected_map_mod', None):
            self._auto_select_historic_mod("map", historic_map_path, maps)
    
    def _handle_request_fonts(self, payload: dict) -> None:
        """Return the list of fonts"""
        if not self.mod_storage:
            return
        
        try:
            fonts = self.mod_storage.list_mods_for_category(self.mod_storage.CATEGORY_FONTS)
        except Exception as exc:
            log.error(f"[SkinMonitor] Failed to list fonts: {exc}")
            fonts = []
        
        # Get historic mod and add it to response
        historic_font_path = None
        try:
            from utils.core.mod_historic import get_historic_mod
            historic_font_path = get_historic_mod("font")
        except Exception:
            pass
        
        response_payload = {
            "type": "fonts-response",
            "fonts": fonts,
            "historicMod": historic_font_path,  # Add historic mod identifier
            "timestamp": int(time.time() * 1000),
        }
        self._send_response(json.dumps(response_payload))
        
        # Auto-select historic mod if available and not already selected
        if historic_font_path and not getattr(self.shared_state, 'selected_font_mod', None):
            self._auto_select_historic_mod("font", historic_font_path, fonts)
    
    def _handle_request_announcers(self, payload: dict) -> None:
        """Return the list of announcers"""
        if not self.mod_storage:
            return
        
        try:
            announcers = self.mod_storage.list_mods_for_category(self.mod_storage.CATEGORY_ANNOUNCERS)
        except Exception as exc:
            log.error(f"[SkinMonitor] Failed to list announcers: {exc}")
            announcers = []
        
        # Get historic mod and add it to response
        historic_announcer_path = None
        try:
            from utils.core.mod_historic import get_historic_mod
            historic_announcer_path = get_historic_mod("announcer")
        except Exception:
            pass
        
        response_payload = {
            "type": "announcers-response",
            "announcers": announcers,
            "historicMod": historic_announcer_path,  # Add historic mod identifier
            "timestamp": int(time.time() * 1000),
        }
        self._send_response(json.dumps(response_payload))
        
        # Auto-select historic mod if available and not already selected
        if historic_announcer_path and not getattr(self.shared_state, 'selected_announcer_mod', None):
            self._auto_select_historic_mod("announcer", historic_announcer_path, announcers)
    
    def _handle_request_others(self, payload: dict) -> None:
        """Return the list of others"""
        if not self.mod_storage:
            return
        
        try:
            others = self.mod_storage.list_mods_for_category(self.mod_storage.CATEGORY_OTHERS)
        except Exception as exc:
            log.error(f"[SkinMonitor] Failed to list others: {exc}")
            others = []
        
        # Get historic mod and add it to response
        historic_other_paths = None
        try:
            from utils.core.mod_historic import get_historic_mod
            historic_other_paths = get_historic_mod("other")
            # Convert to list if it's a single string (legacy format)
            if isinstance(historic_other_paths, str):
                historic_other_paths = [historic_other_paths]
        except Exception:
            pass
        
        response_payload = {
            "type": "others-response",
            "others": others,
            "historicMod": historic_other_paths,  # List of historic mod identifiers (or None)
            "timestamp": int(time.time() * 1000),
        }
        self._send_response(json.dumps(response_payload))
        
        # Auto-select historic mods if available and not already selected
        selected_other_mods = getattr(self.shared_state, 'selected_other_mods', None)
        if not selected_other_mods:
            # Fallback to legacy single mod
            selected_other_mod = getattr(self.shared_state, 'selected_other_mod', None)
            if selected_other_mod:
                selected_other_mods = [selected_other_mod]
        if historic_other_paths and (not selected_other_mods or len(selected_other_mods) == 0):
            # Handle multiple historic other mods
            if isinstance(historic_other_paths, list):
                for historic_path in historic_other_paths:
                    self._auto_select_historic_mod("other", historic_path, others)
            else:
                # Legacy single mod format
                self._auto_select_historic_mod("other", historic_other_paths, others)
    
    def _handle_select_skin_mod(self, payload: dict) -> None:
        """Handle mod selection for injection over hovered skin"""
        if not self.mod_storage:
            log.warning("[SkinMonitor] Cannot handle mod selection - mod storage not available")
            return

        champion_id = payload.get("championId")
        skin_id = payload.get("skinId")
        mod_id = payload.get("modId")
        mod_data = payload.get("modData", {})

        if not champion_id or not skin_id:
            log.warning(f"[SkinMonitor] Invalid mod selection payload: championId={champion_id}, skinId={skin_id}")
            return

        # Handle deselection (mod_id is null)
        if mod_id is None:
            # Clear selected mod if it matches this skin
            if (hasattr(self.shared_state, 'selected_custom_mod') and 
                self.shared_state.selected_custom_mod and 
                self.shared_state.selected_custom_mod.get("skin_id") == skin_id):
                self.shared_state.selected_custom_mod = None
                log.info(f"[SkinMonitor] Custom mod deselected for skin {skin_id}")
            return

        try:
            # Find the mod in storage
            entries = self.mod_storage.list_mods_for_skin(skin_id)
            selected_mod = None
            for entry in entries:
                # Match by mod name or relative path
                if (entry.mod_name == mod_id or 
                    str(entry.path.relative_to(self.mod_storage.mods_root)).replace("\\", "/") == mod_id):
                    selected_mod = entry
                    break

            if not selected_mod:
                log.warning(f"[SkinMonitor] Mod not found: {mod_id} for skin {skin_id}")
                return

            # Extract mod immediately when selected (not during injection)
            if not self.injection_manager:
                log.warning("[SkinMonitor] Cannot extract mod - injection manager not available")
                return
                
            injector = self.injection_manager.injector
            if not injector:
                log.warning("[SkinMonitor] Cannot extract mod - injector not available")
                return

            mod_source = Path(selected_mod.path)
            if not mod_source.exists():
                log.error(f"[SkinMonitor] Mod file not found: {mod_source}")
                return

            # Determine mod folder name
            if mod_source.is_dir():
                mod_folder_name = mod_source.name
            elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                mod_folder_name = mod_source.stem
            else:
                mod_folder_name = mod_source.stem

            # Extract/copy mod to injection mods directory immediately
            import shutil
            import zipfile
            
            # Check if other mods (map/font/announcer/other) are already selected
            # If so, don't clean - just extract the skin mod alongside them
            selected_other_mods = getattr(self.shared_state, 'selected_other_mods', None)
            if not selected_other_mods:
                # Fallback to legacy single mod
                selected_other_mod = getattr(self.shared_state, 'selected_other_mod', None)
                if selected_other_mod:
                    selected_other_mods = [selected_other_mod]
            has_other_mods = (
                (hasattr(self.shared_state, 'selected_map_mod') and self.shared_state.selected_map_mod) or
                (hasattr(self.shared_state, 'selected_font_mod') and self.shared_state.selected_font_mod) or
                (hasattr(self.shared_state, 'selected_announcer_mod') and self.shared_state.selected_announcer_mod) or
                (selected_other_mods and len(selected_other_mods) > 0)
            )
            
            # Only clean mods directory if no other mods are selected
            if not has_other_mods:
                injector._clean_mods_dir()
            else:
                log.info("[SkinMonitor] Other mods selected - keeping existing mods and adding skin mod")
            
            if mod_source.is_dir():
                mod_dest = injector.mods_dir / mod_source.name
                shutil.copytree(mod_source, mod_dest, dirs_exist_ok=True)
                log.info(f"[SkinMonitor] Copied mod directory to: {mod_dest}")
            elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                # Extract ZIP or FANTOME file
                mod_dest = injector.mods_dir / mod_source.stem
                if mod_dest.exists():
                    shutil.rmtree(mod_dest, ignore_errors=True)
                mod_dest.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(mod_source, 'r') as zip_ref:
                    zip_ref.extractall(mod_dest)
                file_type = "ZIP" if mod_source.suffix.lower() == ".zip" else "FANTOME"
                log.info(f"[SkinMonitor] Extracted {file_type} mod to: {mod_dest}")
            else:
                # For other file types, create folder and copy file
                mod_dest = injector.mods_dir / mod_folder_name
                if mod_dest.exists():
                    shutil.rmtree(mod_dest, ignore_errors=True)
                mod_dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(mod_source, mod_dest / mod_source.name)
                log.info(f"[SkinMonitor] Copied mod file to folder: {mod_dest}")

            # Store selected mod in shared state for injection trigger
            # Include the extracted folder name so injection knows what to use
            self.shared_state.selected_custom_mod = {
                "skin_id": skin_id,
                "champion_id": champion_id,
                "mod_name": selected_mod.mod_name,
                "mod_path": str(selected_mod.path),
                "mod_folder_name": mod_folder_name,  # Add this for injection
                "relative_path": str(selected_mod.path.relative_to(self.mod_storage.mods_root)).replace("\\", "/"),
            }
            
            # Disable HistoricMode if active (custom mod takes priority)
            if getattr(self.shared_state, 'historic_mode_active', False):
                self.shared_state.historic_mode_active = False
                self.shared_state.historic_skin_id = None
                log.info("[HISTORIC] Historic mode DISABLED due to custom mod selection")
                
                # Broadcast deactivated state to JavaScript
                try:
                    if self.shared_state and hasattr(self.shared_state, 'ui_skin_thread') and self.shared_state.ui_skin_thread:
                        self.shared_state.ui_skin_thread._broadcast_historic_state()
                except Exception as e:
                    log.debug(f"[SkinMonitor] Failed to broadcast historic state on custom mod selection: {e}")
            
            log.info(f"[SkinMonitor] Custom mod selected and extracted: {selected_mod.mod_name} (skin {skin_id})")
            log.info(f"[SkinMonitor] Mod ready for injection on threshold trigger")

        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle mod selection: {e}")
            import traceback
            log.debug(f"[SkinMonitor] Traceback: {traceback.format_exc()}")
    
    def _handle_select_map(self, payload: dict) -> None:
        """Handle map mod selection for injection"""
        if not self.mod_storage:
            log.warning("[SkinMonitor] Cannot handle map selection - mod storage not available")
            return
        
        map_id = payload.get("mapId")
        map_data = payload.get("mapData", {})
        
        # Handle deselection (map_id is null)
        if map_id is None:
            if hasattr(self.shared_state, 'selected_map_mod') and self.shared_state.selected_map_mod:
                self.shared_state.selected_map_mod = None
                log.info(f"[SkinMonitor] Map mod deselected")
                # Clear historic mod when deselected
                try:
                    from utils.core.mod_historic import clear_historic_mod
                    clear_historic_mod("map")
                    log.debug("[MOD_HISTORIC] Cleared historic map mod")
                except Exception as e:
                    log.debug(f"[MOD_HISTORIC] Failed to clear historic map mod: {e}")
            return
        
        try:
            # Find the mod in storage
            entries = self.mod_storage.list_mods_for_category(self.mod_storage.CATEGORY_MAPS)
            selected_mod = None
            # map_data contains: id (relative path), name, path, updatedAt, description
            mod_identifier = map_data.get("id") or map_data.get("name") or map_id
            for entry_dict in entries:
                # Match by id (relative path) or name
                if (entry_dict.get("id") == mod_identifier or 
                    entry_dict.get("name") == mod_identifier):
                    # Convert dict to Path for extraction
                    mod_path = self.mod_storage.mods_root / entry_dict["path"].replace("/", "\\")
                    selected_mod = type('ModEntry', (), {
                        'mod_name': entry_dict["name"],
                        'path': mod_path
                    })()
                    break
            
            if not selected_mod:
                log.warning(f"[SkinMonitor] Map mod not found: {map_id}")
                return
            
            # Extract mod immediately when selected
            if not self.injection_manager:
                log.warning("[SkinMonitor] Cannot extract map mod - injection manager not available")
                return
                
            injector = self.injection_manager.injector
            if not injector:
                log.warning("[SkinMonitor] Cannot extract map mod - injector not available")
                return

            mod_source = Path(selected_mod.path)
            if not mod_source.exists():
                log.error(f"[SkinMonitor] Map mod file not found: {mod_source}")
                return

            # Determine mod folder name
            if mod_source.is_dir():
                mod_folder_name = mod_source.name
            elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                mod_folder_name = mod_source.stem
            else:
                mod_folder_name = mod_source.stem

            # Extract/copy mod to injection mods directory immediately
            import shutil
            import zipfile
            
            # Don't clean mods directory - we want to keep skin mod if it exists
            # Just ensure the map mod is extracted
            
            if mod_source.is_dir():
                mod_dest = injector.mods_dir / mod_source.name
                if mod_dest.exists():
                    shutil.rmtree(mod_dest, ignore_errors=True)
                shutil.copytree(mod_source, mod_dest, dirs_exist_ok=True)
                log.info(f"[SkinMonitor] Copied map mod directory to: {mod_dest}")
            elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                # Extract ZIP or FANTOME file
                mod_dest = injector.mods_dir / mod_source.stem
                if mod_dest.exists():
                    shutil.rmtree(mod_dest, ignore_errors=True)
                mod_dest.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(mod_source, 'r') as zip_ref:
                    zip_ref.extractall(mod_dest)
                file_type = "ZIP" if mod_source.suffix.lower() == ".zip" else "FANTOME"
                log.info(f"[SkinMonitor] Extracted {file_type} map mod to: {mod_dest}")
            else:
                # For other file types, create folder and copy file
                mod_dest = injector.mods_dir / mod_folder_name
                if mod_dest.exists():
                    shutil.rmtree(mod_dest, ignore_errors=True)
                mod_dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(mod_source, mod_dest / mod_source.name)
                log.info(f"[SkinMonitor] Copied map mod file to folder: {mod_dest}")

            # Store selected map mod in shared state for injection
            self.shared_state.selected_map_mod = {
                "mod_name": selected_mod.mod_name,
                "mod_path": str(selected_mod.path),
                "mod_folder_name": mod_folder_name,
                "relative_path": str(selected_mod.path.relative_to(self.mod_storage.mods_root)).replace("\\", "/"),
            }
            
            log.info(f"[SkinMonitor] Map mod selected and extracted: {selected_mod.mod_name}")
            log.info(f"[SkinMonitor] Map mod ready for injection alongside skin")

        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle map selection: {e}")
            import traceback
            log.debug(f"[SkinMonitor] Traceback: {traceback.format_exc()}")
    
    def _handle_select_font(self, payload: dict) -> None:
        """Handle font mod selection for injection"""
        if not self.mod_storage:
            log.warning("[SkinMonitor] Cannot handle font selection - mod storage not available")
            return
        
        font_id = payload.get("fontId")
        font_data = payload.get("fontData", {})
        
        # Handle deselection (font_id is null)
        if font_id is None:
            if hasattr(self.shared_state, 'selected_font_mod') and self.shared_state.selected_font_mod:
                self.shared_state.selected_font_mod = None
                log.info(f"[SkinMonitor] Font mod deselected")
                # Clear historic mod when deselected
                try:
                    from utils.core.mod_historic import clear_historic_mod
                    clear_historic_mod("font")
                    log.debug("[MOD_HISTORIC] Cleared historic font mod")
                except Exception as e:
                    log.debug(f"[MOD_HISTORIC] Failed to clear historic font mod: {e}")
            return
        
        try:
            # Find the mod in storage
            entries = self.mod_storage.list_mods_for_category(self.mod_storage.CATEGORY_FONTS)
            selected_mod = None
            # font_data contains: id (relative path), name, path, updatedAt, description
            mod_identifier = font_data.get("id") or font_data.get("name") or font_id
            for entry_dict in entries:
                # Match by id (relative path) or name
                if (entry_dict.get("id") == mod_identifier or 
                    entry_dict.get("name") == mod_identifier):
                    # Convert dict to Path for extraction
                    mod_path = self.mod_storage.mods_root / entry_dict["path"].replace("/", "\\")
                    selected_mod = type('ModEntry', (), {
                        'mod_name': entry_dict["name"],
                        'path': mod_path
                    })()
                    break
            
            if not selected_mod:
                log.warning(f"[SkinMonitor] Font mod not found: {font_id}")
                return
            
            # Extract mod immediately when selected
            if not self.injection_manager:
                log.warning("[SkinMonitor] Cannot extract font mod - injection manager not available")
                return
                
            injector = self.injection_manager.injector
            if not injector:
                log.warning("[SkinMonitor] Cannot extract font mod - injector not available")
                return

            mod_source = Path(selected_mod.path)
            if not mod_source.exists():
                log.error(f"[SkinMonitor] Font mod file not found: {mod_source}")
                return

            # Determine mod folder name
            if mod_source.is_dir():
                mod_folder_name = mod_source.name
            elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                mod_folder_name = mod_source.stem
            else:
                mod_folder_name = mod_source.stem

            # Extract/copy mod to injection mods directory immediately
            import shutil
            import zipfile
            
            # Don't clean mods directory - we want to keep skin/map mods if they exist
            
            if mod_source.is_dir():
                mod_dest = injector.mods_dir / mod_source.name
                if mod_dest.exists():
                    shutil.rmtree(mod_dest, ignore_errors=True)
                shutil.copytree(mod_source, mod_dest, dirs_exist_ok=True)
                log.info(f"[SkinMonitor] Copied font mod directory to: {mod_dest}")
            elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                # Extract ZIP or FANTOME file
                mod_dest = injector.mods_dir / mod_source.stem
                if mod_dest.exists():
                    shutil.rmtree(mod_dest, ignore_errors=True)
                mod_dest.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(mod_source, 'r') as zip_ref:
                    zip_ref.extractall(mod_dest)
                file_type = "ZIP" if mod_source.suffix.lower() == ".zip" else "FANTOME"
                log.info(f"[SkinMonitor] Extracted {file_type} font mod to: {mod_dest}")
            else:
                # For other file types, create folder and copy file
                mod_dest = injector.mods_dir / mod_folder_name
                if mod_dest.exists():
                    shutil.rmtree(mod_dest, ignore_errors=True)
                mod_dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(mod_source, mod_dest / mod_source.name)
                log.info(f"[SkinMonitor] Copied font mod file to folder: {mod_dest}")

            # Store selected font mod in shared state for injection
            self.shared_state.selected_font_mod = {
                "mod_name": selected_mod.mod_name,
                "mod_path": str(selected_mod.path),
                "mod_folder_name": mod_folder_name,
                "relative_path": str(selected_mod.path.relative_to(self.mod_storage.mods_root)).replace("\\", "/"),
            }
            
            log.info(f"[SkinMonitor] Font mod selected and extracted: {selected_mod.mod_name}")
            log.info(f"[SkinMonitor] Font mod ready for injection alongside skin")

        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle font selection: {e}")
            import traceback
            log.debug(f"[SkinMonitor] Traceback: {traceback.format_exc()}")
    
    def _handle_select_announcer(self, payload: dict) -> None:
        """Handle announcer mod selection for injection"""
        if not self.mod_storage:
            log.warning("[SkinMonitor] Cannot handle announcer selection - mod storage not available")
            return
        
        announcer_id = payload.get("announcerId")
        announcer_data = payload.get("announcerData", {})
        
        # Handle deselection (announcer_id is null)
        if announcer_id is None:
            if hasattr(self.shared_state, 'selected_announcer_mod') and self.shared_state.selected_announcer_mod:
                self.shared_state.selected_announcer_mod = None
                log.info(f"[SkinMonitor] Announcer mod deselected")
                # Clear historic mod when deselected
                try:
                    from utils.core.mod_historic import clear_historic_mod
                    clear_historic_mod("announcer")
                    log.debug("[MOD_HISTORIC] Cleared historic announcer mod")
                except Exception as e:
                    log.debug(f"[MOD_HISTORIC] Failed to clear historic announcer mod: {e}")
            return
        
        try:
            # Find the mod in storage
            entries = self.mod_storage.list_mods_for_category(self.mod_storage.CATEGORY_ANNOUNCERS)
            selected_mod = None
            # announcer_data contains: id (relative path), name, path, updatedAt, description
            mod_identifier = announcer_data.get("id") or announcer_data.get("name") or announcer_id
            for entry_dict in entries:
                # Match by id (relative path) or name
                if (entry_dict.get("id") == mod_identifier or 
                    entry_dict.get("name") == mod_identifier):
                    # Convert dict to Path for extraction
                    mod_path = self.mod_storage.mods_root / entry_dict["path"].replace("/", "\\")
                    selected_mod = type('ModEntry', (), {
                        'mod_name': entry_dict["name"],
                        'path': mod_path
                    })()
                    break
            
            if not selected_mod:
                log.warning(f"[SkinMonitor] Announcer mod not found: {announcer_id}")
                return
            
            # Extract mod immediately when selected
            if not self.injection_manager:
                log.warning("[SkinMonitor] Cannot extract announcer mod - injection manager not available")
                return
                
            injector = self.injection_manager.injector
            if not injector:
                log.warning("[SkinMonitor] Cannot extract announcer mod - injector not available")
                return

            mod_source = Path(selected_mod.path)
            if not mod_source.exists():
                log.error(f"[SkinMonitor] Announcer mod file not found: {mod_source}")
                return

            # Determine mod folder name
            if mod_source.is_dir():
                mod_folder_name = mod_source.name
            elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                mod_folder_name = mod_source.stem
            else:
                mod_folder_name = mod_source.stem

            # Extract/copy mod to injection mods directory immediately
            import shutil
            import zipfile
            
            # Don't clean mods directory - we want to keep skin/map/font mods if they exist
            
            if mod_source.is_dir():
                mod_dest = injector.mods_dir / mod_source.name
                if mod_dest.exists():
                    shutil.rmtree(mod_dest, ignore_errors=True)
                shutil.copytree(mod_source, mod_dest, dirs_exist_ok=True)
                log.info(f"[SkinMonitor] Copied announcer mod directory to: {mod_dest}")
            elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                # Extract ZIP or FANTOME file
                mod_dest = injector.mods_dir / mod_source.stem
                if mod_dest.exists():
                    shutil.rmtree(mod_dest, ignore_errors=True)
                mod_dest.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(mod_source, 'r') as zip_ref:
                    zip_ref.extractall(mod_dest)
                file_type = "ZIP" if mod_source.suffix.lower() == ".zip" else "FANTOME"
                log.info(f"[SkinMonitor] Extracted {file_type} announcer mod to: {mod_dest}")
            else:
                # For other file types, create folder and copy file
                mod_dest = injector.mods_dir / mod_folder_name
                if mod_dest.exists():
                    shutil.rmtree(mod_dest, ignore_errors=True)
                mod_dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(mod_source, mod_dest / mod_source.name)
                log.info(f"[SkinMonitor] Copied announcer mod file to folder: {mod_dest}")

            # Store selected announcer mod in shared state for injection
            self.shared_state.selected_announcer_mod = {
                "mod_name": selected_mod.mod_name,
                "mod_path": str(selected_mod.path),
                "mod_folder_name": mod_folder_name,
                "relative_path": str(selected_mod.path.relative_to(self.mod_storage.mods_root)).replace("\\", "/"),
            }
            
            log.info(f"[SkinMonitor] Announcer mod selected and extracted: {selected_mod.mod_name}")
            log.info(f"[SkinMonitor] Announcer mod ready for injection alongside skin")

        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle announcer selection: {e}")
            import traceback
            log.debug(f"[SkinMonitor] Traceback: {traceback.format_exc()}")
    
    def _handle_select_other(self, payload: dict) -> None:
        """Handle other mod selection for injection (supports multiple selections)"""
        if not self.mod_storage:
            log.warning("[SkinMonitor] Cannot handle other selection - mod storage not available")
            return
        
        other_id = payload.get("otherId")
        other_data = payload.get("otherData", {})
        action = payload.get("action", "select")  # "select" or "deselect"
        
        # Initialize selected_other_mods as list if it doesn't exist
        if not hasattr(self.shared_state, 'selected_other_mods'):
            self.shared_state.selected_other_mods = []
        
        # Handle deselection
        if action == "deselect" or other_id is None:
            if other_id:
                # Remove specific mod from list
                self.shared_state.selected_other_mods = [
                    mod for mod in self.shared_state.selected_other_mods 
                    if mod.get("relative_path") != other_data.get("id")
                ]
                log.info(f"[SkinMonitor] Other mod deselected: {other_id}")
            else:
                # Clear all (legacy support)
                self.shared_state.selected_other_mods = []
                log.info(f"[SkinMonitor] All other mods deselected")
                # Clear historic mod when all deselected
                try:
                    from utils.core.mod_historic import clear_historic_mod
                    clear_historic_mod("other")
                    log.debug("[MOD_HISTORIC] Cleared historic other mod")
                except Exception as e:
                    log.debug(f"[MOD_HISTORIC] Failed to clear historic other mod: {e}")
            return
        
        try:
            # other_data contains: id (relative path), name, path, updatedAt, description
            rel_path = other_data.get("path") or other_data.get("id") or other_id
            if not rel_path:
                log.warning("[SkinMonitor] Other mod selection missing path/id")
                return

            mod_path = self.mod_storage.mods_root / str(rel_path).replace("/", "\\")
            selected_mod = type("ModEntry", (), {
                "mod_name": other_data.get("name") or other_id or mod_path.name,
                "path": mod_path,
            })()
            
            # Extract mod immediately when selected
            if not self.injection_manager:
                log.warning("[SkinMonitor] Cannot extract other mod - injection manager not available")
                return
                
            injector = self.injection_manager.injector
            if not injector:
                log.warning("[SkinMonitor] Cannot extract other mod - injector not available")
                return

            mod_source = Path(selected_mod.path)
            if not mod_source.exists():
                log.error(f"[SkinMonitor] Other mod file not found: {mod_source}")
                return

            # Determine mod folder name
            if mod_source.is_dir():
                mod_folder_name = mod_source.name
            elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                mod_folder_name = mod_source.stem
            else:
                mod_folder_name = mod_source.stem

            # Extract/copy mod to injection mods directory immediately
            import shutil
            import zipfile
            
            # Don't clean mods directory - we want to keep skin/map/font/announcer mods if they exist
            
            if mod_source.is_dir():
                mod_dest = injector.mods_dir / mod_source.name
                if mod_dest.exists():
                    shutil.rmtree(mod_dest, ignore_errors=True)
                shutil.copytree(mod_source, mod_dest, dirs_exist_ok=True)
                log.info(f"[SkinMonitor] Copied other mod directory to: {mod_dest}")
            elif mod_source.is_file() and mod_source.suffix.lower() in {".zip", ".fantome"}:
                # Extract ZIP or FANTOME file
                mod_dest = injector.mods_dir / mod_source.stem
                if mod_dest.exists():
                    shutil.rmtree(mod_dest, ignore_errors=True)
                mod_dest.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(mod_source, 'r') as zip_ref:
                    zip_ref.extractall(mod_dest)
                file_type = "ZIP" if mod_source.suffix.lower() == ".zip" else "FANTOME"
                log.info(f"[SkinMonitor] Extracted {file_type} other mod to: {mod_dest}")
            else:
                # For other file types, create folder and copy file
                mod_dest = injector.mods_dir / mod_folder_name
                if mod_dest.exists():
                    shutil.rmtree(mod_dest, ignore_errors=True)
                mod_dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(mod_source, mod_dest / mod_source.name)
                log.info(f"[SkinMonitor] Copied other mod file to folder: {mod_dest}")

            # Store selected other mod in shared state for injection (add to list)
            mod_info = {
                "mod_name": selected_mod.mod_name,
                "mod_path": str(selected_mod.path),
                "mod_folder_name": mod_folder_name,
                "relative_path": str(selected_mod.path.relative_to(self.mod_storage.mods_root)).replace("\\", "/"),
            }
            
            # Check if mod is already in list (by relative_path)
            relative_path = mod_info["relative_path"]
            existing_index = None
            for i, existing_mod in enumerate(self.shared_state.selected_other_mods):
                if existing_mod.get("relative_path") == relative_path:
                    existing_index = i
                    break
            
            if existing_index is None:
                # Add new mod to list
                self.shared_state.selected_other_mods.append(mod_info)
                log.info(f"[SkinMonitor] Other mod selected and extracted: {selected_mod.mod_name}")
                log.info(f"[SkinMonitor] Other mod ready for injection alongside skin (total: {len(self.shared_state.selected_other_mods)})")
            else:
                log.info(f"[SkinMonitor] Other mod already selected: {selected_mod.mod_name}")

        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle other selection: {e}")
            import traceback
            log.debug(f"[SkinMonitor] Traceback: {traceback.format_exc()}")

    def _handle_request_category_mods(self, payload: dict) -> None:
        """Return the list of mods for a specific top-level category under %LOCALAPPDATA%\\Rose\\mods."""
        if not self.mod_storage:
            return

        category = payload.get("category")
        if category not in {
            self.mod_storage.CATEGORY_UI,
            self.mod_storage.CATEGORY_VOICEOVER,
            self.mod_storage.CATEGORY_LOADING_SCREEN,
            self.mod_storage.CATEGORY_VFX,
            self.mod_storage.CATEGORY_SFX,
            self.mod_storage.CATEGORY_OTHERS,
        }:
            log.warning(f"[SkinMonitor] Invalid category for request-category-mods: {category}")
            return

        try:
            mods = self.mod_storage.list_mods_for_category(category)
        except Exception as exc:
            log.error(f"[SkinMonitor] Failed to list category {category}: {exc}")
            mods = []

        historic_other_paths = None
        try:
            from utils.core.mod_historic import get_historic_mod
            historic_other_paths = get_historic_mod("other")
            if isinstance(historic_other_paths, str):
                historic_other_paths = [historic_other_paths]
        except Exception:
            pass

        response_payload = {
            "type": "category-mods-response",
            "category": category,
            "mods": mods,
            "historicMod": historic_other_paths,
            "timestamp": int(time.time() * 1000),
        }
        self._send_response(json.dumps(response_payload))
    
    def _handle_open_logs_folder(self, payload: dict) -> None:
        """Handle open logs folder request"""
        try:
            logs_folder = get_user_data_dir() / "logs"
            logs_folder.mkdir(parents=True, exist_ok=True)
            
            if sys.platform == "win32":
                os.startfile(str(logs_folder))
            else:
                subprocess.Popen(["xdg-open" if os.name != "nt" else "explorer", str(logs_folder)])
            log.info(f"[SkinMonitor] Opened logs folder: {logs_folder}")
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to open logs folder: {e}")
    
    def _handle_open_pengu_loader_ui(self, payload: dict) -> None:
        """Handle open Pengu Loader UI request"""
        try:
            from utils.integration.pengu_loader import PENGU_DIR, PENGU_EXE
            
            if not PENGU_EXE.exists():
                log.warning(f"[SkinMonitor] Pengu Loader executable not found: {PENGU_EXE}")
                return
            
            command = [str(PENGU_EXE), "--ui"]
            
            if sys.platform == "win32":
                subprocess.Popen(command, cwd=str(PENGU_DIR), creationflags=0)
            else:
                subprocess.Popen(command, cwd=str(PENGU_DIR))
            
            log.info(f"[SkinMonitor] Launched Pengu Loader UI: {' '.join(command)}")
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to launch Pengu Loader UI: {e}")
    
    def _handle_settings_save(self, payload: dict) -> None:
        """Handle settings save"""
        try:
            threshold = max(0.3, min(2.0, float(payload.get("threshold", 0.5))))
            monitor_auto_resume_timeout = max(20, min(180, int(payload.get("monitorAutoResumeTimeout", 60))))
            autostart = payload.get("autostart", False)
            game_path = payload.get("gamePath", "")
            
            set_config_option("General", "injection_threshold", f"{threshold:.2f}")
            log.info(f"[SkinMonitor] Injection threshold updated to {threshold:.2f}s")
            
            set_config_option("General", "monitor_auto_resume_timeout", str(monitor_auto_resume_timeout))
            log.info(f"[SkinMonitor] Monitor auto-resume timeout updated to {monitor_auto_resume_timeout}s")
            
            if game_path and game_path.strip():
                set_config_option("General", "leaguePath", game_path.strip())
                # Try to infer and save client path
                from injection.config.config_manager import ConfigManager
                config_manager = ConfigManager()
                inferred_client_path = config_manager.infer_client_path_from_league_path(game_path.strip())
                if inferred_client_path:
                    set_config_option("General", "clientPath", inferred_client_path)
                    log.info(f"[SkinMonitor] League path updated to: {game_path.strip()}, client path: {inferred_client_path}")
                else:
                    log.info(f"[SkinMonitor] League path updated to: {game_path.strip()} (client path could not be inferred)")
            else:
                set_config_option("General", "leaguePath", "")
                set_config_option("General", "clientPath", "")
                log.info("[SkinMonitor] League path cleared, will use auto-detection")
            
            autostart_current = is_registered_for_autostart()
            if autostart != autostart_current:
                if autostart:
                    if not is_admin():
                        self._send_settings_save_error("Administrator privileges are required to enable auto-start.")
                        return
                    
                    success, message_text = register_autostart()
                    if success:
                        log.info("[SkinMonitor] Auto-start registered via settings panel")
                    else:
                        self._send_settings_save_error(f"Failed to enable auto-start: {message_text}")
                        return
                else:
                    if not is_admin():
                        self._send_settings_save_error("Administrator privileges are required to disable auto-start.")
                        return
                    
                    success, message_text = unregister_autostart()
                    if success:
                        log.info("[SkinMonitor] Auto-start unregistered via settings panel")
                    else:
                        self._send_settings_save_error(f"Failed to disable auto-start: {message_text}")
                        return
            
            self._send_settings_save_success()
            log.info("[SkinMonitor] Settings saved successfully")
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle settings save: {e}")
            self._send_settings_save_error(str(e))
    
    def _handle_skin_detection(self, payload: dict) -> None:
        """Handle skin detection message"""
        skin_name = payload.get("skin")
        if not isinstance(skin_name, str) or not skin_name.strip():
            return
        
        if not self.flow_controller.should_process_payload():
            return
        
        skin_name = skin_name.strip()
        if skin_name == self.skin_processor.last_skin_name:
            return
        
        self.skin_processor.last_skin_name = skin_name
        self.skin_processor.process_skin_name(skin_name, self.broadcaster)
    
    def _auto_select_historic_mod(self, mod_type: str, historic_path: str, mod_list: list) -> None:
        """Auto-select a historic mod if it exists in the mod list
        
        Args:
            mod_type: One of "map", "font", "announcer", "other"
            historic_path: Relative path to the historic mod
            mod_list: List of available mods (dicts with id, name, path, etc.)
        """
        try:
            # Find the mod in the list by matching relative path
            selected_mod_dict = None
            for mod_dict in mod_list:
                mod_id = mod_dict.get("id") or mod_dict.get("relativePath") or ""
                # Normalize paths for comparison
                if mod_id.replace("\\", "/") == historic_path.replace("\\", "/"):
                    selected_mod_dict = mod_dict
                    break
            
            if not selected_mod_dict:
                log.debug(f"[MOD_HISTORIC] Historic {mod_type} mod not found in available mods: {historic_path}")
                return
            
            # Create a payload to trigger selection (similar to what frontend would send)
            if mod_type == "map":
                self._handle_select_map({
                    "mapId": selected_mod_dict.get("id") or selected_mod_dict.get("name"),
                    "mapData": selected_mod_dict
                })
            elif mod_type == "font":
                self._handle_select_font({
                    "fontId": selected_mod_dict.get("id") or selected_mod_dict.get("name"),
                    "fontData": selected_mod_dict
                })
            elif mod_type == "announcer":
                self._handle_select_announcer({
                    "announcerId": selected_mod_dict.get("id") or selected_mod_dict.get("name"),
                    "announcerData": selected_mod_dict
                })
            elif mod_type == "other":
                self._handle_select_other({
                    "otherId": selected_mod_dict.get("id") or selected_mod_dict.get("name"),
                    "otherData": selected_mod_dict
                })
            
            log.info(f"[MOD_HISTORIC] Auto-selected historic {mod_type} mod: {selected_mod_dict.get('name', historic_path)}")
        except Exception as e:
            log.debug(f"[MOD_HISTORIC] Failed to auto-select historic {mod_type} mod: {e}")
    
    def _send_response(self, message: str) -> None:
        """Send response message to clients"""
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        
        if running_loop is self.websocket_server.loop:
            self.websocket_server.loop.create_task(self.websocket_server.broadcast(message))
        else:
            asyncio.run_coroutine_threadsafe(
                self.websocket_server.broadcast(message), self.websocket_server.loop
            )
    
    def _send_settings_save_success(self) -> None:
        """Send settings save success response"""
        payload = {"type": "settings-saved", "success": True}
        self._send_response(json.dumps(payload))
    
    def _send_settings_save_error(self, error: str) -> None:
        """Send settings save error response"""
        payload = {"type": "settings-saved", "success": False, "error": error}
        self._send_response(json.dumps(payload))
    
    def _cleanup_empty_skin_folders(self) -> None:
        """Clean up empty skin folders in the mods directory"""
        try:
            skins_dir = self.mod_storage.skins_dir
            if not skins_dir.exists() or not skins_dir.is_dir():
                return
            
            # Get all skin folders
            empty_folders = []
            for skin_folder in skins_dir.iterdir():
                if skin_folder.is_dir():
                    try:
                        items = list(skin_folder.iterdir())
                        if len(items) == 0:
                            empty_folders.append(skin_folder)
                    except Exception as e:
                        log.debug(f"[SkinMonitor] Error checking folder {skin_folder}: {e}")
            
            # Delete empty folders
            for empty_folder in empty_folders:
                try:
                    empty_folder.rmdir()
                    log.info(f"[SkinMonitor] Cleaned up empty skin folder: {empty_folder}")
                except Exception as e:
                    log.debug(f"[SkinMonitor] Error deleting empty folder {empty_folder}: {e}")
            
            # Check if skins directory itself is now empty (but don't delete it)
            try:
                if skins_dir.exists() and skins_dir.is_dir():
                    remaining_items = list(skins_dir.iterdir())
                    if len(remaining_items) == 0:
                        log.debug(f"[SkinMonitor] Skins directory is now empty (kept for future use)")
            except Exception:
                pass
        except Exception as e:
            log.debug(f"[SkinMonitor] Error during folder cleanup: {e}")
    
    def _handle_add_custom_mods_category_selected(self, payload: dict) -> None:
        """Handle category selection for custom mods"""
        try:
            category = payload.get("category")
            if category not in {self.mod_storage.CATEGORY_MAPS, self.mod_storage.CATEGORY_FONTS, 
                               self.mod_storage.CATEGORY_ANNOUNCERS, self.mod_storage.CATEGORY_OTHERS,
                               self.mod_storage.CATEGORY_UI, self.mod_storage.CATEGORY_VOICEOVER,
                               self.mod_storage.CATEGORY_LOADING_SCREEN, self.mod_storage.CATEGORY_VFX,
                               self.mod_storage.CATEGORY_SFX}:
                log.warning(f"[SkinMonitor] Invalid category: {category}")
                return
            
            category_folder = self.mod_storage.mods_root / category
            category_folder.mkdir(parents=True, exist_ok=True)
            
            if sys.platform == "win32":
                os.startfile(str(category_folder))
            else:
                subprocess.Popen(["xdg-open" if os.name != "nt" else "explorer", str(category_folder)])
            
            log.info(f"[SkinMonitor] Opened {category} folder: {category_folder}")
            
            response_payload = {
                "type": "folder-opened-response",
                "success": True,
                "path": str(category_folder),
            }
            self._send_response(json.dumps(response_payload))
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to open {category} folder: {e}")
            response_payload = {
                "type": "folder-opened-response",
                "success": False,
                "error": str(e),
            }
            self._send_response(json.dumps(response_payload))
    
    def _extract_champions_from_data(self, data, champions_dict):
        """Recursively extract champion data from nested structures"""
        if isinstance(data, dict):
            # Check if this dict itself represents a champion
            champ_id = data.get("id") or data.get("championId") or data.get("itemId") or data.get("item_id")
            champ_name = data.get("name") or data.get("title") or data.get("localizedName")
            
            # Only extract if we have both ID and name, and ID looks like a champion ID (not a skin ID)
            if champ_id and champ_name:
                try:
                    champ_id_int = int(champ_id)
                    # Champion IDs are typically < 1000, skin IDs are much higher
                    # Also check if the name doesn't look like a skin name (contains "Skin" or has very long names)
                    if champ_id_int < 1000 and "skin" not in champ_name.lower():
                        champions_dict[champ_id_int] = {"id": champ_id_int, "name": champ_name}
                except (ValueError, TypeError):
                    pass
            
            # Recursively search in all values
            for value in data.values():
                self._extract_champions_from_data(value, champions_dict)
        
        elif isinstance(data, list):
            # Recursively search in all list items
            for item in data:
                self._extract_champions_from_data(item, champions_dict)
    
    def _handle_add_custom_mods_champion_selected(self, payload: dict) -> None:
        """Handle champion list request for custom mods"""
        try:
            action = payload.get("action")
            if action != "list":
                return
            
            # Clean up empty skin folders before showing champion list
            self._cleanup_empty_skin_folders()
            
            # Check if LCU is available
            if not self.skin_scraper or not self.skin_scraper.lcu or not self.skin_scraper.lcu.ok:
                response_payload = {
                    "type": "champions-list-response",
                    "champions": [],
                    "error": "LCU is not available. Please ensure League of Legends client is running.",
                }
                self._send_response(json.dumps(response_payload))
                return
            
            champions = []
            champions_dict = {}  # Use dict to avoid duplicates
            
            # Use shop endpoint to get all champions with retry logic
            max_retries = 3
            retry_delay = 0.5  # Wait 0.5 seconds between retries
            
            for attempt in range(max_retries):
                try:
                    champions_data = self.skin_scraper.lcu.get("/lol-store/v1/champions", timeout=5.0)
                    
                    if champions_data:
                        # Log response type for debugging
                        if attempt == 0:  # Only log structure on first attempt to avoid spam
                            log.debug(f"[SkinMonitor] Shop endpoint response type: {type(champions_data).__name__}")
                            if isinstance(champions_data, dict):
                                log.debug(f"[SkinMonitor] Shop endpoint response keys: {list(champions_data.keys())[:10]}")
                            elif isinstance(champions_data, list):
                                log.debug(f"[SkinMonitor] Shop endpoint response length: {len(champions_data)}")
                        
                        # Recursively extract champion data from the response
                        self._extract_champions_from_data(champions_data, champions_dict)
                        
                        # If we found champions, we're done
                        if len(champions_dict) > 0:
                            log.debug(f"[SkinMonitor] Successfully fetched {len(champions_dict)} champions from shop endpoint (attempt {attempt + 1})")
                            break
                        else:
                            log.debug(f"[SkinMonitor] Shop endpoint returned data but no champions extracted (attempt {attempt + 1})")
                    else:
                        log.debug(f"[SkinMonitor] Shop endpoint returned no data (attempt {attempt + 1})")
                    
                    # If we got here and haven't found champions, wait and retry
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        
                except Exception as e:
                    log.debug(f"[SkinMonitor] Failed to fetch champions from shop endpoint (attempt {attempt + 1}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
            
            if len(champions_dict) == 0:
                log.warning(f"[SkinMonitor] Failed to fetch champions from shop endpoint after {max_retries} attempts")
            
            # Sort champions by name
            champions = list(champions_dict.values())
            champions.sort(key=lambda x: x["name"])
            
            response_payload = {
                "type": "champions-list-response",
                "champions": champions,
            }
            self._send_response(json.dumps(response_payload))
            log.info(f"[SkinMonitor] Sent champions list: {len(champions)} champions")
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to fetch champions list: {e}")
            response_payload = {
                "type": "champions-list-response",
                "champions": [],
                "error": f"Failed to fetch champions: {str(e)}",
            }
            self._send_response(json.dumps(response_payload))
    
    def _handle_add_custom_mods_skin_selected(self, payload: dict) -> None:
        """Handle skin selection for custom mods"""
        try:
            action = payload.get("action")
            champion_id = payload.get("championId")
            
            if action == "list":
                # Return skins list for champion
                if not champion_id:
                    response_payload = {
                        "type": "champion-skins-response",
                        "championId": None,
                        "skins": [],
                        "error": "Champion ID is required",
                    }
                    self._send_response(json.dumps(response_payload))
                    return
                
                # Check if LCU is available
                if not self.skin_scraper or not self.skin_scraper.lcu or not self.skin_scraper.lcu.ok:
                    response_payload = {
                        "type": "champion-skins-response",
                        "championId": champion_id,
                        "skins": [],
                        "error": "LCU is not available. Please ensure League of Legends client is running.",
                    }
                    self._send_response(json.dumps(response_payload))
                    return
                
                # Fetch champion data
                champion_data = self.skin_scraper.lcu.get(
                    f"/lol-game-data/assets/v1/champions/{champion_id}.json",
                    timeout=5.0
                )
                
                skins = []
                champion_name = None
                
                if champion_data and isinstance(champion_data, dict):
                    champion_name = champion_data.get("name", f"Champion {champion_id}")
                    raw_skins = champion_data.get("skins", [])
                    
                    for skin in raw_skins:
                        try:
                            skin_id = skin.get("id")
                            if not skin_id:
                                # Calculate skin ID: champion_id * 1000 + skin_index
                                skin_index = skin.get("num", 0)
                                skin_id = int(champion_id) * 1000 + int(skin_index)
                            
                            skin_name = skin.get("name", f"Skin {skin_id}")
                            skins.append({
                                "id": skin_id,
                                "skinId": skin_id,
                                "name": skin_name,
                            })
                        except (ValueError, TypeError, AttributeError):
                            continue
                
                # Sort skins by ID
                skins.sort(key=lambda x: x["skinId"])
                
                response_payload = {
                    "type": "champion-skins-response",
                    "championId": champion_id,
                    "championName": champion_name,
                    "skins": skins,
                }
                self._send_response(json.dumps(response_payload))
                log.info(f"[SkinMonitor] Sent skins list for champion {champion_id}: {len(skins)} skins")
            
            elif action == "create":
                # Create folder and open
                champion_id = payload.get("championId")
                skin_id = payload.get("skinId")
                
                if not champion_id or not skin_id:
                    response_payload = {
                        "type": "folder-opened-response",
                        "success": False,
                        "error": "Champion ID and Skin ID are required",
                    }
                    self._send_response(json.dumps(response_payload))
                    return
                
                # Create skin folder
                skin_folder = self.mod_storage.get_skin_dir(skin_id)
                skin_folder.mkdir(parents=True, exist_ok=True)
                
                # Open folder
                if sys.platform == "win32":
                    os.startfile(str(skin_folder))
                else:
                    subprocess.Popen(["xdg-open" if os.name != "nt" else "explorer", str(skin_folder)])
                
                log.info(f"[SkinMonitor] Created and opened skin folder: {skin_folder}")
                
                response_payload = {
                    "type": "folder-opened-response",
                    "success": True,
                    "path": str(skin_folder),
                }
                self._send_response(json.dumps(response_payload))
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle skin selection: {e}")
            import traceback
            log.debug(f"[SkinMonitor] Traceback: {traceback.format_exc()}")
            
            response_payload = {
                "type": "folder-opened-response" if action == "create" else "champion-skins-response",
                "success": False,
                "error": str(e),
            }
            if action == "list":
                response_payload["championId"] = champion_id
                response_payload["skins"] = []
            self._send_response(json.dumps(response_payload))

