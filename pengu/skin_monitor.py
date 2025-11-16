#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pengu Skin Monitor
------------------

Receives skin hover notifications from the Pengu Loader `LU-SkinMonitor` plugin
over WebSocket and updates the shared application state accordingly. This
replaces the legacy UIA-based skin detection pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Optional, Set

from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, unquote
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.server import WebSocketServerProtocol, serve

from utils.paths import get_user_data_dir, get_skins_dir, get_asset_path
from utils.utilities import get_champion_id_from_skin_id

log = logging.getLogger(__name__)

SPECIAL_BASE_SKIN_IDS = {
    99007,  # Elementalist Lux
    145070,  # Risen Legend Kai'Sa
    103085,  # Risen Legend Ahri
}
SPECIAL_CHROMA_SKIN_IDS = {
    145071,  # Immortalized Legend Kai'Sa
    100001,  # Kai'Sa HOL chroma
    103086,  # Immortalized Legend Ahri
    88888,  # Ahri HOL chroma
}


class PenguSkinMonitorThread(threading.Thread):
    """
    Background thread hosting a WebSocket server that listens for skin hover
    events emitted by the Pengu plugin.
    """

    def __init__(
        self,
        shared_state,
        lcu=None,
        skin_scraper=None,
        injection_manager=None,
        host: str = "127.0.0.1",
        port: int = 3000,
    ) -> None:
        super().__init__(daemon=True, name="PenguSkinMonitor")
        self.shared_state = shared_state
        self.lcu = lcu
        self.skin_scraper = skin_scraper
        self.injection_manager = injection_manager
        self.host = host
        self.port = port

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server = None
        self._shutdown_event: Optional[asyncio.Event] = None
        self._connections: Set[WebSocketServerProtocol] = set()

        self._stop_event = threading.Event()
        self._injection_disconnect_active = False
        self._last_phase = None

        # Skin mapping cache (per language)
        self.skin_id_mapping: dict[str, int] = {}
        self.skin_mapping_loaded = False
        self.last_skin_name: Optional[str] = None

        # HTTP server for serving local files
        self._http_server: Optional[HTTPServer] = None
        self._http_port = 3001  # Different port from WebSocket

    # ------------------------------------------------------------------ Thread
    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._shutdown_event = asyncio.Event()

        # Start HTTP server for serving local files
        self._start_http_server()

        try:
            self._server = self._loop.run_until_complete(
                serve(self._handler, self.host, self.port, ping_interval=None)
            )
            log.info(
                "[PenguSkinMonitor] Listening for Pengu Loader events on ws://%s:%s",
                self.host,
                self.port,
            )
            log.info(
                "[PenguSkinMonitor] HTTP server for local files on http://%s:%s",
                self.host,
                self._http_port,
            )
            self._loop.run_until_complete(self._shutdown_event.wait())
        except Exception as exc:  # noqa: BLE001
            log.error("[PenguSkinMonitor] Server stopped unexpectedly: %s", exc)
        finally:
            self._stop_http_server()
            self._loop.run_until_complete(self._shutdown())
            self._loop.close()
            log.info("[PenguSkinMonitor] Thread terminated")

    async def _shutdown(self) -> None:
        # Close active sockets
        for ws in list(self._connections):
            try:
                await ws.close()
            except Exception:
                pass

        self._connections.clear()

        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None

    def stop(self) -> None:
        self._stop_event.set()
        self._stop_http_server()
        if self._loop and self._shutdown_event:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._signal_shutdown(), self._loop
                )
            except RuntimeError:
                pass

    async def _signal_shutdown(self) -> None:
        if self._shutdown_event and not self._shutdown_event.is_set():
            self._shutdown_event.set()

    def force_disconnect(self) -> None:
        """
        Mimic the legacy UIA behaviour when injection is about to occur.
        """
        self._injection_disconnect_active = True
        self.last_skin_name = None
        self.shared_state.ui_skin_id = None
        self.shared_state.ui_last_text = None

    def clear_cache(self) -> None:
        """
        Reset cached mappings/state (called during champion exchange events).
        """
        self.last_skin_name = None
        self.shared_state.ui_skin_id = None
        self.shared_state.ui_last_text = None
        self.skin_mapping_loaded = False
        self.skin_id_mapping.clear()

    # ------------------------------------------------------------ WebSocket IO
    async def _handler(self, websocket: WebSocketServerProtocol) -> None:
        client = websocket.remote_address
        log.info("[PenguSkinMonitor] Client connected: %s", client)
        self._connections.add(websocket)
        try:
            async for message in websocket:
                self._handle_message(message)
        except (ConnectionClosedError, ConnectionClosedOK):
            log.debug("[PenguSkinMonitor] Client disconnected: %s", client)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "[PenguSkinMonitor] Error handling client %s: %s", client, exc
            )
        finally:
            self._connections.discard(websocket)

    def _handle_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError as exc:
            log.warning("[PenguSkinMonitor] Invalid payload: %s (%s)", message, exc)
            return

        payload_type = payload.get("type")
        if payload_type == "chroma-log":
            event = payload.get("event") or payload.get("message") or "unknown"
            details = payload.get("data") or payload
            log.info("[ChromaWheel] %s | %s", event, details)
            return

        if payload_type == "request-local-preview":
            # Handle request for local preview image (for special skins like Elementalist Lux)
            champion_id = payload.get("championId")
            skin_id = payload.get("skinId")
            chroma_id = payload.get("chromaId")
            
            if champion_id and skin_id and chroma_id:
                try:
                    from ui.chroma_preview_manager import get_preview_manager
                    preview_manager = get_preview_manager()
                    
                    # Get preview path (chroma_id is the form ID for Elementalist Lux)
                    preview_path = preview_manager.get_preview_path(
                        champion_name="",  # Not needed for path construction
                        skin_name="",  # Not needed for path construction
                        chroma_id=chroma_id if chroma_id != skin_id else None,
                        skin_id=skin_id,
                        champion_id=champion_id
                    )
                    
                    if preview_path and preview_path.exists():
                        # Serve via HTTP instead of file:// (browsers block file:// URLs)
                        http_url = f"http://{self.host}:{self._http_port}/preview/{champion_id}/{skin_id}/{chroma_id}/{chroma_id}.png"
                        log.debug(f"[PenguSkinMonitor] Local preview found: {preview_path} -> {http_url}")
                        
                        # Send the HTTP URL back to JavaScript
                        payload = {
                            "type": "local-preview-url",
                            "championId": champion_id,
                            "skinId": skin_id,
                            "chromaId": chroma_id,
                            "url": http_url,
                            "timestamp": int(time.time() * 1000),
                        }
                        message = json.dumps(payload)
                        try:
                            running_loop = asyncio.get_running_loop()
                        except RuntimeError:
                            running_loop = None

                        if running_loop is self._loop:
                            self._loop.create_task(self._broadcast(message))
                        else:
                            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)
                    else:
                        log.debug(f"[PenguSkinMonitor] Local preview not found: champion={champion_id}, skin={skin_id}, chroma={chroma_id}")
                except Exception as e:
                    log.debug(f"[PenguSkinMonitor] Failed to get local preview: {e}")
            return

        if payload_type == "request-local-asset":
            # Handle request for local asset (like Elementalist Lux button icons)
            asset_path = payload.get("assetPath")
            chroma_id = payload.get("chromaId")
            
            if asset_path:
                try:
                    from utils.paths import get_asset_path
                    asset_file = get_asset_path(asset_path)
                    
                    if asset_file and asset_file.exists():
                        # Serve via HTTP instead of file:// (browsers block file:// URLs)
                        http_url = f"http://{self.host}:{self._http_port}/asset/{asset_path.replace(chr(92), '/')}"  # Replace backslashes with forward slashes
                        log.debug(f"[PenguSkinMonitor] Local asset found: {asset_file} -> {http_url}")
                        
                        # Send the HTTP URL back to JavaScript
                        payload = {
                            "type": "local-asset-url",
                            "assetPath": asset_path,
                            "chromaId": chroma_id,
                            "url": http_url,
                            "timestamp": int(time.time() * 1000),
                        }
                        message = json.dumps(payload)
                        try:
                            running_loop = asyncio.get_running_loop()
                        except RuntimeError:
                            running_loop = None

                        if running_loop is self._loop:
                            self._loop.create_task(self._broadcast(message))
                        else:
                            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)
                    else:
                        log.debug(f"[PenguSkinMonitor] Local asset not found: {asset_path}")
                except Exception as e:
                    log.debug(f"[PenguSkinMonitor] Failed to get local asset: {e}")
            return

        if payload_type == "chroma-selection":
            # Handle chroma selection from JavaScript plugin
            chroma_id = payload.get("chromaId") or payload.get("skinId")
            chroma_name = payload.get("chromaName") or "Unknown"
            base_skin_id = payload.get("baseSkinId")
            
            if chroma_id is not None:
                # Use ChromaSelector's logic to handle chroma selection
                from ui.chroma_selector import get_chroma_selector
                chroma_selector = get_chroma_selector()
                
                if chroma_selector:
                    # Call ChromaSelector's _on_chroma_selected to use its logic
                    chroma_selector._on_chroma_selected(chroma_id, chroma_name)
                    log.info(f"[PenguSkinMonitor] Chroma selected via ChromaSelector: {chroma_name} (ID: {chroma_id})")
                    
                    # Also call the panel's wrapper to track colors and broadcast state
                    # This ensures the panel's current_chroma_color is updated
                    if chroma_selector.panel:
                        try:
                            chroma_selector.panel._on_chroma_selected_wrapper(chroma_id, chroma_name)
                        except Exception as e:
                            log.debug(f"[PenguSkinMonitor] Failed to call panel wrapper: {e}")
                            # Fallback: broadcast state anyway
                            self._broadcast_chroma_state()
                    else:
                        # Fallback: broadcast state if panel not available
                        self._broadcast_chroma_state()
                else:
                    # Fallback: update shared state directly if ChromaSelector not available
                    self.shared_state.selected_chroma_id = chroma_id if chroma_id != 0 else None
                    self.shared_state.last_hovered_skin_id = chroma_id
                    log.info(f"[PenguSkinMonitor] Chroma selected (fallback): {chroma_name} (ID: {chroma_id})")
                    
                    # Try to call panel wrapper directly to track colors
                    try:
                        from ui.chroma_panel import get_chroma_panel
                        panel = get_chroma_panel(state=self.shared_state)
                        if panel:
                            panel._on_chroma_selected_wrapper(chroma_id, chroma_name)
                        else:
                            # Panel not available - broadcast state anyway
                            self._broadcast_chroma_state()
                    except Exception as e:
                        log.debug(f"[PenguSkinMonitor] Failed to call panel wrapper in fallback: {e}")
                        # Broadcast state anyway
                        self._broadcast_chroma_state()
            return

        if payload_type == "dice-button-click":
            # Handle dice button click from JavaScript plugin
            button_state = payload.get("state", "disabled")
            log.info(f"[PenguSkinMonitor] Dice button clicked from JavaScript: state={button_state}")
            
            # Forward to UI's dice button handler
            try:
                from ui.user_interface import get_user_interface
                ui = get_user_interface(self.shared_state, self.skin_scraper)
                
                if button_state == "disabled":
                    # Start randomization
                    ui._handle_dice_click_disabled()
                elif button_state == "enabled":
                    # Cancel randomization
                    ui._handle_dice_click_enabled()
                else:
                    log.warning(f"[PenguSkinMonitor] Unknown dice button state: {button_state}")
            except Exception as e:
                log.error(f"[PenguSkinMonitor] Failed to handle dice button click: {e}")
            return

        skin_name = payload.get("skin")
        if not isinstance(skin_name, str) or not skin_name.strip():
            return

        if not self._should_process_payload():
            return

        skin_name = skin_name.strip()
        if skin_name == self.last_skin_name:
            return

        self.last_skin_name = skin_name
        self._process_skin_name(skin_name)

    # ----------------------------------------------------------- Flow control
    def _should_process_payload(self) -> bool:
        """
        Mirror the legacy logic that decides whether skin detection should be
        active for the current phase/state.
        """
        current_phase = getattr(self.shared_state, "phase", None)
        if current_phase != self._last_phase:
            if current_phase == "ChampSelect":
                self._injection_disconnect_active = False
            self._last_phase = current_phase

        if self._injection_disconnect_active:
            if current_phase in {"ChampSelect", "FINALIZATION"} or getattr(
                self.shared_state, "own_champion_locked", False
            ):
                log.debug(
                    "[PenguSkinMonitor] Resuming after injection disconnect (phase=%s)",
                    current_phase,
                )
                self._injection_disconnect_active = False
            else:
                return False

        if getattr(self.shared_state, "phase", None) == "Lobby" and getattr(
            self.shared_state, "is_swiftplay_mode", False
        ):
            return True

        if getattr(self.shared_state, "own_champion_locked", False):
            return True

        if getattr(self.shared_state, "phase", None) == "FINALIZATION":
            return True

        return False

    # ------------------------------------------------------------ Skin logic
    def _process_skin_name(self, skin_name: str) -> None:
        try:
            log.info("[PenguSkinMonitor] Skin detected: '%s'", skin_name)
            self.shared_state.ui_last_text = skin_name

            if getattr(self.shared_state, "is_swiftplay_mode", False):
                self._process_swiftplay_skin_name(skin_name)
            else:
                self._process_regular_skin_name(skin_name)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "[PenguSkinMonitor] Error processing skin '%s': %s",
                skin_name,
                exc,
            )

    def _process_swiftplay_skin_name(self, skin_name: str) -> None:
        skin_id = self._find_skin_id_by_name(skin_name)
        if skin_id is None:
            log.warning(
                "[PenguSkinMonitor] Unable to map Swiftplay skin '%s' to ID",
                skin_name,
            )
            return

        champion_id = get_champion_id_from_skin_id(skin_id)
        self.shared_state.swiftplay_skin_tracking[champion_id] = skin_id
        self.shared_state.ui_skin_id = skin_id
        self.shared_state.last_hovered_skin_id = skin_id

        log.info(
            "[PenguSkinMonitor] Swiftplay skin '%s' mapped to champion %s (id=%s)",
            skin_name,
            champion_id,
            skin_id,
        )
        self._broadcast_skin_state(skin_name, skin_id)

    def _process_regular_skin_name(self, skin_name: str) -> None:
        skin_id = self._find_skin_id(skin_name)
        if skin_id is None:
            log.debug(
                "[PenguSkinMonitor] No skin ID found for '%s' with current data",
                skin_name,
            )
            return

        self.shared_state.ui_skin_id = skin_id
        self.shared_state.last_hovered_skin_id = skin_id

        english_skin_name = None
        try:
            champ_id = getattr(self.shared_state, "locked_champ_id", None)
            if (
                self.skin_scraper
                and champ_id
                and self.skin_scraper.cache.is_loaded_for_champion(champ_id)
            ):
                skin_data = self.skin_scraper.cache.get_skin_by_id(skin_id)
                english_skin_name = (skin_data or {}).get("skinName", "").strip()
        except Exception:
            english_skin_name = None

        self.shared_state.last_hovered_skin_key = english_skin_name or skin_name
        log.info(
            "[PenguSkinMonitor] Skin '%s' mapped to ID %s (key=%s)",
            skin_name,
            skin_id,
            self.shared_state.last_hovered_skin_key,
        )
        self._broadcast_skin_state(skin_name, skin_id)

    # ------------------------------------------------------- Skin lookup utils
    def _load_skin_id_mapping(self) -> bool:
        language = getattr(self.shared_state, "current_language", None)
        if not language:
            log.warning("[PenguSkinMonitor] No language detected; cannot load mapping")
            return False

        mapping_path = (
            get_user_data_dir()
            / "skinid_mapping"
            / language
            / "skin_ids.json"
        )

        if not mapping_path.exists():
            log.warning(
                "[PenguSkinMonitor] Skin mapping file missing: %s", mapping_path
            )
            return False

        try:
            with open(mapping_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "[PenguSkinMonitor] Failed to load skin mapping %s: %s",
                mapping_path,
                exc,
            )
            return False

        self.skin_id_mapping.clear()
        for skin_id_str, name in data.items():
            try:
                skin_id = int(skin_id_str)
            except (TypeError, ValueError):
                continue
            normalized = (name or "").strip().lower()
            if normalized and normalized not in self.skin_id_mapping:
                self.skin_id_mapping[normalized] = skin_id

        self.skin_mapping_loaded = True
        log.info(
            "[PenguSkinMonitor] Loaded %s skin mappings for '%s'",
            len(self.skin_id_mapping),
            language,
        )
        return True

    def _find_skin_id_by_name(self, skin_name: str) -> Optional[int]:
        if not self.skin_mapping_loaded:
            if not self._load_skin_id_mapping():
                return None

        normalized = skin_name.strip().lower()
        if normalized in self.skin_id_mapping:
            return self.skin_id_mapping[normalized]

        for mapped_name, skin_id in self.skin_id_mapping.items():
            if normalized in mapped_name or mapped_name in normalized:
                return skin_id

        return None

    def _find_skin_id(self, skin_name: str) -> Optional[int]:
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
            log.info(
                "[PenguSkinMonitor] Matched '%s' -> '%s' (ID=%s, similarity=%.2f)",
                skin_name,
                matched_name,
                skin_id,
                similarity,
            )
            return skin_id

        return None

    # ---------------------------------------------------------- JS Integration
    def _broadcast_skin_state(self, skin_name: str, skin_id: Optional[int]) -> None:
        if not self._loop or not self._connections:
            return

        champion_id = (
            get_champion_id_from_skin_id(skin_id)
            if skin_id is not None
            else None
        )
        has_chromas = self._skin_has_chromas(skin_id)
        payload = {
            "type": "skin-state",
            "skinName": skin_name,
            "skinId": skin_id,
            "championId": champion_id,
            "hasChromas": has_chromas,
        }
        log.info(
            "[PenguSkinMonitor] Skin state → name='%s' id=%s champion=%s hasChromas=%s",
            skin_name,
            skin_id,
            champion_id,
            has_chromas,
        )
        message = json.dumps(payload)
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            self._loop.create_task(self._broadcast(message))
        else:
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)

    async def _broadcast(self, message: str) -> None:
        stale: list[WebSocketServerProtocol] = []
        for ws in list(self._connections):
            try:
                await ws.send(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self._connections.discard(ws)

    def _broadcast_chroma_state(self) -> None:
        """Broadcast current chroma selection state to JavaScript"""
        if not self._loop or not self._connections:
            return

        # Get chroma state from ChromaPanelManager
        from ui.chroma_panel import get_chroma_panel
        panel = get_chroma_panel(state=self.shared_state)
        
        if panel:
            with panel.lock:
                selected_chroma_id = panel.current_selected_chroma_id
                chroma_color = panel.current_chroma_color
                chroma_colors = panel.current_chroma_colors
                current_skin_id = panel.current_skin_id
        else:
            selected_chroma_id = self.shared_state.selected_chroma_id
            chroma_color = None
            chroma_colors = None
            current_skin_id = None

        payload = {
            "type": "chroma-state",
            "selectedChromaId": selected_chroma_id,
            "chromaColor": chroma_color,
            "chromaColors": chroma_colors,
            "currentSkinId": current_skin_id,
            "timestamp": int(time.time() * 1000),
        }
        
        log.debug(
            "[PenguSkinMonitor] Broadcasting chroma state → selectedChromaId=%s chromaColor=%s",
            selected_chroma_id,
            chroma_color,
        )
        
        message = json.dumps(payload)
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            self._loop.create_task(self._broadcast(message))
        else:
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)

    def _broadcast_historic_state(self) -> None:
        """Broadcast current historic mode state to JavaScript"""
        if not self._loop or not self._connections:
            return

        # Get historic mode state from SharedState
        historic_mode_active = getattr(self.shared_state, 'historic_mode_active', False)
        historic_skin_id = getattr(self.shared_state, 'historic_skin_id', None)

        payload = {
            "type": "historic-state",
            "active": historic_mode_active,
            "historicSkinId": historic_skin_id,
            "timestamp": int(time.time() * 1000),
        }
        
        log.debug(
            "[PenguSkinMonitor] Broadcasting historic state → active=%s historicSkinId=%s",
            historic_mode_active,
            historic_skin_id,
        )
        
        message = json.dumps(payload)
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            self._loop.create_task(self._broadcast(message))
        else:
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)
    
    def _broadcast_phase_change(self, phase: str) -> None:
        """Broadcast phase change to JavaScript plugins"""
        if not self._loop or not self._connections:
            return

        # Include basic game mode context from shared state so JS plugins
        # (like LU-ChromaWheel) can adapt visuals such as ARAM backgrounds
        game_mode = getattr(self.shared_state, "current_game_mode", None)
        map_id = getattr(self.shared_state, "current_map_id", None)
        queue_id = getattr(self.shared_state, "current_queue_id", None)

        payload = {
            "type": "phase-change",
            "phase": phase,
            "gameMode": game_mode,
            "mapId": map_id,
            "queueId": queue_id,
            "timestamp": int(time.time() * 1000),
        }
        
        log.debug(
            "[PenguSkinMonitor] Broadcasting phase change → phase=%s, gameMode=%s, mapId=%s, queueId=%s",
            phase,
            game_mode,
            map_id,
            queue_id,
        )
        
        message = json.dumps(payload)
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            self._loop.create_task(self._broadcast(message))
        else:
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)
    
    def _broadcast_champion_locked(self, locked: bool) -> None:
        """Broadcast champion lock state to JavaScript plugins"""
        if not self._loop or not self._connections:
            return

        payload = {
            "type": "champion-locked",
            "locked": locked,
            "timestamp": int(time.time() * 1000),
        }
        
        log.debug(
            "[PenguSkinMonitor] Broadcasting champion lock state → locked=%s",
            locked,
        )
        
        message = json.dumps(payload)
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            self._loop.create_task(self._broadcast(message))
        else:
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)
    
    def _broadcast_random_mode_state(self) -> None:
        """Broadcast random mode state to JavaScript plugins"""
        if not self._loop or not self._connections:
            return

        # Get random mode state from SharedState
        random_mode_active = getattr(self.shared_state, 'random_mode_active', False)
        random_skin_id = getattr(self.shared_state, 'random_skin_id', None)
        
        # Determine dice button state based on random mode
        dice_state = 'enabled' if random_mode_active else 'disabled'

        payload = {
            "type": "random-mode-state",
            "active": random_mode_active,
            "randomSkinId": random_skin_id,
            "diceState": dice_state,
            "timestamp": int(time.time() * 1000),
        }
        
        log.debug(
            "[PenguSkinMonitor] Broadcasting random mode state → active=%s diceState=%s randomSkinId=%s",
            random_mode_active,
            dice_state,
            random_skin_id,
        )
        
        message = json.dumps(payload)
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            self._loop.create_task(self._broadcast(message))
        else:
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)

    def _start_http_server(self) -> None:
        """Start HTTP server for serving local preview images and assets"""
        class LocalFileHandler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                self.skins_dir = get_skins_dir()
                try:
                    # Get assets directory
                    test_asset = get_asset_path("dummy")
                    self.assets_dir = test_asset.parent if test_asset else None
                except:
                    self.assets_dir = None
                super().__init__(*args, **kwargs)

            def do_GET(self):
                try:
                    parsed_path = urlparse(self.path)
                    path = unquote(parsed_path.path)
                    
                    # Handle preview requests: /preview/{champion_id}/{skin_id}/{chroma_id}/{chroma_id}.png
                    if path.startswith("/preview/"):
                        parts = path.replace("/preview/", "").split("/")
                        if len(parts) >= 4:
                            champion_id = parts[0]
                            skin_id = parts[1]
                            chroma_id = parts[2]
                            
                            # Construct file path
                            if chroma_id == skin_id:
                                # Base skin preview
                                file_path = self.skins_dir / champion_id / skin_id / f"{skin_id}.png"
                            else:
                                # Chroma preview
                                file_path = self.skins_dir / champion_id / skin_id / chroma_id / f"{chroma_id}.png"
                            
                            if file_path.exists():
                                self.send_response(200)
                                self.send_header("Content-Type", "image/png")
                                self.send_header("Access-Control-Allow-Origin", "*")
                                self.end_headers()
                                with open(file_path, "rb") as f:
                                    self.wfile.write(f.read())
                                return
                    
                    # Handle asset requests: /asset/elementalist_buttons/{form_id}.png
                    elif path.startswith("/asset/"):
                        asset_path = path.replace("/asset/", "").replace("/", chr(92))  # Convert to Windows path
                        if self.assets_dir:
                            file_path = self.assets_dir / asset_path
                            if file_path.exists():
                                self.send_response(200)
                                # Determine content type from extension
                                if file_path.suffix.lower() == ".png":
                                    self.send_header("Content-Type", "image/png")
                                elif file_path.suffix.lower() in [".jpg", ".jpeg"]:
                                    self.send_header("Content-Type", "image/jpeg")
                                else:
                                    self.send_header("Content-Type", "application/octet-stream")
                                self.send_header("Access-Control-Allow-Origin", "*")
                                self.end_headers()
                                with open(file_path, "rb") as f:
                                    self.wfile.write(f.read())
                                return
                    
                    # 404 for unknown paths
                    self.send_response(404)
                    self.end_headers()
                except Exception as e:
                    log.debug(f"[PenguSkinMonitor] HTTP server error: {e}")
                    self.send_response(500)
                    self.end_headers()

            def log_message(self, format, *args):
                # Suppress default logging
                pass

        try:
            self._http_server = HTTPServer((self.host, self._http_port), LocalFileHandler)
            http_thread = threading.Thread(target=self._http_server.serve_forever, daemon=True)
            http_thread.start()
            log.info(f"[PenguSkinMonitor] HTTP server started on http://{self.host}:{self._http_port}")
        except Exception as e:
            log.warning(f"[PenguSkinMonitor] Failed to start HTTP server: {e}")

    def _stop_http_server(self) -> None:
        """Stop HTTP server"""
        if self._http_server:
            try:
                self._http_server.shutdown()
                self._http_server.server_close()
                log.info("[PenguSkinMonitor] HTTP server stopped")
            except Exception as e:
                log.debug(f"[PenguSkinMonitor] Error stopping HTTP server: {e}")
            finally:
                self._http_server = None

    def _skin_has_chromas(self, skin_id: Optional[int]) -> bool:
        if skin_id is None:
            return False

        if skin_id == 99007:
            return True

        if 99991 <= skin_id <= 99999:
            return True

        if skin_id in SPECIAL_BASE_SKIN_IDS:
            return True

        if skin_id in SPECIAL_CHROMA_SKIN_IDS:
            return True

        if self.skin_scraper and self.skin_scraper.cache:
            chroma_id_map = getattr(
                self.skin_scraper.cache, "chroma_id_map", None
            )
            if chroma_id_map and skin_id in chroma_id_map:
                return True

            try:
                chromas = self.skin_scraper.get_chromas_for_skin(skin_id)
                if chromas:
                    return True
            except Exception:
                return False

        return False
