import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from injection.core import manager as manager_module
from injection.core.manager import InjectionManager
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
    def _manager(self):
        manager = InjectionManager.__new__(InjectionManager)
        manager._injection_in_progress = False
        manager.stop_injection_by_user = Mock()
        manager.inject_skin_immediately = Mock()
        return manager

    def test_stops_the_running_injection_then_injects_the_skin(self):
        manager = self._manager()
        stop = Mock()
        self.assertTrue(manager.swap_skin_for_reconnect(103001, 103, stop))
        manager.stop_injection_by_user.assert_called_once()
        deadline = time.monotonic() + 2
        while not manager.inject_skin_immediately.called and time.monotonic() < deadline:
            time.sleep(0.01)
        manager.inject_skin_immediately.assert_called_once_with("skin_103001", stop_callback=stop, champion_id=103)

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


if __name__ == "__main__":
    unittest.main()
