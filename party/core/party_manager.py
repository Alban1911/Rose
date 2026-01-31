#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Party Manager
Main orchestrator for party mode P2P skin sharing
"""

import asyncio
import time
from typing import Callable, Dict, List, Optional

from lcu import LCU
from state import SharedState
from utils.core.logging import get_logger

from ..network.stun_client import StunClient
from ..network.udp_transport import UDPTransport
from ..network.peer_connection import PeerConnection, ConnectionState
from ..protocol.crypto import PartyCrypto
from ..protocol.token_codec import PartyToken, create_token
from ..protocol.message_types import (
    Message,
    MessageType,
    SkinSelection,
    create_lobby_info,
    create_lobby_match,
    create_skin_update,
    create_skin_sync,
)
from ..discovery.lobby_matcher import LobbyMatcher
from ..discovery.skin_collector import SkinCollector, PartySkinData
from .party_state import PartyState

log = get_logger()

# Lobby check interval
LOBBY_CHECK_INTERVAL = 2.0
# Skin broadcast interval
SKIN_BROADCAST_INTERVAL = 1.0


class PartyManager:
    """Main orchestrator for party mode"""

    def __init__(self, lcu: LCU, state: SharedState, injection_manager=None):
        """Initialize party manager

        Args:
            lcu: LCU client instance
            state: Shared application state
            injection_manager: Optional injection manager for party injection
        """
        self.lcu = lcu
        self.state = state
        self.injection_manager = injection_manager

        # Party state
        self.party_state = PartyState()

        # Networking
        self._transport: Optional[UDPTransport] = None
        self._stun_client = StunClient()
        self._my_key: Optional[bytes] = None
        self._my_token: Optional[PartyToken] = None

        # Peer connections
        self._peers: Dict[int, PeerConnection] = {}  # summoner_id -> connection

        # Discovery
        self._lobby_matcher: Optional[LobbyMatcher] = None
        self._skin_collector: Optional[SkinCollector] = None

        # Background tasks
        self._running = False
        self._lobby_check_task: Optional[asyncio.Task] = None
        self._skin_broadcast_task: Optional[asyncio.Task] = None

        # Callbacks for UI updates
        self._on_state_change: Optional[Callable[[PartyState], None]] = None
        self._on_peer_update: Optional[Callable[[int, dict], None]] = None

    @property
    def enabled(self) -> bool:
        """Check if party mode is enabled"""
        return self.party_state.enabled

    @property
    def my_token_str(self) -> Optional[str]:
        """Get our party token as string"""
        return self.party_state.my_token

    def set_callbacks(
        self,
        on_state_change: Optional[Callable[[PartyState], None]] = None,
        on_peer_update: Optional[Callable[[int, dict], None]] = None,
    ):
        """Set callback functions for UI updates"""
        self._on_state_change = on_state_change
        self._on_peer_update = on_peer_update

    async def enable(self) -> str:
        """Enable party mode and generate party token

        Returns:
            Party token string for sharing

        Raises:
            RuntimeError: If enabling fails
        """
        if self.party_state.enabled:
            return self.party_state.my_token or ""

        log.info("[PARTY] Enabling party mode...")

        try:
            # Initialize components
            self._lobby_matcher = LobbyMatcher(self.lcu, self.state)
            self._skin_collector = SkinCollector(self.state)

            # Get our summoner info
            my_summoner_id = self._lobby_matcher.get_my_summoner_id()
            my_summoner_name = self._lobby_matcher.get_my_summoner_name()

            if not my_summoner_id:
                raise RuntimeError("Failed to get summoner ID - is League client running?")

            self.party_state.my_summoner_id = my_summoner_id
            self.party_state.my_summoner_name = my_summoner_name

            # Create UDP transport
            self._transport = UDPTransport()
            await self._transport.bind()
            # Discover external address via STUN using our actual socket (so token port matches)
            stun_result = await self._stun_client.discover(self._transport.get_socket())
            if not stun_result:
                raise RuntimeError("STUN discovery failed - check network connection")
            # Now start receiving (after STUN so response went to us)
            await self._transport.start_receiving()

            # Generate encryption key
            self._my_key = PartyCrypto.generate_key()

            # Create party token
            self._my_token = create_token(
                external_ip=stun_result.external_ip,
                external_port=stun_result.external_port,
                internal_ip=stun_result.local_ip,
                internal_port=stun_result.local_port,
                summoner_id=my_summoner_id,
                encryption_key=self._my_key,
            )

            token_str = self._my_token.encode()
            self.party_state.my_token = token_str
            self.party_state.enabled = True

            # Start background tasks
            self._running = True
            self._lobby_check_task = asyncio.create_task(self._lobby_check_loop())
            self._skin_broadcast_task = asyncio.create_task(self._skin_broadcast_loop())

            log.info(f"[PARTY] Party mode enabled. Token: {token_str[:20]}...")
            self._notify_state_change()

            return token_str

        except Exception as e:
            log.error(f"[PARTY] Failed to enable party mode: {e}")
            await self.disable()
            raise RuntimeError(f"Failed to enable party mode: {e}")

    async def disable(self):
        """Disable party mode"""
        log.info("[PARTY] Disabling party mode...")

        self._running = False

        # Cancel background tasks
        for task in [self._lobby_check_task, self._skin_broadcast_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._lobby_check_task = None
        self._skin_broadcast_task = None

        # Disconnect all peers
        for peer in list(self._peers.values()):
            await peer.disconnect()
        self._peers.clear()

        # Stop transport
        if self._transport:
            await self._transport.stop()
            self._transport = None

        # Clear state
        self.party_state.clear_all()
        self._my_key = None
        self._my_token = None

        log.info("[PARTY] Party mode disabled")
        self._notify_state_change()

    async def add_peer(self, token_str: str) -> bool:
        """Add a peer from their party token

        Args:
            token_str: Peer's party token string

        Returns:
            True if peer added and connected successfully
        """
        if not self.party_state.enabled:
            log.warning("[PARTY] Cannot add peer - party mode not enabled")
            return False

        try:
            # Decode token
            token = PartyToken.decode(token_str)
            log.info(f"[PARTY] Adding peer: {token}")

            # Check if already connected
            if token.summoner_id in self._peers:
                existing = self._peers[token.summoner_id]
                if existing.is_connected:
                    log.info(f"[PARTY] Already connected to summoner {token.summoner_id}")
                    return True
                else:
                    # Remove stale connection
                    await existing.disconnect()
                    del self._peers[token.summoner_id]

            # Check if trying to connect to self
            if token.summoner_id == self.party_state.my_summoner_id:
                log.warning("[PARTY] Cannot add self as peer")
                return False

            # Create peer connection
            peer = PeerConnection(
                token=token,
                transport=self._transport,
                my_summoner_id=self.party_state.my_summoner_id,
                my_summoner_name=self.party_state.my_summoner_name,
                my_key=self._my_key,
            )

            # Set callbacks
            peer.set_callbacks(
                on_message=lambda msg: self._handle_peer_message(token.summoner_id, msg),
                on_state_change=lambda state: self._handle_peer_state_change(
                    token.summoner_id, state
                ),
                on_skin_update=lambda sel: self._handle_peer_skin_update(
                    token.summoner_id, sel
                ),
            )

            # Attempt connection
            self.party_state.add_peer(token.summoner_id, connected=False)
            self._notify_state_change()

            if await peer.connect():
                self._peers[token.summoner_id] = peer
                self.party_state.update_peer_connection(token.summoner_id, True)
                self.party_state.peers[token.summoner_id].summoner_name = peer.summoner_name

                log.info(f"[PARTY] Connected to {peer.summoner_name} ({token.summoner_id})")
                self._notify_state_change()

                # Send our current skin selection
                await self._send_my_skin_to_peer(peer)

                return True
            else:
                self.party_state.remove_peer(token.summoner_id)
                self._notify_state_change()
                return False

        except ValueError as e:
            log.warning(f"[PARTY] Invalid token: {e}")
            return False
        except Exception as e:
            log.error(f"[PARTY] Failed to add peer: {e}")
            return False

    async def remove_peer(self, summoner_id: int):
        """Remove a peer connection

        Args:
            summoner_id: Peer's summoner ID
        """
        if summoner_id in self._peers:
            await self._peers[summoner_id].disconnect()
            del self._peers[summoner_id]

        self.party_state.remove_peer(summoner_id)
        self._skin_collector.clear_peer(summoner_id)
        self._notify_state_change()
        log.info(f"[PARTY] Removed peer {summoner_id}")

    async def broadcast_skin_update(self):
        """Broadcast our current skin selection to all peers"""
        if not self.enabled:
            return

        selection = self._skin_collector.get_my_selection(
            self.party_state.my_summoner_id,
            self.party_state.my_summoner_name,
        )

        if not selection:
            return

        msg = create_skin_update(selection)

        for peer in self._peers.values():
            if peer.is_connected:
                try:
                    await peer.send_message(msg)
                except Exception as e:
                    log.debug(f"[PARTY] Failed to send skin update to {peer.summoner_id}: {e}")

    def get_party_skins(self) -> List[PartySkinData]:
        """Get all skin selections for injection

        Returns:
            List of PartySkinData for party members
        """
        if not self.enabled or not self._lobby_matcher or not self._skin_collector:
            return []

        # Get team champion mapping (may be empty if session cleared after game start)
        team_champions = self._lobby_matcher.get_team_champion_mapping()

        # Use connected peers (not just lobby): at injection time phase may be GameStart/InProgress
        # and lobby check may have cleared in_lobby, so get_lobby_peers() can be empty
        connected_peers = [
            self._peers[p.summoner_id]
            for p in self.party_state.get_connected_peers()
            if p.summoner_id in self._peers
        ]

        return self._skin_collector.collect_all_skins(
            peers=connected_peers,
            my_summoner_id=self.party_state.my_summoner_id,
            my_summoner_name=self.party_state.my_summoner_name,
            team_champions=team_champions,
        )

    def get_state_dict(self) -> dict:
        """Get party state as dictionary for UI"""
        return self.party_state.to_dict()

    # Private methods

    async def _send_my_skin_to_peer(self, peer: PeerConnection):
        """Send our current skin selection to a specific peer"""
        selection = self._skin_collector.get_my_selection(
            self.party_state.my_summoner_id,
            self.party_state.my_summoner_name,
        )

        if selection:
            try:
                await peer.send_skin_update(selection)
            except Exception as e:
                log.debug(f"[PARTY] Failed to send skin to peer: {e}")

    def _handle_peer_message(self, summoner_id: int, msg: Message):
        """Handle message from peer"""
        if msg.type == MessageType.LOBBY_INFO:
            # Peer shared their lobby info
            peer_lobby_ids = msg.payload.get("lobby_summoner_ids", [])
            our_lobby_ids = list(self._lobby_matcher.get_all_summoner_ids())

            # Check for overlap
            common = set(peer_lobby_ids) & set(our_lobby_ids)
            if common:
                self.party_state.update_peer_lobby_status(summoner_id, True)
                log.info(f"[PARTY] Peer {summoner_id} is in our lobby")

    def _handle_peer_state_change(self, summoner_id: int, state: ConnectionState):
        """Handle peer connection state change"""
        if state == ConnectionState.CONNECTED:
            self.party_state.update_peer_connection(summoner_id, True)
        elif state in (ConnectionState.DISCONNECTED, ConnectionState.DEAD):
            self.party_state.update_peer_connection(summoner_id, False)

        self._notify_state_change()

    def _handle_peer_skin_update(self, summoner_id: int, selection: SkinSelection):
        """Handle skin update from peer"""
        self.party_state.update_peer_skin(summoner_id, selection)
        self._skin_collector.update_from_peer(selection)
        self._notify_state_change()

    async def _lobby_check_loop(self):
        """Background loop to check lobby membership"""
        while self._running:
            try:
                await asyncio.sleep(LOBBY_CHECK_INTERVAL)

                if not self._running or not self._lobby_matcher:
                    continue

                # Get current lobby members
                lobby_ids = self._lobby_matcher.get_all_summoner_ids()

                # Update peer lobby status
                for summoner_id, peer in self._peers.items():
                    in_lobby = summoner_id in lobby_ids
                    if peer.peer_info.in_lobby != in_lobby:
                        self.party_state.update_peer_lobby_status(summoner_id, in_lobby)

                        if in_lobby:
                            log.info(f"[PARTY] Peer {peer.summoner_name} joined our lobby")
                        else:
                            log.info(f"[PARTY] Peer {peer.summoner_name} left our lobby")

                # Broadcast lobby info to peers
                if lobby_ids:
                    msg = create_lobby_info(
                        summoner_id=self.party_state.my_summoner_id,
                        lobby_summoner_ids=list(lobby_ids),
                        game_mode=self.state.current_game_mode,
                    )
                    for peer in self._peers.values():
                        if peer.is_connected:
                            try:
                                await peer.send_message(msg)
                            except Exception:
                                pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.debug(f"[PARTY] Lobby check error: {e}")

    async def _skin_broadcast_loop(self):
        """Background loop to broadcast skin updates"""
        last_skin_id = None
        last_chroma_id = None

        while self._running:
            try:
                await asyncio.sleep(SKIN_BROADCAST_INTERVAL)

                if not self._running:
                    continue

                # Check if skin selection changed
                current_skin_id = self.state.last_hovered_skin_id
                current_chroma_id = getattr(self.state, "selected_chroma_id", None)

                if current_skin_id != last_skin_id or current_chroma_id != last_chroma_id:
                    last_skin_id = current_skin_id
                    last_chroma_id = current_chroma_id

                    # Broadcast update
                    await self.broadcast_skin_update()

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.debug(f"[PARTY] Skin broadcast error: {e}")

    def _notify_state_change(self):
        """Notify UI of state change"""
        if self._on_state_change:
            self._on_state_change(self.party_state)
