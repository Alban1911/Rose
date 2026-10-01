#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket Server Management
Handles WebSocket server lifecycle and connection management
"""

import asyncio
import json
import logging
import sys
import threading
import time
import traceback
from typing import Optional, Set, Callable
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.server import WebSocketServerProtocol, serve
from utils.core.security import is_loopback_origin

log = logging.getLogger(__name__)

# Suppress websockets library DEBUG logs
logging.getLogger("websockets.server").setLevel(logging.WARNING)
logging.getLogger("websockets.protocol").setLevel(logging.WARNING)

# Plugins get no answer while the loop is busy (no skin detection, no chroma
# button), so a longer block is logged with where the loop is stuck
BLOCKED_LOOP_WARNING_S = 5.0
# While it stays blocked, log where it's stuck again this often
BLOCKED_LOOP_REPEAT_S = 60.0


class WebSocketServer:
    """Manages WebSocket server lifecycle and connections"""
    
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: Optional[int] = None,
        message_handler: Optional[Callable[[str], None]] = None,
        http_handler: Optional[Callable[[str, dict], Optional[tuple]]] = None,
    ):
        """Initialize WebSocket server
        
        Args:
            host: Server host address
            port: Server port (will find free port if None)
            message_handler: Callback for handling WebSocket messages
            http_handler: Callback for handling HTTP requests
        """
        self.host = host
        self.port = port or 50000  # Default port if not specified (high port range like LCU)
        self.message_handler = message_handler
        self.http_handler = http_handler
        
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server = None
        self._shutdown_event: Optional[asyncio.Event] = None
        self._connections: Set[WebSocketServerProtocol] = set()
        self._stop_event = threading.Event()
        self.ready_event = threading.Event()
    
        # Watchdog: the loop beats while it's free; the message being handled
        # is logged if it blocks
        self._last_beat = time.monotonic()
        self._loop_thread_id: Optional[int] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._handling: Optional[str] = None
        self.watchdog_interval_s = 1.0
    
    def run(self) -> None:
        """Run the WebSocket server in an event loop"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop_thread_id = threading.get_ident()
        self._shutdown_event = asyncio.Event()
        
        try:
            # Create server that handles both HTTP and WebSocket
            self._server = self._loop.run_until_complete(
                serve(
                    self._handler,
                    self.host,
                    self.port,
                    # Keepalive: reduces random idle WS disconnects on some machines (AV/VPN/web-shields).
                    # The plugin can reconnect, but we prefer to avoid reconnects in the first place.
                    ping_interval=20,
                    ping_timeout=20,
                    process_request=self._process_http_request if self.http_handler else None
                )
            )
            log.info(
                "[SkinMonitor] Server started on http://%s:%s (HTTP) and ws://%s:%s (WebSocket)",
                self.host,
                self.port,
                self.host,
                self.port,
            )
            self.ready_event.set()
            self._last_beat = time.monotonic()
            self._heartbeat_task = self._loop.create_task(self._heartbeat())
            threading.Thread(target=self._watch_loop, daemon=True, name="BridgeWatchdog").start()
            self._loop.run_until_complete(self._shutdown_event.wait())
        except Exception as exc:  # noqa: BLE001
            log.error("[SkinMonitor] Server stopped unexpectedly: %s", exc)
        finally:
            self._stop_event.set()  # stops the watchdog
            self._loop.run_until_complete(self._shutdown())
            self._loop.close()
            log.info("[SkinMonitor] Thread terminated")
    
    async def _shutdown(self) -> None:
        """Shutdown server and close all connections"""
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        for ws in list(self._connections):
            try:
                await ws.close()
            except Exception as e:
                log.debug(f"[SkinMonitor] Error closing connection during shutdown: {e}")
        
        self._connections.clear()
        
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception as e:
                log.debug(f"[SkinMonitor] Error waiting for server close: {e}")
            self._server = None
    
    def stop(self) -> None:
        """Stop the server"""
        self._stop_event.set()
        if self._loop and self._shutdown_event:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._signal_shutdown(), self._loop
                )
            except RuntimeError:
                pass
    
    async def _signal_shutdown(self) -> None:
        """Signal shutdown event"""
        if self._shutdown_event and not self._shutdown_event.is_set():
            self._shutdown_event.set()
    
    async def _handler(self, websocket: WebSocketServerProtocol) -> None:
        """Handle WebSocket connection"""
        client = websocket.remote_address
        log.info("[SkinMonitor] Client connected: %s", client)
        self._connections.add(websocket)
        try:
            async for message in websocket:
                if self.message_handler:
                    self._handling = message
                    try:
                        self.message_handler(message)
                    finally:
                        self._handling = None
        except (ConnectionClosedError, ConnectionClosedOK):
            pass
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "[SkinMonitor] Error handling client %s: %s", client, exc
            )
        finally:
            self._connections.discard(websocket)
            log.info(
                "[SkinMonitor] Client disconnected: %s (code %s)", client, websocket.close_code
            )

    async def _heartbeat(self) -> None:
        """Beat while the loop is free (read by the watchdog)"""
        while True:
            self._last_beat = time.monotonic()
            await asyncio.sleep(self.watchdog_interval_s / 2)

    def _watch_loop(self) -> None:
        """Log where the loop is stuck when it stops beating"""
        blocked_since = None
        last_report = 0.0
        last_check = time.monotonic()
        while not self._stop_event.wait(self.watchdog_interval_s):
            now = time.monotonic()
            overslept = now - last_check > self.watchdog_interval_s * 3
            last_check = now
            if overslept:
                continue  # the whole process was paused (PC asleep), not the loop

            idle = now - self._last_beat
            if idle < BLOCKED_LOOP_WARNING_S:
                if blocked_since is not None:
                    log.warning(
                        "[SkinMonitor] Bridge loop resumed after being blocked for %.1fs",
                        now - blocked_since,
                    )
                    blocked_since = None
                continue

            if blocked_since is None:
                blocked_since = self._last_beat
            elif now - last_report < BLOCKED_LOOP_REPEAT_S:
                continue
            last_report = now

            handling = self._message_type(self._handling)
            log.warning(
                "[SkinMonitor] Bridge loop blocked for %.0fs - plugins get no answers until it resumes%s. Stuck at:\n%s",
                idle,
                f" (handling a {handling} message)" if handling else "",
                self._loop_stack(),
            )

    @staticmethod
    def _message_type(message) -> Optional[str]:
        """Type of a plugin message, never its content (it can hold a party token)"""
        if message is None:
            return None
        try:
            return str(json.loads(message).get("type") or "untyped")
        except Exception:
            return "non-JSON"

    def _loop_stack(self) -> str:
        """Current stack of the loop thread"""
        frame = sys._current_frames().get(self._loop_thread_id)
        if frame is None:
            return "  (loop thread not running)"
        return "".join(traceback.format_stack(frame)).rstrip()
    
    async def _process_http_request(self, path: str, request_headers) -> Optional[tuple]:
        """Process HTTP requests (delegates to http_handler)"""
        origin = request_headers.get("Origin")
        upgrade = (request_headers.get("Upgrade") or "").lower()
        if upgrade == "websocket" and origin and not is_loopback_origin(origin):
            log.warning("[SkinMonitor] Blocked WebSocket request from origin: %s", origin)
            return (403, {"Content-Type": "text/plain"}, b"Forbidden")

        if self.http_handler:
            if path.startswith("/market-thumb"):
                # Fetches a remote image: keep it off the loop so the bridge stays responsive
                return await asyncio.get_running_loop().run_in_executor(
                    None, self.http_handler, path, request_headers
                )
            return self.http_handler(path, request_headers)
        return None
    
    async def broadcast(self, message: str) -> None:
        """Broadcast message to all connected clients"""
        stale: list[WebSocketServerProtocol] = []
        for ws in list(self._connections):
            try:
                await ws.send(message)
            except Exception as e:
                log.debug(f"[SkinMonitor] Broadcast failed to client, marking stale: {e}")
                stale.append(ws)
        for ws in stale:
            self._connections.discard(ws)
    
    @property
    def connections(self) -> Set[WebSocketServerProtocol]:
        """Get set of active connections"""
        return self._connections
    
    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """Get event loop"""
        return self._loop

