import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from party.core.party_manager import PartyManager
from party.core.party_storage import PartyStorage
from party.discovery.auto_lobby_room import AutoLobbyRoom, compute_auto_room_key
from party.network.ws_relay import PartyRelay, compute_room_key
from party.protocol.token_codec import PartyToken, create_token


class DummyLCU:
    def __init__(self, summoner_id=101, name="Local"):
        self.current_summoner = {
            "summonerId": summoner_id,
            "displayName": name,
        }
        self.session = {
            "myTeam": [
                {"summonerId": summoner_id, "championId": 1},
                {"summonerId": 202, "championId": 2},
            ]
        }

    def get(self, path):
        if path == "/lol-lobby/v2/lobby":
            return {
                "members": [
                    {"summonerId": 101},
                    {"summonerId": 202},
                ]
            }
        return None


class DummyState:
    phase = "Lobby"
    locked_champ_id = None
    hovered_champ_id = None
    last_hovered_skin_id = None
    selected_chroma_id = None
    selected_custom_mod = None


class FakeRelay:
    connect_results = []
    instances = []

    def __init__(self, room_key):
        self.room_key = room_key
        self.connected = False
        self.members = []
        self.callback = None
        self.joined = None
        self.sent_skins = []
        type(self).instances.append(self)

    def set_on_members_changed(self, callback):
        self.callback = callback

    async def connect(self, timeout=15.0):
        result = (
            type(self).connect_results.pop(0)
            if type(self).connect_results
            else True
        )
        self.connected = result
        return result

    async def join(self, summoner_id, summoner_name):
        self.joined = (summoner_id, summoner_name)

    async def send_skin(self, skin):
        self.sent_skins.append(skin)

    async def disconnect(self):
        self.connected = False
        self.members = []


class PartyReliabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = PartyStorage(
            Path(self.temp_dir.name) / "party_mode.json"
        )
        FakeRelay.connect_results = []
        FakeRelay.instances = []
        self.relay_patch = patch(
            "party.core.party_manager.PartyRelay",
            FakeRelay,
        )
        self.relay_patch.start()
        self.always_on_patch = patch(
            "party.core.party_manager.PARTY_MODE_ALWAYS_ON",
            False,
        )
        self.always_on_patch.start()

    def tearDown(self):
        self.always_on_patch.stop()
        self.relay_patch.stop()
        self.temp_dir.cleanup()

    async def test_pair_once_restores_same_room_after_restart(self):
        first = PartyManager(
            DummyLCU(),
            DummyState(),
            storage=self.storage,
        )
        await first.enable()

        friend_key = b"f" * 32
        friend_token = create_token(202, friend_key).encode()
        success, error = await first.add_peer(friend_token)
        self.assertTrue(success)
        self.assertIsNone(error)
        expected_room = compute_room_key(202, friend_key)
        self.assertEqual(first._active_room_key, expected_room)
        await first.disable(persist=False)

        restarted = PartyManager(
            DummyLCU(),
            DummyState(),
            storage=self.storage,
        )
        restored = await restarted.restore_if_configured()
        self.assertTrue(restored)
        self.assertTrue(restarted.enabled)
        self.assertEqual(restarted._active_room_key, expected_room)
        self.assertEqual(restarted._relay.room_key, expected_room)
        self.assertIn(202, restarted.party_state.peers)
        await restarted.disable(persist=False)

    async def test_personal_invitation_keeps_same_room_key(self):
        first = PartyManager(
            DummyLCU(),
            DummyState(),
            storage=self.storage,
        )
        token_one = PartyToken.decode(await first.enable())
        room_one = compute_room_key(token_one.summoner_id, token_one.encryption_key)
        await first.disable(persist=False)

        second = PartyManager(
            DummyLCU(),
            DummyState(),
            storage=self.storage,
        )
        token_two = PartyToken.decode(await second.enable())
        room_two = compute_room_key(token_two.summoner_id, token_two.encryption_key)
        self.assertEqual(token_one.encryption_key, token_two.encryption_key)
        self.assertEqual(room_one, room_two)
        await second.disable(persist=False)

    async def test_group_invitation_keeps_friends_of_friends_in_same_room(self):
        host = PartyManager(
            DummyLCU(101, "Host"),
            DummyState(),
            storage=self.storage,
        )
        host_token = await host.enable()
        host_invitation = PartyToken.decode(host_token)
        group_room = compute_room_key(
            host_invitation.summoner_id,
            host_invitation.encryption_key,
        )

        friend = PartyManager(
            DummyLCU(202, "Friend"),
            DummyState(),
            storage=self.storage,
        )
        await friend.enable()
        success, _ = await friend.add_peer(host_token)
        self.assertTrue(success)
        forwarded = PartyToken.decode(friend.my_token_str)
        self.assertEqual(
            compute_room_key(
                forwarded.summoner_id,
                forwarded.encryption_key,
            ),
            group_room,
        )

        third = PartyManager(
            DummyLCU(303, "Third"),
            DummyState(),
            storage=self.storage,
        )
        await third.enable()
        success, _ = await third.add_peer(friend.my_token_str)
        self.assertTrue(success)
        self.assertEqual(third._active_room_key, group_room)

        await host.disable(persist=False)
        await friend.disable(persist=False)
        await third.disable(persist=False)

    async def test_relay_failure_reconnects_without_disabling_party(self):
        FakeRelay.connect_results = [False, True]
        manager = PartyManager(
            DummyLCU(),
            DummyState(),
            storage=self.storage,
        )
        await manager.enable()
        self.assertTrue(manager.enabled)
        self.assertFalse(manager.party_state.relay_connected)

        manager._next_reconnect_at = 0.0
        connected = await manager._ensure_relay_connected()
        self.assertTrue(connected)
        self.assertTrue(manager.party_state.relay_connected)
        self.assertEqual(FakeRelay.instances[-1].joined, (101, "Local"))
        await manager.disable(persist=False)

    async def test_forgetting_host_returns_to_personal_room(self):
        manager = PartyManager(
            DummyLCU(),
            DummyState(),
            storage=self.storage,
        )
        own_token = PartyToken.decode(await manager.enable())
        own_room = compute_room_key(101, own_token.encryption_key)

        friend_token = create_token(202, b"x" * 32).encode()
        success, _ = await manager.add_peer(friend_token)
        self.assertTrue(success)
        await manager.remove_peer(202)

        self.assertEqual(manager._active_room_key, own_room)
        account = self.storage.load_account(101)
        self.assertNotIn("202", account["trusted_peers"])
        self.assertIn(202, account["ignored_peers"])
        await manager.disable(persist=False)

    async def test_common_custom_mod_metadata_survives_relay_update(self):
        manager = PartyManager(
            DummyLCU(),
            DummyState(),
            storage=self.storage,
        )
        await manager.enable()
        member = {
            "summoner_id": 202,
            "summoner_name": "Friend",
            "skin": {
                "champion_id": 2,
                "skin_id": 2001,
                "custom_mod_hash": "abcdef0123456789",
                "is_custom": True,
            },
        }
        manager._relay.members = [member]
        manager._on_relay_members_changed([member])
        selection = manager.party_state.peers[202].skin_selection
        self.assertEqual(selection.custom_mod_hash, "abcdef0123456789")
        self.assertTrue(selection.is_custom)

        with patch.object(
            PartyManager,
            "find_local_mod_by_hash",
            return_value="skins/2/shared.fantome",
        ):
            skins = manager.get_party_skins()
        self.assertEqual(len(skins), 1)
        self.assertEqual(
            skins[0].custom_mod_path,
            "skins/2/shared.fantome",
        )
        await manager.disable(persist=False)


class AutomaticLobbyRoomTests(unittest.TestCase):
    def test_same_premade_members_always_derive_same_room(self):
        expected = compute_auto_room_key([303, 101, 202])
        self.assertEqual(expected, compute_auto_room_key([202, 303, 101]))
        self.assertEqual(expected, compute_auto_room_key([101, 202, 303, 202]))

    def test_room_is_frozen_across_matchmaking_and_champion_select(self):
        room = AutoLobbyRoom()
        lobby_room = room.update("Lobby", [101, 202], 101)
        self.assertIsNotNone(lobby_room)

        # myTeam can contain matchmade strangers, but is intentionally never
        # used to replace the premade room during these phases.
        self.assertEqual(room.update("Matchmaking", [], 101), lobby_room)
        self.assertEqual(
            room.update("ChampSelect", [101, 202, 303, 404, 505], 101),
            lobby_room,
        )
        self.assertEqual(room.update("InProgress", [], 101), lobby_room)

    def test_lobby_membership_change_moves_everyone_to_new_room(self):
        room = AutoLobbyRoom()
        first = room.update("Lobby", [101, 202], 101)
        second = room.update("Lobby", [101, 202, 303], 101)
        self.assertNotEqual(first, second)
        self.assertEqual(second, compute_auto_room_key([101, 202, 303]))

    def test_solo_lobby_and_end_of_game_clear_automatic_room(self):
        room = AutoLobbyRoom()
        room.update("Lobby", [101, 202], 101)
        self.assertIsNone(room.update("EndOfGame", [], 101))
        self.assertIsNone(room.update("Lobby", [101], 101))

    def test_saved_room_can_be_restored_mid_champion_select(self):
        room = AutoLobbyRoom()
        expected = compute_auto_room_key([101, 202])
        room.restore(expected, [101, 202])
        self.assertEqual(room.update("ChampSelect", [], 101), expected)

    def test_duplicate_restart_socket_prefers_member_with_skin(self):
        members = PartyRelay._deduplicate_members([
            {"summoner_id": 101, "summoner_name": "Old"},
            {
                "summoner_id": 101,
                "summoner_name": "New",
                "skin": {"champion_id": 1, "skin_id": 1001},
            },
            {"summoner_id": 202, "summoner_name": "Friend"},
        ])
        self.assertEqual(len(members), 2)
        local = next(m for m in members if m["summoner_id"] == 101)
        self.assertEqual(local["skin"]["skin_id"], 1001)


class MutableLobbyLCU(DummyLCU):
    def __init__(self, summoner_id=101, name="Local", lobby_ids=None):
        super().__init__(summoner_id, name)
        self.lobby_ids = list(lobby_ids or [summoner_id])

    def get(self, path):
        if path == "/lol-lobby/v2/lobby":
            return {
                "members": [
                    {"summonerId": value}
                    for value in self.lobby_ids
                ]
            }
        return None


class AutomaticPartyManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = PartyStorage(
            Path(self.temp_dir.name) / "party_mode.json"
        )
        FakeRelay.connect_results = []
        FakeRelay.instances = []
        self.relay_patch = patch(
            "party.core.party_manager.PartyRelay",
            FakeRelay,
        )
        self.relay_patch.start()

    def tearDown(self):
        self.relay_patch.stop()
        self.temp_dir.cleanup()

    async def test_always_on_starts_without_saved_setting_or_token_action(self):
        lcu = MutableLobbyLCU(101, "Local", [101, 202])
        manager = PartyManager(lcu, DummyState(), storage=self.storage)
        restored = await manager.restore_if_configured()
        self.assertTrue(restored)
        self.assertTrue(manager.enabled)
        self.assertTrue(manager.party_state.automatic)
        self.assertTrue(manager.party_state.auto_room_active)
        self.assertEqual(
            manager._active_room_key,
            compute_auto_room_key([101, 202]),
        )
        await manager.disable(persist=False)

    async def test_two_clients_in_same_lobby_choose_identical_room(self):
        first = PartyManager(
            MutableLobbyLCU(101, "First", [101, 202]),
            DummyState(),
            storage=self.storage,
        )
        second = PartyManager(
            MutableLobbyLCU(202, "Second", [202, 101]),
            DummyState(),
            storage=self.storage,
        )
        await first.enable()
        await second.enable()
        self.assertEqual(first._active_room_key, second._active_room_key)
        self.assertEqual(
            first._active_room_key,
            compute_auto_room_key([101, 202]),
        )
        await first.disable(persist=False)
        await second.disable(persist=False)

    async def test_room_does_not_change_when_premade_endpoint_disappears(self):
        state = DummyState()
        state.phase = "Lobby"
        lcu = MutableLobbyLCU(101, "Local", [101, 202])
        manager = PartyManager(lcu, state, storage=self.storage)
        await manager.enable()
        expected = manager._active_room_key

        state.phase = "ChampSelect"
        lcu.lobby_ids = []
        await manager._sync_auto_lobby_room()
        self.assertEqual(manager._active_room_key, expected)
        await manager.disable(persist=False)

    async def test_return_to_solo_lobby_leaves_shared_room(self):
        state = DummyState()
        state.phase = "Lobby"
        lcu = MutableLobbyLCU(101, "Local", [101, 202])
        manager = PartyManager(lcu, state, storage=self.storage)
        await manager.enable()
        shared_room = manager._active_room_key

        lcu.lobby_ids = [101]
        await manager._sync_auto_lobby_room()
        self.assertNotEqual(manager._active_room_key, shared_room)
        self.assertEqual(manager._active_room_key, manager._personal_room_key)
        self.assertFalse(manager.party_state.auto_room_active)
        await manager.disable(persist=False)


if __name__ == "__main__":
    unittest.main()
