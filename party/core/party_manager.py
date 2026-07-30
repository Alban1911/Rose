#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Party Manager
Orchestrator for party mode skin sharing via WebSocket relay.
"""

import asyncio
import base64
import secrets
import time
from typing import Callable, Dict, List, Optional, Tuple

from config import PARTY_AUTO_ROOM_MAX_AGE_SECONDS, PARTY_MODE_ALWAYS_ON
from lcu import LCU
from state import SharedState
from utils.core.logging import get_logger

from ..network.ws_relay import PartyRelay, compute_room_key
from ..protocol.token_codec import PartyToken, create_token
from ..protocol.message_types import SkinSelection
from ..discovery.lobby_matcher import LobbyMatcher
from ..discovery.auto_lobby_room import AutoLobbyRoom
from ..discovery.skin_collector import SkinCollector, PartySkinData
from .party_state import PartyState
from .party_storage import PartyStorage

log = get_logger()

LOBBY_CHECK_INTERVAL = 2.0
SKIN_BROADCAST_INTERVAL = 1.0
SKIN_RESYNC_INTERVAL = 10.0
RECONNECT_MAX_DELAY = 15.0


class PartyManager:
    """Main orchestrator for party mode."""

    def __init__(
        self,
        lcu: LCU,
        state: SharedState,
        injection_manager=None,
        storage: Optional[PartyStorage] = None,
    ):
        self.lcu = lcu
        self.state = state
        self.injection_manager = injection_manager
        self._storage = storage or PartyStorage()

        self.party_state = PartyState()
        self.party_state.automatic = PARTY_MODE_ALWAYS_ON

        # Networking
        self._my_key: Optional[bytes] = None
        self._my_token: Optional[PartyToken] = None
        self._relay: Optional[PartyRelay] = None
        self._active_room_key: Optional[str] = None
        self._active_room_host_id: Optional[int] = None
        self._active_room_host_key: Optional[bytes] = None
        self._personal_room_key: Optional[str] = None
        self._auto_lobby_room = AutoLobbyRoom()
        self._ignored_peer_ids = set()
        self._trusted_peer_names: Dict[int, str] = {}
        self._relay_lock = asyncio.Lock()
        self._next_reconnect_at = 0.0
        self._reconnect_delay = 1.0

        # Discovery
        self._lobby_matcher: Optional[LobbyMatcher] = None
        self._skin_collector: Optional[SkinCollector] = None

        # Background tasks
        self._running = False
        self._restore_attempted = False
        self._enable_lock = asyncio.Lock()
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
        """Enable Party Mode and restore the last approved room."""
        async with self._enable_lock:
            if self.party_state.enabled:
                return self.party_state.my_token or ""

            log.info("[PARTY] Enabling party mode...")

            try:
                self._lobby_matcher = LobbyMatcher(self.lcu, self.state)
                self._skin_collector = SkinCollector(self.state)

                my_summoner_id = self._lobby_matcher.get_my_summoner_id()
                my_summoner_name = self._lobby_matcher.get_my_summoner_name()

                if not my_summoner_id:
                    raise RuntimeError(
                        "Failed to get summoner ID - is League client running?"
                    )

                self.party_state.my_summoner_id = my_summoner_id
                self.party_state.my_summoner_name = my_summoner_name

                account = self._storage.load_account(my_summoner_id)
                self._my_key = self._load_or_create_personal_key(account)
                self.party_state.enabled = True
                self.party_state.auto_reconnect = True
                self.party_state.automatic = PARTY_MODE_ALWAYS_ON
                if PARTY_MODE_ALWAYS_ON:
                    self._ignored_peer_ids = set()
                    self._trusted_peer_names = {}
                else:
                    self._ignored_peer_ids = {
                        int(value) for value in account.get(
                            "ignored_peers", []
                        )
                    }
                    self._trusted_peer_names = {
                        int(peer_id): peer_data.get(
                            "summoner_name", "Unknown"
                        )
                        for peer_id, peer_data in account.get(
                            "trusted_peers", {}
                        ).items()
                    }

                own_room_key = compute_room_key(my_summoner_id, self._my_key)
                self._personal_room_key = own_room_key

                if PARTY_MODE_ALWAYS_ON:
                    updated_at = float(
                        account.get("auto_room_updated_at") or 0
                    )
                    if (
                        account.get("auto_room_key")
                        and time.time() - updated_at
                        <= PARTY_AUTO_ROOM_MAX_AGE_SECONDS
                    ):
                        self._auto_lobby_room.restore(
                            account.get("auto_room_key"),
                            account.get("auto_lobby_members", []),
                        )

                    auto_room_key = self._auto_lobby_room.update(
                        getattr(self.state, "phase", ""),
                        self._lobby_matcher.get_lobby_summoner_ids(),
                        my_summoner_id,
                    )
                    self._active_room_key = auto_room_key or own_room_key
                    self._active_room_host_id = my_summoner_id
                    self._active_room_host_key = self._my_key
                    self.party_state.auto_room_active = bool(auto_room_key)
                else:
                    saved_room_key = account.get("active_room_key")
                    saved_host_id = int(
                        account.get("active_room_host_id") or my_summoner_id
                    )
                    saved_host_key = self._decode_stored_key(
                        account.get("active_room_host_key")
                    )
                    if (
                        saved_room_key
                        and saved_host_key
                        and compute_room_key(saved_host_id, saved_host_key)
                        == saved_room_key
                    ):
                        self._active_room_key = saved_room_key
                        self._active_room_host_id = saved_host_id
                        self._active_room_host_key = saved_host_key
                    else:
                        self._active_room_key = own_room_key
                        self._active_room_host_id = my_summoner_id
                        self._active_room_host_key = self._my_key

                # The displayed invitation always points at the room we are
                # actually using. Friends-of-friends therefore join the same
                # group instead of accidentally creating a split room.
                self._refresh_group_token()
                token_str = self.party_state.my_token

                if not PARTY_MODE_ALWAYS_ON:
                    for peer_id, peer_data in account.get(
                        "trusted_peers", {}
                    ).items():
                        sid = int(peer_id)
                        if sid in self._ignored_peer_ids:
                            continue
                        self.party_state.add_peer(
                            sid,
                            summoner_name=peer_data.get(
                                "summoner_name", "Unknown"
                            ),
                            connected=False,
                            connection_state="connecting",
                        )

                own_key_b64 = base64.urlsafe_b64encode(self._my_key).decode("ascii")
                self._storage.update_account(
                    my_summoner_id,
                    auto_enable=True,
                    own_key=own_key_b64,
                    active_room_key=(
                        None
                        if PARTY_MODE_ALWAYS_ON
                        else (
                            self._active_room_key
                            if self._active_room_key != own_room_key
                            else None
                        )
                    ),
                    active_room_host_id=(
                        my_summoner_id
                        if PARTY_MODE_ALWAYS_ON
                        else self._active_room_host_id
                    ),
                    active_room_host_key=(
                        None
                        if PARTY_MODE_ALWAYS_ON
                        or self._active_room_key == own_room_key
                        else base64.urlsafe_b64encode(
                            self._active_room_host_key
                        ).decode("ascii")
                    ),
                    auto_room_key=(
                        self._auto_lobby_room.active_room_key
                        if PARTY_MODE_ALWAYS_ON
                        else account.get("auto_room_key")
                    ),
                    auto_lobby_members=(
                        list(self._auto_lobby_room.lobby_members)
                        if PARTY_MODE_ALWAYS_ON
                        else account.get("auto_lobby_members", [])
                    ),
                    auto_room_updated_at=(
                        time.time()
                        if PARTY_MODE_ALWAYS_ON
                        and self._auto_lobby_room.active_room_key
                        else account.get("auto_room_updated_at")
                    ),
                )

                # A temporary relay outage no longer disables Party Mode. The
                # background loop keeps retrying until the connection returns.
                await self._replace_relay(self._active_room_key)

                self._running = True
                self._lobby_check_task = asyncio.create_task(
                    self._lobby_check_loop()
                )
                self._skin_broadcast_task = asyncio.create_task(
                    self._skin_broadcast_loop()
                )

                log.info(
                    f"[PARTY] Party mode enabled with persistent room "
                    f"{self._active_room_key[:8]}..."
                )
                self._notify_state_change()
                return token_str

            except Exception as e:
                log.error(f"[PARTY] Failed to enable party mode: {e}")
                await self.disable(persist=False)
                raise RuntimeError(f"Failed to enable party mode: {e}")

    async def restore_if_configured(self) -> bool:
        """Auto-enable once for the current account when it was enabled before."""
        if self.party_state.enabled:
            return True
        if self._restore_attempted:
            return False

        matcher = LobbyMatcher(self.lcu, self.state)
        summoner_id = matcher.get_my_summoner_id()
        if not summoner_id:
            return False
        self._restore_attempted = True
        account = self._storage.load_account(summoner_id)
        if not PARTY_MODE_ALWAYS_ON and not account.get("auto_enable"):
            return False

        log.info("[PARTY] Starting automatic Party Mode session")
        await self.enable()
        return True

    async def disable(self, persist: bool = True):
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

        if persist and self.party_state.my_summoner_id:
            self._storage.update_account(
                self.party_state.my_summoner_id,
                auto_enable=False,
            )

        self.party_state.clear_all()
        self._my_key = None
        self._my_token = None
        self._active_room_key = None
        self._active_room_host_id = None
        self._active_room_host_key = None
        self._personal_room_key = None
        self._auto_lobby_room.clear()
        self._trusted_peer_names = {}

        log.info("[PARTY] Party mode disabled")
        self._notify_state_change()

    async def add_peer(self, token_str: str) -> Tuple[bool, Optional[str]]:
        """Approve a friend once and persist their shared relay room."""
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
                        self._remember_peer(
                            token.summoner_id,
                            member.get("summoner_name", "Unknown"),
                        )
                        return True, None

            # Check if we're already in the target room
            target_room_key = compute_room_key(token.summoner_id, token.encryption_key)
            if self._relay and self._relay.room_key == target_room_key:
                log.info("[PARTY] Already in peer's room")
                self._remember_peer(token.summoner_id)
                return True, None

            # Switch once, then remember the room across Rose restarts.
            if not await self._replace_relay(target_room_key):
                return False, "Failed to connect to relay"

            self._active_room_key = target_room_key
            self._active_room_host_id = token.summoner_id
            self._active_room_host_key = token.encryption_key
            self._refresh_group_token()
            self._remember_peer(token.summoner_id)
            self._storage.update_account(
                self.party_state.my_summoner_id,
                active_room_key=target_room_key,
                active_room_host_id=token.summoner_id,
                active_room_host_key=base64.urlsafe_b64encode(
                    token.encryption_key
                ).decode("ascii"),
            )

            log.info(f"[PARTY] Joined party room {target_room_key[:8]}...")
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

    async def remove_peer(self, summoner_id: int):
        """Forget a persistent friend and stop applying their selections."""
        my_id = self.party_state.my_summoner_id
        if my_id:
            self._storage.forget_peer(my_id, summoner_id)
        self._ignored_peer_ids.add(int(summoner_id))
        self._trusted_peer_names.pop(int(summoner_id), None)
        self.party_state.remove_peer(summoner_id)
        if self._skin_collector:
            self._skin_collector.clear_peer(summoner_id)

        # If this friend hosted the saved room, return to our own stable room.
        if (
            my_id
            and self._my_key
            and self._active_room_host_id == int(summoner_id)
            and int(summoner_id) != int(my_id)
        ):
            own_room_key = compute_room_key(my_id, self._my_key)
            self._active_room_key = own_room_key
            self._active_room_host_id = my_id
            self._active_room_host_key = self._my_key
            self._refresh_group_token()
            self._storage.update_account(
                my_id,
                active_room_key=None,
                active_room_host_id=my_id,
                active_room_host_key=None,
            )
            await self._replace_relay(own_room_key)

        self._notify_state_change()
        log.info(f"[PARTY] Forgot persistent peer {summoner_id}")

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
        self.party_state.relay_connected = bool(
            self._relay and self._relay.connected
        )
        self._reconnect_delay = 1.0
        self._next_reconnect_at = 0.0

        # Update party state with relay members (exclude ourselves)
        current_peer_ids = set()
        for member in members:
            sid = int(member.get("summoner_id", 0) or 0)
            if sid == my_id or not sid or sid in self._ignored_peer_ids:
                continue

            current_peer_ids.add(sid)
            name = member.get("summoner_name", "Unknown")
            skin = member.get("skin")
            self._remember_peer(sid, name)

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
                        custom_mod_hash=skin.get("custom_mod_hash"),
                        is_custom=bool(skin.get("is_custom")),
                    )
                    self.party_state.update_peer_skin(sid, sel)
                    self._skin_collector.update_from_peer(sel)
                except Exception as e:
                    log.debug(f"[PARTY] Failed to update peer skin: {e}")

        # Keep approved friends visible while offline. They are automatically
        # marked connected again as soon as their Rose rejoins the room.
        stale = [sid for sid in self.party_state.peers if sid not in current_peer_ids]
        for sid in stale:
            peer = self.party_state.peers[sid]
            peer.connected = False
            peer.connection_state = "connecting"
            peer.in_lobby = False
            if self._skin_collector:
                self._skin_collector.clear_peer(sid)
            log.info(f"[PARTY] Peer {sid} offline; waiting for automatic reconnect")

        self._notify_state_change()

    # ─── Background tasks ────────────────────────────────────────────────

    async def _lobby_check_loop(self):
        """Check lobby membership and repair relay connectivity."""
        while self._running:
            try:
                await asyncio.sleep(LOBBY_CHECK_INTERVAL)
                if not self._running or not self._lobby_matcher:
                    continue

                if PARTY_MODE_ALWAYS_ON:
                    await self._sync_auto_lobby_room()

                if not self._relay or not self._relay.connected:
                    self.party_state.relay_connected = False
                    await self._ensure_relay_connected()

                lobby_ids = self._lobby_matcher.get_all_summoner_ids()
                state_changed = False
                for sid in self.party_state.peers:
                    in_lobby = sid in lobby_ids
                    if self.party_state.peers[sid].in_lobby != in_lobby:
                        self.party_state.update_peer_lobby_status(sid, in_lobby)
                        state_changed = True
                        name = self.party_state.peers[sid].summoner_name
                        if in_lobby:
                            log.info(f"[PARTY] Peer {name} joined our lobby")
                        else:
                            log.info(f"[PARTY] Peer {name} left our lobby")
                if state_changed:
                    self._notify_state_change()

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.info(f"[PARTY] Lobby check error: {e}")

    async def _skin_broadcast_loop(self):
        """Broadcast skin updates when selection changes."""
        last_skin_id = None
        last_chroma_id = None
        last_custom_mod = None
        last_broadcast_at = 0.0

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
                now = time.monotonic()

                if (current_skin_id != last_skin_id or
                    current_chroma_id != last_chroma_id or
                    custom_mod_key != last_custom_mod or
                    now - last_broadcast_at >= SKIN_RESYNC_INTERVAL):
                    last_skin_id = current_skin_id
                    last_chroma_id = current_chroma_id
                    last_custom_mod = custom_mod_key
                    await self.broadcast_skin_update()
                    last_broadcast_at = now

                # The invitation displayed in the UI always remains valid.
                if self._my_token and self._my_token.time_until_expiry() < 300:
                    self._refresh_group_token()
                    self._notify_state_change()

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.info(f"[PARTY] Skin broadcast error: {e}")

    def _load_or_create_personal_key(self, account: dict) -> bytes:
        key = self._decode_stored_key(account.get("own_key"))
        if key:
            return key
        if account.get("own_key"):
            log.warning("[PARTY] Stored personal room key is invalid; rotating it")
        return secrets.token_bytes(32)

    @staticmethod
    def _decode_stored_key(encoded) -> Optional[bytes]:
        if not encoded:
            return None
        try:
            key = base64.urlsafe_b64decode(str(encoded).encode("ascii"))
            return key if len(key) == 32 else None
        except Exception:
            return None

    def _refresh_group_token(self):
        if not self._active_room_host_id or not self._active_room_host_key:
            return
        self._my_token = create_token(
            summoner_id=self._active_room_host_id,
            encryption_key=self._active_room_host_key,
        )
        self.party_state.my_token = self._my_token.encode()

    def _remember_peer(self, summoner_id: int, summoner_name: str = "Unknown"):
        sid = int(summoner_id)
        if sid in self._ignored_peer_ids:
            self._ignored_peer_ids.remove(sid)
        my_id = self.party_state.my_summoner_id
        old_name = self._trusted_peer_names.get(sid)
        resolved_name = (
            summoner_name
            if summoner_name and summoner_name != "Unknown"
            else old_name or "Unknown"
        )
        if (
            my_id
            and not PARTY_MODE_ALWAYS_ON
            and old_name != resolved_name
        ):
            self._storage.trust_peer(my_id, sid, resolved_name)
        self._trusted_peer_names[sid] = resolved_name
        if sid not in self.party_state.peers:
            self.party_state.add_peer(
                sid,
                summoner_name=resolved_name,
                connected=False,
                connection_state="connecting",
            )

    async def _sync_auto_lobby_room(self):
        """Follow the premade lobby while freezing the room during the game."""
        if (
            not self._lobby_matcher
            or not self._personal_room_key
            or not self.party_state.my_summoner_id
        ):
            return

        auto_room_key = self._auto_lobby_room.update(
            getattr(self.state, "phase", ""),
            self._lobby_matcher.get_lobby_summoner_ids(),
            self.party_state.my_summoner_id,
        )
        target_room_key = auto_room_key or self._personal_room_key
        auto_active = bool(auto_room_key)
        self.party_state.auto_room_active = auto_active

        if target_room_key == self._active_room_key:
            return

        old_room_key = self._active_room_key
        self._active_room_key = target_room_key
        self.party_state.clear_peers()
        if self._skin_collector:
            self._skin_collector.clear_all()

        self._storage.update_account(
            self.party_state.my_summoner_id,
            auto_room_key=auto_room_key,
            auto_lobby_members=list(self._auto_lobby_room.lobby_members),
            auto_room_updated_at=(time.time() if auto_active else None),
        )

        log.info(
            f"[PARTY] Automatic lobby room changed "
            f"{(old_room_key or 'none')[:8]} -> {target_room_key[:8]}"
        )
        await self._replace_relay(target_room_key)

    async def _replace_relay(self, room_key: str) -> bool:
        """Atomically replace the transport and announce our current identity."""
        async with self._relay_lock:
            if self._relay:
                await self._relay.disconnect()

            relay = PartyRelay(room_key)
            relay.set_on_members_changed(self._on_relay_members_changed)
            self._relay = relay
            self.party_state.relay_connected = False

            if not await relay.connect():
                self._schedule_reconnect()
                self._notify_state_change()
                return False

            await relay.join(
                self.party_state.my_summoner_id,
                self.party_state.my_summoner_name,
            )
            self.party_state.relay_connected = True
            self._reconnect_delay = 1.0
            self._next_reconnect_at = 0.0
            await self.broadcast_skin_update()
            self._notify_state_change()
            return True

    async def _ensure_relay_connected(self) -> bool:
        if self._relay and self._relay.connected:
            return True
        if not self._active_room_key:
            return False
        if time.monotonic() < self._next_reconnect_at:
            return False

        log.info(
            f"[PARTY] Reconnecting to persistent room "
            f"{self._active_room_key[:8]}..."
        )
        return await self._replace_relay(self._active_room_key)

    def _schedule_reconnect(self):
        self._next_reconnect_at = time.monotonic() + self._reconnect_delay
        self._reconnect_delay = min(
            self._reconnect_delay * 2.0,
            RECONNECT_MAX_DELAY,
        )

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
