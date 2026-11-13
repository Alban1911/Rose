import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from injection.core import manager as manager_module
from injection.core.manager import InjectionManager
from injection.game.game_monitor import CLIENT_OUTAGE_GRACE_S, make_game_ended_callback
from injection.mods.zip_resolver import ZipResolver
from pengu.communication.message_handler import MessageHandler
from threads.handlers.phase_handler import PhaseHandler


def _tracker(**state):
    defaults = dict(game_skin_swap=None, locked_champ_id=103, selected_skin_id=103000, is_swiftplay_mode=False)
    return PhaseHandler(Mock(), SimpleNamespace(**{**defaults, **state}))


class GameSkinSwapTrackingTests(unittest.TestCase):
    def test_default_skin_game_can_swap(self):
        handler = _tracker()
        handler._track_game_skin_swap("GameStart")
        self.assertEqual(handler.state.game_skin_swap, {"champion_id": 103, "swappable": True})

    def test_owned_skin_game_cannot_swap(self):
        # The server tells the game to load the owned skin, which an injected skin does not replace
        handler = _tracker(selected_skin_id=103015)
        handler._track_game_skin_swap("GameStart")
        self.assertFalse(handler.state.game_skin_swap["swappable"])

    def test_survives_the_reconnect_that_clears_the_locked_champion(self):
        handler = _tracker()
        handler._track_game_skin_swap("InProgress")
        handler.state.locked_champ_id = None
        for phase in ("Reconnect", "GameStart", "InProgress"):
            handler._track_game_skin_swap(phase)
        self.assertEqual(handler.state.game_skin_swap["champion_id"], 103)

    def test_cleared_once_the_game_is_over(self):
        handler = _tracker()
        handler._track_game_skin_swap("InProgress")
        handler._track_game_skin_swap("EndOfGame")
        self.assertIsNone(handler.state.game_skin_swap)

    def test_no_swap_in_rift_classic(self):
        # Its skins come from another library, under other champion IDs
        handler = _tracker(current_game_mode="JADE")
        handler._track_game_skin_swap("GameStart")
        self.assertIsNone(handler.state.game_skin_swap)


class SkinsOnDiskTests(unittest.TestCase):
    def test_lists_skins_with_a_file_but_not_the_default_or_empty_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            champ = Path(tmp) / "103"
            for skin_id, ext in ((103000, ".zip"), (103001, ".zip"), (103015, ".fantome")):
                (champ / str(skin_id)).mkdir(parents=True)
                (champ / str(skin_id) / f"{skin_id}{ext}").touch()
            (champ / "103002").mkdir()
            self.assertEqual(ZipResolver(Path(tmp)).skin_ids_on_disk(103), [103001, 103015])
            self.assertEqual(ZipResolver(Path(tmp)).skin_ids_on_disk(1), [])


class SwapForReconnectTests(unittest.TestCase):
    def _manager(self, inject=None):
        manager = InjectionManager.__new__(InjectionManager)
        manager._injection_in_progress = False
        manager._swap_lock = threading.Lock()
        manager.injector = SimpleNamespace(overlay_manager=SimpleNamespace(ready_count=0))
        manager.stop_injection_by_user = Mock()
        manager.inject_skin_immediately = Mock(side_effect=inject)
        return manager

    def test_reports_success_once_the_new_overlay_is_ready(self):
        released = threading.Event()

        def inject(*args, **kwargs):
            manager.injector.overlay_manager.ready_count += 1
            released.wait(2)  # the injection then serves the overlay until the game ends
            return True

        manager = self._manager(inject)
        stop = Mock()
        self.assertTrue(manager.swap_skin_for_reconnect(103001, 103, stop))
        released.set()
        manager.stop_injection_by_user.assert_called_once()
        manager.inject_skin_immediately.assert_called_once_with("skin_103001", stop_callback=stop, champion_id=103)

    def test_reports_failure_when_the_injection_ends_before_its_overlay_is_ready(self):
        # A skin that fails to unpack, a cooldown, a patcher failure
        manager = self._manager(lambda *a, **k: False)
        self.assertFalse(manager.swap_skin_for_reconnect(103001, 103))

    def test_a_second_swap_is_refused_while_the_first_applies(self):
        started, released = threading.Event(), threading.Event()

        def inject(*args, **kwargs):
            started.set()
            released.wait(2)
            return False

        manager = self._manager(inject)
        first = threading.Thread(target=manager.swap_skin_for_reconnect, args=(103001, 103))
        first.start()
        self.assertTrue(started.wait(2))
        self.assertFalse(manager.swap_skin_for_reconnect(103002, 103))
        released.set()
        first.join(2)
        manager.inject_skin_immediately.assert_called_once()

    def test_gives_up_when_the_running_injection_does_not_stop(self):
        manager = self._manager()
        manager._injection_in_progress = True
        with patch.object(manager_module, "SKIN_SWAP_STOP_TIMEOUT_S", 0.1):
            self.assertFalse(manager.swap_skin_for_reconnect(103001, 103))
        manager.inject_skin_immediately.assert_not_called()

    def test_a_finished_injection_discards_its_early_patcher_before_letting_a_swap_in(self):
        # After the release, a swap's injection may already have started its own patcher
        from party.integration.injection_hook import PartyInjectionHook

        party_manager = Mock(enabled=True)
        party_manager.party_state.peers = {2: object()}
        manager = InjectionManager(shared_state=SimpleNamespace(party_manager=party_manager, ui_skin_thread=None))
        manager._initialized = True
        manager.injector = Mock(game_dir=Path("."))
        manager.injector.inject_extra_mods.return_value = True
        manager.refresh_injection_threshold = Mock(return_value=0.0)
        manager.injection_threshold = 0.0
        manager.start_patcher_in_background = Mock()
        seen = []
        manager.discard_early_patcher = Mock(
            side_effect=lambda: seen.append((manager._injection_in_progress, manager.injection_lock.locked()))
        )
        with patch.object(PartyInjectionHook, "prepare_party_mods", return_value=["party_2"]):
            self.assertTrue(manager.inject_party_skins_only())
        self.assertEqual(seen, [(True, True)])
        self.assertFalse(manager._injection_in_progress)

    def test_the_lock_is_released_even_when_the_discard_fails(self):
        manager = InjectionManager(shared_state=None)
        manager._initialized = True
        manager.injector = Mock(game_dir=Path("."))
        manager.refresh_injection_threshold = Mock(return_value=0.0)
        manager.injection_threshold = 0.0
        manager.start_patcher_in_background = Mock()
        manager.discard_early_patcher = Mock(side_effect=RuntimeError("LTF host gone"))
        with self.assertRaises(RuntimeError):
            manager._run_injection("skin_103001", lambda extra: True)
        self.assertFalse(manager.injection_lock.locked())
        self.assertFalse(manager._injection_in_progress)


class SwapGameEndedTests(unittest.TestCase):
    def test_a_swap_made_on_the_reconnect_screen_outlives_a_client_outage(self):
        # The swap is made out of the game: it must not wait for InProgress to end
        state = SimpleNamespace(phase="Reconnect", stop=False)
        now = [0.0]
        callback = make_game_ended_callback(state, clock=lambda: now[0], game_started=True)
        self.assertFalse(callback())
        state.phase = None
        self.assertFalse(callback())
        now[0] = CLIENT_OUTAGE_GRACE_S
        self.assertTrue(callback())

    def test_a_swap_ends_with_the_game(self):
        state = SimpleNamespace(phase="Reconnect", stop=False)
        callback = make_game_ended_callback(state, game_started=True)
        state.phase = "EndOfGame"
        self.assertTrue(callback())


class SkinSwapRequestTests(unittest.TestCase):
    def _reply(self, phase="Reconnect", swap=None):
        handler = MessageHandler.__new__(MessageHandler)
        handler.shared_state = SimpleNamespace(phase=phase, game_skin_swap=swap)
        handler.injection_manager = Mock()
        handler.injection_manager.injector.zip_resolver.skin_ids_on_disk.return_value = [103001]
        handler._send_response = Mock()
        handler._handle_skin_swap_request({})
        return json.loads(handler._send_response.call_args[0][0])

    def test_offers_the_skins_on_disk(self):
        reply = self._reply(swap={"champion_id": 103, "swappable": True})
        self.assertEqual((reply["championId"], reply["skinIds"], reply["reason"]), (103, [103001], None))

    def test_explains_an_owned_skin(self):
        self.assertEqual(self._reply(swap={"champion_id": 103, "swappable": False})["reason"], "owned")

    def test_only_on_the_reconnect_screen(self):
        # While the game runs, Rose's injection would freeze it
        reply = self._reply(phase="InProgress", swap={"champion_id": 103, "swappable": True})
        self.assertEqual(reply["reason"], "unavailable")


class SkinSwapSelectTests(unittest.TestCase):
    def _select(self, skin_id):
        handler = MessageHandler.__new__(MessageHandler)
        handler.shared_state = SimpleNamespace(phase="Reconnect", game_skin_swap={"champion_id": 103, "swappable": True})
        handler.injection_manager = Mock()
        handler.injection_manager.injector.zip_resolver.skin_ids_on_disk.return_value = [103001]
        handler.injection_manager.swap_skin_for_reconnect.return_value = True
        sent = threading.Event()
        handler._send_response = Mock(side_effect=lambda _: sent.set())
        handler._handle_skin_swap_select({"skinId": skin_id})
        self.assertTrue(sent.wait(2))
        return handler, json.loads(handler._send_response.call_args[0][0])

    def test_swaps_to_an_offered_skin(self):
        handler, reply = self._select(103001)
        self.assertTrue(reply["success"])
        handler.injection_manager.swap_skin_for_reconnect.assert_called_once()

    def test_refuses_a_skin_it_did_not_offer_without_stopping_anything(self):
        handler, reply = self._select(266001)
        self.assertFalse(reply["success"])
        handler.injection_manager.swap_skin_for_reconnect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
