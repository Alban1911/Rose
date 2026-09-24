#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Party Manager
Orchestrator for party mode skin sharing via LAN direct connection.
Host runs a local WebSocket server; clients connect directly.
"""

import asyncio
import secrets
import time
from typing import Callable, Dict, List, Optional, Tuple, Union

from lcu import LCU
from state import SharedState
from utils.core.logging import get_logger

from ..network.lan_server import PartyLANServer, get_network_interfaces, DEFAULT_PORT
from ..network.ws_relay import PartyRelay
from ..protocol.token_codec import PartyToken, create_token
from ..protocol.message_types import SkinSelection
from ..discovery.lobby_matcher import LobbyMatcher
from ..discovery.skin_collector import SkinCollector, PartySkinData
from .party_state import PartyState

log = get_logger()

LOBBY_CHECK_INTERVAL = 2.0
SKIN_BROADCAST_INTERVAL = 1.0


class PartyManager:
    """Main orchestrator for party mode."""

    def __init__(self, lcu: LCU, state: SharedState, injection_manager=None):
        self.lcu = lcu
        self.state = state
        self.injection_manager = injection_manager

        self.party_state = PartyState()

        # Networking — either a LAN server (host) or a relay client (client)
        self._my_key: Optional[bytes] = None
        self._my_token: Optional[PartyToken] = None
        self._relay: Optional[Union[PartyLANServer, PartyRelay]] = None
        self._is_host: bool = False

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
        return self.party_state.enabled

    @property
    def my_token_str(self) -> Optional[str]:
        return self.party_state.my_token

    def set_callbacks(
        self,
        on_state_change: Optional[Callable[[PartyState], None]] = None,
        on_peer_update: Optional[Callable[[int, dict], None]] = None,
    ):
        self._on_state_change = on_state_change
        self._on_peer_update = on_peer_update

    async def enable(self, host_ip: str = "", host_port: int = DEFAULT_PORT) -> str:
        """Enable party mode as HOST: start a local WebSocket server.

        Args:
            host_ip: IP address to advertise in the token (e.g. Hamachi IP).
            host_port: Port to listen on.

        Returns:
            The generated party token string.
        """
        if self.party_state.enabled:
            return self.party_state.my_token or ""

        log.info("[PARTY] Enabling party mode (LAN host)...")

        try:
            if not self._lobby_matcher:
                self._lobby_matcher = LobbyMatcher(self.lcu, self.state)
            if not self._skin_collector:
                self._skin_collector = SkinCollector(self.state)

            my_summoner_id = self._lobby_matcher.get_my_summoner_id()
            my_summoner_name = self._lobby_matcher.get_my_summoner_name()

            if not my_summoner_id:
                raise RuntimeError("Failed to get summoner ID - is League client running?")

            self.party_state.my_summoner_id = my_summoner_id
            self.party_state.my_summoner_name = my_summoner_name

            # If no host_ip provided, auto-detect best interface
            if not host_ip:
                interfaces = get_network_interfaces()
                for iface in interfaces:
                    if iface["ip"] != "127.0.0.1":
                        host_ip = iface["ip"]
                        break
                if not host_ip:
                    host_ip = "127.0.0.1"
                log.info(f"[PARTY] Auto-selected host IP: {host_ip}")

            # Start the local LAN server
            log.info(f"[PARTY] Starting local WebSocket server on 0.0.0.0:{host_port}...")
            self._relay = PartyLANServer(host="0.0.0.0", port=host_port)
            self._relay.set_on_members_changed(self._on_relay_members_changed)
            self._is_host = True

            if not await self._relay.start():
                raise RuntimeError(
                    f"Failed to start party server on port {host_port}. "
                    f"Is another instance running?"
                )

            # Host joins its own room
            await self._relay.join(my_summoner_id, my_summoner_name)

            # Determine actual bound port (PartyLANServer may have fallen back to port + 1)
            actual_port = getattr(self._relay, "port", host_port)

            # Generate key and token with host IP/port
            self._my_key = secrets.token_bytes(32)
            self._my_token = create_token(
                summoner_id=my_summoner_id,
                encryption_key=self._my_key,
                host_ip=host_ip,
                host_port=actual_port,
            )

            token_str = self._my_token.encode()
            self.party_state.my_token = token_str
            self.party_state.is_host = True
            self.party_state.enabled = True

            # Start background tasks
            self._running = True
            self._lobby_check_task = asyncio.create_task(self._lobby_check_loop())
            self._skin_broadcast_task = asyncio.create_task(self._skin_broadcast_loop())

            log.info(
                f"[PARTY] Party mode enabled successfully! Hosting at {host_ip}:{host_port} | "
                f"Token: {token_str[:25]}..."
            )
            self._notify_state_change()
            return token_str

        except Exception as e:
            log.error(f"[PARTY] Failed to enable party mode: {e}")
            await self.disable()
            raise RuntimeError(f"Failed to enable party mode: {e}")

    async def disable(self):
        """Disable party mode (stop server or disconnect from host)."""
        log.info("[PARTY] Disabling party mode...")
        self._running = False

        for task in [self._lobby_check_task, self._skin_broadcast_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._lobby_check_task = None
        self._skin_broadcast_task = None

        if self._relay:
            await self._relay.disconnect()
            self._relay = None

        self._is_host = False
        self.party_state.clear_all()
        self._my_key = None
        self._my_token = None

        log.info("[PARTY] Party mode disabled")
        self._notify_state_change()

    async def join(self, token_str: str) -> Tuple[bool, Optional[str]]:
        """Join another player's party room directly as a client without hosting a server.

        Args:
            token_str: Party token string from the host.

        Returns:
            Tuple of (success, error_message).
        """
        token_str = "".join(token_str.split())
        if not token_str:
            return False, "Party token cannot be empty"

        try:
            token = PartyToken.decode(token_str)
            log.info(f"[PARTY] Joining party of host {token.summoner_id}")

            if token.version < 3 or not token.host_ip:
                return False, (
                    "This token uses an older format that requires a relay server. "
                    "Ask your friend to update Rose and generate a new token."
                )

            # Initialize discovery components if not already initialized
            if not self._lobby_matcher:
                self._lobby_matcher = LobbyMatcher(self.lcu, self.state)
            if not self._skin_collector:
                self._skin_collector = SkinCollector(self.state)

            my_summoner_id = self._lobby_matcher.get_my_summoner_id()
            my_summoner_name = self._lobby_matcher.get_my_summoner_name()

            if not my_summoner_id:
                return False, "Failed to get summoner ID - is League client running?"

            if token.summoner_id == my_summoner_id:
                return False, "You cannot join your own party token"

            self.party_state.my_summoner_id = my_summoner_id
            self.party_state.my_summoner_name = my_summoner_name

            # Check if host is already connected in our current relay
            if self._relay and self._relay.connected:
                for member in self._relay.members:
                    if member.get("summoner_id") == token.summoner_id:
                        log.info(f"[PARTY] Host {token.summoner_id} is already connected")
                        return True, None

            # If we are currently hosting or connected to another room, disconnect first
            if self._relay:
                await self._relay.disconnect()
                self._relay = None

            self._is_host = False
            self.party_state.is_host = False
            self.party_state.my_token = None

            # Connect directly to the LAN host
            host_url = f"ws://{token.host_ip}:{token.host_port}"
            log.info(f"[PARTY] Connecting to LAN host at {host_url}")

            relay = PartyRelay(room_key="lan-direct")
            relay.set_on_members_changed(self._on_relay_members_changed)

            if not await relay.connect_to(host_url):
                return False, (
                    f"Failed to connect to {token.host_ip}:{token.host_port}. "
                    f"Make sure your friend is hosting and "
                    f"you're on the same network (Radmin VPN / Hamachi / LAN)."
                )

            self._relay = relay
            await self._relay.join(my_summoner_id, my_summoner_name)

            self.party_state.enabled = True

            # Start background tasks
            if not self._running:
                self._running = True
                self._lobby_check_task = asyncio.create_task(self._lobby_check_loop())
                self._skin_broadcast_task = asyncio.create_task(self._skin_broadcast_loop())

            log.info(f"[PARTY] Successfully joined LAN party at {host_url}")
            self._notify_state_change()
            return True, None

        except ValueError as e:
            error_str = str(e)
            if "expired" in error_str.lower():
                return False, "Token has expired. Ask your friend for a new one."
            return False, f"Invalid token: {error_str}"
        except Exception as e:
            log.error(f"[PARTY] Failed to join party: {e}")
            return False, f"Unexpected error: {e}"

    async def add_peer(self, token_str: str) -> Tuple[bool, Optional[str]]:
        """Legacy alias: join another player's party by token."""
        return await self.join(token_str)

    async def remove_peer(self, summoner_id: int):
        """Remove a peer (not really applicable in shared room model, but kept for UI)."""
        self.party_state.remove_peer(summoner_id)
        if self._skin_collector:
            self._skin_collector.clear_peer(summoner_id)
        self._notify_state_change()
        log.info(f"[PARTY] Removed peer {summoner_id}")

    async def broadcast_skin_update(self):
        """Broadcast our current skin selection to the relay room."""
        if not self.enabled or not self._relay or not self._relay.connected:
            return

        selection = self._skin_collector.get_my_selection(
            self.party_state.my_summoner_id,
            self.party_state.my_summoner_name,
        )

        if not selection:
            return

        skin_data = {
            "champion_id": selection.champion_id,
            "skin_id": selection.skin_id,
            "chroma_id": selection.chroma_id,
        }

        # For custom mods, share a content hash instead of the file path
        if selection.custom_mod_path:
            mod_hash = self._hash_custom_mod(selection.custom_mod_path)
            if mod_hash:
                skin_data["custom_mod_hash"] = mod_hash
                skin_data["is_custom"] = True

        await self._relay.send_skin(skin_data)

    def get_party_skins(self) -> List[PartySkinData]:
        """Get all skin selections for injection."""
        if not self.enabled or not self._lobby_matcher or not self._skin_collector:
            return []

        team_champions = self._lobby_matcher.get_team_champion_mapping()

        # Collect skins from relay members
        return self._skin_collector.collect_relay_skins(
            members=self._relay.members if self._relay else [],
            my_summoner_id=self.party_state.my_summoner_id,
            team_champions=team_champions,
        )

    def get_state_dict(self) -> dict:
        return self.party_state.to_dict()

    # ─── Relay callbacks ─────────────────────────────────────────────────

    def _on_relay_members_changed(self, members: list):
        """Called by the relay when the member list changes."""
        my_id = self.party_state.my_summoner_id

        # Update party state with relay members (exclude ourselves)
        current_peer_ids = set()
        for member in members:
            sid = member.get("summoner_id", 0)
            if sid == my_id or not sid:
                continue

            current_peer_ids.add(sid)
            name = member.get("summoner_name", "Unknown")
            skin = member.get("skin")

            if sid not in self.party_state.peers:
                self.party_state.add_peer(
                    sid,
                    summoner_name=name,
                    connected=True,
                    connection_state="connected",
                )
            else:
                self.party_state.peers[sid].summoner_name = name
                self.party_state.peers[sid].connected = True
                self.party_state.peers[sid].connection_state = "connected"

            # Update skin selection
            if skin and self._skin_collector:
                try:
                    sel = SkinSelection(
                        summoner_id=sid,
                        summoner_name=name,
                        champion_id=skin.get("champion_id", 0),
                        skin_id=skin.get("skin_id", 0),
                        chroma_id=skin.get("chroma_id"),
                    )
                    self.party_state.update_peer_skin(sid, sel)
                    self._skin_collector.update_from_peer(sel)
                except Exception as e:
                    log.debug(f"[PARTY] Failed to update peer skin: {e}")

        # Remove peers that are no longer in the room
        stale = [sid for sid in self.party_state.peers if sid not in current_peer_ids]
        for sid in stale:
            self.party_state.remove_peer(sid)
            if self._skin_collector:
                self._skin_collector.clear_peer(sid)
            log.info(f"[PARTY] Removed peer {sid}")

        self._notify_state_change()

    # ─── Background tasks ────────────────────────────────────────────────

    async def _lobby_check_loop(self):
        """Check lobby membership and update peer status."""
        while self._running:
            try:
                await asyncio.sleep(LOBBY_CHECK_INTERVAL)
                if not self._running or not self._lobby_matcher:
                    continue

                lobby_ids = self._lobby_matcher.get_all_summoner_ids()
                for sid in self.party_state.peers:
                    in_lobby = sid in lobby_ids
                    if self.party_state.peers[sid].in_lobby != in_lobby:
                        self.party_state.update_peer_lobby_status(sid, in_lobby)
                        name = self.party_state.peers[sid].summoner_name
                        if in_lobby:
                            log.info(f"[PARTY] Peer {name} joined our lobby")
                        else:
                            log.info(f"[PARTY] Peer {name} left our lobby")

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.info(f"[PARTY] Lobby check error: {e}")

    async def _skin_broadcast_loop(self):
        """Broadcast skin updates when selection changes."""
        last_skin_id = None
        last_chroma_id = None
        last_custom_mod = None

        while self._running:
            try:
                await asyncio.sleep(SKIN_BROADCAST_INTERVAL)
                if not self._running:
                    continue

                # Resolve effective skin id (considering random mode and historic mode)
                if getattr(self.state, "random_mode_active", False) and getattr(self.state, "random_skin_id", None):
                    current_skin_id = self.state.random_skin_id
                    current_chroma_id = getattr(self.state, "random_chroma_id", None)
                elif getattr(self.state, "historic_mode_active", False) and getattr(self.state, "historic_skin_id", None):
                    current_skin_id = self.state.historic_skin_id
                    current_chroma_id = None
                else:
                    current_skin_id = self.state.last_hovered_skin_id
                    current_chroma_id = getattr(self.state, "selected_chroma_id", None)

                current_custom_mod = getattr(self.state, "selected_custom_mod", None)
                # Track custom mod by its path to detect changes
                custom_mod_key = current_custom_mod.get("relative_path") if current_custom_mod else None

                if (current_skin_id != last_skin_id or
                    current_chroma_id != last_chroma_id or
                    custom_mod_key != last_custom_mod):
                    last_skin_id = current_skin_id
                    last_chroma_id = current_chroma_id
                    last_custom_mod = custom_mod_key
                    await self.broadcast_skin_update()

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.info(f"[PARTY] Skin broadcast error: {e}")

    @staticmethod
    def _hash_custom_mod(mod_path: str) -> Optional[str]:
        """Compute a content hash of a custom mod zip file."""
        import hashlib
        from utils.core.paths import get_user_data_dir

        try:
            mods_root = get_user_data_dir() / "mods"
            full_path = mods_root / mod_path
            if not full_path.exists():
                return None

            h = hashlib.sha256()
            with open(full_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()[:16]
        except Exception as e:
            log.debug(f"[PARTY] Failed to hash custom mod: {e}")
            return None

    @staticmethod
    def find_local_mod_by_hash(content_hash: str, champion_id: int) -> Optional[str]:
        """Search local mods for a zip matching the given content hash.

        Returns:
            Relative path to the matching mod (from mods root), or None.
        """
        import hashlib
        from utils.core.paths import get_user_data_dir

        try:
            mods_root = get_user_data_dir() / "mods"
            skins_dir = mods_root / "skins"
            if not skins_dir.exists():
                return None

            # Scan all mod zips
            for skin_dir in skins_dir.iterdir():
                if not skin_dir.is_dir():
                    continue
                for mod_file in skin_dir.iterdir():
                    if not mod_file.is_file():
                        continue
                    if mod_file.suffix.lower() not in (".zip", ".fantome"):
                        continue
                    try:
                        h = hashlib.sha256()
                        with open(mod_file, "rb") as f:
                            for chunk in iter(lambda: f.read(65536), b""):
                                h.update(chunk)
                        if h.hexdigest()[:16] == content_hash:
                            return str(mod_file.relative_to(mods_root))
                    except Exception:
                        continue
        except Exception as e:
            log.debug(f"[PARTY] Error searching local mods: {e}")

        return None

    def _notify_state_change(self):
        if self._on_state_change:
            self._on_state_change(self.party_state)
