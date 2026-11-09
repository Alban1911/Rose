#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Message Handler
Routes and handles different WebSocket message types
"""

import asyncio
import base64
import binascii
import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from functools import partial
from pathlib import Path, PureWindowsPath
from typing import NamedTuple, Optional, Sequence, TypedDict
from urllib.parse import quote

from config import get_config_float, get_config_option, set_config_option
from injection.mods.mod_source import LtkEntry, ModSource
from injection.mods.storage import ModStorageService
from injection.overlay.ltf_report import has_ltf_logs_hint, ltk_failure_cause
from injection.baseskin.library import stored_skin_rewrite
from injection.overlay.ltk_library import LtkLibrary
from utils.core.paths import get_user_data_dir, get_asset_path, open_folder_in_explorer
from utils.core import issue_reporter
from utils.core.issue_reporter import clear_issues, in_this_session, parse_stamp, read_issues_tail, remove_issues
from utils.core.safe_extract import MOD_ARCHIVE_SUFFIXES
from utils.core.utilities import get_base_skin_id_for_chroma
from ui.handlers.randomization_handler import cancel_random_mode_for_selection
from utils.system.admin_utils import (
    is_admin,
    is_registered_for_autostart,
    register_autostart,
    unregister_autostart,
)

log = logging.getLogger(__name__)


def _is_unc_path(path_value: str) -> bool:
    """Return True for UNC/device paths that can trigger network auth/probing."""
    stripped = path_value.strip()
    return stripped.startswith(("\\\\", "//"))


def _is_safe_relative_path(path_value: str) -> bool:
    """Validate a client-supplied path is relative and cannot traverse upward."""
    if not isinstance(path_value, str):
        return False

    cleaned = path_value.strip().replace("/", "\\")
    if not cleaned:
        return False

    candidate = PureWindowsPath(cleaned)
    if candidate.is_absolute() or candidate.drive or _is_unc_path(cleaned):
        return False

    return all(part not in {"", ".", ".."} for part in candidate.parts)


# Messages that wait on the user (file picker) or on disk and LCU work. They run
# in order on one worker thread, so the bridge keeps answering every plugin
# meanwhile (Manage Mods stayed on "Loading champions..." during an import)
BACKGROUND_MESSAGE_TYPES = frozenset({
    "add-custom-mods-category-selected",
    "add-custom-mods-champion-selected",
    "add-custom-mods-skin-selected",
    "request-manage-categories",
    "request-manage-champion-mods",
    "request-manage-category-mods",
    "set-champion-mod-image",
    "delete-champion-mod",
    "delete-champion-mods",
    "delete-category-mod",
    "delete-category-mods",
    "rename-champion-mod",
    "rename-category-mod",
})


def _image_editable(mod_path: Path) -> bool:
    """A stored folder holds its image (META/image.png); an archive has it
    beside it, under its name (ModStorageService.set_champion_mod_image)."""
    return mod_path.is_dir() or mod_path.suffix.lower() in MOD_ARCHIVE_SUFFIXES


def _mod_thumbnail_details(
    image_files: Sequence[Path],
    mods_root: Path,
    port: int,
) -> tuple[Optional[str], Optional[str]]:
    """A saved mod's preview image, the first of its *image_files*
    (SavedMod.image_paths) there is, as the plugins load it."""
    thumbnail_path = next((path for path in image_files if path.is_file()), None)
    if thumbnail_path is None:
        return None, None
    relative_path = str(thumbnail_path.relative_to(mods_root)).replace("\\", "/")
    quoted_path = quote(relative_path, safe="/")
    version = thumbnail_path.stat().st_mtime_ns
    return relative_path, f"http://127.0.0.1:{port}/mod-asset/{quoted_path}?v={version}"


def _unavailable(source: ModSource) -> Optional[str]:
    """Why a picked saved mod cannot be injected from *source*, as the user
    is told; None when it can."""
    if source.available:
        return None
    if isinstance(source, LtkEntry):
        return "This mod is missing from LTK Manager - add it again"
    return "The mod files are missing"


class ListedMod(TypedDict, total=False):
    """A mod as the plugins' listings hold it, sent back with a selection:
    its id is its relative path (its identity), path where it is."""

    id: str
    name: str
    path: str
    updatedAt: float
    description: str


class _OneModCategory(NamedTuple):
    """A category the user picks one mod of: the select message's id and data
    keys, the category, and the shared state attribute that keeps the pick
    (its mod_historic key is the kind _ONE_MOD_CATEGORIES files it under)."""

    id_key: str
    data_key: str
    category: str
    state_attr: str


_ONE_MOD_CATEGORIES = {
    "map": _OneModCategory("mapId", "mapData", "maps", "selected_map_mod"),
    "font": _OneModCategory("fontId", "fontData", "fonts", "selected_font_mod"),
    "announcer": _OneModCategory("announcerId", "announcerData", "announcers", "selected_announcer_mod"),
}


# LTK Manager's rule for a base skin that uses another skin's model or name:
# its patcher turns the whole champion WAD off in game (a "skinhack")
SKINHACK_RULE = "bin/skinhack"


def _rejected_import(item: dict, result: dict) -> dict:
    """The import error for a mod LTK Manager will turn off in game. "code"
    picks the panel's (translated) text; "error" is for the log."""
    problems = result.get("problems") or []
    reason = " ".join(p.get("description") or p.get("title") or "" for p in problems).strip()
    if any(p.get("rule") == SKINHACK_RULE for p in problems):
        code, error = "ltk_skinhack", "LTK Manager considers this mod a skinhack, so it can't be played"
    else:
        code = "ltk_rejected"
        error = "LTK Manager found problems it can't repair in this mod" + (f" ({reason})" if reason else "") + \
            ", so it can't be played"
    return {"fileName": item.get("fileName", ""), "error": error, "code": code, "reason": reason}


def _choose_mod_files() -> list[Path]:
    """Show a native file picker for one or more user-selected mod archives."""
    root = None
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        selected_files = filedialog.askopenfilenames(
            title="Select Rose mod files",
            filetypes=[
                ("Rose mods", "*.fantome *.zip *.modpkg"),
                ("Fantome mods", "*.fantome"),
                ("ZIP mods", "*.zip"),
                ("Mod packages", "*.modpkg"),
                ("All files", "*.*"),
            ],
        )
        return [Path(selected) for selected in selected_files]
    except Exception as exc:  # noqa: BLE001
        log.error("[SkinMonitor] Could not open the mod file picker: %s", exc)
        return []
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def _choose_mod_image_file() -> Optional[Path]:
    """Show a native file picker for a skin mod preview image."""
    root = None
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        selected = filedialog.askopenfilename(
            title="Select a PNG image for the skin mod",
            filetypes=[("PNG images", "*.png")],
        )
        return Path(selected) if selected else None
    except Exception as exc:  # noqa: BLE001
        log.error("[ManageMods] Could not open the skin mod image picker: %s", exc)
        raise RuntimeError(f"Could not open image picker: {exc}") from exc
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


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
        # Worker thread for BACKGROUND_MESSAGE_TYPES, started on first use
        self._background_queue: Optional[queue.Queue] = None
        self._background_lock = threading.Lock()
        self.websocket_server = websocket_server
        self.broadcaster = broadcaster
        self.skin_processor = skin_processor
        self.flow_controller = flow_controller
        self.skin_scraper = skin_scraper
        self.port = port
        self.mod_storage = mod_storage or ModStorageService()
        self.injection_manager = injection_manager

    def _is_valid_local_league_path(self, game_path: str) -> bool:
        """Validate a League install path without touching UNC/network paths."""
        if not isinstance(game_path, str):
            return False

        cleaned = game_path.strip()
        if not cleaned or _is_unc_path(cleaned):
            return False

        game_dir = Path(cleaned)
        if not game_dir.is_absolute():
            return False

        try:
            if game_dir.exists() and game_dir.is_dir():
                from config import GAME_EXECUTABLE_NAMES
                return any((game_dir / name).is_file() for name in GAME_EXECUTABLE_NAMES)
        except Exception as e:
            log.debug(f"[Settings] Could not validate League path {game_path!r}: {e}")
            return False

        return False
    
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
        
        if not isinstance(payload, dict):
            log.warning("[SkinMonitor] Ignoring payload that is not an object: %.200s", message)
            return

        payload_type = payload.get("type")
        if payload_type in BACKGROUND_MESSAGE_TYPES:
            self._run_in_background(payload_type, payload)
            return
        # An error escaping here would end the bridge connection and drop
        # every message after it. A handler that keeps failing (on every
        # hover, say) is reported once per message type and error.
        try:
            self._route(payload_type, payload)
        except Exception as e:  # noqa: BLE001
            key = (payload_type, repr(e))
            if key != getattr(self, "_last_route_error", None):
                self._last_route_error = key
                log.exception("[SkinMonitor] Failed to handle %s: %s", payload_type, e)

    def _run_in_background(self, payload_type: str, payload: dict) -> None:
        """Queue a message for the worker thread, starting it on first use."""
        with self._background_lock:
            if self._background_queue is None:
                self._background_queue = queue.Queue()
                threading.Thread(
                    target=self._background_worker, name="BridgeWorker", daemon=True
                ).start()
            self._background_queue.put((payload_type, payload))

    def _background_worker(self) -> None:
        while True:
            payload_type, payload = self._background_queue.get()
            try:
                self._route(payload_type, payload)
            except Exception as e:  # noqa: BLE001
                log.exception("[SkinMonitor] Failed to handle %s: %s", payload_type, e)

    def _route(self, payload_type: Optional[str], payload: dict) -> None:
        # Route to appropriate handler
        if payload_type in {"chroma-log", "plugin-log"}:
            self._handle_chroma_log(payload)
        elif payload_type == "request-local-preview":
            self._handle_request_local_preview(payload)
        elif payload_type == "request-local-asset":
            self._handle_request_local_asset(payload)
        elif payload_type == "chroma-selection":
            self._handle_chroma_selection(payload)
        elif payload_type == "dice-button-click":
            self._handle_dice_button_click(payload)
        elif payload_type == "favorite-toggle-skin":
            self._handle_favorite_toggle_skin(payload)
        elif payload_type == "favorite-toggle-chroma":
            self._handle_favorite_toggle_chroma(payload)
        elif payload_type == "request-favorites":
            self._handle_request_favorites(payload)
        elif payload_type == "settings-request":
            self._handle_settings_request(payload)
        elif payload_type == "path-validate":
            self._handle_path_validate(payload)
        elif payload_type == "open-mods-folder":
            self._handle_open_mods_folder(payload)
        elif payload_type == "request-skin-mods":
            self._handle_request_skin_mods(payload)
        elif payload_type == "request-manage-categories":
            self._handle_request_manage_categories(payload)
        elif payload_type == "request-manage-champion-mods":
            self._handle_request_manage_champion_mods(payload)
        elif payload_type == "request-manage-category-mods":
            self._handle_request_manage_category_mods(payload)
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
        elif payload_type in ("select-map", "select-font", "select-announcer"):
            self._handle_select_one_mod(payload_type[len("select-"):], payload)
        elif payload_type == "select-other":
            self._handle_select_other(payload)
        elif payload_type == "open-logs-folder":
            self._handle_open_logs_folder(payload)
        elif payload_type == "diagnostics-request":
            self._handle_diagnostics_request(payload)
        elif payload_type == "diagnostics-clear":
            self._handle_diagnostics_clear(payload)
        elif payload_type == "stop-injection":
            self._handle_stop_injection(payload)
        elif payload_type == "diagnostics-delete":
            self._handle_diagnostics_delete(payload)
        elif payload_type == "diagnostics-clear-category":
            self._handle_diagnostics_clear_category(payload)
        elif payload_type == "diagnostics-clear-tracker":
            self._handle_diagnostics_clear_tracker(payload)
        elif payload_type == "diagnostics-apply-recommended":
            self._handle_diagnostics_apply_recommended(payload)
        elif payload_type == "open-pengu-loader-ui":
            self._handle_open_pengu_loader_ui(payload)
        elif payload_type == "settings-save":
            self._handle_settings_save(payload)
        elif payload_type == "language-save":
            self._handle_language_save(payload)
        elif payload_type == "add-custom-mods-category-selected":
            self._handle_add_custom_mods_category_selected(payload)
        elif payload_type == "add-custom-mods-champion-selected":
            self._handle_add_custom_mods_champion_selected(payload)
        elif payload_type == "add-custom-mods-skin-selected":
            self._handle_add_custom_mods_skin_selected(payload)
        elif payload_type == "find-match-hover":
            self._handle_find_match_hover(payload)
        elif payload_type == "dismiss-custom-mod":
            self._handle_dismiss_custom_mod(payload)
        elif payload_type == "delete-champion-mod":
            self._handle_delete_champion_mod(payload)
        elif payload_type == "delete-champion-mods":
            self._handle_delete_champion_mods(payload)
        elif payload_type == "delete-category-mod":
            self._handle_delete_category_mod(payload)
        elif payload_type == "delete-category-mods":
            self._handle_delete_category_mods(payload)
        elif payload_type == "rename-champion-mod":
            self._handle_rename_champion_mod(payload)
        elif payload_type == "set-champion-mod-image":
            self._handle_set_champion_mod_image(payload)
        elif payload_type == "rename-category-mod":
            self._handle_rename_category_mod(payload)
        elif payload_type == "dismiss-historic":
            self._handle_dismiss_historic(payload)
        # Party mode messages
        elif payload_type == "party-enable":
            self._handle_party_enable(payload)
        elif payload_type == "party-disable":
            self._handle_party_disable(payload)
        elif payload_type == "party-add-peer":
            self._handle_party_add_peer(payload)
        elif payload_type == "party-remove-peer":
            self._handle_party_remove_peer(payload)
        elif payload_type == "party-get-state":
            self._handle_party_get_state(payload)
        elif payload.get("skin"):
            # Handle skin detection message
            self._handle_skin_detection(payload)
    
    def _handle_chroma_log(self, payload: dict) -> None:
        """Forward structured plugin logs at their requested severity."""
        source = str(payload.get("source") or "UnknownPlugin")[:64]
        event = payload.get("event") or payload.get("message") or "unknown"
        level = str(payload.get("level") or "info").lower()
        logger = {
            "debug": log.debug,
            "warn": log.warning,
            "warning": log.warning,
            "error": log.error,
            "critical": log.critical,
        }.get(level, log.info)
        details = payload.get("data")
        if details is None:
            logger("[PLUGIN:%s] %s", source, event)
        else:
            logger("[PLUGIN:%s] %s | %s", source, event, details)
    
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
                    encoded_asset_path = quote(asset_path.replace(chr(92), "/"), safe="/")
                    http_url = f"http://localhost:{self.port}/asset/{encoded_asset_path}"
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
                cancel_random_mode_for_selection(
                    self.shared_state, chroma_id, f"chroma selection (chromaId={chroma_id})"
                )
                
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
    
    def _handle_find_match_hover(self, payload: dict) -> None:
        """Handle Find-Match button hover — force base skins immediately."""
        t0 = time.perf_counter()
        js_ts = payload.get("timestamp", 0)
        now_ms = int(time.time() * 1000)
        latency = now_ms - js_ts if js_ts else "?"
        log.info(f"[SkinMonitor] Find-Match hover received (JS→Py latency: {latency}ms)")
        self.shared_state._find_match_hover_at = t0
        callback = getattr(self.shared_state, "force_base_skins_callback", None)
        if callback:
            try:
                callback()
                elapsed_ms = (time.perf_counter() - t0) * 1000
                log.info(f"[SkinMonitor] Base skin force completed in {elapsed_ms:.0f}ms")
            except Exception as e:
                log.warning(f"[SkinMonitor] Base skin force failed: {e}")
        else:
            log.debug("[SkinMonitor] No force_base_skins_callback registered")

    def _handle_dice_button_click(self, payload: dict) -> None:
        """Handle dice button click"""
        button_state = payload.get("state", "disabled")
        mode = payload.get("mode", "all")
        log.info(f"[SkinMonitor] Dice button clicked from JavaScript: state={button_state}, mode={mode}")
        
        try:
            from ui.core.user_interface import get_user_interface
            ui = get_user_interface(self.shared_state, self.skin_scraper)
            
            if button_state == "disabled":
                ui._handle_dice_click_disabled(mode=mode)
            elif button_state == "enabled":
                ui._handle_dice_click_enabled()
            else:
                log.warning(f"[SkinMonitor] Unknown dice button state: {button_state}")
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle dice button click: {e}")

    def _handle_favorite_toggle_skin(self, payload: dict) -> None:
        """Handle skin favorite toggle event from JavaScript"""
        try:
            import importlib
            import utils.core.favorites
            importlib.reload(utils.core.favorites)
            from utils.core.favorites import toggle_skin_favorite
            champion_id = payload.get("championId")
            skin_id = payload.get("skinId")
            if not champion_id or not skin_id:
                log.warning("[SkinMonitor] Invalid favorite-toggle-skin payload: %s", payload)
                return
            
            is_fav, champ_favs = toggle_skin_favorite(int(champion_id), int(skin_id))
            log.info(f"[SkinMonitor] Toggled favorite skin {skin_id} for champion {champion_id} -> {is_fav}")
            self.broadcaster.broadcast_favorites_state(int(champion_id))
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle favorite-toggle-skin: {e}")

    def _handle_favorite_toggle_chroma(self, payload: dict) -> None:
        """Handle chroma favorite toggle event from JavaScript"""
        try:
            import importlib
            import utils.core.favorites
            importlib.reload(utils.core.favorites)
            from utils.core.favorites import toggle_chroma_favorite
            champion_id = payload.get("championId")
            skin_id = payload.get("skinId")
            chroma_id = payload.get("chromaId")
            if not champion_id or not skin_id or not chroma_id:
                log.warning("[SkinMonitor] Invalid favorite-toggle-chroma payload: %s", payload)
                return
            
            is_fav, champ_favs = toggle_chroma_favorite(int(champion_id), int(skin_id), int(chroma_id))
            log.info(f"[SkinMonitor] Toggled favorite chroma {chroma_id} for skin {skin_id} -> {is_fav}")
            self.broadcaster.broadcast_favorites_state(int(champion_id))
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle favorite-toggle-chroma: {e}")

    def _handle_request_favorites(self, payload: dict) -> None:
        """Handle favorites request from JavaScript"""
        try:
            champion_id = payload.get("championId")
            if champion_id:
                self.broadcaster.broadcast_favorites_state(int(champion_id))
            else:
                self.broadcaster.broadcast_favorites_state()
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle request-favorites: {e}")
    
    def _handle_settings_request(self, payload: dict) -> None:
        """Handle settings request"""
        try:
            from config import INJECTION_THRESHOLD_DEFAULT_S, clamp_injection_threshold
            threshold = clamp_injection_threshold(
                get_config_float("General", "injection_threshold", INJECTION_THRESHOLD_DEFAULT_S)
            )
            monitor_auto_resume_timeout = get_config_float("General", "monitor_auto_resume_timeout", 60.0)
            autostart = is_registered_for_autostart()
            hide_empty_categories = (get_config_option("General", "hide_empty_categories", "false") or "false").lower() == "true"
            game_path = get_config_option("General", "leaguePath") or ""
            # Only this session's errors light up Troubleshooting
            diagnostics_errors = [e for e in self._compute_diagnostics_errors() if e.get("thisSession")]
            
            path_valid = False
            if game_path:
                path_valid = self._is_valid_local_league_path(game_path)
            
            from config import APP_VERSION
            response_payload = {
                "type": "settings-data",
                "threshold": threshold,
                "monitorAutoResumeTimeout": int(monitor_auto_resume_timeout),
                "autostart": autostart,
                "hideEmptyCategories": hide_empty_categories,
                "gamePath": game_path,
                "gamePathValid": path_valid,
                "hasErrors": len(diagnostics_errors) > 0,
                "errorsCount": len(diagnostics_errors),
                "version": APP_VERSION,
            }
            self._send_response(json.dumps(response_payload))
            
            log.info(f"[SkinMonitor] Settings data sent: threshold={threshold}, monitor_auto_resume_timeout={monitor_auto_resume_timeout}, autostart={autostart}, hide_empty_categories={hide_empty_categories}, gamePath={game_path}, valid={path_valid}")
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle settings request: {e}")

    def _handle_diagnostics_clear(self, payload: dict) -> None:
        """Clear rose_diagnostics.txt (Diagnostics)"""
        try:
            ok = clear_issues()
            response_payload = {
                "type": "diagnostics-cleared",
                "success": bool(ok),
            }
            self._send_response(json.dumps(response_payload))
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to clear diagnostics: {e}")
            try:
                self._send_response(json.dumps({"type": "diagnostics-cleared", "success": False}))
            except Exception as send_error:
                log.debug('[SkinMonitor] Could not send diagnostics failure response: %s', send_error)

    def _handle_stop_injection(self, payload: dict) -> None:
        """Stop injection from the reconnect screen so a crashing mod can be skipped."""
        stopped = False
        try:
            if self.injection_manager:
                self.injection_manager.stop_injection_by_user()
                stopped = True
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to stop injection: {e}")
        self._send_response(json.dumps({"type": "injection-stopped", "success": stopped}))

    def _handle_diagnostics_delete(self, payload: dict) -> None:
        """Delete the Troubleshooting entries the user dismissed, then resend the list."""
        keys = {str(k).strip() for k in (payload.get("keys") or []) if str(k).strip()}
        if keys:
            self._compute_diagnostics_errors(delete_keys=keys)
        self._handle_diagnostics_request(payload)

    def _handle_diagnostics_clear_category(self, payload: dict) -> None:
        """
        Clear only a diagnostics category from rose_diagnostics.txt.
        Categories:
          - injection_threshold
          - monitor_timeout
          - disk_space
        """
        try:
            cats = payload.get("categories") or []
            if isinstance(cats, str):
                cats = [cats]
            if payload.get("category"):
                cats.append(payload.get("category"))

            norm: set[str] = set()
            for c in cats:
                cl = str(c or "").strip().lower()
                if not cl:
                    continue
                if cl in ('disk_space', 'low_disk_space'):
                    norm.add('disk_space')
                    continue
                if cl in ("injection_threshold", "threshold", "injection"):
                    norm.add("injection_threshold")
                elif cl in ("monitor_timeout", "monitor", "monitor_auto_resume_timeout", "auto_resume"):
                    norm.add("monitor_timeout")

            ok = self._clear_issues_categories(norm) if norm else False
            self._send_response(
                json.dumps(
                    {
                        "type": "diagnostics-cleared-category",
                        "success": bool(ok),
                        "categories": sorted(norm),
                    }
                )
            )
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to clear diagnostics category: {e}")
            try:
                self._send_response(json.dumps({"type": "diagnostics-cleared-category", "success": False, "categories": []}))
            except Exception as send_error:
                log.debug('[SkinMonitor] Could not send diagnostics failure response: %s', send_error)

    def _handle_diagnostics_clear_tracker(self, payload: dict) -> None:
        """Clear base skin confirmation tracker samples."""
        try:
            from injection.config.base_skin_tracker import clear_samples
            clear_samples()
            self._send_response(json.dumps({"type": "diagnostics-tracker-cleared", "success": True}))
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to clear tracker samples: {e}")
            try:
                self._send_response(json.dumps({"type": "diagnostics-tracker-cleared", "success": False}))
            except Exception as send_error:
                log.debug('[SkinMonitor] Could not send diagnostics failure response: %s', send_error)

    def _handle_diagnostics_apply_recommended(self, payload: dict) -> None:
        """Apply the tracker-recommended injection threshold value."""
        try:
            from injection.config.base_skin_tracker import get_stats as _get_skin_stats
            stats = _get_skin_stats()
            rec_ms = stats.get("recommended_threshold_ms")
            if rec_ms is None:
                self._send_response(json.dumps({"type": "diagnostics-applied-recommended", "success": False, "reason": "no data"}))
                return

            from config import clamp_injection_threshold, set_config_option
            rec_s = round(clamp_injection_threshold(float(rec_ms) / 1000.0), 2)

            set_config_option("General", "injection_threshold", str(rec_s))

            # Refresh the live threshold if injection manager is available
            try:
                if hasattr(self, '_injection_manager') and self._injection_manager:
                    self._injection_manager.refresh_injection_threshold()
            except Exception as e:
                log.warning('[SkinMonitor] Recommended threshold saved but not applied to the running injector: %s', e)

            self._send_response(json.dumps({
                "type": "diagnostics-applied-recommended",
                "success": True,
                "appliedThresholdS": rec_s,
                "appliedThresholdMs": rec_ms,
            }))
            log.info(f"[SkinMonitor] Applied recommended threshold: {rec_s}s ({rec_ms}ms)")
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to apply recommended threshold: {e}")
            try:
                self._send_response(json.dumps({"type": "diagnostics-applied-recommended", "success": False}))
            except Exception as send_error:
                log.debug('[SkinMonitor] Could not send diagnostics failure response: %s', send_error)

    def _clear_issues_categories(self, categories: set[str]) -> bool:
        """Remove matching diagnostics entries from rose_diagnostics.txt (best-effort)."""
        try:
            if not categories:
                return False
            p = get_user_data_dir() / "rose_diagnostics.txt"
            if not p.exists():
                return True

            txt = p.read_text(encoding="utf-8", errors="ignore").splitlines()

            # Parse file into entry blocks: ["ts | msg", optional "Fix: ..."]
            blocks: list[tuple[str, str]] = []
            i = 0
            while i < len(txt):
                line = (txt[i] or "").rstrip()
                if " | " in line:
                    msg = line
                    fix = ""
                    if i + 1 < len(txt):
                        nxt = (txt[i + 1] or "").rstrip()
                        if nxt.startswith("Fix:"):
                            fix = nxt
                            i += 1
                    blocks.append((msg, fix))
                i += 1

            def _cat_for(msg_line: str, fix_line: str) -> str:
                ml = (msg_line or "").lower()
                fl = (fix_line or "").lower()
                # Match the same categories we summarize
                if 'not enough disk space' in ml or ('disk space' in ml and 'injection failed' in ml):
                    return 'disk_space'
                if "auto-resume safety" in ml or "monitor auto-resume timeout" in fl:
                    return "monitor_timeout"
                if "base skin forcing took longer" in ml or "injection threshold" in ml or "injection threshold" in fl or "base skin force time" in fl or "base skin confirmation" in fl or "verification failed" in ml:
                    return "injection_threshold"
                return "other"

            kept_lines: list[str] = []
            for msg_line, fix_line in blocks:
                cat = _cat_for(msg_line, fix_line)
                if cat in categories:
                    continue
                kept_lines.append(msg_line)
                if fix_line:
                    kept_lines.append(fix_line)

            # Preserve trailing newline style expected by the reader
            p.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""), encoding="utf-8", errors="ignore")
            return True
        except Exception as e:
            log.warning(f"[SkinMonitor] Could not clear diagnostics categories {categories}: {e}")
            return False

    def _handle_diagnostics_request(self, payload: dict) -> None:
        """
        Return a compact, user-friendly list of recent errors, derived from rose_diagnostics.txt.
        Also includes base skin confirmation stats from the tracker.
        The goal is "what to change" rather than raw logs.
        """
        try:
            out = self._compute_diagnostics_errors()

            # Include base skin confirmation stats from the tracker
            tracker_stats = {}
            try:
                from injection.config.base_skin_tracker import get_stats as _get_skin_stats
                tracker_stats = _get_skin_stats()
            except Exception as e:
                log.debug('[SkinMonitor] Base skin tracker stats unavailable: %s', e)

            response_payload = {
                "type": "diagnostics-data",
                "errors": out,
                "path": str(get_user_data_dir() / "rose_diagnostics.txt"),
                "baseSkinStats": tracker_stats,
                "sessionStart": issue_reporter.SESSION_START,
            }
            self._send_response(json.dumps(response_payload))
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle diagnostics request: {e}")
            try:
                self._send_response(json.dumps({"type": "diagnostics-data", "errors": [], "path": ""}))
            except Exception as send_error:
                log.debug('[SkinMonitor] Could not send diagnostics failure response: %s', send_error)

    def _compute_diagnostics_errors(self, delete_keys: Optional[set[str]] = None) -> list[dict]:
        """Compute compact diagnostics error list from rose_diagnostics.txt (never raises).

        With delete_keys, first removes every report whose summary key is in it.
        """
        try:
            raw_lines = read_issues_tail(max_lines=400)

            entries: list[dict] = []
            i = 0
            while i < len(raw_lines):
                line = (raw_lines[i] or "").strip()
                if " | " in line:
                    ts_part, msg = line.split(" | ", 1)
                    fix = None
                    if i + 1 < len(raw_lines):
                        nxt = (raw_lines[i + 1] or "").strip()
                        if nxt.startswith("Fix:"):
                            fix = nxt
                            i += 1
                    entries.append({"ts": ts_part.strip(), "msg": msg.strip(), "fix": (fix or "").strip()})
                i += 1

            def _summarize(msg: str, fix: str) -> Optional[dict]:
                ml = (msg or "").lower()
                fl = (fix or "").lower()

                # Filter out "not actually an error" noise
                if "injection skipped" in ml and "base skin selected" in ml:
                    return None

                # Parse helper(s)
                def _extract_first_seconds(text: str) -> Optional[float]:
                    try:
                        m = re.search(r"after\s+(\d+(?:\.\d+)?)\s*s", text, flags=re.IGNORECASE)
                        if not m:
                            return None
                        return float(m.group(1))
                    except Exception:
                        return None

                def _clamp(v: float, lo: float, hi: float) -> float:
                    try:
                        return max(lo, min(hi, float(v)))
                    except Exception:
                        return float(lo)

                # Category: Monitor Auto-Resume Timeout (AUTO_RESUME_TRIGGERED)
                if "monitor auto-resume timeout" in fl or "auto-resume safety" in ml:
                    observed = _extract_first_seconds(msg or "")  # from "after 60s"
                    recommended = None
                    if isinstance(observed, (int, float)):
                        recommended = int(_clamp(max(float(observed) + 30.0, 60.0), 1.0, 180.0))
                    return {
                        "code": "AUTO_RESUME_TRIGGERED",
                        "text": "Monitor Auto-Resume Timeout → increase",
                        "observedTimeoutS": observed,
                        "recommendedMonitorTimeoutS": recommended,
                    }

                # Category: Injection Threshold (BASE_SKIN_FORCE_SLOW / BASE_SKIN_VERIFY_FAILED)
                if "injection threshold" in ml or "injection threshold" in fl or "base skin force time" in fl or "base skin confirmation" in fl:
                    # Use tracker-based recommendation when available (p90 + buffer from real data),
                    # fall back to parsing the hint text for legacy diagnostics entries.
                    recommended_ms = None
                    tracker_p90 = None
                    tracker_samples = None
                    try:
                        from injection.config.base_skin_tracker import get_stats as _get_skin_stats
                        stats = _get_skin_stats()
                        if stats.get("recommended_threshold_ms") is not None:
                            recommended_ms = stats["recommended_threshold_ms"]
                            tracker_p90 = stats.get("p90_ms")
                            tracker_samples = stats.get("confirmed_count")
                    except Exception as e:
                        log.debug('[SkinMonitor] Base skin tracker stats unavailable for summary: %s', e)

                    force_ms = None
                    thresh_ms = None
                    if recommended_ms is None:
                        # Legacy fallback: parse single-sample hint text
                        try:
                            m = re.search(
                                r"base skin force time:\s*([0-9.]+)\s*(ms|s)\s*[,)]?\s*.*?"
                                r"injection threshold:\s*([0-9.]+)\s*(ms|s)",
                                fix or "",
                                flags=re.IGNORECASE,
                            )
                            if m:
                                force_v = float(m.group(1))
                                force_u = (m.group(2) or "").lower()
                                thresh_v = float(m.group(3))
                                thresh_u = (m.group(4) or "").lower()
                                force_ms = int(round(force_v * (1000.0 if force_u == "s" else 1.0)))
                                thresh_ms = int(round(thresh_v * (1000.0 if thresh_u == "s" else 1.0)))
                            if isinstance(force_ms, (int, float)) and force_ms is not None:
                                recommended_ms = int(_clamp(max(float(force_ms) + 250.0, 500.0), 1.0, 2000.0))
                        except Exception:
                            pass

                    recommended_s = (float(recommended_ms) / 1000.0) if isinstance(recommended_ms, int) else None
                    code_out = "BASE_SKIN_VERIFY_FAILED" if ("verification failed" in ml) else "BASE_SKIN_FORCE_SLOW"
                    result = {
                        "code": code_out,
                        "text": "Injection Threshold → increase",
                        "baseSkinForceTimeMs": force_ms,
                        "injectionThresholdAtTimeMs": thresh_ms,
                        "recommendedThresholdMs": recommended_ms,
                        "recommendedThresholdS": recommended_s,
                    }
                    if tracker_p90 is not None:
                        result["trackerP90Ms"] = tracker_p90
                    if tracker_samples is not None:
                        result["trackerSamples"] = tracker_samples
                    return result

                # Category: LTK Manager's built-in mods hold every champion's
                # archive (before the LTF category: it names LTK Manager too)
                if "built-in mods put every champion" in ml:
                    builtins = msg.split('(', 1)[1].rsplit(')', 1)[0].strip() if '(' in msg else ''
                    return {
                        'code': 'LTK_HEAVY_BUILTINS',
                        'text': 'LTK Manager built-in mods slow every game -> turn them off',
                        'detail': builtins,
                    }

                # Category: LTK Manager's own programs set to run as
                # administrator (before the LTF category: it names LTK Manager)
                if "ltk manager is set to run as administrator" in ml:
                    programs = msg.split('(', 1)[1].rsplit(')', 1)[0].strip() if '(' in msg else ''
                    return {
                        'code': 'LTK_ELEVATED',
                        'text': 'LTK Manager set to run as administrator -> turn it off',
                        'detail': programs,
                    }

                # Category: LTK Manager's automatic mod check took minutes while
                # the game loaded (before the LTF category: it names LTK Manager)
                if "automatic mod check took" in ml:
                    took = re.search(r"took (\d+)s", msg)
                    return {
                        'code': 'LTK_SLOW_MOD_CHECK',
                        'text': 'LTK Manager mod check slows loading -> turn it off',
                        'detail': took.group(1) if took else '',
                    }

                # Category: the League client runs as administrator (checked on
                # each client connection; before the Windows account category)
                if "can't apply skins" in ml and 'league client runs as administrator' in ml:
                    return {
                        'code': 'LEAGUE_ELEVATED',
                        'text': 'League runs as administrator -> start it normally',
                        'cause': 'running',
                    }
                if "can't apply skins" in ml and 'league is set to run as administrator' in ml:
                    programs = msg.split('(', 1)[1].rsplit(')', 1)[0].strip() if '(' in msg else ''
                    return {
                        'code': 'LEAGUE_ELEVATED',
                        'text': 'League set to run as administrator -> turn it off',
                        'cause': 'setting',
                        'detail': programs,
                    }

                # Category: Windows runs every program as administrator (startup
                # check; before the LTF category, whose markers it also names)
                if "can't apply skins" in ml and 'as administrator' in ml:
                    if 'built-in administrator' in ml:
                        cause = 'builtin'
                    elif 'user account control is turned off' in ml:
                        cause = 'uac'
                    else:
                        cause = 'other'
                    return {
                        'code': 'WINDOWS_ADMIN_SHELL',
                        'text': 'Windows runs programs as administrator -> use a regular account',
                        'cause': cause,
                    }

                # Category: Low disk space during overlay creation
                if 'not enough disk space' in ml or ('disk space' in ml and 'injection failed' in ml):
                    return {
                        'code': 'LOW_DISK_SPACE',
                        'text': 'Low Disk Space -> free up space',
                    }

                # Category: LTF session (Rose's bridge driving LTK Manager).
                # The overlay manager's import messages and hints are the
                # markers: a mod name or an error text names nothing reliable
                is_import_failure = (
                    ml.startswith('injection failed: could not install') or 'no mods could be installed' in ml
                )
                is_ltf_report = (
                    is_import_failure
                    or has_ltf_logs_hint(fl)
                    or 'ltf' in ml or 'ltk patcher' in ml or 'ltk manager' in ml
                )
                if is_ltf_report:
                    if 'bridge files are missing' in ml:
                        return {'code': 'LTF_MISSING', 'text': 'LTF bridge files missing -> reinstall Rose'}
                    if 'ltk manager is not installed' in ml:
                        return {'code': 'LTK_MANAGER_MISSING', 'text': 'LTK Manager missing -> install it'}
                    detail = msg.split('Injection failed:', 1)[-1].strip()
                    # An install that failed because LTK Manager's browser did not
                    # answer is not an import problem (older reports name it so)
                    if is_import_failure and ltk_failure_cause(detail) != 'cdp':
                        return {
                            'code': 'LTF_IMPORT_FAILED',
                            'text': 'Mod import failed',
                            'detail': detail,
                            'cause': 'import',
                        }
                    return {
                        'code': 'LTF_FAILED',
                        'text': 'LTK patcher error',
                        'detail': detail,
                        # Picks the panel's hint: what to do depends on why
                        # the session failed
                        'cause': ltk_failure_cause(detail),
                    }

                # Fallback: keep it short
                short = msg.strip()
                if len(short) > 60:
                    short = short[:57] + "..."
                return {"code": "", "text": short or ""} if (short or "") else None

            def _summary_key(msg: str, fix: str) -> str:
                summary_obj = _summarize(msg, fix)
                return (summary_obj.get("text") or "").strip() if summary_obj else ""

            if delete_keys:
                # Drop older duplicates too, or they would take the deleted entry's place
                remove_issues(
                    lambda msg_line, fix_line: _summary_key(msg_line.split(" | ", 1)[1].strip(), fix_line.strip())
                    in delete_keys
                )
                entries = [e for e in entries if _summary_key(e.get("msg", ""), e.get("fix", "")) not in delete_keys]

            # Keep last N unique summaries (most recent occurrences), most recent first
            seen: set[str] = set()
            out: list[dict] = []
            for ent in reversed(entries):
                summary_obj = _summarize(ent.get("msg", ""), ent.get("fix", ""))
                if not summary_obj:
                    continue
                summary_text = (summary_obj.get("text") or "").strip()
                if not summary_text:
                    continue
                if summary_text in seen:
                    continue
                seen.add(summary_text)
                stamp = parse_stamp(ent.get("ts", ""))
                when = stamp.when
                payload = {
                    "ts": datetime.fromtimestamp(when).strftime("%d/%m/%y %H:%M") if when is not None else ent.get("ts", ""),
                    "at": when,
                    "thisSession": in_this_session(stamp),
                    "key": summary_text,
                    **summary_obj,
                }
                out.append(payload)
                if len(out) >= 8:
                    break
            return out
        except Exception as e:
            # Troubleshooting would look empty while errors were recorded
            log.warning(f"[SkinMonitor] Could not read the diagnostics entries: {e}")
            return []
    
    def _handle_path_validate(self, payload: dict) -> None:
        """Handle path validation request"""
        try:
            game_path = payload.get("gamePath", "")
            path_valid = False
            
            if game_path and game_path.strip():
                path_valid = self._is_valid_local_league_path(game_path)
            
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
            open_folder_in_explorer(mods_folder)
            log.info(f"[SkinMonitor] Opened mods folder: {mods_folder}")
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to open mods folder: {e}")
    
    def _handle_request_skin_mods(self, payload: dict) -> None:
        """Return the list of custom mods for a champion (all skins)"""
        if not self.mod_storage:
            return

        skin_id = payload.get("skinId")
        if skin_id is None:
            return

        champion_id = payload.get("championId")
        if not champion_id:
            from utils.core.utilities import get_champion_id_from_skin_id
            champion_id = get_champion_id_from_skin_id(int(skin_id))

        try:
            entries = self.mod_storage.list_mods_for_champion(champion_id)
        except Exception as exc:
            log.error(f"[SkinMonitor] Failed to list skin mods: {exc}")
            entries = []

        compatible_skin_ids = self._get_compatible_skin_ids(skin_id)
        mods_payload = [
            {
                **self._champion_mod_payload(entry),
                "availableForRequestedSkin": bool(self._get_entry_target_skin_ids(entry) & compatible_skin_ids),
            }
            for entry in entries
        ]

        # Get historic custom mod path for this champion if available
        historic_mod_path = None
        try:
            from utils.core.historic import get_historic_skin_for_champion, is_custom_mod_path, get_custom_mod_path
            if champion_id:
                historic_value = get_historic_skin_for_champion(champion_id)
                if historic_value and is_custom_mod_path(historic_value):
                    historic_mod_path = get_custom_mod_path(historic_value)
                    historic_identifier = self._normalize_mod_identifier(historic_mod_path)
                    matching_mod = next(
                        (
                            mod
                            for mod in mods_payload
                            if self._normalize_mod_identifier(mod.get("relativePath"))
                            == historic_identifier
                        ),
                        None,
                    )
                    # A saved mod is only a candidate for the current skin.
                    # Do not send it to the UI for unrelated skins, otherwise
                    # the UI can restore it before the user chooses a skin.
                    if not matching_mod or not matching_mod.get("availableForRequestedSkin"):
                        historic_mod_path = None
        except Exception as e:
            log.warning('[SkinMonitor] Could not resolve saved custom mod for skin; it will not be restored: %s', e)

        response_payload = {
            "type": "skin-mods-response",
            "requestId": payload.get("requestId"),
            "championId": champion_id,
            "skinId": skin_id,
            "mods": mods_payload,
            "hideEmptyCategories": (get_config_option("General", "hide_empty_categories", "false") or "false").lower() == "true",
            "historicMod": historic_mod_path,  # Add historic mod path if available
            "compatibleSkinIds": sorted(compatible_skin_ids),
            "timestamp": int(time.time() * 1000),
        }
        self._send_response(json.dumps(response_payload))

    def _lookup_champion_name(self, champion_id: object) -> Optional[str]:
        try:
            champ_id = int(champion_id)
        except (TypeError, ValueError):
            return None
        scraper = getattr(self, "skin_scraper", None)
        lcu = getattr(scraper, "lcu", None) if scraper else None
        if not lcu or not getattr(lcu, "ok", False):
            return None
        try:
            champion_data = lcu.get(
                f"/lol-game-data/assets/v1/champions/{champ_id}.json",
                timeout=5.0,
            )
        except Exception as e:
            log.debug(f"[SkinMonitor] Could not fetch champion {champ_id} data: {e}")
            return None
        if not isinstance(champion_data, dict):
            return None
        name = champion_data.get("name")
        return str(name) if name else None

    def _champion_mod_payload(self, entry) -> dict:
        """A saved skin mod (SkinModEntry) as the plugins list it."""
        try:
            relative_path = entry.path.relative_to(self.mod_storage.mods_root)
        except Exception:
            relative_path = entry.path
        thumbnail_relative_path = None
        thumbnail_url = None
        try:
            thumbnail_relative_path, thumbnail_url = _mod_thumbnail_details(
                entry.image_files,
                self.mod_storage.mods_root,
                self.port,
            )
        except Exception as e:
            log.debug(f"[SkinMonitor] No thumbnail for mod {entry.path}: {e}")
        return {
            "modName": entry.mod_name,
            "displayName": entry.display_name,
            "skinId": entry.skin_id,
            "targetSkinIds": sorted(self._get_entry_target_skin_ids(entry)),
            "description": entry.description,
            "updatedAt": int(entry.updated_at * 1000),
            "relativePath": str(relative_path).replace("\\", "/"),
            "thumbnailRelativePath": thumbnail_relative_path,
            "thumbnailUrl": thumbnail_url,
            "imageEditable": _image_editable(entry.path),
        }

    def _handle_request_manage_champion_mods(self, payload: dict) -> None:
        """List champion mods for the Settings manage UI without touching champ-select state."""
        if not self.mod_storage:
            return
        champion_id = payload.get("championId")
        if not champion_id:
            return
        try:
            entries = self.mod_storage.list_mods_for_champion(champion_id)
        except Exception as exc:
            log.error("[ManageMods] Failed to list champion mods: %s", exc)
            entries = []
        self._send_response(json.dumps({
            "type": "manage-champion-mods-response",
            "championId": champion_id,
            "championName": self._lookup_champion_name(champion_id),
            "mods": [self._champion_mod_payload(entry) for entry in entries],
            "timestamp": int(time.time() * 1000),
        }))

    def _handle_request_manage_categories(self, payload: dict) -> None:
        """List the categories Manage Mods offers: only those with a mod added."""
        if not self.mod_storage:
            return
        try:
            categories = self.mod_storage.categories_with_mods()
        except Exception as exc:
            log.error("[ManageMods] Failed to list categories with mods: %s", exc)
            categories = []
        self._send_response(json.dumps({
            "type": "manage-categories-response",
            "categories": categories,
        }))

    def _handle_request_manage_category_mods(self, payload: dict) -> None:
        """List category mods for the Settings manage UI without historic auto-select."""
        if not self.mod_storage:
            return
        category = payload.get("category")
        if category not in self.mod_storage.MOD_CATEGORIES:
            log.warning("[ManageMods] Invalid category: %s", category)
            return
        try:
            mods = self.mod_storage.list_mods_for_category(category)
        except Exception as exc:
            log.error("[ManageMods] Failed to list category %s: %s", category, exc)
            mods = []
        self._send_response(json.dumps({
            "type": "manage-category-mods-response",
            "category": category,
            "mods": mods,
            "timestamp": int(time.time() * 1000),
        }))

    def _get_compatible_skin_ids(self, skin_id: int | str) -> set[int]:
        """Return storage skin IDs that can be used for a requested skin.

        Most mods are stored under the exact skin ID. Chroma/form IDs are
        sometimes reported by the client even though their mod is stored
        under the base skin ID, so include that base ID when it is known.
        """
        try:
            requested_skin_id = int(skin_id)
        except (TypeError, ValueError):
            return set()

        compatible_ids = {requested_skin_id}
        cache = getattr(self.skin_scraper, "cache", None)
        chroma_id_map = getattr(cache, "chroma_id_map", None)
        base_skin_id = get_base_skin_id_for_chroma(requested_skin_id, chroma_id_map)
        if base_skin_id is not None:
            compatible_ids.add(int(base_skin_id))
        return compatible_ids

    @staticmethod
    def _get_entry_target_skin_ids(entry) -> set[int]:
        """Return the manually configured target IDs for a stored mod."""
        normalized = set()
        try:
            target_ids = getattr(entry, "target_skin_ids", ()) or ()
            for value in target_ids:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    normalized.add(value)
        except (AttributeError, TypeError):
            pass
        if not normalized:
            try:
                normalized.add(int(entry.skin_id))
            except (AttributeError, TypeError, ValueError):
                pass
        return normalized

    @staticmethod
    def _normalize_mod_identifier(value: object) -> str:
        return str(value or "").strip().replace(chr(92), "/").casefold()

    def _mod_matches_identifier(self, entry, mod_id: object) -> bool:
        """Match a client ID without allowing ambiguous names to win first."""
        requested = self._normalize_mod_identifier(mod_id)
        if not requested:
            return False

        try:
            relative_path = entry.path.relative_to(self.mod_storage.mods_root)
        except (ValueError, AttributeError):
            relative_path = entry.path

        relative_value = self._normalize_mod_identifier(str(relative_path))
        name_value = self._normalize_mod_identifier(entry.mod_name)
        return requested in {relative_value, name_value}

    def _send_custom_mod_selection_result(
        self,
        payload: dict,
        *,
        success: bool,
        operation: str,
        error: str | None = None,
        selected_mod=None,
    ) -> None:
        """Tell every UI whether its selection request was applied."""
        result = {
            "type": "custom-mod-selection-result",
            "success": success,
            "operation": operation,
            "requestId": payload.get("requestId"),
            "championId": payload.get("championId"),
            "skinId": payload.get("skinId"),
            "modId": payload.get("modId"),
            "timestamp": int(time.time() * 1000),
        }
        if error:
            result["error"] = error
        if selected_mod is not None:
            try:
                relative_path = selected_mod.path.relative_to(self.mod_storage.mods_root)
            except (ValueError, AttributeError):
                relative_path = selected_mod.path
            result.update(
                {
                    "modName": selected_mod.mod_name,
                    "displayName": selected_mod.display_name,
                    "relativePath": str(relative_path).replace(chr(92), "/"),
                    "targetSkinId": payload.get("skinId"),
                    "storageSkinId": selected_mod.skin_id,
                    "targetSkinIds": sorted(self._get_entry_target_skin_ids(selected_mod)),
                }
            )
        self._send_response(json.dumps(result))
    
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
        except Exception as e:
            log.warning('[SkinMonitor] Could not load saved map selection; it will not be restored: %s', e)
        
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
        except Exception as e:
            log.warning('[SkinMonitor] Could not load saved font selection; it will not be restored: %s', e)
        
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
        except Exception as e:
            log.warning('[SkinMonitor] Could not load saved announcer selection; it will not be restored: %s', e)
        
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
        except Exception as e:
            log.warning('[SkinMonitor] Could not load saved other mods selection; it will not be restored: %s', e)
        
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
            self._send_custom_mod_selection_result(
                payload,
                success=False,
                operation="select" if payload.get("modId") is not None else "deselect",
                error="Mod storage is not available",
            )
            return

        champion_id = payload.get("championId")
        skin_id = payload.get("skinId")
        mod_id = payload.get("modId")

        try:
            champion_id = int(champion_id)
            skin_id = int(skin_id)
        except (TypeError, ValueError):
            champion_id = None
            skin_id = None

        operation = "select" if mod_id is not None else "deselect"
        if not champion_id or not skin_id:
            log.warning(f"[SkinMonitor] Invalid mod selection payload: championId={champion_id}, skinId={skin_id}")
            self._send_custom_mod_selection_result(
                payload,
                success=False,
                operation=operation,
                error="Champion or skin ID is invalid",
            )
            return

        payload = {**payload, "championId": champion_id, "skinId": skin_id}

        # Handle deselection (mod_id is null)
        if mod_id is None:
            # Clear selected mod if it matches this skin, and remove extracted files so it
            # doesn't keep injecting after being unchecked.
            selected_custom_mod = getattr(self.shared_state, "selected_custom_mod", None)
            selected_target_skin_ids = set()
            if selected_custom_mod:
                try:
                    selected_target_skin_ids = {
                        int(value)
                        for value in selected_custom_mod.get("target_skin_ids", ())
                        if int(value) > 0
                    }
                except (TypeError, ValueError):
                    selected_target_skin_ids = set()
            selected_matches_skin = bool(
                selected_custom_mod
                and selected_custom_mod.get("champion_id") == champion_id
                and (
                    selected_custom_mod.get("skin_id") in self._get_compatible_skin_ids(skin_id)
                    or selected_custom_mod.get("storage_skin_id") in self._get_compatible_skin_ids(skin_id)
                    or bool(selected_target_skin_ids & self._get_compatible_skin_ids(skin_id))
                )
            )
            requested_mod_id = payload.get("expectedModId") or payload.get("modId")
            selected_matches_requested_mod = True
            if selected_custom_mod and requested_mod_id:
                selected_identifiers = {
                    self._normalize_mod_identifier(selected_custom_mod.get("relative_path")),
                    self._normalize_mod_identifier(selected_custom_mod.get("mod_name")),
                }
                selected_matches_requested_mod = (
                    self._normalize_mod_identifier(requested_mod_id) in selected_identifiers
                )

            should_clear_selection = (
                selected_custom_mod
                and selected_matches_requested_mod
                and (selected_matches_skin or bool(requested_mod_id))
            )
            if should_clear_selection:
                # If this mod was saved as "historic" for auto-selection, clear it too.
                # Otherwise InjectionTrigger will auto-reselect it at injection time.
                try:
                    from utils.core.historic import (
                        clear_historic_entry,
                        get_historic_skin_for_champion,
                        is_custom_mod_path,
                        get_custom_mod_path,
                    )

                    champ_id = self.shared_state.selected_custom_mod.get("champion_id")
                    rel_path = self.shared_state.selected_custom_mod.get("relative_path")
                    if champ_id and rel_path:
                        historic_value = get_historic_skin_for_champion(int(champ_id))
                        if historic_value is not None and is_custom_mod_path(historic_value):
                            historic_path = get_custom_mod_path(historic_value)
                            if historic_path and historic_path.replace("\\", "/") == str(rel_path).replace("\\", "/"):
                                clear_historic_entry(int(champ_id))
                                log.info("[HISTORIC] Cleared saved custom mod for champion %s", champ_id)
                except Exception as exc:
                    log.debug("[HISTORIC] Failed to clear saved custom mod on deselect: %s", exc)

                self._take_back_custom_mod("SkinMonitor")
                self.shared_state.selected_custom_mod = None
                log.info(f"[SkinMonitor] Custom mod deselected for skin {skin_id}")

                # Broadcast deactivated custom mod state to JavaScript
                try:
                    if self.shared_state and hasattr(self.shared_state, 'ui_skin_thread') and self.shared_state.ui_skin_thread:
                        self.shared_state.ui_skin_thread._broadcast_custom_mod_state()
                except Exception as e:
                    log.debug(f"[SkinMonitor] Failed to broadcast custom mod state on deselect: {e}")
                self._send_custom_mod_selection_result(
                    payload,
                    success=True,
                    operation="deselect",
                )
            elif selected_custom_mod and requested_mod_id and not selected_matches_requested_mod:
                log.info("[SkinMonitor] Ignoring stale custom mod deselection for %s", requested_mod_id)
                self._send_custom_mod_selection_result(
                    payload,
                    success=False,
                    operation="deselect",
                    error="A different custom mod is already selected",
                )
            else:
                self._send_custom_mod_selection_result(
                    payload,
                    success=True,
                    operation="deselect",
                )
            return

        selected_mod = None
        try:
            # Find the mod in storage (search all skins for this champion)
            if not champion_id:
                from utils.core.utilities import get_champion_id_from_skin_id
                champion_id = get_champion_id_from_skin_id(int(skin_id))

            entries = self.mod_storage.list_mods_for_champion(champion_id)
            selected_mod = None
            for entry in entries:
                # Match by mod name or relative path
                if (entry.mod_name == mod_id or
                    str(entry.path.relative_to(self.mod_storage.mods_root)).replace("\\", "/") == mod_id):
                    selected_mod = entry
                    break

            compatible_skin_ids = self._get_compatible_skin_ids(skin_id)
            matching_entries = [
                entry
                for entry in entries
                if (
                    self._get_entry_target_skin_ids(entry) & compatible_skin_ids
                    and self._mod_matches_identifier(entry, mod_id)
                )
            ]
            # Prefer a mod whose manual target list explicitly contains the
            # requested skin or chroma.
            selected_mod = next(
                (
                    entry
                    for entry in matching_entries
                    if skin_id in self._get_entry_target_skin_ids(entry)
                ),
                matching_entries[0] if matching_entries else None,
            )

            if not selected_mod:
                log.warning(f"[SkinMonitor] Mod not found: {mod_id} for champion {champion_id}")
                self._send_custom_mod_selection_result(
                    payload,
                    success=False,
                    operation="select",
                    error="The selected mod is no longer available for this skin",
                )
                return

            # Extract mod immediately when selected (not during injection)
            if not self.injection_manager:
                log.warning("[SkinMonitor] Cannot extract mod - injection manager not available")
                self._send_custom_mod_selection_result(
                    payload,
                    success=False,
                    operation="select",
                    error="The injection manager is not ready",
                    selected_mod=selected_mod,
                )
                return
                
            injector = self.injection_manager.injector
            if not injector:
                log.warning("[SkinMonitor] Cannot extract mod - injector not available")
                self._send_custom_mod_selection_result(
                    payload,
                    success=False,
                    operation="select",
                    error="The injector is not ready",
                    selected_mod=selected_mod,
                )
                return

            source = selected_mod.source
            error = _unavailable(source)
            if error:
                log.warning(f"[SkinMonitor] Cannot select {selected_mod.mod_name}: {error}")
                self._send_custom_mod_selection_result(
                    payload,
                    success=False,
                    operation="select",
                    error=error,
                    selected_mod=selected_mod,
                )
                return

            # Extract/copy mod to injection mods directory immediately
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
            
            prepared = source.put(injector.mods_dir)
            if prepared is None:
                raise RuntimeError("The mod could not be linked or extracted into the injection folder")
            log.info(f"[SkinMonitor] Prepared mod for the injection: {prepared}")

            self.shared_state.selected_custom_mod = {
                "skin_id": int(skin_id),
                "storage_skin_id": selected_mod.skin_id,
                "target_skin_ids": sorted(self._get_entry_target_skin_ids(selected_mod)),
                "champion_id": champion_id,
                "mod_name": selected_mod.mod_name,
                "display_name": selected_mod.display_name,
                "relative_path": str(selected_mod.path.relative_to(self.mod_storage.mods_root)).replace("\\", "/"),
                "source": source,
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
            
            log.info(
                "[SkinMonitor] Custom mod selected and extracted: %s "
                "(target skin %s; storage skin %s)",
                selected_mod.mod_name,
                skin_id,
                selected_mod.skin_id,
            )
            log.info(f"[SkinMonitor] Mod ready for injection on threshold trigger")

            # Broadcast custom mod state to JavaScript to show mod name
            try:
                if self.shared_state and hasattr(self.shared_state, 'ui_skin_thread') and self.shared_state.ui_skin_thread:
                    self.shared_state.ui_skin_thread._broadcast_custom_mod_state()
            except Exception as e:
                log.debug(f"[SkinMonitor] Failed to broadcast custom mod state on selection: {e}")

            self._send_custom_mod_selection_result(
                payload,
                success=True,
                operation="select",
                selected_mod=selected_mod,
            )

        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle mod selection: {e}")
            import traceback
            log.debug(f"[SkinMonitor] Traceback: {traceback.format_exc()}")
            self._send_custom_mod_selection_result(
                payload,
                success=False,
                operation="select",
                error=f"Could not prepare the mod: {e}",
                selected_mod=selected_mod,
            )
    
    def _handle_dismiss_custom_mod(self, payload: dict) -> None:
        """Dismiss the active custom mod selection (close-button on popup)"""
        if not getattr(self.shared_state, "selected_custom_mod", None):
            return

        self._take_back_custom_mod("Dismiss")

        # Clear historic entry so it doesn't auto-reselect
        try:
            from utils.core.historic import (
                clear_historic_entry,
                get_historic_skin_for_champion,
                is_custom_mod_path,
                get_custom_mod_path,
            )
            champ_id = self.shared_state.selected_custom_mod.get("champion_id")
            rel_path = self.shared_state.selected_custom_mod.get("relative_path")
            if champ_id and rel_path:
                historic_value = get_historic_skin_for_champion(int(champ_id))
                if historic_value is not None and is_custom_mod_path(historic_value):
                    historic_path = get_custom_mod_path(historic_value)
                    if historic_path and historic_path.replace("\\", "/") == str(rel_path).replace("\\", "/"):
                        clear_historic_entry(int(champ_id))
                        log.info("[Dismiss] Cleared historic entry for champion %s", champ_id)
        except Exception as exc:
            log.debug("[Dismiss] Failed to clear historic entry: %s", exc)

        self.shared_state.selected_custom_mod = None
        log.info("[Dismiss] Custom mod dismissed via popup close button")

        # Broadcast cleared state
        try:
            if hasattr(self.shared_state, "ui_skin_thread") and self.shared_state.ui_skin_thread:
                self.shared_state.ui_skin_thread._broadcast_custom_mod_state()
        except Exception as exc:
            log.debug("[Dismiss] Failed to broadcast custom mod state: %s", exc)

    def _take_back_custom_mod(self, tag: str) -> None:
        """Take the selected custom mod back out of the injection's mods
        folder (its source's take_back), so it does not keep injecting once
        unpicked. Best effort: a failure is only logged under *tag*."""
        try:
            mod = self.shared_state.selected_custom_mod.get("source")
            injector = getattr(self.injection_manager, "injector", None)
            if mod is not None and injector is not None:
                mod.take_back(injector.mods_dir)
        except Exception as exc:
            log.debug("[%s] Failed to take the custom mod out of the injection: %s", tag, exc)

    def _clear_active_selection_if_matches(self, champion_id: object, relative_path: object) -> None:
        """Clear the active/historic custom mod selection if it points at the deleted mod."""
        if not relative_path:
            return
        normalized_target = str(relative_path).replace("\\", "/")

        selected = getattr(self.shared_state, "selected_custom_mod", None)
        if selected:
            selected_rel = selected.get("relative_path")
            if selected_rel and str(selected_rel).replace("\\", "/") == normalized_target:
                self.shared_state.selected_custom_mod = None
                try:
                    if hasattr(self.shared_state, "ui_skin_thread") and self.shared_state.ui_skin_thread:
                        self.shared_state.ui_skin_thread._broadcast_custom_mod_state()
                except Exception as exc:
                    log.debug("[DeleteMod] Failed to broadcast custom mod state: %s", exc)

        try:
            from utils.core.historic import (
                clear_historic_entry,
                get_historic_skin_for_champion,
                is_custom_mod_path,
                get_custom_mod_path,
            )
            if champion_id:
                historic_value = get_historic_skin_for_champion(int(champion_id))
                if historic_value is not None and is_custom_mod_path(historic_value):
                    historic_path = get_custom_mod_path(historic_value)
                    if historic_path and historic_path.replace("\\", "/") == normalized_target:
                        clear_historic_entry(int(champion_id))
                        log.info("[DeleteMod] Cleared historic entry for champion %s", champion_id)
        except Exception as exc:
            log.debug("[DeleteMod] Failed to clear historic entry: %s", exc)

    def _handle_delete_champion_mod(self, payload: dict) -> None:
        """Permanently delete an imported skin mod from a champion's mod folder."""
        champion_id = payload.get("championId")
        mod_name = payload.get("modName")
        relative_path = payload.get("relativePath")
        if not self.mod_storage:
            self._send_response(json.dumps({
                "type": "champion-mod-deleted",
                "success": False,
                "championId": champion_id,
                "modName": mod_name,
                "error": "Mod storage is not available",
            }))
            return
        try:
            deleted = self.mod_storage.delete_champion_mod(
                champion_id,
                mod_name=mod_name,
                relative_path=relative_path,
            )
            if deleted:
                self._clear_active_selection_if_matches(champion_id, relative_path)
                log.info(
                    "[DeleteMod] Deleted champion mod: champion=%s, mod=%s",
                    champion_id,
                    mod_name,
                )
            response_payload = {
                "type": "champion-mod-deleted",
                "success": deleted,
                "championId": champion_id,
                "modName": mod_name,
                "relativePath": relative_path,
            }
            if not deleted:
                response_payload["error"] = "Mod not found"
            self._send_response(json.dumps(response_payload))
        except Exception as exc:
            log.error("[DeleteMod] Failed to delete champion mod: %s", exc)
            self._send_response(json.dumps({
                "type": "champion-mod-deleted",
                "success": False,
                "championId": champion_id,
                "modName": mod_name,
                "error": str(exc),
            }))

    def _handle_delete_champion_mods(self, payload: dict) -> None:
        """Delete selected skin mods and report each result in one response."""
        champion_id = payload.get("championId")
        mods = payload.get("mods")
        if not self.mod_storage:
            error = "Mod storage is not available"
            results = []
        elif not isinstance(mods, list) or not mods:
            error = "At least one skin mod is required"
            results = []
        else:
            error = None
            results = []
            for mod in mods:
                if not isinstance(mod, dict):
                    results.append({"success": False, "error": "Invalid mod entry"})
                    continue
                mod_name = mod.get("modName")
                relative_path = mod.get("relativePath")
                try:
                    deleted = self.mod_storage.delete_champion_mod(
                        champion_id,
                        mod_name=mod_name,
                        relative_path=relative_path,
                    )
                    if deleted:
                        self._clear_active_selection_if_matches(champion_id, relative_path)
                        results.append({
                            "success": True,
                            "modName": mod_name,
                            "relativePath": relative_path,
                        })
                    else:
                        results.append({
                            "success": False,
                            "modName": mod_name,
                            "relativePath": relative_path,
                            "error": "Mod not found",
                        })
                except Exception as exc:
                    log.error("[DeleteMod] Failed to delete champion mod %s: %s", mod_name, exc)
                    results.append({
                        "success": False,
                        "modName": mod_name,
                        "relativePath": relative_path,
                        "error": str(exc),
                    })

        deleted_count = sum(result.get("success", False) for result in results)
        failures = len(results) - deleted_count
        response = {
            "type": "champion-mods-bulk-deleted",
            "championId": champion_id,
            "success": failures == 0 and error is None,
            "partial": deleted_count > 0 and failures > 0,
            "deletedCount": deleted_count,
            "results": results,
        }
        if error:
            response["error"] = error
        self._send_response(json.dumps(response))

    def _clear_category_selection_if_matches(self, category: object, mod_name: object) -> None:
        """Clear live selection and mod historic if they point at the deleted category mod."""
        if not category or not mod_name:
            return
        target = f"{category}/{mod_name}".replace("\\", "/")
        # An archive mod is selected by its path, extension included
        targets = {target, f"{target}.fantome"}

        def _same_path(value: object) -> bool:
            return bool(value) and str(value).replace("\\", "/") in targets

        single_attr = {
            "maps": ("selected_map_mod", "map"),
            "fonts": ("selected_font_mod", "font"),
            "announcers": ("selected_announcer_mod", "announcer"),
        }.get(str(category))
        if single_attr:
            attr, historic_key = single_attr
            selected = getattr(self.shared_state, attr, None)
            if isinstance(selected, dict) and _same_path(selected.get("relative_path")):
                setattr(self.shared_state, attr, None)
            try:
                from utils.core.mod_historic import clear_historic_mod, get_historic_mod
                historic_value = get_historic_mod(historic_key)
                if _same_path(historic_value):
                    clear_historic_mod(historic_key)
            except Exception as exc:
                log.debug("[DeleteMod] Failed to clear category historic: %s", exc)
            return

        selected_others = list(getattr(self.shared_state, "selected_other_mods", None) or [])
        remaining = [
            item for item in selected_others
            if not (isinstance(item, dict) and _same_path(item.get("relative_path")))
        ]
        if len(remaining) != len(selected_others):
            self.shared_state.selected_other_mods = remaining
        try:
            from utils.core.mod_historic import (
                clear_historic_mod,
                get_historic_mod,
                write_historic_mod,
            )
            historic_value = get_historic_mod(str(category))
            if isinstance(historic_value, list):
                kept = [path for path in historic_value if not _same_path(path)]
                if len(kept) != len(historic_value):
                    if kept:
                        write_historic_mod(str(category), kept)
                    else:
                        clear_historic_mod(str(category))
            elif _same_path(historic_value):
                clear_historic_mod(str(category))
        except Exception as exc:
            log.debug("[DeleteMod] Failed to clear category historic: %s", exc)

    def _handle_delete_category_mod(self, payload: dict) -> None:
        """Permanently delete an imported mod from a category folder."""
        category = payload.get("category")
        mod_name = payload.get("modName")
        if not self.mod_storage:
            self._send_response(json.dumps({
                "type": "category-mod-deleted",
                "success": False,
                "category": category,
                "modName": mod_name,
                "error": "Mod storage is not available",
            }))
            return
        try:
            deleted = self.mod_storage.delete_category_mod(category, mod_name)
            if deleted:
                self._clear_category_selection_if_matches(category, mod_name)
                log.info(
                    "[DeleteMod] Deleted category mod: category=%s, mod=%s",
                    category,
                    mod_name,
                )
            response_payload = {
                "type": "category-mod-deleted",
                "success": deleted,
                "category": category,
                "modName": mod_name,
            }
            if not deleted:
                response_payload["error"] = "Mod not found"
            self._send_response(json.dumps(response_payload))
        except Exception as exc:
            log.error("[DeleteMod] Failed to delete category mod: %s", exc)
            self._send_response(json.dumps({
                "type": "category-mod-deleted",
                "success": False,
                "category": category,
                "modName": mod_name,
                "error": str(exc),
            }))

    def _handle_delete_category_mods(self, payload: dict) -> None:
        """Delete selected category mods and report each result in one response."""
        category = payload.get("category")
        mods = payload.get("mods")
        if not self.mod_storage:
            error = "Mod storage is not available"
            results = []
        elif not isinstance(mods, list) or not mods:
            error = "At least one category mod is required"
            results = []
        else:
            error = None
            results = []
            for mod in mods:
                if not isinstance(mod, dict):
                    results.append({"success": False, "error": "Invalid mod entry"})
                    continue
                mod_name = mod.get("modName")
                try:
                    deleted = self.mod_storage.delete_category_mod(category, mod_name)
                    if deleted:
                        self._clear_category_selection_if_matches(category, mod_name)
                        results.append({"success": True, "modName": mod_name})
                    else:
                        results.append({
                            "success": False,
                            "modName": mod_name,
                            "error": "Mod not found",
                        })
                except Exception as exc:
                    log.error(
                        "[DeleteMod] Failed to delete category mod %s/%s: %s",
                        category,
                        mod_name,
                        exc,
                    )
                    results.append({
                        "success": False,
                        "modName": mod_name,
                        "error": str(exc),
                    })

        deleted_count = sum(result.get("success", False) for result in results)
        failures = len(results) - deleted_count
        response = {
            "type": "category-mods-bulk-deleted",
            "category": category,
            "success": failures == 0 and error is None,
            "partial": deleted_count > 0 and failures > 0,
            "deletedCount": deleted_count,
            "results": results,
        }
        if error:
            response["error"] = error
        self._send_response(json.dumps(response))

    def _sync_selected_custom_mod_display_name(
        self,
        champion_id: object,
        relative_path: object,
        mod_name: object,
        display_name: str,
    ) -> None:
        """Keep the live selection/popup in sync after a display-name rename."""
        selected = getattr(self.shared_state, "selected_custom_mod", None)
        if not isinstance(selected, dict):
            return

        selected_rel = str(selected.get("relative_path") or "").replace("\\", "/")
        target_rel = str(relative_path or "").replace("\\", "/")
        same_path = bool(target_rel) and selected_rel == target_rel
        try:
            same_champion = (
                champion_id is not None
                and selected.get("champion_id") is not None
                and int(selected.get("champion_id")) == int(champion_id)
            )
        except (TypeError, ValueError):
            same_champion = False
        same_name = bool(mod_name) and selected.get("mod_name") == mod_name
        if not (same_path or (same_champion and same_name)):
            return

        selected["display_name"] = display_name
        try:
            if hasattr(self.shared_state, "ui_skin_thread") and self.shared_state.ui_skin_thread:
                self.shared_state.ui_skin_thread._broadcast_custom_mod_state()
        except Exception as exc:
            log.debug("[RenameMod] Failed to broadcast custom mod state: %s", exc)

    def _handle_rename_champion_mod(self, payload: dict) -> None:
        """Set a display alias for an imported skin mod (folder is untouched)."""
        champion_id = payload.get("championId")
        mod_name = payload.get("modName")
        relative_path = payload.get("relativePath")
        new_name = payload.get("newName")
        if not self.mod_storage:
            self._send_response(json.dumps({
                "type": "champion-mod-renamed",
                "success": False,
                "championId": champion_id,
                "modName": mod_name,
                "error": "Mod storage is not available",
            }))
            return
        try:
            display_name = self.mod_storage.set_champion_mod_display_name(
                champion_id,
                new_name,
                mod_name=mod_name,
                relative_path=relative_path,
            )
            self._sync_selected_custom_mod_display_name(
                champion_id,
                relative_path,
                mod_name,
                display_name,
            )
            log.info(
                "[RenameMod] Renamed champion mod: champion=%s, mod=%s -> %s",
                champion_id,
                mod_name,
                display_name,
            )
            self._send_response(json.dumps({
                "type": "champion-mod-renamed",
                "success": True,
                "championId": champion_id,
                "modName": mod_name,
                "displayName": display_name,
            }))
        except Exception as exc:
            log.error("[RenameMod] Failed to rename champion mod: %s", exc)
            self._send_response(json.dumps({
                "type": "champion-mod-renamed",
                "success": False,
                "championId": champion_id,
                "modName": mod_name,
                "error": str(exc),
            }))

    def _handle_set_champion_mod_image(self, payload: dict) -> None:
        """Add or replace a skin mod preview image and refresh its cache URL."""
        champion_id = payload.get("championId")
        relative_path = payload.get("relativePath")
        try:
            if not self.mod_storage:
                raise RuntimeError("Mod storage is not available")
            if not champion_id or not isinstance(relative_path, str):
                raise ValueError("Champion ID and mod path are required")

            selected_image = _choose_mod_image_file()
            if selected_image is None:
                self._send_response(json.dumps({
                    "type": "champion-mod-image-updated",
                    "success": False,
                    "cancelled": True,
                    "championId": champion_id,
                }))
                return

            from PIL import Image

            try:
                image_context = Image.open(selected_image)
            except (OSError, ValueError) as exc:
                raise ValueError("The selected file is not a valid PNG image") from exc
            with image_context as image:
                if image.format != "PNG":
                    raise ValueError("The selected file is not a PNG image")
                if image.width > 4096 or image.height > 4096:
                    raise ValueError("Image dimensions must be 4096 by 4096 pixels or smaller")
                image.verify()

            image_path = self.mod_storage.set_champion_mod_image(
                champion_id,
                relative_path,
                selected_image,
            )
            log.info("[ManageMods] Updated skin mod image: %s", image_path)
            self._send_response(json.dumps({
                "type": "champion-mod-image-updated",
                "success": True,
                "championId": champion_id,
                "relativePath": relative_path,
            }))
        except Exception as exc:
            log.error("[ManageMods] Failed to update skin mod image: %s", exc)
            self._send_response(json.dumps({
                "type": "champion-mod-image-updated",
                "success": False,
                "championId": champion_id,
                "relativePath": relative_path,
                "error": str(exc),
            }))

    def _handle_rename_category_mod(self, payload: dict) -> None:
        """Set a display alias for a category mod (folder is untouched)."""
        category = payload.get("category")
        mod_name = payload.get("modName")
        new_name = payload.get("newName")
        if not self.mod_storage:
            self._send_response(json.dumps({
                "type": "category-mod-renamed",
                "success": False,
                "category": category,
                "modName": mod_name,
                "error": "Mod storage is not available",
            }))
            return
        try:
            display_name = self.mod_storage.set_category_mod_display_name(
                category,
                mod_name,
                new_name,
            )
            log.info(
                "[RenameMod] Renamed category mod: category=%s, mod=%s -> %s",
                category,
                mod_name,
                display_name,
            )
            self._send_response(json.dumps({
                "type": "category-mod-renamed",
                "success": True,
                "category": category,
                "modName": mod_name,
                "displayName": display_name,
            }))
        except Exception as exc:
            log.error("[RenameMod] Failed to rename category mod: %s", exc)
            self._send_response(json.dumps({
                "type": "category-mod-renamed",
                "success": False,
                "category": category,
                "modName": mod_name,
                "error": str(exc),
            }))

    def _handle_dismiss_historic(self, payload: dict) -> None:
        """Dismiss historic mode (close-button on popup)"""
        try:
            from utils.core.historic import (
                clear_historic_entry,
                get_historic_skin_for_champion,
                is_custom_mod_path,
            )

            champ_id = (
                self.shared_state.locked_champ_id
                or self.shared_state.hovered_champ_id
            )
            historic_value = (
                get_historic_skin_for_champion(int(champ_id))
                if champ_id is not None
                else None
            )
            if champ_id is not None and is_custom_mod_path(historic_value):
                clear_historic_entry(int(champ_id))
                log.info("[Dismiss] Cleared custom historic entry for champion %s", champ_id)
        except Exception as exc:
            log.debug("[Dismiss] Failed to clear custom historic entry: %s", exc)

        self.shared_state.historic_mode_active = False
        self.shared_state.historic_skin_id = None
        self.shared_state.historic_first_detection_done = True
        log.info("[Dismiss] Historic mode dismissed via popup close button")

        # Broadcast cleared state
        try:
            if hasattr(self.shared_state, "ui_skin_thread") and self.shared_state.ui_skin_thread:
                self.shared_state.ui_skin_thread._broadcast_historic_state()
        except Exception as exc:
            log.debug("[Dismiss] Failed to broadcast historic state: %s", exc)

    def _prepare_saved_mod(self, identifier: object, categories: Sequence[str], label: str) -> Optional[dict]:
        """Ready the saved mod a plugin picked in one of *categories* for the
        injection (its source's put: an entry LTK Manager holds needs nothing,
        Rose's copy is linked in) and return its selection: mod_name,
        relative_path and source. None, logged, when it cannot be injected.
        *identifier* is the mod's identity or, in a single category, its name."""
        relative_path = str(identifier or "").replace("\\", "/").strip("/")
        if not _is_safe_relative_path(relative_path):
            log.warning(f"[SkinMonitor] Blocked unsafe {label} mod path: {identifier}")
            return None
        if "/" not in relative_path and len(categories) == 1:
            relative_path = f"{categories[0]}/{relative_path}"
        mod = self.mod_storage.saved_mod(relative_path)
        if mod is None or mod.kind not in categories:
            log.warning(f"[SkinMonitor] {label.capitalize()} mod not found: {identifier}")
            return None
        injector = getattr(self.injection_manager, "injector", None)
        if not injector:
            log.warning(f"[SkinMonitor] Cannot prepare the {label} mod - injector not available")
            return None
        source = mod.source
        error = _unavailable(source)
        if error is None and source.put(injector.mods_dir) is None:
            error = "The mod could not be linked into the injection folder"
        if error:
            log.warning(f"[SkinMonitor] Cannot select the {label} mod {mod.name}: {error}")
            return None
        log.info(f"[SkinMonitor] {label.capitalize()} mod ready for injection alongside the skin: {mod.name}")
        return {"mod_name": mod.name, "relative_path": mod.identity, "source": source}

    def _handle_select_one_mod(self, kind: str, payload: dict) -> None:
        """Select the map, font or announcer mod (*kind*) for the injection,
        or deselect it (a null id)"""
        pick = _ONE_MOD_CATEGORIES[kind]
        if not self.mod_storage:
            log.warning(f"[SkinMonitor] Cannot handle {kind} selection - mod storage not available")
            return

        mod_id = payload.get(pick.id_key)
        if mod_id is None:
            if getattr(self.shared_state, pick.state_attr, None):
                setattr(self.shared_state, pick.state_attr, None)
                log.info(f"[SkinMonitor] {kind.capitalize()} mod deselected")
                try:
                    from utils.core.mod_historic import clear_historic_mod
                    clear_historic_mod(kind)
                    log.debug(f"[MOD_HISTORIC] Cleared historic {kind} mod")
                except Exception as e:
                    log.debug(f"[MOD_HISTORIC] Failed to clear historic {kind} mod: {e}")
            return

        data: ListedMod = payload.get(pick.data_key) or {}
        try:
            selection = self._prepare_saved_mod(data.get("id") or data.get("name") or mod_id, (pick.category,), kind)
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle {kind} selection: {e}")
            import traceback
            log.debug(f"[SkinMonitor] Traceback: {traceback.format_exc()}")
            return
        if selection is not None:
            setattr(self.shared_state, pick.state_attr, selection)

    def _handle_select_other(self, payload: dict) -> None:
        """Handle other mod selection for injection (supports multiple selections)"""
        if not self.mod_storage:
            log.warning("[SkinMonitor] Cannot handle other selection - mod storage not available")
            return

        other_id = payload.get("otherId")
        # The category's "None" entry deselects each mod with otherData null
        other_data: ListedMod = payload.get("otherData") or {}
        action = payload.get("action", "select")  # "select" or "deselect"

        # Initialize selected_other_mods as list if it doesn't exist
        if not hasattr(self.shared_state, 'selected_other_mods'):
            self.shared_state.selected_other_mods = []

        # Handle deselection
        if action == "deselect" or other_id is None:
            if other_id:
                # Remove specific mod from list (its relative path is otherData's id, else otherId)
                def _rel(value) -> str:
                    return str(value or "").replace("\\", "/").lstrip("/").lower()

                target = _rel(other_data.get("id") or other_id)
                self.shared_state.selected_other_mods = [
                    mod for mod in (self.shared_state.selected_other_mods or [])
                    if mod and _rel(mod.get("relative_path")) != target
                ]
                log.info(f"[SkinMonitor] Other mod deselected: {other_id}")
            else:
                # Clear all (legacy support)
                self.shared_state.selected_other_mods = []
                log.info(f"[SkinMonitor] All other mods deselected")
            self._save_other_mods_historic("deselect")
            return

        try:
            selection = self._prepare_saved_mod(
                other_data.get("path") or other_data.get("id") or other_id,
                self.mod_storage.MOD_CATEGORIES,
                "other",
            )
            if selection is None:
                return

            selected = self.shared_state.selected_other_mods
            if any(existing.get("relative_path") == selection["relative_path"] for existing in selected):
                log.info(f"[SkinMonitor] Other mod already selected: {selection['mod_name']}")
            else:
                selected.append(selection)
                log.info(f"[SkinMonitor] Other mods ready for injection alongside skin (total: {len(selected)})")
            self._save_other_mods_historic("select")

        except Exception as e:
            log.error(f"[SkinMonitor] Failed to handle other selection: {e}")
            import traceback
            log.debug(f"[SkinMonitor] Traceback: {traceback.format_exc()}")

    def _save_other_mods_historic(self, action: str) -> None:
        """Save the selected other mods per category (ui/voiceover/loading_screen/vfx/sfx/others) for the next game"""
        try:
            from utils.core.mod_historic import write_historic_mod, clear_historic_mod

            by_cat = {"ui": [], "voiceover": [], "loading_screen": [], "vfx": [], "sfx": [], "others": []}
            for m in (self.shared_state.selected_other_mods or []):
                rp = str(m.get("relative_path") or "").replace("\\", "/").lstrip("/")
                if not rp:
                    continue
                cat = (rp.split("/", 1)[0] if "/" in rp else rp).strip().lower()
                if cat not in by_cat:
                    cat = "others"
                by_cat[cat].append(rp)

            for cat, paths in by_cat.items():
                if paths:
                    write_historic_mod(cat, paths)
                else:
                    clear_historic_mod(cat)
        except Exception as e:
            log.debug(f"[MOD_HISTORIC] Failed to update category historic after {action}: {e}")

    def _handle_request_category_mods(self, payload: dict) -> None:
        """Return the list of mods for a specific top-level category under %LOCALAPPDATA%\\Rose\\mods."""
        if not self.mod_storage:
            return

        category = payload.get("category")
        if category not in self.mod_storage.MOD_CATEGORIES:
            log.warning(f"[SkinMonitor] Invalid category for request-category-mods: {category}")
            return

        try:
            mods = self.mod_storage.list_mods_for_category(category)
        except Exception as exc:
            log.error(f"[SkinMonitor] Failed to list category {category}: {exc}")
            mods = []

        historic_paths = None
        try:
            from utils.core.mod_historic import get_historic_mod
            historic_paths = get_historic_mod(str(category))
            if isinstance(historic_paths, str):
                historic_paths = [historic_paths]
        except Exception as e:
            log.warning('[SkinMonitor] Could not load saved category mod selection; it will not be restored: %s', e)

        response_payload = {
            "type": "category-mods-response",
            "category": category,
            "mods": mods,
            "historicMod": historic_paths,
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
            
            # No arguments launch Pengu's normal standalone graphical interface.
            command = [str(PENGU_EXE)]
            
            if sys.platform == "win32":
                subprocess.Popen(command, cwd=str(PENGU_DIR), creationflags=0)
            else:
                subprocess.Popen(command, cwd=str(PENGU_DIR))
            
            log.info(f"[SkinMonitor] Launched Pengu Loader UI: {' '.join(command)}")
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to launch Pengu Loader UI: {e}")
    
    def _handle_language_save(self, payload: dict) -> None:
        """Save the language of Rose's menus ("auto": the client's) and tell the plugins"""
        from utils.core.i18n import AUTO, LANGUAGES
        language = payload.get("language")
        if language != AUTO and language not in LANGUAGES:
            log.warning(f"[SkinMonitor] Unknown menu language: {language!r}")
            return
        if (get_config_option("General", "language") or AUTO) != language:
            set_config_option("General", "language", language)
            log.info(f"[SkinMonitor] Menu language set to {language}")
            self.broadcaster.broadcast_language_changed()

    def _handle_settings_save(self, payload: dict) -> None:
        """Handle settings save"""
        try:
            from config import INJECTION_THRESHOLD_DEFAULT_S, clamp_injection_threshold
            threshold = clamp_injection_threshold(payload.get("threshold", INJECTION_THRESHOLD_DEFAULT_S))
            monitor_auto_resume_timeout = max(1, min(180, int(payload.get("monitorAutoResumeTimeout", 60))))
            autostart = payload.get("autostart", False)
            hide_empty_categories = bool(payload.get("hideEmptyCategories", False))
            game_path = payload.get("gamePath", "")

            set_config_option("General", "injection_threshold", f"{threshold:.2f}")
            log.info(f"[SkinMonitor] Injection threshold updated to {threshold:.2f}s")
            
            set_config_option("General", "monitor_auto_resume_timeout", str(monitor_auto_resume_timeout))
            log.info(f"[SkinMonitor] Monitor auto-resume timeout updated to {monitor_auto_resume_timeout}s")

            set_config_option("General", "hide_empty_categories", "true" if hide_empty_categories else "false")
            log.info(f"[SkinMonitor] Hide empty mod categories updated to {hide_empty_categories}")
            
            if game_path and game_path.strip():
                if not self._is_valid_local_league_path(game_path):
                    self._send_settings_save_error("League path must be a valid local League of Legends folder.")
                    return
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

        # Always remember last hover text, even if we currently gate payload processing
        # (e.g. before lock / during phase transitions). This prevents reconnects from
        # causing "no last hovered skin" at injection time.
        try:
            self.shared_state.ui_last_text = skin_name.strip()
        except Exception as e:
            log.debug('[SkinMonitor] Could not store last hovered skin text: %s', e)
        
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
            
            log.info(f"[MOD_HISTORIC] Restoring historic {mod_type} mod: {selected_mod_dict.get('name', historic_path)}")
            self._select_as_the_plugin_would(mod_type, selected_mod_dict)
        except Exception as e:
            log.debug(f"[MOD_HISTORIC] Failed to auto-select historic {mod_type} mod: {e}")
    
    def _select_as_the_plugin_would(self, mod_type: str, listed: ListedMod) -> None:
        """Select a listed mod through the plugin's own selection messages: a
        mod that cannot be injected (missing from LTK Manager) is refused there."""
        mod_id = listed.get("id") or listed.get("name")
        pick = _ONE_MOD_CATEGORIES.get(mod_type)
        if pick is not None:
            self._handle_select_one_mod(mod_type, {pick.id_key: mod_id, pick.data_key: listed})
        elif mod_type == "other":
            self._handle_select_other({"otherId": mod_id, "otherData": listed})

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
    
    # Client phases where LTK Manager belongs to the game's injection, or is about to: a queue
    # or a match found leads to champion select, whose countdown stages the game's mods
    _MOD_CHECK_BUSY_PHASES = frozenset({
        "Matchmaking", "ReadyCheck", "ChampSelect", "FINALIZATION", "GameStart", "InProgress", "Reconnect",
    })
    # Client phases where the base-skin fix of an added skin waits until the client is idle
    # (injection.baseskin.library): it rewrites the whole mod, which neither the countdown's
    # staging nor a running game should share the disk with
    _BASE_SKIN_WAIT_PHASES = frozenset({"FINALIZATION", "GameStart", "InProgress", "Reconnect"})

    def _fix_base_skin(self, imported: list[dict], game_dir) -> None:
        """Make each just-imported skin match the base skin's identity (its
        sound banks, bank units, SKN/SKL padding and championSkinName: see
        injection.baseskin) so LTK Manager does not take it for a skinhack,
        writing the mod again only when it did not. A mod written again gets
        "baseSkin" ({"fixes": how many}). This needs the game's files, not
        LTK Manager, so it also runs during champion select. A mod it cannot
        read is left as it was added."""
        if game_dir is None or not imported:
            return
        for item in imported:
            name = item.get("modName") or item.get("fileName") or ""
            try:
                from injection.baseskin.library import describe, fix_stored_mod

                storage = getattr(self, "mod_storage", None)
                result = fix_stored_mod(storage, Path(item["path"]), Path(game_dir))
            except Exception as e:  # noqa: BLE001 - a fix must never fail the import
                log.warning(f"[BASESKIN] Could not check {name} against the base skin: {e}")
                continue
            if not result.changed:
                log.info(f"[BASESKIN] {name} already matches the base skin")
                continue
            item["baseSkin"] = {"fixes": result.fixes}
            log.info(f"[BASESKIN] Fixed {name} so LTK Manager does not take it for a skinhack: {describe(result)}")
            for note in result.findings.notes:
                log.debug(f"[BASESKIN] {name}: {note}")

    def _ltk_takes_added_mods(self) -> bool:
        """Whether LTK Manager is to check the mods added now, and keep a
        category's in its library (_check_imported_mods): the injection
        knows the game folder, and no game wants LTK Manager. Such a mod is
        stored as it was picked (ModStorageService._write_stored_archive)."""
        overlay = getattr(getattr(getattr(self, "injection_manager", None), "injector", None), "overlay_manager", None)
        return overlay is not None and getattr(overlay, "game_dir", None) is not None and not self._ltk_wanted_by_game()

    def _keep_mods_left_in_rose(self, imported: list[dict]) -> None:
        """Copy into Rose each category mod added as it was picked that LTK
        Manager did not take (it was busy, missing, or could not check it):
        it stays in Rose, imported for each game, and its file is still the
        one the user picked (ModStorageService.keep_own_copy)."""
        for item in imported:
            if item.get("savedAlready"):
                continue
            try:
                saved = self.mod_storage.saved_mod(item["relativePath"])
                if saved is not None and saved.pending:
                    self.mod_storage.keep_own_copy(item["relativePath"])
            except Exception as e:  # noqa: BLE001 - the mod is added; it works as it is
                log.warning(f"[MODS] Could not copy {item.get('modName')} into Rose: {e}")

    def _ltk_wanted_by_game(self) -> bool:
        """Whether LTK Manager is, or is about to be, the game's: the client
        queues, found a match, is in champion select or a game, or an
        injection runs."""
        phase = getattr(getattr(self, "shared_state", None), "phase", None)
        injection_manager = getattr(self, "injection_manager", None)
        return phase in self._MOD_CHECK_BUSY_PHASES or bool(getattr(injection_manager, "_injection_in_progress", False))

    def _check_imported_mods(self, imported: list[dict], errors: list[dict], remove, skins: bool = False) -> list[dict]:
        """Make each just-imported custom skin (*skins*: not a map, font...
        mod) match the base skin (_fix_base_skin), have LTK Manager check and
        repair each mod (LtkLibrary.check_mod), and return the mods added. A
        pending one (a category's) moves into LTK Manager's library as it is
        checked, and Rose's copy of one LTK Manager kept is deleted; any other
        (a custom skin) stays Rose's and is checked while no base-skin fix
        holds it (stored_skin_rewrite): LTK Manager's repair is written into
        its file, whose hashes its manifest records again, and it leaves LTK
        Manager. One LTK Manager will still turn off in game (a skinhack, a
        problem it cannot repair) is not added: *remove* deletes it again, and
        it joins *errors* with the reason. A checked mod gets the verdict as
        "health"; one saved already (the same mod added again) is not checked.
        LTK Manager's check is skipped while a game wants it (_ltk_wanted_by_game:
        a queue, champion select, a game), and one running gives way when the
        client gets there: the mod stays in Rose as it was added. From the
        countdown on, the base-skin fix waits for the client to be idle."""
        injection_manager = getattr(self, "injection_manager", None)
        injector = getattr(injection_manager, "injector", None)
        overlay = getattr(injector, "overlay_manager", None)
        phase = getattr(getattr(self, "shared_state", None), "phase", None)
        injecting = bool(getattr(injection_manager, "_injection_in_progress", False))
        if skins and imported:
            if phase in self._BASE_SKIN_WAIT_PHASES or injecting:
                log.info("[BASESKIN] The added skins are matched to the base skin once the client is idle, "
                         "not during the countdown or a game")
            else:
                # Before LTK Manager's check, so its verdict is on the mod as it will be played
                game_dir = getattr(overlay, "game_dir", None) or getattr(injector, "game_dir", None)
                self._fix_base_skin(imported, game_dir)
        if overlay is None or not imported:
            return imported
        if self._ltk_wanted_by_game():
            log.info("[MODCHECK] Not checking the added mods with LTK Manager while a game wants it "
                     "(a queue, champion select, a game)")
            return imported
        self._send_response(json.dumps({"type": "mod-import-checking", "fileCount": len(imported)}))
        library = LtkLibrary(overlay.host, overlay.game_dir)
        kept = []
        for item in imported:
            if item.get("savedAlready") or self._ltk_wanted_by_game():
                kept.append(item)
                continue
            saved = self.mod_storage.saved_mod(item["relativePath"])
            mod_path, name = Path(item["path"]), item.get("modName") or Path(item["path"]).name
            try:
                if saved and saved.pending:
                    result = library.check_mod(mod_path, name, partial(self.mod_storage.attach_ltk_entry,
                                                                       item["relativePath"]),
                                               stop=self._ltk_wanted_by_game)
                else:
                    with stored_skin_rewrite():
                        result = library.check_mod(mod_path, name, stop=self._ltk_wanted_by_game)
                        if result and result.get("repaired") and not result.get("problems"):
                            self.mod_storage.refresh_mod_hashes(mod_path)
            except Exception as e:  # noqa: BLE001 - a check must never fail the import
                log.warning(f"[MODCHECK] Could not check {item.get('modName')}: {e}")
                result = None
            if result and result.get("problems"):
                rejection = _rejected_import(item, result)
                try:
                    remove(item)
                except Exception as e:  # noqa: BLE001 - kept, with the warning, rather than half removed
                    log.warning(f"[MODCHECK] Could not remove {item.get('modName')} again: {e}")
                    item["health"] = result
                    kept.append(item)
                    continue
                log.warning(f"[MODCHECK] Not adding {item.get('modName')}: {rejection['error']}")
                errors.append(rejection)
                continue
            if result is not None:
                item["health"] = result
                if result.get("ltkId"):
                    self.mod_storage.drop_stored_copy(item["relativePath"])
            kept.append(item)
        return kept

    def _send_mod_import_started(self, mod_files: list[Path]) -> None:
        """Tell the plugins selected mods are being imported."""
        payload = {
            "type": "mod-import-started",
            "fileCount": len(mod_files),
        }
        if len(mod_files) == 1:
            payload["fileName"] = mod_files[0].name
        self._send_response(json.dumps(payload))

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
            except Exception as e:
                log.debug('[SkinMonitor] Could not inspect skins directory after cleanup: %s', e)
        except Exception as e:
            log.debug(f"[SkinMonitor] Error during folder cleanup: {e}")
    
    def _handle_add_custom_mods_category_selected(self, payload: dict) -> None:
        """Open a file picker and import selected mods into the selected category."""
        category = payload.get("category")
        try:
            if category not in self.mod_storage.MOD_CATEGORIES:
                log.warning(f"[SkinMonitor] Invalid category: {category}")
                return

            selected_mod_files = _choose_mod_files()
            if not selected_mod_files:
                self._send_response(json.dumps({
                    "type": "folder-opened-response",
                    "success": False,
                    "cancelled": True,
                    "error": "Mod selection cancelled",
                }))
                return

            self._send_mod_import_started(selected_mod_files)
            imported = []
            errors = []
            as_picked = self._ltk_takes_added_mods()
            for mod_file in selected_mod_files:
                try:
                    added = self.mod_storage.import_category_mod_file(
                        category,
                        mod_file,
                        as_picked=as_picked,
                    )
                    imported.append({
                        "fileName": mod_file.name,
                        "path": str(added.identity_path),
                        "relativePath": added.identity_path.relative_to(self.mod_storage.mods_root).as_posix(),
                        "modName": added.name,
                        "savedAlready": added.nothing_added,
                    })
                    log.info(
                        f"[SkinMonitor] Imported {category} mod {added.name} to {added.identity_path}"
                    )
                except Exception as exc:
                    log.error(
                        f"[SkinMonitor] Failed to import {category} mod {mod_file.name}: {exc}"
                    )
                    errors.append({"fileName": mod_file.name, "error": str(exc)})

            imported = self._check_imported_mods(
                imported, errors,
                lambda item: self.mod_storage.delete_category_mod(category, item["modName"]),
            )
            if as_picked:
                self._keep_mods_left_in_rose(imported)
            response_payload = {
                "type": "folder-opened-response",
                "success": bool(imported) and not errors,
                "partial": bool(imported) and bool(errors),
                "category": category,
                "imported": imported,
                "importErrors": errors,
            }
            if imported:
                response_payload.update({
                    "path": imported[0]["path"],
                    "modName": imported[0]["modName"],
                })
            if errors and not imported:
                response_payload["error"] = (
                    errors[0]["error"]
                    if len(selected_mod_files) == 1
                    else "Failed to import all selected mods"
                )
            self._send_response(json.dumps(response_payload))
        except Exception as e:
            log.error(f"[SkinMonitor] Failed to import {category} mod: {e}")
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
            if payload.get("withModsOnly") and self.mod_storage:
                # Manage Mods only offers champions that have custom skins
                champions = [c for c in champions if self.mod_storage.list_mods_for_champion(c["id"])]
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
        """Persist manual skin/chroma targets and open one champion mod folder."""
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
                            skin_entry = {
                                "id": skin_id,
                                "skinId": skin_id,
                                "name": skin_name,
                            }
                            tile_path = skin.get("tilePath")
                            if tile_path:
                                skin_entry["tilePath"] = tile_path
                            skins.append(skin_entry)

                            # Chromas are separate selectable targets. Keep
                            # their real IDs so a mod can be placed under the
                            # exact chroma folder instead of being inferred
                            # from the user's explicit folder choice.
                            raw_chromas = skin.get("chromas", []) or []
                            if not isinstance(raw_chromas, list):
                                raw_chromas = []
                            if not raw_chromas and self.skin_scraper:
                                try:
                                    raw_chromas = (
                                        self.skin_scraper.get_chromas_for_skin(int(skin_id))
                                        or []
                                    )
                                except (AttributeError, TypeError, ValueError):
                                    raw_chromas = []

                            for chroma in raw_chromas:
                                if not isinstance(chroma, dict):
                                    continue
                                chroma_id = chroma.get("id")
                                if chroma_id is None:
                                    continue
                                chroma_id = int(chroma_id)
                                chroma_name = str(
                                    chroma.get("name") or f"Chroma {chroma_id}"
                                )
                                chroma_entry = {
                                    "id": chroma_id,
                                    "skinId": chroma_id,
                                    "baseSkinId": int(skin_id),
                                    "isChroma": True,
                                    "name": f"{skin_name} — {chroma_name}",
                                }
                                chroma_tile_path = (
                                    chroma.get("tilePath")
                                    or chroma.get("chromaPath")
                                )
                                if chroma_tile_path:
                                    chroma_entry["tilePath"] = chroma_tile_path
                                skins.append(chroma_entry)
                        except (ValueError, TypeError, AttributeError):
                            continue
                
                # Sort base skins and chromas together by their real target ID.
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
                # Store all manually selected skins/chromas in one champion folder.
                champion_id = payload.get("championId")
                raw_skin_ids = payload.get("skinIds")
                if raw_skin_ids is None:
                    raw_skin_ids = [payload.get("skinId")]
                elif not isinstance(raw_skin_ids, list):
                    raw_skin_ids = [raw_skin_ids]
                
                if not champion_id or not raw_skin_ids or any(
                    skin_id is None for skin_id in raw_skin_ids
                ):
                    response_payload = {
                        "type": "folder-opened-response",
                        "success": False,
                        "error": "Champion ID and at least one Skin ID are required",
                    }
                    self._send_response(json.dumps(response_payload))
                    return
                if not str(champion_id).isdigit() or any(
                    not str(skin_id).isdigit() for skin_id in raw_skin_ids
                ):
                    response_payload = {
                        "type": "folder-opened-response",
                        "success": False,
                        "error": "Champion ID and Skin IDs must be numeric",
                    }
                    self._send_response(json.dumps(response_payload))
                    return
                
                champion_id = int(champion_id)
                skin_ids = []
                for raw_skin_id in raw_skin_ids:
                    skin_id = int(raw_skin_id)
                    if skin_id not in skin_ids:
                        skin_ids.append(skin_id)
                if champion_id <= 0 or any(skin_id <= 0 for skin_id in skin_ids):
                    response_payload = {
                        "type": "folder-opened-response",
                        "success": False,
                        "error": "Champion ID and Skin IDs must be positive",
                    }
                    self._send_response(json.dumps(response_payload))
                    return

                selected_mod_files = _choose_mod_files()
                if not selected_mod_files:
                    self._send_response(json.dumps({
                        "type": "folder-opened-response",
                        "success": False,
                        "cancelled": True,
                        "error": "Mod selection cancelled",
                    }))
                    return

                self._send_mod_import_started(selected_mod_files)
                imported = []
                errors = []
                for mod_file in selected_mod_files:
                    try:
                        added = self.mod_storage.import_mod_file(
                            champion_id,
                            mod_file,
                            skin_ids,
                        )
                        imported.append({
                            "fileName": mod_file.name,
                            "path": str(added.identity_path),
                            "relativePath": added.identity_path.relative_to(self.mod_storage.mods_root).as_posix(),
                            "modName": added.name,
                            "savedAlready": added.nothing_added,
                            "targetManifest": str(self.mod_storage.get_champion_dir(champion_id)
                                                  / ModStorageService.TARGET_METADATA),
                        })
                        log.info(
                            f"[SkinMonitor] Imported mod for champion "
                            f"{champion_id}, mod {added.name}, targets {skin_ids}"
                        )
                    except Exception as exc:
                        log.error(
                            f"[SkinMonitor] Failed to import skin mod {mod_file.name}: {exc}"
                        )
                        errors.append({"fileName": mod_file.name, "error": str(exc)})

                imported = self._check_imported_mods(
                    imported, errors,
                    lambda item: self.mod_storage.delete_champion_mod(champion_id, mod_name=item["modName"]),
                    skins=True,
                )
                response_payload = {
                    "type": "folder-opened-response",
                    "success": bool(imported) and not errors,
                    "partial": bool(imported) and bool(errors),
                    "imported": imported,
                    "importErrors": errors,
                    "championFolder": str(self.mod_storage.get_champion_dir(champion_id)),
                    "skinIds": skin_ids,
                }
                if imported:
                    response_payload.update({
                        "path": imported[0]["path"],
                        "modName": imported[0]["modName"],
                        "targetManifest": imported[0]["targetManifest"],
                    })
                if errors and not imported:
                    response_payload["error"] = (
                        errors[0]["error"]
                        if len(selected_mod_files) == 1
                        else "Failed to import all selected mods"
                    )
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

    # ==================== Party Mode Handlers ====================

    def _handle_party_enable(self, payload: dict) -> None:
        """Handle party mode enable request"""
        try:
            party_manager = getattr(self.shared_state, 'party_manager', None)
            if not party_manager:
                # Initialize party manager
                from party.core.party_manager import PartyManager
                from lcu import LCU

                # Get LCU instance from skin_scraper
                lcu = self.skin_scraper.lcu if self.skin_scraper else None
                if not lcu:
                    response_payload = {
                        "type": "party-enabled",
                        "success": False,
                        "error": "LCU not available - is League client running?",
                    }
                    self._send_response(json.dumps(response_payload))
                    return

                party_manager = PartyManager(lcu, self.shared_state, self.injection_manager)
                self.shared_state.party_manager = party_manager
                party_manager.set_callbacks(
                    on_state_change=lambda state: self.broadcaster.broadcast_party_state()
                )

            # Enable party mode (async operation)
            import asyncio

            async def do_enable():
                try:
                    token = await party_manager.enable()
                    self.shared_state.party_mode_enabled = True
                    self.shared_state.party_token = token
                    response_payload = {
                        "type": "party-enabled",
                        "success": True,
                        "token": token,
                    }
                    self._send_response(json.dumps(response_payload))
                    log.info(f"[PARTY] Party mode enabled, token: {token[:30]}...")
                except Exception as e:
                    log.error(f"[PARTY] Failed to enable party mode: {e}")
                    from utils.core.i18n import text_fields
                    error = e.args[0] if e.args else str(e)
                    response_payload = {
                        "type": "party-enabled",
                        "success": False,
                        "error": str(error),
                        **text_fields("error", error),
                    }
                    self._send_response(json.dumps(response_payload))

            # Run in event loop
            if self.websocket_server and self.websocket_server.loop:
                asyncio.run_coroutine_threadsafe(do_enable(), self.websocket_server.loop)
            else:
                log.warning("[PARTY] No event loop available")

        except Exception as e:
            log.error(f"[PARTY] Error handling party enable: {e}")
            response_payload = {
                "type": "party-enabled",
                "success": False,
                "error": str(e),
            }
            self._send_response(json.dumps(response_payload))

    def _handle_party_disable(self, payload: dict) -> None:
        """Handle party mode disable request"""
        try:
            party_manager = getattr(self.shared_state, 'party_manager', None)
            if not party_manager:
                response_payload = {
                    "type": "party-disabled",
                    "success": True,
                }
                self._send_response(json.dumps(response_payload))
                return

            import asyncio

            async def do_disable():
                try:
                    await party_manager.disable()
                    self.shared_state.party_mode_enabled = False
                    self.shared_state.party_token = None
                    response_payload = {
                        "type": "party-disabled",
                        "success": True,
                    }
                    self._send_response(json.dumps(response_payload))
                    log.info("[PARTY] Party mode disabled")
                except Exception as e:
                    log.error(f"[PARTY] Failed to disable party mode: {e}")
                    response_payload = {
                        "type": "party-disabled",
                        "success": False,
                        "error": str(e),
                    }
                    self._send_response(json.dumps(response_payload))

            if self.websocket_server and self.websocket_server.loop:
                asyncio.run_coroutine_threadsafe(do_disable(), self.websocket_server.loop)

        except Exception as e:
            log.error(f"[PARTY] Error handling party disable: {e}")

    def _handle_party_add_peer(self, payload: dict) -> None:
        """Handle add peer request"""
        try:
            token = payload.get("token", "")
            if not token:
                response_payload = {
                    "type": "party-peer-added",
                    "success": False,
                    "error": "No token provided",
                }
                self._send_response(json.dumps(response_payload))
                return

            party_manager = getattr(self.shared_state, 'party_manager', None)
            if not party_manager or not party_manager.enabled:
                response_payload = {
                    "type": "party-peer-added",
                    "success": False,
                    "error": "Party mode not enabled",
                }
                self._send_response(json.dumps(response_payload))
                return

            import asyncio

            async def do_add_peer():
                try:
                    success, message = await party_manager.add_peer(token)
                    from utils.core.i18n import text_fields
                    response_payload = {
                        "type": "party-peer-added",
                        "success": success,
                        "message": message if success else None,
                        "error": None if success else message,
                        **text_fields("message" if success else "error", message),
                    }
                    self._send_response(json.dumps(response_payload))
                    if success:
                        log.info(f"[PARTY] Peer added: {message}")
                    else:
                        log.warning(f"[PARTY] Failed to add peer: {message}")
                except Exception as e:
                    log.error(f"[PARTY] Failed to add peer: {e}")
                    response_payload = {
                        "type": "party-peer-added",
                        "success": False,
                        "error": str(e),
                    }
                    self._send_response(json.dumps(response_payload))

            if self.websocket_server and self.websocket_server.loop:
                asyncio.run_coroutine_threadsafe(do_add_peer(), self.websocket_server.loop)

        except Exception as e:
            log.error(f"[PARTY] Error handling add peer: {e}")

    def _handle_party_remove_peer(self, payload: dict) -> None:
        """Handle remove peer request"""
        try:
            summoner_id = payload.get("summoner_id")
            if not summoner_id:
                return

            party_manager = getattr(self.shared_state, 'party_manager', None)
            if not party_manager:
                return

            import asyncio

            async def do_remove_peer():
                try:
                    await party_manager.remove_peer(int(summoner_id))
                    response_payload = {
                        "type": "party-peer-removed",
                        "success": True,
                        "summoner_id": summoner_id,
                    }
                    self._send_response(json.dumps(response_payload))
                    log.info(f"[PARTY] Peer {summoner_id} removed")
                except Exception as e:
                    log.error(f"[PARTY] Failed to remove peer: {e}")

            if self.websocket_server and self.websocket_server.loop:
                asyncio.run_coroutine_threadsafe(do_remove_peer(), self.websocket_server.loop)

        except Exception as e:
            log.error(f"[PARTY] Error handling remove peer: {e}")

    def _handle_party_get_state(self, payload: dict) -> None:
        """Handle get party state request"""
        try:
            party_manager = getattr(self.shared_state, 'party_manager', None)
            if not party_manager:
                response_payload = {
                    "type": "party-state",
                    "enabled": False,
                    "my_token": None,
                    "peers": [],
                    "timestamp": int(time.time() * 1000),
                }
            else:
                state_dict = party_manager.get_state_dict()
                response_payload = {
                    "type": "party-state",
                    **state_dict,
                    "timestamp": int(time.time() * 1000),
                }

            self._send_response(json.dumps(response_payload))

        except Exception as e:
            log.error(f"[PARTY] Error getting party state: {e}")
