#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Peer Connection Management
Handles individual P2P connections with peers
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

from utils.core.logging import get_logger

from ..protocol.crypto import PartyCrypto, derive_shared_key
from ..protocol.message_types import (
    Message,
    MessageType,
    SkinSelection,
    create_hello,
    create_hello_ack,
    create_ping,
    create_pong,
    create_skin_update,
)
from ..protocol.token_codec import PartyToken
from .udp_transport import UDPTransport, PeerEndpoint

log = get_logger()

# Connection configuration
HANDSHAKE_TIMEOUT = 10.0
PING_INTERVAL = 15.0
PING_TIMEOUT = 5.0
DEAD_TIMEOUT = 45.0


class ConnectionState(Enum):
    """Peer connection state"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    HANDSHAKING = "handshaking"
    CONNECTED = "connected"
    DEAD = "dead"


@dataclass
class PeerInfo:
    """Information about a connected peer"""
    summoner_id: int
    summoner_name: str = "Unknown"
    connected_at: float = 0.0
    last_seen: float = 0.0
    in_lobby: bool = False
    skin_selection: Optional[SkinSelection] = None


class PeerConnection:
    """Manages a single P2P connection with a peer"""

    def __init__(
        self,
        token: PartyToken,
        transport: UDPTransport,
        my_summoner_id: int,
        my_summoner_name: str,
        my_key: bytes,
    ):
        """Initialize peer connection

        Args:
            token: Peer's party token
            transport: UDP transport to use
            my_summoner_id: Our summoner ID
            my_summoner_name: Our summoner name
            my_key: Our encryption key
        """
        self.token = token
        self.transport = transport
        self.my_summoner_id = my_summoner_id
        self.my_summoner_name = my_summoner_name
        self.my_key = my_key

        # Peer info
        self.peer_info = PeerInfo(
            summoner_id=token.summoner_id,
            summoner_name="Unknown",
        )

        # Connection state
        self.state = ConnectionState.DISCONNECTED
        self._remote_addr: Optional[Tuple[str, int]] = None
        self._crypto: Optional[PartyCrypto] = None
        self._sequence = 0

        # Ping/pong tracking
        self._last_ping_time = 0.0
        self._last_pong_time = 0.0
        self._pending_ping_seq = -1

        # Background tasks
        self._keepalive_task: Optional[asyncio.Task] = None
        self._running = False

        # Message callbacks
        self._on_message: Optional[Callable[[Message], None]] = None
        self._on_state_change: Optional[Callable[[ConnectionState], None]] = None
        self._on_skin_update: Optional[Callable[[SkinSelection], None]] = None

    @property
    def summoner_id(self) -> int:
        """Get peer's summoner ID"""
        return self.token.summoner_id

    @property
    def summoner_name(self) -> str:
        """Get peer's summoner name"""
        return self.peer_info.summoner_name

    @property
    def is_connected(self) -> bool:
        """Check if connection is established"""
        return self.state == ConnectionState.CONNECTED

    @property
    def skin_selection(self) -> Optional[SkinSelection]:
        """Get peer's current skin selection"""
        return self.peer_info.skin_selection

    def set_callbacks(
        self,
        on_message: Optional[Callable[[Message], None]] = None,
        on_state_change: Optional[Callable[[ConnectionState], None]] = None,
        on_skin_update: Optional[Callable[[SkinSelection], None]] = None,
    ):
        """Set callback functions"""
        self._on_message = on_message
        self._on_state_change = on_state_change
        self._on_skin_update = on_skin_update

    async def connect(self) -> bool:
        """Establish connection with peer

        Returns:
            True if connection established, False otherwise
        """
        if self.state in (ConnectionState.CONNECTED, ConnectionState.CONNECTING):
            return self.state == ConnectionState.CONNECTED

        self._set_state(ConnectionState.CONNECTING)

        try:
            # Create endpoint for hole punching
            endpoint = PeerEndpoint(
                external_ip=self.token.external_ip,
                external_port=self.token.external_port,
                internal_ip=self.token.internal_ip,
                internal_port=self.token.internal_port,
            )

            # Attempt hole punching
            punch_data = f"PUNCH:{self.my_summoner_id}".encode()
            remote_addr = await self.transport.hole_punch(endpoint, punch_data)

            if not remote_addr:
                log.warning(f"[PEER] Hole punch failed for {self.summoner_id}")
                self._set_state(ConnectionState.DISCONNECTED)
                return False

            self._remote_addr = remote_addr

            # Derive shared encryption key
            shared_key = derive_shared_key(self.my_key, self.token.encryption_key)
            self._crypto = PartyCrypto(shared_key)

            # Perform handshake
            self._set_state(ConnectionState.HANDSHAKING)
            if not await self._handshake():
                log.warning(f"[PEER] Handshake failed for {self.summoner_id}")
                self._set_state(ConnectionState.DISCONNECTED)
                return False

            self._set_state(ConnectionState.CONNECTED)
            self.peer_info.connected_at = time.time()
            self.peer_info.last_seen = time.time()

            # Start keepalive
            self._running = True
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())

            # Register packet handler
            self.transport.set_handler(self._remote_addr, self._handle_packet)

            log.info(
                f"[PEER] Connected to {self.peer_info.summoner_name} "
                f"(ID: {self.summoner_id}) at {self._remote_addr}"
            )
            return True

        except Exception as e:
            log.error(f"[PEER] Connection error: {e}")
            self._set_state(ConnectionState.DISCONNECTED)
            return False

    async def disconnect(self):
        """Disconnect from peer"""
        self._running = False

        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None

        if self._remote_addr:
            self.transport.remove_handler(self._remote_addr)

        self._set_state(ConnectionState.DISCONNECTED)
        log.info(f"[PEER] Disconnected from {self.summoner_id}")

    async def send_message(self, msg: Message):
        """Send a message to the peer

        Args:
            msg: Message to send
        """
        if not self._remote_addr or not self._crypto:
            raise RuntimeError("Not connected")

        msg.sequence = self._next_sequence()
        plaintext = msg.to_bytes()
        ciphertext = self._crypto.encrypt(plaintext)

        await self.transport.send(ciphertext, self._remote_addr)

    async def send_skin_update(self, selection: SkinSelection):
        """Send skin selection update to peer"""
        msg = create_skin_update(selection)
        await self.send_message(msg)

    def _handle_packet(self, data: bytes, addr: Tuple[str, int]):
        """Handle incoming packet from peer"""
        if not self._crypto:
            return

        try:
            plaintext = self._crypto.decrypt(data)
            msg = Message.from_bytes(plaintext)
            self._handle_message(msg)
        except Exception as e:
            log.debug(f"[PEER] Failed to process packet: {e}")

    def _handle_message(self, msg: Message):
        """Process received message"""
        self.peer_info.last_seen = time.time()

        if msg.type == MessageType.PING:
            # Respond with pong
            asyncio.create_task(self._send_pong(msg.sequence))

        elif msg.type == MessageType.PONG:
            if msg.sequence == self._pending_ping_seq:
                self._last_pong_time = time.time()
                self._pending_ping_seq = -1

        elif msg.type == MessageType.SKIN_UPDATE:
            try:
                selection = SkinSelection.from_dict(msg.payload)
                self.peer_info.skin_selection = selection
                log.info(
                    f"[PEER] {self.summoner_name} selected skin {selection.skin_id} "
                    f"for champion {selection.champion_id}"
                )
                if self._on_skin_update:
                    self._on_skin_update(selection)
            except Exception as e:
                log.warning(f"[PEER] Failed to parse skin update: {e}")

        elif msg.type == MessageType.SKIN_CLEAR:
            self.peer_info.skin_selection = None
            log.info(f"[PEER] {self.summoner_name} cleared skin selection")

        elif msg.type == MessageType.LOBBY_MATCH:
            self.peer_info.in_lobby = msg.payload.get("matched", False)

        # Call general message callback
        if self._on_message:
            self._on_message(msg)

    async def _handshake(self) -> bool:
        """Perform connection handshake

        Returns:
            True if handshake successful
        """
        try:
            # Send HELLO
            hello_msg = create_hello(
                self.my_summoner_id,
                self.my_summoner_name,
                self.my_key,
            )
            await self.send_message(hello_msg)

            # Wait for HELLO or HELLO_ACK
            start_time = time.time()
            while time.time() - start_time < HANDSHAKE_TIMEOUT:
                try:
                    data, addr = await self.transport.recv(timeout=1.0)

                    if addr != self._remote_addr:
                        continue

                    if not self._crypto:
                        continue

                    plaintext = self._crypto.decrypt(data)
                    msg = Message.from_bytes(plaintext)

                    if msg.type == MessageType.HELLO:
                        # Peer sent HELLO, respond with HELLO_ACK
                        self.peer_info.summoner_name = msg.payload.get(
                            "summoner_name", "Unknown"
                        )
                        ack_msg = create_hello_ack(
                            self.my_summoner_id,
                            self.my_summoner_name,
                        )
                        await self.send_message(ack_msg)
                        return True

                    elif msg.type == MessageType.HELLO_ACK:
                        # Received ACK
                        self.peer_info.summoner_name = msg.payload.get(
                            "summoner_name", "Unknown"
                        )
                        return True

                except asyncio.TimeoutError:
                    # Resend HELLO
                    await self.send_message(hello_msg)
                    continue
                except Exception as e:
                    log.debug(f"[PEER] Handshake recv error: {e}")
                    continue

            return False

        except Exception as e:
            log.error(f"[PEER] Handshake error: {e}")
            return False

    async def _keepalive_loop(self):
        """Background keepalive loop"""
        while self._running:
            try:
                await asyncio.sleep(PING_INTERVAL)

                if not self._running:
                    break

                # Check if peer is dead
                time_since_seen = time.time() - self.peer_info.last_seen
                if time_since_seen > DEAD_TIMEOUT:
                    log.warning(
                        f"[PEER] {self.summoner_name} appears dead "
                        f"(last seen {time_since_seen:.1f}s ago)"
                    )
                    self._set_state(ConnectionState.DEAD)
                    break

                # Send ping
                self._pending_ping_seq = self._next_sequence()
                self._last_ping_time = time.time()
                ping_msg = create_ping(self._pending_ping_seq)
                await self.send_message(ping_msg)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.debug(f"[PEER] Keepalive error: {e}")

    async def _send_pong(self, sequence: int):
        """Send pong response"""
        try:
            pong_msg = create_pong(sequence)
            await self.send_message(pong_msg)
        except Exception as e:
            log.debug(f"[PEER] Failed to send pong: {e}")

    def _next_sequence(self) -> int:
        """Get next message sequence number"""
        self._sequence = (self._sequence + 1) % 65536
        return self._sequence

    def _set_state(self, new_state: ConnectionState):
        """Update connection state"""
        if self.state != new_state:
            old_state = self.state
            self.state = new_state
            log.debug(f"[PEER] {self.summoner_id}: {old_state.value} -> {new_state.value}")
            if self._on_state_change:
                self._on_state_change(new_state)
