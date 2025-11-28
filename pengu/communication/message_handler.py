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
        elif payload_type == "open-logs-folder":
            self._handle_open_logs_folder(payload)
        elif payload_type == "open-pengu-loader-ui":
            self._handle_open_pengu_loader_ui(payload)
        elif payload_type == "settings-save":
            self._handle_settings_save(payload)
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
            monitor_auto_resume_timeout = get_config_float("General", "monitor_auto_resume_timeout", 20.0)
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

        response_payload = {
            "type": "skin-mods-response",
            "championId": champion_id,
            "skinId": skin_id,
            "mods": mods_payload,
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
            monitor_auto_resume_timeout = max(20, min(90, int(payload.get("monitorAutoResumeTimeout", 20))))
            autostart = payload.get("autostart", False)
            game_path = payload.get("gamePath", "")
            
            set_config_option("General", "injection_threshold", f"{threshold:.2f}")
            log.info(f"[SkinMonitor] Injection threshold updated to {threshold:.2f}s")
            
            set_config_option("General", "monitor_auto_resume_timeout", str(monitor_auto_resume_timeout))
            log.info(f"[SkinMonitor] Monitor auto-resume timeout updated to {monitor_auto_resume_timeout}s")
            
            if game_path and game_path.strip():
                set_config_option("General", "leaguePath", game_path.strip())
                log.info(f"[SkinMonitor] Game path updated to: {game_path.strip()}")
            else:
                set_config_option("General", "leaguePath", "")
                log.info("[SkinMonitor] Game path cleared, will use auto-detection")
            
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

