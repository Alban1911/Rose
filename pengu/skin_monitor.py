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
from typing import Optional, Set

from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.server import WebSocketServerProtocol, serve

from utils.paths import get_user_data_dir
from utils.utilities import get_champion_id_from_skin_id

log = logging.getLogger(__name__)


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

    # ------------------------------------------------------------------ Thread
    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._shutdown_event = asyncio.Event()

        try:
            self._server = self._loop.run_until_complete(
                serve(self._handler, self.host, self.port, ping_interval=None)
            )
            log.info(
                "[PenguSkinMonitor] Listening for Pengu Loader events on ws://%s:%s",
                self.host,
                self.port,
            )
            self._loop.run_until_complete(self._shutdown_event.wait())
        except Exception as exc:  # noqa: BLE001
            log.error("[PenguSkinMonitor] Server stopped unexpectedly: %s", exc)
        finally:
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
