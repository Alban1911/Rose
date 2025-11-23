#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket event thread
"""

import threading
from typing import Optional

from config import (
    WS_PING_INTERVAL_DEFAULT, WS_PING_TIMEOUT_DEFAULT, TIMER_HZ_DEFAULT,
    FALLBACK_LOADOUT_MS_DEFAULT
)
from lcu import LCU
from state import SharedState
from utils.core.logging import get_logger

from ..websocket.websocket_connection import WebSocketConnection
from ..websocket.websocket_event_handler import WebSocketEventHandler
from ..handlers.champion_lock_handler import ChampionLockHandler
from ..handlers.game_mode_detector import GameModeDetector
from ..utilities.timer_manager import TimerManager

log = get_logger()


class WSEventThread(threading.Thread):
    """WebSocket event thread with WAMP + lock counter + timer"""
    
    def __init__(
        self,
        lcu: LCU,
        state: SharedState,
        ping_interval: int = WS_PING_INTERVAL_DEFAULT,
        ping_timeout: int = WS_PING_TIMEOUT_DEFAULT,
        timer_hz: int = TIMER_HZ_DEFAULT,
        fallback_ms: int = FALLBACK_LOADOUT_MS_DEFAULT,
        injection_manager=None,
        skin_scraper=None,
        app_status_callback=None,
        app_status=None,
    ):
        super().__init__(daemon=True)
        self.lcu = lcu
        self.state = state
        self.injection_manager = injection_manager
        self.skin_scraper = skin_scraper
        self.app_status_callback = app_status_callback
        self.app_status = app_status
        
        # Initialize handlers
        self.champion_lock_handler = ChampionLockHandler(
            lcu, state, injection_manager, skin_scraper
        )
        self.game_mode_detector = GameModeDetector(lcu, state)
        self.timer_manager = TimerManager(
            lcu, state, timer_hz, fallback_ms, injection_manager, skin_scraper
        )
        self.event_handler = WebSocketEventHandler(
            lcu, state, self.champion_lock_handler, self.game_mode_detector, self.timer_manager, injection_manager
        )
        
        # Initialize WebSocket connection
        self.connection = WebSocketConnection(
            lcu,
            state,
            ping_interval,
            ping_timeout,
            on_message=self._on_message,
            app_status_callback=app_status_callback,
        )
    
    def run(self):
        """Main WebSocket loop"""
        self.connection.run()
    
    def _on_message(self, ws, msg):
        """WebSocket message received (delegates to event handler)"""
        self.event_handler.handle_message(ws, msg)
    
    def stop(self):
        """Stop the WebSocket thread gracefully"""
        self.connection.stop()
    
    # Backward compatibility properties
    @property
    def is_connected(self) -> bool:
        """Get WebSocket connection status"""
        return self.connection.is_connected
    
    @property
    def ws(self):
        """Get WebSocket instance (for backward compatibility)"""
        return self.connection.ws
    
    @property
    def ticker(self):
        """Get current ticker instance (for backward compatibility)"""
        return self.timer_manager.ticker
    
    @ticker.setter
    def ticker(self, value):
        """Set ticker instance (for backward compatibility)"""
        self.timer_manager.ticker = value
    
    @property
    def last_locked_champion_id(self) -> Optional[int]:
        """Get last locked champion ID (for backward compatibility)"""
        return self.champion_lock_handler.last_locked_champion_id
    
    @last_locked_champion_id.setter
    def last_locked_champion_id(self, value: Optional[int]):
        """Set last locked champion ID (for backward compatibility)"""
        self.champion_lock_handler.last_locked_champion_id = value
