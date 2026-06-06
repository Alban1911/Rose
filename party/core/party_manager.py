#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Party Manager
Orchestrator for party mode skin sharing via WebSocket relay.
"""

import asyncio
import secrets
import time
from typing import Callable, Dict, List, Optional, Tuple

from lcu import LCU
from state import SharedState
from utils.core.logging import get_logger

from ..network.ws_relay import PartyRelay, compute_room_key
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

        # Networking
        self._my_key: Optional[bytes] = None
        self._my_token: Optional[PartyToken] = None
        self._relay: Optional[PartyRelay] = None

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

    async def enable(self) -> str:
        """Enable party mode: generate token and connect to relay room."""
        if self.party_state.enabled:
            return self.party_state.my_token or ""

        log.info("[PARTY] Enabling party mode...")

        try:
            self._lobby_matcher = LobbyMatcher(self.lcu, self.state)
            self._skin_collector = SkinCollector(self.state)

            my_summoner_id = self._lobby_matcher.get_my_summoner_id()
            my_summoner_name = self._lobby_matcher.get_my_summoner_name()

            if not my_summoner_id:
                raise RuntimeError("Failed to get summoner ID - is League client running?")

            self.party_state.my_summoner_id = my_summoner_id
            self.party_state.my_summoner_name = my_summoner_name

            # Generate key and token
            self._my_key = secrets.token_bytes(32)
            self._my_token = create_token(
                summoner_id=my_summoner_id,
                encryption_key=self._my_key,
            )

            token_str = self._my_token.encode()
            self.party_state.my_token = token_str
            self.party_state.enabled = True

            # Connect to relay room
            room_key = compute_room_key(my_summoner_id, self._my_key)
            self._relay = PartyRelay(room_key)
            self._relay.set_on_members_changed(self._on_relay_members_changed)

            if await self._relay.connect():
                await self._relay.join(my_summoner_id, my_summoner_name)
                log.info(f"[PARTY] Connected to relay room {room_key[:8]}...")
            else:
                log.warning("[PARTY] Relay connection failed, party mode limited")

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
        """Disable party mode."""
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

        self.party_state.clear_all()
        self._my_key = None
        self._my_token = None

        log.info("[PARTY] Party mode disabled")
        self._notify_state_change()

    async def add_peer(self, token_str: str) -> Tuple[bool, Optional[str]]:
        """Join another player's party room by pasting their token."""
        if not self.party_state.enabled:
            return False, "Party mode not enabled"

        token_str = "".join(token_str.split())

        try:
            token = PartyToken.decode(token_str)
            log.info(f"[PARTY] Joining party of summoner {token.summoner_id}")

            if token.summoner_id == self.party_state.my_summoner_id:
                return False, "You cannot add yourself"

            # Check if peer is already in our room (they joined us)
            if self._relay and self._relay.connected:
                for member in self._relay.members:
                    if member.get("summoner_id") == token.summoner_id:
                        log.info(f"[PARTY] Peer {token.summoner_id} is already in our room")
                        return True, None

            # Check if we're already in the target room
            target_room_key = compute_room_key(token.summoner_id, token.encryption_key)
            if self._relay and self._relay.room_key == target_room_key:
                log.info(f"[PARTY] Already in peer's room")
                return True, None

            # Disconnect from current room and join the host's room
            if self._relay:
                await self._relay.disconnect()

            self._relay = PartyRelay(target_room_key)
            self._relay.set_on_members_changed(self._on_relay_members_changed)

            if not await self._relay.connect():
                return False, "Failed to connect to relay"

            await self._relay.join(
                self.party_state.my_summoner_id,
                self.party_state.my_summoner_name,
            )

            log.info(f"[PARTY] Joined party room {target_room_key[:8]}...")
            return True, None

        except ValueError as e:
            error_str = str(e)
            if "expired" in error_str.lower():
                return False, "Token has expired. Ask your friend for a new one."
            return False, f"Invalid token: {error_str}"
        except Exception as e:
            log.error(f"[PARTY] Failed to join party: {e}")
            return False, f"Unexpected error: {e}"

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
