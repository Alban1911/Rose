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

        self.last_skin_id: Optional[int] = None

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
        self.last_skin_id = None
        self.shared_state.ui_skin_id = None
        self.shared_state.ui_last_text = None

    def clear_cache(self) -> None:
        """
        Reset cached mappings/state (called during champion exchange events).
        """
        self.last_skin_id = None
        self.shared_state.ui_skin_id = None
        self.shared_state.ui_last_text = None

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

        skin_id_raw = payload.get("skinId")
        if skin_id_raw is None:
            legacy_skin = payload.get("skin")
            if legacy_skin:
                log.debug(
                    "[PenguSkinMonitor] Ignoring legacy skin payload in ID mode: %s",
                    legacy_skin,
                )
            return

        try:
            skin_id = int(skin_id_raw)
        except (TypeError, ValueError):
            return

        if skin_id <= 0:
            return

        if not self._should_process_payload():
            return

        if skin_id == self.last_skin_id:
            return

        self.last_skin_id = skin_id
        self._process_skin_id(skin_id)

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
    def _process_skin_id(self, skin_id: int) -> None:
        try:
            champion_id = get_champion_id_from_skin_id(skin_id)
            if getattr(self.shared_state, "is_swiftplay_mode", False) and champion_id:
                self.shared_state.swiftplay_skin_tracking[champion_id] = skin_id

            self.shared_state.ui_skin_id = skin_id
            self.shared_state.last_hovered_skin_id = skin_id

            skin_name = self._resolve_skin_name(skin_id)
            self.shared_state.ui_last_text = skin_name
            self.shared_state.last_hovered_skin_key = skin_name or f"Skin {skin_id}"

            log.info(
                "[PenguSkinMonitor] Skin ID detected: %s (champion=%s, name='%s')",
                skin_id,
                champion_id,
                skin_name or "unknown",
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "[PenguSkinMonitor] Error processing skin ID %s: %s",
                skin_id,
                exc,
            )

    # ------------------------------------------------------- Skin lookup utils
    def _resolve_skin_name(self, skin_id: int) -> Optional[str]:
        if not self.skin_scraper:
            return None

        # Try using the currently locked champion, if available.
        champ_id = getattr(self.shared_state, "locked_champ_id", None)
        if champ_id:
            try:
                self.skin_scraper.scrape_champion_skins(champ_id)
            except Exception:
                champ_id = None

        try:
            skin_data = self.skin_scraper.cache.get_skin_by_id(skin_id)
        except Exception:
            return None

        if not skin_data:
            return None

        name = (skin_data.get("skinName") or "").strip()
        return name or None

