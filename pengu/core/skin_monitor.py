#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pengu Skin Monitor
------------------

Receives skin hover notifications from the Pengu Loader `ROSE-SkinMonitor` plugin
over WebSocket and updates the shared application state accordingly. This
replaces the legacy UIA-based skin detection pipeline.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from utils.core.utilities import find_free_port, write_bridge_port, delete_bridge_port_file

from .websocket_server import WebSocketServer
from .http_handler import HTTPHandler
from ..communication.message_handler import MessageHandler
from injection.mods.storage import ModStorageService
from ..processing.skin_processor import SkinProcessor
from ..processing.skin_mapping import SkinMapping
from ..communication.broadcaster import Broadcaster
from ..processing.flow_controller import FlowController
log = logging.getLogger(__name__)

# Suppress websockets library DEBUG logs
logging.getLogger("websockets.server").setLevel(logging.WARNING)
logging.getLogger("websockets.protocol").setLevel(logging.WARNING)


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
        port: Optional[int] = None,
    ) -> None:
        super().__init__(daemon=True, name="PenguSkinMonitor")
        self.shared_state = shared_state
        self.lcu = lcu
        self.skin_scraper = skin_scraper
        self.injection_manager = injection_manager
        self.host = host
        
        # Find free port if not specified (use high port range like LCU)
        if port is None:
            free_port = find_free_port(start_port=50000)
            if free_port is None:
                log.error("[SkinMonitor] Failed to find a free port, using default 50000")
                self.port = 50000
            else:
                self.port = free_port
        else:
            self.port = port
        
        # Write port to file for plugin discovery
        write_bridge_port(self.port)

        # Initialize modules
        self.skin_mapping = SkinMapping(shared_state)
        self.skin_processor = SkinProcessor(shared_state, skin_scraper, self.skin_mapping)
        self.flow_controller = FlowController(shared_state)
        self.mod_storage_service = ModStorageService()

        # Initialize HTTP handler
        self.http_handler = HTTPHandler(self.port)
        
        # Initialize WebSocket server
        self.websocket_server = WebSocketServer(
            host=self.host,
            port=self.port,
            message_handler=self._handle_message,
            http_handler=self.http_handler.handle_request,
        )
        
        # Initialize broadcaster
        self.broadcaster = Broadcaster(self.websocket_server, shared_state, self.skin_mapping, skin_scraper)

        # Initialize message handler
        self.message_handler = MessageHandler(
            shared_state=shared_state,
            websocket_server=self.websocket_server,
            broadcaster=self.broadcaster,
            skin_processor=self.skin_processor,
            flow_controller=self.flow_controller,
            skin_scraper=skin_scraper,
            mod_storage=self.mod_storage_service,
            injection_manager=self.injection_manager,
            port=self.port,
        )
        
        # Set message handler on WebSocket server
        self.websocket_server.message_handler = self.message_handler.handle_message

    def run(self) -> None:
        """Run the WebSocket server"""
        self.websocket_server.run()

    def stop(self) -> None:
        """Stop the server"""
        self.websocket_server.stop()
        # Clean up port file on shutdown
        delete_bridge_port_file()

    def force_disconnect(self) -> None:
        """
        Mimic the legacy UIA behaviour when injection is about to occur.
        """
        self.flow_controller.force_disconnect()
        self.skin_processor.clear_cache()
        self.shared_state.ui_skin_id = None
        self.shared_state.ui_last_text = None

    def clear_cache(self) -> None:
        """
        Reset cached mappings/state (called during champion exchange events).
        """
        self.skin_processor.clear_cache()
        self.skin_mapping.clear()
        self.shared_state.ui_skin_id = None
        self.shared_state.ui_last_text = None

    def _handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message (delegates to message handler)"""
        self.message_handler.handle_message(message)

    # ---------------------------------------------------------- JS Integration
    # These methods delegate to broadcaster for backward compatibility
    
    def _broadcast_skin_state(self, skin_name: str, skin_id: Optional[int]) -> None:
        """Broadcast skin state (delegates to broadcaster)"""
        self.broadcaster.broadcast_skin_state(skin_name, skin_id)

    def _broadcast_chroma_state(self) -> None:
        """Broadcast chroma state (delegates to broadcaster)"""
        self.broadcaster.broadcast_chroma_state()

    def _broadcast_historic_state(self) -> None:
        """Broadcast historic state (delegates to broadcaster)"""
        self.broadcaster.broadcast_historic_state()

    def _broadcast_custom_mod_state(self) -> None:
        """Broadcast custom mod state (delegates to broadcaster)"""
        self.broadcaster.broadcast_custom_mod_state()
    
    def _broadcast_phase_change(self, phase: str) -> None:
        """Broadcast phase change (delegates to broadcaster)"""
        self.broadcaster.broadcast_phase_change(phase)
    
    def _broadcast_champion_locked(self, locked: bool) -> None:
        """Broadcast champion lock state (delegates to broadcaster)"""
        self.broadcaster.broadcast_champion_locked(locked)
    
    def _broadcast_random_mode_state(self) -> None:
        """Broadcast random mode state (delegates to broadcaster)"""
        self.broadcaster.broadcast_random_mode_state()

    def _broadcast_skip_base_skin(self) -> None:
        self.broadcaster.broadcast_skip_base_skin()
    
    # Backward compatibility properties
    @property
    def ready_event(self) -> threading.Event:
        """Get ready event from WebSocket server"""
        return self.websocket_server.ready_event
    
    @property
    def last_skin_name(self) -> Optional[str]:
        """Get last skin name from processor"""
        return self.skin_processor.last_skin_name
    
    @last_skin_name.setter
    def last_skin_name(self, value: Optional[str]) -> None:
        """Set last skin name on processor"""
        self.skin_processor.last_skin_name = value
