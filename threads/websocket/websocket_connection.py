#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket Connection Management
Handles WebSocket connection lifecycle and callbacks
"""

import base64
import json
import logging
import os
import ssl
import time
from typing import Optional, Callable

import websocket  # websocket-client

from config import WS_PING_INTERVAL_DEFAULT, WS_PING_TIMEOUT_DEFAULT, WS_RECONNECT_DELAY
from lcu import LCU
from state import SharedState
from utils.core.logging import get_logger

log = get_logger()

# Disable websocket ping logs
logging.getLogger("websocket").setLevel(logging.WARNING)


class WebSocketConnection:
    """Manages WebSocket connection lifecycle"""
    
    def __init__(
        self,
        lcu: LCU,
        state: SharedState,
        ping_interval: int = WS_PING_INTERVAL_DEFAULT,
        ping_timeout: int = WS_PING_TIMEOUT_DEFAULT,
        on_open: Optional[Callable] = None,
        on_message: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        on_close: Optional[Callable] = None,
        app_status_callback: Optional[Callable] = None,
    ):
        """Initialize WebSocket connection manager
        
        Args:
            lcu: LCU client instance
            state: Shared application state
            ping_interval: WebSocket ping interval
            ping_timeout: WebSocket ping timeout
            on_open: Callback for connection opened
            on_message: Callback for message received
            on_error: Callback for error
            on_close: Callback for connection closed
            app_status_callback: Callback for app status updates
        """
        self.lcu = lcu
        self.state = state
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.on_open = on_open
        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close
        self.app_status_callback = app_status_callback
        
        self.ws = None
        self.is_connected = False
    
    def run(self):
        """Main WebSocket connection loop"""
        if websocket is None:
            return
        
        # Remove proxy environment variables
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ.pop(k, None)
        
        while not self.state.stop:
            self.lcu.refresh_if_needed()
            if not self.lcu.ok:
                time.sleep(WS_RECONNECT_DELAY)
                continue
            
            url = f"wss://127.0.0.1:{self.lcu.port}/"
            origin = f"https://127.0.0.1:{self.lcu.port}"
            token = base64.b64encode(f"riot:{self.lcu.pw}".encode("utf-8")).decode("ascii")
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            try:
                self.ws = websocket.WebSocketApp(
                    url,
                    header=[f"Authorization: Basic {token}"],
                    subprotocols=["wamp"],
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self.ws.run_forever(
                    origin=origin,
                    sslopt={"context": ctx},
                    http_proxy_host=None,
                    http_proxy_port=None,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                )
            except Exception as e:
                log.debug(f"[ws] exception: {e}")
            
            # Check if we should stop before reconnecting
            if self.state.stop:
                break
            time.sleep(WS_RECONNECT_DELAY)
        
        # Ensure WebSocket is closed on thread exit
        if self.ws:
            try:
                self.ws.close()
                log.debug("[ws] WebSocket closed on thread exit")
            except Exception:
                pass
    
    def _on_open(self, ws):
        """WebSocket connection opened"""
        from utils.core.logging import log_status
        
        separator = "=" * 80
        log.info(separator)
        log.info("WEBSOCKET CONNECTED")
        log.info("   Status: Active")
        log.info(separator)
        
        self.is_connected = True
        
        # Update app status
        if self.app_status_callback:
            self.app_status_callback()
        
        try:
            ws.send('[5,"OnJsonApiEvent"]')
        except Exception as e:
            log.debug(f"WebSocket: Subscribe error: {e}")
    
    def _on_message(self, ws, msg):
        """WebSocket message received"""
        if self.on_message:
            self.on_message(ws, msg)
    
    def _on_error(self, ws, err):
        """WebSocket error"""
        log.debug(f"WebSocket: Error: {err}")
        if self.on_error:
            self.on_error(ws, err)
    
    def _on_close(self, ws, status, msg):
        """WebSocket connection closed"""
        separator = "=" * 80
        log.info(separator)
        log.info("WEBSOCKET DISCONNECTED")
        log.info(f"   Status Code: {status}")
        log.info(f"   Message: {msg}")
        log.info(separator)
        
        self.is_connected = False
        
        # Update app status
        if self.app_status_callback:
            self.app_status_callback()
        
        if self.on_close:
            self.on_close(ws, status, msg)
    
    def stop(self):
        """Stop the WebSocket connection"""
        if self.ws:
            try:
                self.ws.close()
                log.debug("[ws] WebSocket close requested")
            except Exception:
                pass

