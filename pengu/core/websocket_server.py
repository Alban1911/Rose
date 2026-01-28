#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket Server Management
Handles WebSocket server lifecycle and connection management
"""

import asyncio
import logging
import threading
from typing import Optional, Set, Callable
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.server import WebSocketServerProtocol, serve

log = logging.getLogger(__name__)

# Suppress websockets library DEBUG logs
logging.getLogger("websockets.server").setLevel(logging.WARNING)
logging.getLogger("websockets.protocol").setLevel(logging.WARNING)


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
    
    def run(self) -> None:
        """Run the WebSocket server in an event loop"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
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
            self._loop.run_until_complete(self._shutdown_event.wait())
        except Exception as exc:  # noqa: BLE001
            log.error("[SkinMonitor] Server stopped unexpectedly: %s", exc)
        finally:
            self._loop.run_until_complete(self._shutdown())
            self._loop.close()
            log.info("[SkinMonitor] Thread terminated")
    
    async def _shutdown(self) -> None:
        """Shutdown server and close all connections"""
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
                    self.message_handler(message)
        except (ConnectionClosedError, ConnectionClosedOK):
            log.debug("[SkinMonitor] Client disconnected: %s", client)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "[SkinMonitor] Error handling client %s: %s", client, exc
            )
        finally:
            self._connections.discard(websocket)
    
    async def _process_http_request(self, path: str, request_headers) -> Optional[tuple]:
        """Process HTTP requests (delegates to http_handler)"""
        if self.http_handler:
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

