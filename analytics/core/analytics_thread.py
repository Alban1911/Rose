#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analytics thread for periodic user tracking pings
"""

import threading
from typing import Optional

from config import ANALYTICS_PING_INTERVAL_S, APP_VERSION
from state import SharedState
from utils.core.logging import get_logger
from .analytics_client import AnalyticsClient

log = get_logger()


class AnalyticsThread(threading.Thread):
    """Background thread that tracks startup, presence, and shutdown."""
    
    def __init__(self, state: SharedState, ping_interval: Optional[float] = None):
        """
        Initialize analytics thread.
        
        Args:
            state: SharedState instance for checking stop flag
            ping_interval: Interval between presence heartbeats in seconds (defaults to ANALYTICS_PING_INTERVAL_S)
        """
        super().__init__(daemon=True)
        self.state = state
        self.ping_interval = ANALYTICS_PING_INTERVAL_S if ping_interval is None else ping_interval
        self.client = AnalyticsClient()
        self._stop_event = threading.Event()
    
    def run(self) -> None:
        """Send a startup ping, periodic heartbeats, and a best-effort close ping."""
        log.info("Analytics thread started (heartbeat interval: %ss)", self.ping_interval)

        self.client.send_ping(APP_VERSION, event="startup")
        try:
            while not self.state.stop and not self._stop_event.is_set():
                if self._stop_event.wait(timeout=self.ping_interval):
                    break

                if self.state.stop:
                    break

                self.client.send_ping(APP_VERSION, event="heartbeat")
        finally:
            # This is best-effort; crashes, force-kills, and power loss cannot
            # reliably send a shutdown notification.
            self.client.send_ping(APP_VERSION, event="close", timeout=2)

        log.info("Analytics thread stopped")
    
    def stop(self) -> None:
        """Stop the analytics thread"""
        self._stop_event.set()

