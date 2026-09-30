import asyncio
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from party.core import party_storage
from party.core.party_manager import PartyManager
from party.discovery import custom_mods
from party.discovery.skin_collector import PartySkinData, SkinCollector
from party.integration.injection_hook import PartyInjectionHook
from party.protocol.token_codec import PartyToken, create_token


def make_state(**overrides):
    state = SimpleNamespace(
        phase="ChampSelect",
        locked_champ_id=103,
        hovered_champ_id=None,
        last_hovered_skin_id=103001,
        selected_chroma_id=None,
        selected_custom_mod=None,
        historic_mode_active=False,
        historic_skin_id=None,
        random_mode_active=False,
        random_skin_id=None,
    )
    state.__dict__.update(overrides)
    return state


def member(summoner_id, name, champion_id=None, skin_id=None, **skin_fields):
    skin = None
    if champion_id is not None:
        skin = {"champion_id": champion_id, "skin_id": skin_id, **skin_fields}
    return {"summoner_id": summoner_id, "summoner_name": name, "skin": skin}


class TokenTests(unittest.TestCase):
    def test_old_tokens_are_accepted(self):
        token = create_token(summoner_id=42, encryption_key=b"k" * 32)
        token.timestamp -= 7 * 24 * 3600

        decoded = PartyToken.decode(token.encode())

        self.assertEqual(decoded.summoner_id, 42)
        self.assertEqual(decoded.encryption_key, b"k" * 32)


class PartyStorageTests(unittest.TestCase):
    def test_key_is_kept_per_summoner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(party_storage, "get_user_data_dir", return_value=Path(temp_dir)):
                first = party_storage.load_party_key(1)
                again = party_storage.load_party_key(1)
                other = party_storage.load_party_key(2)

        self.assertEqual(len(first), 32)
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)

    def test_corrupt_file_gets_a_new_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / party_storage.PARTY_KEYS_FILE).write_text("{not json", encoding="utf-8")
            with patch.object(party_storage, "get_user_data_dir", return_value=Path(temp_dir)):
                key = party_storage.load_party_key(1)
                self.assertEqual(party_storage.load_party_key(1), key)


class CustomModsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.mods_root = self.root / "mods"
        patcher = patch.object(custom_mods, "get_user_data_dir", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def _write_mod_files(self, folder: Path, wad: bytes = b"wad-bytes"):
        (folder / "WAD").mkdir(parents=True)
        (folder / "WAD" / "Ahri.wad.client").write_bytes(wad)
        (folder / "META").mkdir()
        (folder / "META" / "info.json").write_text('{"Name": "Test"}', encoding="utf-8")

    def _make_archive(self, path: Path, wad: bytes = b"wad-bytes"):
        source = self.root / f"source-{path.stem}"
        self._write_mod_files(source, wad)
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as archive:
            for file_path in source.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(source).as_posix())

    def test_archive_and_extracted_folder_share_content_hash(self):
        archive = self.root / "mod.zip"
        self._make_archive(archive)
        folder = self.root / "extracted"
        self._write_mod_files(folder)

        archive_content, archive_legacy = custom_mods.mod_hashes(archive)
        folder_content, folder_legacy = custom_mods.mod_hashes(folder)

        self.assertIsNotNone(archive_content)
        self.assertEqual(archive_content, folder_content)
        self.assertEqual(len(archive_legacy), 16)
        self.assertIsNone(folder_legacy)

    def test_finds_folder_mod_by_content_and_archive_by_legacy_hash(self):
        folder = self.mods_root / "skins" / "103000" / "My Ahri"
        self._write_mod_files(folder)
        archive = self.mods_root / "skins" / "103001" / "Old Ahri.zip"
        self._make_archive(archive, wad=b"other-wad-bytes")
        content_hash, _ = custom_mods.mod_hashes(folder)
        _, legacy_hash = custom_mods.mod_hashes(archive)

        self.assertEqual(
            custom_mods.find_local_mod(103, content_hash=content_hash),
            "skins/103000/My Ahri",
        )
        self.assertEqual(
            custom_mods.find_local_mod(103, legacy_hash=legacy_hash),
            "skins/103001/Old Ahri.zip",
        )
        # Another champion's folder is never searched
        self.assertIsNone(custom_mods.find_local_mod(11, content_hash=content_hash))


class SkinCollectorSelectionTests(unittest.TestCase):
    def pick(self, **state):
        selection = SkinCollector(make_state(**state)).get_my_selection(1, "Me")
        if not selection:
            return None
        return selection.skin_id, selection.chroma_id, selection.custom_mod_path

    def test_hovered_skin_and_chroma(self):
        self.assertEqual(self.pick(selected_chroma_id=103004), (103001, 103004, None))
        # A chroma of another skin is ignored
        self.assertEqual(self.pick(selected_chroma_id=103104), (103001, None, None))

    def test_historic_then_random_take_priority(self):
        self.assertEqual(
            self.pick(historic_mode_active=True, historic_skin_id=103015, random_mode_active=True, random_skin_id=103020),
            (103015, None, None),
        )
        self.assertEqual(self.pick(random_mode_active=True, random_skin_id=103020), (103020, None, None))

    def test_custom_mods(self):
        self.assertEqual(
            self.pick(selected_custom_mod={"skin_id": 103001, "relative_path": "skins/103000/Mod"}),
            (103001, None, "skins/103000/Mod"),
        )
        self.assertEqual(
            self.pick(historic_mode_active=True, historic_skin_id="path:skins/103000/Mod", last_hovered_skin_id=None),
            (103000, None, "skins/103000/Mod"),
        )

    def test_no_champion_no_selection(self):
        self.assertIsNone(self.pick(locked_champ_id=None))

    def test_friends_keep_the_skin_our_injection_applies(self):
        state = make_state(locked_champ_id=60025, last_hovered_skin_id=60025026, champ_select_generation=3)
        collector = SkinCollector(state)
        collector.freeze_my_selection(1, "Me")

        # Forcing the base skin: Rift Classic shows it as Morgana Classic
        state.last_hovered_skin_id = 60025301
        self.assertEqual(collector.get_my_selection(1, "Me").skin_id, 60025026)

        # Next champ select: live selection again
        state.champ_select_generation = 4
        self.assertEqual(collector.get_my_selection(1, "Me").skin_id, 60025301)


class SkinCollectorInjectionTests(unittest.TestCase):
    def collect(self, members, team_champions=None, team_champion_ids=None, my_champion_id=None):
        with patch("party.discovery.skin_collector.find_local_mod", return_value=None):
            skins = SkinCollector(make_state()).collect_relay_skins(
                members, 1, team_champions or {}, team_champion_ids, my_champion_id
            )
        return [(s.summoner_name, s.champion_id, s.skin_id) for s in skins]

    def test_only_teammates_and_one_skin_per_champion(self):
        members = [
            member(1, "Me", 103, 103001),
            member(2, "Mate", 11, 11002),
            member(3, "Other game", 22, 22003),
            member(4, "Same champ as me", 103, 103005),
            member(5, "Stale pick", 64, 64001),
            member(6, "Duplicate", 11, 11004),
            member(7, "No pick"),
        ]
        skins = self.collect(
            members,
            team_champions={2: 11, 5: 99},
            team_champion_ids={103, 11, 99, 64},
            my_champion_id=103,
        )
        self.assertEqual(skins, [("Mate", 11, 11002)])

    def test_everything_when_champion_select_is_unknown(self):
        members = [member(2, "A", 11, 11002), member(3, "B", 22, 22003)]
        self.assertEqual(self.collect(members), [("A", 11, 11002), ("B", 22, 22003)])

    def test_custom_mod_we_dont_have_falls_back_to_official_skin(self):
        members = [member(2, "A", 11, 11002, is_custom=True, custom_mod_content_hash="abc")]
        self.assertEqual(self.collect(members), [("A", 11, 11002)])

    def test_default_skins_are_skipped(self):
        members = [member(2, "A", 11, 11000), member(3, "B", 22, 22000, is_custom=True, custom_mod_content_hash="abc")]
        self.assertEqual(self.collect(members), [])


class MergedMembersTests(unittest.TestCase):
    def test_newest_state_wins_and_removed_peers_are_hidden(self):
        manager = PartyManager(Mock(), make_state())
        manager.party_state.my_summoner_id = 1
        older = member(2, "B", 11, 11001, sent_at=100)
        newer = member(2, "B", 11, 11002, sent_at=200)
        manager._relays = {
            "a" * 32: SimpleNamespace(members=[member(1, "Me"), newer], connected=False),
            "b" * 32: SimpleNamespace(members=[older, member(3, "C", 22, 22001)], connected=True),
        }
        manager._ignored_peers = {3}

        merged = manager._merged_members()

        self.assertEqual(list(merged), [2])
        state, connected = merged[2]
        self.assertEqual(state["skin"]["skin_id"], 11002)
        self.assertTrue(connected)

    def test_a_friend_who_removed_us_is_gone_for_us_too(self):
        manager = PartyManager(Mock(), make_state())
        manager.party_state.my_summoner_id = 1
        remover = member(2, "B", 11, 11002, removed=[1])
        manager._relays = {"a" * 32: SimpleNamespace(members=[member(1, "Me"), remover], connected=True)}

        self.assertEqual(manager._merged_members(), {})
        self.assertEqual(manager._peers_who_removed_us(), {2})

        # Adding us back
        remover["skin"]["removed"] = []
        self.assertEqual(list(manager._merged_members()), [2])

    def test_removing_a_friend_tells_them(self):
        manager = PartyManager(Mock(), make_state())
        manager.party_state.my_summoner_id = 1
        relay = SimpleNamespace(members=[], connected=True, sent=[])

        async def send_state(state):
            relay.sent.append(state)
        relay.send_state = send_state
        manager._relays = {"a" * 32: relay}

        asyncio.run(manager.remove_peer(2))

        self.assertEqual(relay.sent[-1]["removed"], [2])

    def test_both_removing_each_other_then_adding_back(self):
        me = PartyManager(Mock(), make_state())
        me.party_state.my_summoner_id = 1
        me.party_state.enabled = True
        friend = member(2, "B", 11, 11002, removed=[1])  # they removed us too
        relay = SimpleNamespace(members=[member(1, "Me"), friend], connected=True, sent=[], resume=Mock())

        async def send_state(state):
            relay.sent.append(state)
        relay.send_state = send_state
        me._relays = {"a" * 32: relay}
        asyncio.run(me.remove_peer(2))

        token = create_token(summoner_id=2, encryption_key=b"k" * 32).encode()
        with patch("party.core.party_manager.PEER_WAIT_TIMEOUT", 0.1),                 patch("party.core.party_manager.compute_room_key", return_value="a" * 32):
            ok, message = asyncio.run(me.add_peer(token))

        # Our side is undone right away; they still have to add us back
        self.assertNotIn("removed", relay.sent[-1] or {})
        self.assertFalse(ok)
        self.assertIn("removed you", message)

        friend["skin"]["removed"] = []  # they paste our token
        self.assertEqual(list(me._merged_members()), [2])


class FakeSocket:
    """Records what the relay sends; yields the room messages given."""

    def __init__(self, incoming=()):
        self.sent = []
        self._incoming = list(incoming)

    async def send(self, message):
        self.sent.append(message)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._incoming:
            raise StopAsyncIteration
        return self._incoming.pop(0)


class RelayQuietWhenAloneTests(unittest.TestCase):
    """Every message wakes the room on the relay, which the relay pays for:
    our state only goes out when someone else is there to get it."""

    def setUp(self):
        from party.network.ws_relay import PartyRelay
        self.relay = PartyRelay("a" * 32, 1, "Me")
        self.socket = FakeSocket()
        self.relay._ws = self.socket
        self.relay._connected = True

    def skins_sent(self):
        import json
        return [json.loads(m)["skin"] for m in self.socket.sent if json.loads(m)["type"] == "skin"]

    def test_alone_in_the_room_nothing_is_sent(self):
        self.relay.members = [member(1, "Me")]
        asyncio.run(self.relay.send_state({"skin_id": 103001}))
        self.assertEqual(self.skins_sent(), [])

    def test_a_friend_joining_gets_our_state(self):
        import json
        self.relay.members = [member(1, "Me")]
        asyncio.run(self.relay.send_state({"skin_id": 103001}))
        self.socket._incoming = [json.dumps({"type": "members", "members": [member(1, "Me"), member(2, "B")]})]

        asyncio.run(self.relay._receive(self.socket))

        self.assertEqual(self.skins_sent(), [{"skin_id": 103001}])

    def test_the_same_state_is_not_sent_twice(self):
        self.relay.members = [member(1, "Me"), member(2, "B")]
        asyncio.run(self.relay.send_state({"skin_id": 103001}))
        asyncio.run(self.relay.send_state({"skin_id": 103001}))
        asyncio.run(self.relay.send_state({"skin_id": 103002}))
        self.assertEqual(self.skins_sent(), [{"skin_id": 103001}, {"skin_id": 103002}])

    def test_a_new_connection_gets_our_state_again(self):
        self.relay.members = [member(1, "Me"), member(2, "B")]
        asyncio.run(self.relay.send_state({"skin_id": 103001}))
        self.relay._sent_state = None  # what _open does on a new connection
        asyncio.run(self.relay._deliver_state())
        self.assertEqual(self.skins_sent(), [{"skin_id": 103001}, {"skin_id": 103001}])


class RelayReconnectTests(unittest.TestCase):
    """Every connection wakes the room on the relay, which the relay pays for:
    reconnecting stops instead of looping, until the party needs the room again."""

    def setUp(self):
        from party.network import ws_relay
        self.module = ws_relay
        self.relay = ws_relay.PartyRelay("a" * 32, 1, "Me")
        self.clock = [0.0]
        self.delays = []
        self.opens = 0

        async def sleep(seconds):
            self.delays.append(seconds)
            self.clock[0] += seconds

        self.enterContext(patch.object(ws_relay.asyncio, "sleep", sleep))
        self.enterContext(patch.object(ws_relay, "time", SimpleNamespace(monotonic=lambda: self.clock[0])))

    def run_relay(self, connections, keepalive_ws=None):
        """connections: one entry per attempt, None for a refused one, else
        (seconds the connection lasts, reason it was closed with)."""
        remaining = list(connections)

        async def open_(timeout):
            self.opens += 1
            if not remaining:
                self.relay._closing = True  # the test is over
                return False
            outcome = remaining.pop(0)
            if outcome is None:
                return False
            self.relay._ws = SimpleNamespace(lasts=outcome[0], close_reason=outcome[1])
            self.relay._connected = True
            return True

        async def receive(ws):
            self.clock[0] += ws.lasts

        async def keepalive(ws):
            pass

        self.relay._open = open_
        self.relay._receive = receive
        self.relay._keepalive = keepalive
        asyncio.run(self.relay._run())

    def test_replaced_by_another_connection_stops_reconnecting(self):
        self.relay._ws = SimpleNamespace(lasts=5, close_reason="replaced")
        self.relay._connected = True
        self.run_relay([])
        self.assertEqual(self.opens, 0)
        self.assertTrue(self.relay.stopped)

    def test_connections_that_drop_at_once_back_off_then_stop(self):
        self.run_relay([(1, "")] * 10)
        self.assertEqual(self.delays, list(self.module.RECONNECT_DELAYS))
        self.assertEqual(self.opens, len(self.module.RECONNECT_DELAYS))
        self.assertTrue(self.relay.stopped)

    def test_refused_connections_stop_after_every_delay(self):
        self.run_relay([None] * 10)
        self.assertEqual(self.opens, len(self.module.RECONNECT_DELAYS))
        self.assertTrue(self.relay.stopped)

    def test_a_lasting_connection_starts_the_delays_over(self):
        self.run_relay([(1, ""), (1, ""), (400, ""), (1, "")])
        self.assertEqual(self.delays[:4], [1.0, 2.0, 5.0, 1.0])

    def test_connections_cut_every_100s_back_off_then_stop(self):
        # Cloudflare cuts a connection that carries nothing after 100s: pings
        # that never get through must not keep a room waking up all day
        self.run_relay([(100, "")] * 10)
        self.assertEqual(self.delays, list(self.module.RECONNECT_DELAYS))
        self.assertTrue(self.relay.stopped)

    def test_a_full_room_stops_at_once(self):
        async def open_(timeout):
            self.opens += 1
            self.relay._room_full = True
            return False
        self.relay._open = open_
        asyncio.run(self.relay._run())
        self.assertEqual(self.opens, 1)
        self.assertTrue(self.relay.stopped)

    def test_a_relay_asking_for_a_newer_rose_stops_at_once(self):
        async def open_(timeout):
            self.opens += 1
            self.relay._update_required = True
            return False
        self.relay._open = open_
        asyncio.run(self.relay._run())
        self.assertEqual(self.opens, 1)
        self.assertTrue(self.relay.stopped)

    def test_the_update_refusal_says_so(self):
        error = SimpleNamespace(status_code=426)
        self.assertIn("update Rose", self.module._describe_error(error))

    def test_resume_reconnects_a_stopped_room(self):
        self.relay._stopped = True
        run = Mock()
        with patch.object(self.relay, "_run", run), patch.object(self.module.asyncio, "create_task"):
            self.relay.resume()
        run.assert_called_once()
        self.assertFalse(self.relay.stopped)

    def test_resume_leaves_a_live_room_alone(self):
        with patch.object(self.module.asyncio, "create_task") as create_task:
            self.relay.resume()
        create_task.assert_not_called()


class SkinBroadcastSettleTests(unittest.TestCase):
    """Hovering skins in champ select doesn't send every second: a pick goes
    out once it settles, and the pick our injection starts with at once."""

    def run_loop(self, picks, frozen=False):
        from party.core import party_manager as module
        manager = PartyManager(Mock(), make_state())
        manager._running = True
        manager._skin_collector = Mock(is_frozen=Mock(return_value=frozen))
        remaining = list(picks)
        published = []
        clock = [0.0]

        def current():
            if len(remaining) == 1:
                manager._running = False
            return remaining.pop(0)

        async def publish():
            published.append(manager._skin_state)

        async def sleep(seconds):
            clock[0] += seconds

        manager._current_skin_state = current
        manager._publish_state = publish
        fake_time = SimpleNamespace(time=time.time, monotonic=lambda: clock[0])
        with patch.object(module, "time", fake_time), patch.object(module.asyncio, "sleep", sleep):
            asyncio.run(manager._skin_broadcast_loop())
        return published

    def test_hovering_sends_only_the_pick_that_settles(self):
        a, b, c, d = ({"skin_id": 103000 + n} for n in range(1, 5))
        self.assertEqual(self.run_loop([a, b, c, d, d, d]), [d])

    def test_the_pick_our_injection_starts_with_goes_out_at_once(self):
        a = {"skin_id": 103001}
        self.assertEqual(self.run_loop([a], frozen=True), [a])


class InjectionHookTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.mods_dir = self.root / "mods_dir"
        self.mods_dir.mkdir()
        for target, value in (
            ("party.integration.injection_hook.get_injection_dir", self.root / "injection"),
            ("party.integration.injection_hook.get_mods_root", self.root / "mods"),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.skin_zip = self.root / "zips" / "11002.zip"
        self.skin_zip.parent.mkdir()
        with zipfile.ZipFile(self.skin_zip, "w") as archive:
            archive.writestr("WAD/MasterYi.wad.client", b"skin")

    def injector(self):
        def resolve_zip(zip_arg, chroma_id=None, **_):
            return None if chroma_id else self.skin_zip
        return SimpleNamespace(mods_dir=self.mods_dir, _resolve_zip=Mock(side_effect=resolve_zip))

    def test_skin_is_linked_under_a_party_folder(self):
        hook = PartyInjectionHook(Mock(), make_state())
        skin = PartySkinData(summoner_id=2, summoner_name="B", champion_id=11, skin_id=11002, chroma_id=11005)

        name = hook._prepare_single_skin(skin, self.injector())

        self.assertEqual(name, "party_2")
        # Missing chroma: the base skin is used
        self.assertEqual((self.mods_dir / name / "WAD" / "MasterYi.wad.client").read_bytes(), b"skin")

    def test_custom_mod_folder_is_used(self):
        mod = self.root / "mods" / "skins" / "11000" / "Custom Yi"
        (mod / "WAD").mkdir(parents=True)
        (mod / "WAD" / "MasterYi.wad.client").write_bytes(b"custom")
        hook = PartyInjectionHook(Mock(), make_state())
        skin = PartySkinData(2, "B", 11, 11002, custom_mod_path="skins/11000/Custom Yi")

        name = hook._prepare_single_skin(skin, self.injector())

        self.assertEqual((self.mods_dir / name / "WAD" / "MasterYi.wad.client").read_bytes(), b"custom")

    def test_rift_classic_uses_the_classic_skin(self):
        mod = self.root / "mods" / "skins" / "11000" / "Custom Yi"
        (mod / "WAD").mkdir(parents=True)
        (mod / "WAD" / "MasterYi.wad.client").write_bytes(b"custom")
        hook = PartyInjectionHook(Mock(), make_state())
        skin = PartySkinData(2, "B", 60011, 60011002, custom_mod_path="skins/11000/Custom Yi")
        injector = self.injector()

        name = hook._prepare_single_skin(skin, injector, classic=True)

        # Custom mods target the regular characters, which Classic doesn't load
        self.assertEqual((self.mods_dir / name / "WAD" / "MasterYi.wad.client").read_bytes(), b"skin")
        self.assertTrue(injector._resolve_zip.call_args.kwargs["classic"])


class PartyOnlyInjectionTests(unittest.TestCase):
    def make_manager(self, party_manager):
        from injection.core.manager import InjectionManager

        state = SimpleNamespace(party_manager=party_manager, ui_skin_thread=None)
        manager = InjectionManager(shared_state=state)
        manager._initialized = True
        manager.injector = Mock(game_dir=Path("."))
        manager.injector.inject_extra_mods.return_value = True
        manager.refresh_injection_threshold = Mock(return_value=0.0)
        manager.injection_threshold = 0.0
        manager._start_monitor = Mock()
        manager._stop_monitor = Mock()
        return manager

    def test_party_skins_are_injected_without_our_skin(self):
        party_manager = Mock(enabled=True)
        party_manager.party_state.peers = {2: object()}
        manager = self.make_manager(party_manager)

        with patch.object(PartyInjectionHook, "prepare_party_mods", return_value=["party_2"]) as prepare:
            self.assertTrue(manager.inject_party_skins_only())
            callback = manager.injector.inject_extra_mods.call_args.args[0]
            self.assertEqual(callback(manager.injector), ["party_2"])
            prepare.assert_called_once()
        manager._stop_monitor.assert_called_once()

    def test_nothing_happens_without_party(self):
        manager = self.make_manager(None)

        self.assertFalse(manager.inject_party_skins_only())
        manager.injector.inject_extra_mods.assert_not_called()


if __name__ == "__main__":
    unittest.main()
