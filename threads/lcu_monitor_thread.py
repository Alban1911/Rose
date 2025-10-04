#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU connection monitoring thread for language detection
"""

import time
import threading
from typing import Optional, Callable
from lcu.client import LCU
from state.shared_state import SharedState
from utils.logging import get_logger

log = get_logger()


class LCUMonitorThread(threading.Thread):
    """Thread for monitoring LCU connection and language changes"""
    
    def __init__(self, lcu: LCU, state: SharedState, language_callback: Callable[[str], None], ws_thread=None):
        super().__init__(daemon=True)
        self.lcu = lcu
        self.state = state
        self.language_callback = language_callback
        self.ws_thread = ws_thread
        self.last_lcu_ok = False
        self.last_language = None
        self.waiting_for_connection = False
        self.ws_connected = False

    def run(self):
        """Main monitoring loop"""
        while not self.state.stop:
            try:
                current_lcu_ok = self.lcu.ok
                current_ws_connected = self._is_ws_connected()
                
                # Connection lost
                if self.last_lcu_ok and not current_lcu_ok:
                    log.info("LCU connection lost - waiting for reconnection...")
                    self.waiting_for_connection = True
                    self.last_language = None
                    self.ws_connected = False
                
                # Connection restored
                elif not self.last_lcu_ok and current_lcu_ok:
                    if self.waiting_for_connection:
                        log.info("LCU reconnected - waiting for WebSocket...")
                        self.waiting_for_connection = False
                
                # WebSocket connected after LCU reconnection
                elif current_lcu_ok and current_ws_connected and not self.ws_connected:
                    log.info("WebSocket connected - detecting language...")
                    self.ws_connected = True
                    
                    # Try to get new language
                    try:
                        new_language = self.lcu.get_client_language()
                        if new_language and new_language != self.last_language:
                            log.info(f"Language changed to: {new_language}")
                            self.last_language = new_language
                            self.language_callback(new_language)
                        elif new_language:
                            log.info(f"Language confirmed: {new_language}")
                            self.last_language = new_language
                    except Exception as e:
                        log.debug(f"Failed to get LCU language: {e}")
                
                # WebSocket disconnected
                elif not current_ws_connected and self.ws_connected:
                    self.ws_connected = False
                
                # Still waiting for connection
                elif not current_lcu_ok and self.waiting_for_connection:
                    # Refresh connection periodically
                    self.lcu.refresh_if_needed()
                
                self.last_lcu_ok = current_lcu_ok
                
            except Exception as e:
                log.debug(f"LCU monitor error: {e}")
            
            time.sleep(1.0)
    
    def _is_ws_connected(self) -> bool:
        """Check if WebSocket is connected"""
        if not self.ws_thread:
            return True  # If no WS thread, consider it always connected
        
        try:
            # Check if WebSocket exists and is connected
            return (hasattr(self.ws_thread, 'ws') and 
                    self.ws_thread.ws is not None and
                    hasattr(self.ws_thread.ws, 'sock') and
                    self.ws_thread.ws.sock is not None)
        except Exception:
            return False
