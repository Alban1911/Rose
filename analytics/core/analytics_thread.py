#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analytics thread for periodic user tracking pings
"""

import threading
import time
from typing import Optional

from config import ANALYTICS_PING_INTERVAL_S, APP_VERSION
from state import SharedState
from utils.core.logging import get_logger
from .analytics_client import AnalyticsClient

log = get_logger()


class AnalyticsThread(threading.Thread):
    """Background thread that sends periodic analytics pings"""
    
    def __init__(self, state: SharedState, ping_interval: Optional[float] = None):
        """
        Initialize analytics thread.
        
        Args:
            state: SharedState instance for checking stop flag
            ping_interval: Interval between pings in seconds (defaults to ANALYTICS_PING_INTERVAL_S)
        """
        super().__init__(daemon=True)
        self.state = state
        self.ping_interval = ping_interval or ANALYTICS_PING_INTERVAL_S
        self.client = AnalyticsClient()
        self._stop_event = threading.Event()
    
    def run(self) -> None:
        """Main thread loop - sends pings at regular intervals"""
        log.info(f"Analytics thread started (ping interval: {self.ping_interval}s)")
        
        # Send initial ping immediately
        self.client.send_ping(APP_VERSION)
        
        # Then send pings at regular intervals
        while not self.state.stop and not self._stop_event.is_set():
            # Wait for the ping interval or until stop is requested
            if self._stop_event.wait(timeout=self.ping_interval):
                # Stop event was set
                break
            
            # Check stop flag again before sending ping
            if self.state.stop:
                break
            
            # Send ping
            self.client.send_ping(APP_VERSION)
        
        log.info("Analytics thread stopped")
    
    def stop(self) -> None:
        """Stop the analytics thread"""
        self._stop_event.set()

