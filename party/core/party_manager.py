#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Party Manager
Orchestrator for party mode skin sharing via WebSocket relay.

Everyone keeps their own room open and also joins the rooms of the friends
whose token they paste. Members advertise the rooms they're in, so everyone
linked to a party ends up in all of its rooms: any member's token works,
friends can be added one by one, and older Rose versions (one room each)
still see everybody.
"""

import asyncio
import re
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

from lcu import LCU
from state import SharedState
from utils.core.i18n import Text
from utils.core.logging import get_logger

from ..network.ws_relay import PartyRelay, compute_room_key
from ..protocol.token_codec import PartyToken, create_token
from ..protocol.message_types import SkinSelection
from ..discovery.custom_mods import get_mods_root, mod_hashes
from ..discovery.lobby_matcher import LobbyMatcher
from ..discovery.skin_collector import SkinCollector, PartySkinData
from .party_state import PartyState
from .party_storage import load_party_key

log = get_logger()

LOBBY_CHECK_INTERVAL = 2.0
SKIN_BROADCAST_INTERVAL = 1.0
# How long add_peer waits for the token's owner to show up
PEER_WAIT_TIMEOUT = 4.0
# Most rooms we stay in at once (ours included)
MAX_ROOMS = 8
# Before retrying an advertised room that couldn't be reached
FOLLOW_RETRY_S = 60.0
_ROOM_KEY_RE = re.compile(r"^[0-9a-f]{32}$")


def _to_int(value) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _removed(member: dict, summoner_id: Optional[int]) -> bool:
    """Whether this member's state says they removed that summoner."""
    skin = member.get("skin")
    removed = skin.get("removed") if isinstance(skin, dict) else None
    return isinstance(removed, list) and summoner_id is not None and summoner_id in removed


def _state_time(member: dict) -> int:
    """When a member's state was sent: 0 for older Rose versions, -1 without state."""
    skin = member.get("skin")
    if not isinstance(skin, dict):
        return -1
    return _to_int(skin.get("sent_at")) or 0


class PartyManager:
    """Main orchestrator for party mode."""

    def __init__(self, lcu: LCU, state: SharedState, injection_manager=None):
        self.lcu = lcu
        self.state = state
        self.injection_manager = injection_manager

        self.party_state = PartyState()

        # Networking
        self._my_key: Optional[bytes] = None
        self._home_room: Optional[str] = None
        self._relays: Dict[str, PartyRelay] = {}
        self._unreachable_rooms: Dict[str, float] = {}

        # Our skin pick and the full state last sent to our rooms
        self._skin_state: Optional[dict] = None
        self._published_state: Optional[dict] = None

        # Peers removed by the user (until they're added again)
        self._ignored_peers: Set[int] = set()

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
        return self._fresh_token()

    def set_callbacks(
        self,
        on_state_change: Optional[Callable[[PartyState], None]] = None,
        on_peer_update: Optional[Callable[[int, dict], None]] = None,
    ):
        self._on_state_change = on_state_change
        self._on_peer_update = on_peer_update

    async def enable(self) -> str:
        """Enable party mode: open our room and return our token."""
        if self.party_state.enabled:
            return self._fresh_token() or ""

        log.info("[PARTY] Enabling party mode...")

        try:
            self._lobby_matcher = LobbyMatcher(self.lcu, self.state)
            self._skin_collector = SkinCollector(self.state)

            my_summoner_id = self._lobby_matcher.get_my_summoner_id()
            my_summoner_name = self._lobby_matcher.get_my_summoner_name()

            if not my_summoner_id:
                raise RuntimeError("Couldn't read your summoner ID - is the League client running?")

            self.party_state.my_summoner_id = my_summoner_id
            self.party_state.my_summoner_name = my_summoner_name

            # Same key every session, so the token friends already have keeps working
            self._my_key = load_party_key(my_summoner_id)
            self._home_room = compute_room_key(my_summoner_id, self._my_key)
            self._running = True

            error = await self._join_room(self._home_room)
            if error:
                raise RuntimeError(Text("Couldn't reach the party server: {error}", error=error))

            self.party_state.enabled = True
            self.party_state.connection = "online"
            self.party_state.my_token = self._fresh_token()

            self._lobby_check_task = asyncio.create_task(self._lobby_check_loop())
            self._skin_broadcast_task = asyncio.create_task(self._skin_broadcast_loop())

            log.info(f"[PARTY] Party mode enabled. Token: {self.party_state.my_token[:20]}...")
            self._notify_state_change()
            return self.party_state.my_token

        except Exception as e:
            log.error(f"[PARTY] Failed to enable party mode: {e}")
            await self.disable()
            raise RuntimeError(e.args[0] if e.args else str(e)) from e

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

        relays = list(self._relays.values())
        self._relays.clear()
        if relays:
            await asyncio.gather(*(relay.disconnect() for relay in relays), return_exceptions=True)

        self._unreachable_rooms.clear()
        self._ignored_peers.clear()
        self._skin_state = None
        self._published_state = None
        self.party_state.clear_all()
        self._my_key = None
        self._home_room = None

        log.info("[PARTY] Party mode disabled")
        self._notify_state_change()

    async def add_peer(self, token_str: str) -> Tuple[bool, str]:
        """Join a friend's party by pasting their token.

        Returns:
            (success, message for the user)
        """
        if not self.party_state.enabled:
            return False, "Party mode is not enabled"

        token_str = "".join(token_str.split())

        try:
            token = PartyToken.decode(token_str)
        except ValueError as e:
            log.info(f"[PARTY] Invalid token: {e}")
            return False, "That's not a valid party token. Copy the whole token (it starts with ROSE:)."

        if token.summoner_id == self.party_state.my_summoner_id:
            return False, "That's your own token - send it to your friends instead"

        log.info(f"[PARTY] Joining party of summoner {token.summoner_id}")
        if token.summoner_id in self._ignored_peers:
            # Removed earlier: show them again, and tell them (our state listed them as removed)
            self._ignored_peers.discard(token.summoner_id)
            self._refresh_peers()
            await self._publish_state()
        room_key = compute_room_key(token.summoner_id, token.encryption_key)

        if room_key not in self._relays:
            if len(self._relays) >= MAX_ROOMS:
                return False, "You're linked to too many parties. Disable and re-enable party mode, then try again."
            error = await self._join_room(room_key)
            if error:
                return False, Text("Couldn't reach the party server: {error}", error=error)

        name = await self._wait_for_peer(token.summoner_id, PEER_WAIT_TIMEOUT)
        if not name and token.summoner_id in self._peers_who_removed_us():
            return False, "This friend removed you from their party - they need to add your token back"
        if name:
            log.info(f"[PARTY] Connected to {name}")
            return True, Text("Connected to {name}", name=name)

        log.info(f"[PARTY] Joined room {room_key[:8]}, but summoner {token.summoner_id} isn't in it")
        return True, (
            "Joined, but your friend isn't online in party mode right now. "
            "They'll show up here as soon as their party mode is on."
        )

    async def remove_peer(self, summoner_id: int):
        """Hide a peer and ignore their skins (pasting their token brings them back).

        Our state tells them, so they stop showing us and using our skins too.
        """
        self._ignored_peers.add(summoner_id)
        self.party_state.remove_peer(summoner_id)
        if self._skin_collector:
            self._skin_collector.clear_peer(summoner_id)
        self._notify_state_change()
        log.info(f"[PARTY] Removed peer {summoner_id}")
        await self._publish_state()

    def get_party_skins(self) -> List[PartySkinData]:
        """Get friends' skin selections for injection (last known ones while reconnecting)."""
        if not self.enabled or not self._lobby_matcher or not self._skin_collector:
            return []

        team_champions, team_champion_ids = self._lobby_matcher.get_team_info()

        return self._skin_collector.collect_relay_skins(
            members=[member for member, _ in self._merged_members().values()],
            my_summoner_id=self.party_state.my_summoner_id,
            team_champions=team_champions,
            team_champion_ids=team_champion_ids,
            my_champion_id=self.state.locked_champ_id or self.state.hovered_champ_id,
        )

    def get_state_dict(self) -> dict:
        if self.party_state.enabled:
            # Fresh timestamp: Rose 1.3.1 and older reject tokens older than an hour
            self.party_state.my_token = self._fresh_token()
        return self.party_state.to_dict()

    def _fresh_token(self) -> Optional[str]:
        if not self._my_key or not self.party_state.my_summoner_id:
            return None
        return create_token(
            summoner_id=self.party_state.my_summoner_id,
            encryption_key=self._my_key,
        ).encode()

    # ─── Rooms ───────────────────────────────────────────────────────────

    def _add_relay(self, room_key: str) -> PartyRelay:
        relay = PartyRelay(
            room_key,
            self.party_state.my_summoner_id,
            self.party_state.my_summoner_name,
        )
        relay.set_callbacks(
            on_members_changed=self._on_relay_members_changed,
            on_connection_changed=self._on_relay_connection_changed,
        )
        self._relays[room_key] = relay
        return relay

    async def _connect_relay(self, relay: PartyRelay) -> Optional[str]:
        """Connect a registered room. Returns an error message on failure."""
        # Send our current state along with the join
        await relay.send_state(self._published_state)
        connected = await relay.connect()

        if not self._running or self._relays.get(relay.room_key) is not relay:
            # Party mode was turned off meanwhile
            await relay.disconnect()
            return "party mode was turned off"
        if not connected:
            del self._relays[relay.room_key]
            return relay.last_error or "unknown error"

        self._unreachable_rooms.pop(relay.room_key, None)
        # The room list changed: tell every room
        await self._publish_state()
        return None

    async def _join_room(self, room_key: str) -> Optional[str]:
        """Join a room (no-op if we're already in it). Returns an error message on failure."""
        if room_key in self._relays:
            return None
        return await self._connect_relay(self._add_relay(room_key))

    async def _follow_room(self, relay: PartyRelay):
        error = await self._connect_relay(relay)
        if error and self._running:
            self._unreachable_rooms[relay.room_key] = time.monotonic()
            log.warning(f"[PARTY] Could not join room {relay.room_key[:8]}: {error}")

    def _follow_advertised_rooms(self):
        """Join the rooms our party members are in, so the whole party shares every room."""
        if not self._running:
            return

        now = time.monotonic()
        for member, _ in self._merged_members().values():
            skin = member.get("skin")
            rooms = skin.get("rooms") if isinstance(skin, dict) else None
            if not isinstance(rooms, list):
                continue

            for room_key in rooms[:MAX_ROOMS]:
                if not isinstance(room_key, str) or not _ROOM_KEY_RE.match(room_key):
                    continue
                if room_key in self._relays:
                    continue
                failed_at = self._unreachable_rooms.get(room_key)
                if failed_at is not None and now - failed_at < FOLLOW_RETRY_S:
                    continue
                if len(self._relays) >= MAX_ROOMS:
                    log.warning(f"[PARTY] Already in {MAX_ROOMS} rooms, not joining more")
                    return

                log.info(f"[PARTY] Joining room {room_key[:8]} shared by {member.get('summoner_name')}")
                asyncio.create_task(self._follow_room(self._add_relay(room_key)))

    async def _publish_state(self):
        """Send our state (skin pick + rooms) to every room we're in."""
        state = dict(self._skin_state or {})
        if len(self._relays) > 1:
            # Advertise our rooms so the rest of the party joins them too
            state["rooms"] = sorted(self._relays)[:MAX_ROOMS]
        if self._ignored_peers:
            # The friends we removed hide us too (see _merged_members)
            state["removed"] = sorted(self._ignored_peers)
        if state:
            state["sent_at"] = int(time.time() * 1000)
        else:
            state = None

        self._published_state = state
        relays = list(self._relays.values())
        if relays:
            await asyncio.gather(*(relay.send_state(state) for relay in relays), return_exceptions=True)

    def _merged_members(self) -> Dict[int, Tuple[dict, bool]]:
        """Members of all our rooms, one entry per summoner, with whether
        they're seen in a connected room.

        The newest state wins, so a stale copy (a connection the relay hasn't
        dropped yet, or a room that hasn't received the update yet) is ignored.
        """
        my_id = self.party_state.my_summoner_id
        merged: Dict[int, Tuple[dict, bool]] = {}

        for relay in list(self._relays.values()):
            for member in relay.members:
                sid = _to_int(member.get("summoner_id"))
                if not sid or sid == my_id or sid in self._ignored_peers:
                    continue
                previous = merged.get(sid)
                if previous is None:
                    merged[sid] = (member, relay.connected)
                    continue
                newest = member if _state_time(member) > _state_time(previous[0]) else previous[0]
                merged[sid] = (newest, previous[1] or relay.connected)

        # A friend who removed us is gone for us too, until they add us back
        return {sid: entry for sid, entry in merged.items() if not _removed(entry[0], my_id)}

    def _peers_who_removed_us(self) -> Set[int]:
        my_id = self.party_state.my_summoner_id
        return {
            _to_int(member.get("summoner_id"))
            for relay in list(self._relays.values())
            for member in relay.members
            if _removed(member, my_id)
        }

    async def _wait_for_peer(self, summoner_id: int, timeout: float) -> Optional[str]:
        """Wait until a summoner shows up in one of our rooms; returns their name."""
        deadline = time.monotonic() + timeout
        while True:
            entry = self._merged_members().get(summoner_id)
            if entry:
                return str(entry[0].get("summoner_name") or "your friend")
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.2)

    # ─── Relay callbacks ─────────────────────────────────────────────────

    def _on_relay_members_changed(self, relay: PartyRelay):
        """Called by a relay when its member list changes."""
        self._refresh_peers()
        self._follow_advertised_rooms()

    def _on_relay_connection_changed(self, relay: PartyRelay):
        """Called by a relay when its connection drops or comes back."""
        if self.party_state.enabled:
            self._refresh_peers()

    def _refresh_peers(self):
        """Rebuild the peer list shown in the UI from all our rooms."""
        merged = self._merged_members()

        for sid, (member, connected) in merged.items():
            name = str(member.get("summoner_name") or "Unknown")
            if sid not in self.party_state.peers:
                log.info(f"[PARTY] {name} joined the party")
            self.party_state.add_peer(
                sid,
                summoner_name=name,
                connected=connected,
                connection_state="connected" if connected else "reconnecting",
            )

            selection = self._selection_from_member(sid, name, member)
            if selection:
                self.party_state.update_peer_skin(sid, selection)
                if self._skin_collector:
                    self._skin_collector.update_from_peer(selection)
            else:
                self.party_state.clear_peer_skin(sid)

        for sid in [sid for sid in list(self.party_state.peers) if sid not in merged]:
            name = self.party_state.peers[sid].summoner_name
            self.party_state.remove_peer(sid)
            if self._skin_collector:
                self._skin_collector.clear_peer(sid)
            log.info(f"[PARTY] {name} left the party")

        if self.party_state.enabled:
            home = self._relays.get(self._home_room)
            self.party_state.connection = "online" if home and home.connected else "reconnecting"

        self._notify_state_change()

    @staticmethod
    def _selection_from_member(sid: int, name: str, member: dict) -> Optional[SkinSelection]:
        skin = member.get("skin")
        if not isinstance(skin, dict):
            return None
        champion_id = _to_int(skin.get("champion_id"))
        skin_id = _to_int(skin.get("skin_id"))
        if not champion_id or not skin_id:
            return None
        return SkinSelection(
            summoner_id=sid,
            summoner_name=name,
            champion_id=champion_id,
            skin_id=skin_id,
            chroma_id=_to_int(skin.get("chroma_id")),
        )

    # ─── Background tasks ────────────────────────────────────────────────

    async def _lobby_check_loop(self):
        """Check lobby membership and update peer status."""
        while self._running:
            try:
                await asyncio.sleep(LOBBY_CHECK_INTERVAL)
                if not self._running or not self._lobby_matcher:
                    continue

                # LCU requests block: keep them off the event loop
                lobby_ids = await asyncio.to_thread(self._lobby_matcher.get_all_summoner_ids)
                changed = False
                for sid, peer in list(self.party_state.peers.items()):
                    in_lobby = sid in lobby_ids
                    if peer.in_lobby != in_lobby:
                        self.party_state.update_peer_lobby_status(sid, in_lobby)
                        changed = True
                        if in_lobby:
                            log.info(f"[PARTY] Peer {peer.summoner_name} joined our lobby")
                        else:
                            log.info(f"[PARTY] Peer {peer.summoner_name} left our lobby")
                if changed:
                    self._notify_state_change()

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.info(f"[PARTY] Lobby check error: {e}")

    async def _skin_broadcast_loop(self):
        """Broadcast our pick whenever it changes."""
        while self._running:
            try:
                await asyncio.sleep(SKIN_BROADCAST_INTERVAL)
                if not self._running:
                    continue

                # Hashing a custom mod reads files: keep it off the event loop
                skin_state = await asyncio.to_thread(self._current_skin_state)
                if skin_state is None and self.state.phase != "ChampSelect":
                    # Keep our last pick until the next champion select: friends
                    # may still be injecting it while the game starts
                    continue

                if skin_state != self._skin_state:
                    self._skin_state = skin_state
                    await self._publish_state()

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.info(f"[PARTY] Skin broadcast error: {e}")

    def freeze_my_selection(self) -> None:
        """Keep sharing the skin our injection is about to apply (see SkinCollector)."""
        if self._skin_collector:
            self._skin_collector.freeze_my_selection(
                self.party_state.my_summoner_id,
                self.party_state.my_summoner_name,
            )

    def _current_skin_state(self) -> Optional[dict]:
        """Our current pick as sent to the party, or None."""
        skin_collector = self._skin_collector
        if not skin_collector:
            return None

        selection = skin_collector.get_my_selection(
            self.party_state.my_summoner_id,
            self.party_state.my_summoner_name,
        )
        if not selection:
            return None

        skin_state = {
            "champion_id": selection.champion_id,
            "skin_id": selection.skin_id,
            "chroma_id": selection.chroma_id,
        }

        # For custom mods, share content hashes instead of the files
        if selection.custom_mod_path:
            content_hash, legacy_hash = mod_hashes(get_mods_root() / selection.custom_mod_path)
            if content_hash:
                skin_state["is_custom"] = True
                skin_state["custom_mod_content_hash"] = content_hash
                if legacy_hash:
                    # Older Rose versions match archive mods by whole-file hash
                    skin_state["custom_mod_hash"] = legacy_hash

        return skin_state

    def _notify_state_change(self):
        if self._on_state_change:
            self._on_state_change(self.party_state)
