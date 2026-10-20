import os
import tempfile
import time
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import config
from state import SharedState
from threads.utilities import late_champion_resolver as resolver


GAMEFLOW_SESSION = {
    "gameData": {
        "gameId": 1610582965,
        "teamOne": [
            {"championId": 90, "summonerId": 3112797820913568},
            {"championId": 22, "summonerId": 3113557841716864},
        ],
        "teamTwo": [{"championId": 21, "summonerId": 42}],
        "playerChampionSelections": [{"championId": 22}, {"championId": 21}],
    },
    "phase": "InProgress",
}

NO_CHAMPION_SESSION = {
    "gameData": {
        "gameId": 999,
        "teamOne": [{"championId": 0, "summonerId": 3113557841716864}],
        "teamTwo": [],
    },
    "phase": "InProgress",
}


class _FakeApi:
    """Returns a queued response per path; the last value repeats."""

    def __init__(self, responses):
        self.responses = {path: deque(value) if isinstance(value, (list, tuple)) else value
                          for path, value in responses.items()}
        self.calls = []

    def get(self, path, timeout=None, use_cache=True):
        self.calls.append((path, use_cache))
        value = self.responses.get(path)
        if isinstance(value, deque):
            return value.popleft() if len(value) > 1 else value[0]
        return value


def _lcu(api):
    return SimpleNamespace(_api=api)


class FindMyChampionTests(unittest.TestCase):
    def test_the_local_champion_is_found_in_either_team(self):
        self.assertEqual(
            resolver.find_my_champion(GAMEFLOW_SESSION["gameData"], 3113557841716864),
            ("teamOne", 22),
        )
        self.assertEqual(
            resolver.find_my_champion(GAMEFLOW_SESSION["gameData"], 42), ("teamTwo", 21)
        )

    def test_string_summoner_ids_still_match(self):
        self.assertEqual(
            resolver.find_my_champion(GAMEFLOW_SESSION["gameData"], "3113557841716864"),
            ("teamOne", 22),
        )

    def test_zero_champion_is_not_a_champion(self):
        game = {"teamOne": [{"championId": 0, "summonerId": 7}]}
        self.assertEqual(resolver.find_my_champion(game, 7), (None, None))

    def test_unknown_or_missing_input_returns_none(self):
        for game, summoner in ((None, 1), (GAMEFLOW_SESSION["gameData"], None),
                               (GAMEFLOW_SESSION["gameData"], 123)):
            with self.subTest(summoner=summoner):
                self.assertEqual(resolver.find_my_champion(game, summoner), (None, None))


class BuildInjectionNameTests(unittest.TestCase):
    def test_a_numeric_skin_is_injected_as_skin_id(self):
        self.assertEqual(resolver.build_injection_name(22, 22008), ("skin_22008", None))

    def test_a_chroma_id_uses_the_skin_prefix_and_the_resolver_falls_back(self):
        self.assertEqual(resolver.build_injection_name(103, 103087), ("skin_103087", None))

    def test_missing_historic_entry_is_reported(self):
        name, reason = resolver.build_injection_name(22, None)
        self.assertIsNone(name)
        self.assertIn("no historic skin", reason)

    def test_custom_mod_paths_are_not_supported_late(self):
        name, reason = resolver.build_injection_name(22, "path:skins/22008/mod.fantome")
        self.assertIsNone(name)
        self.assertIn("custom mod", reason)

    def test_a_skin_from_another_champion_is_refused(self):
        name, reason = resolver.build_injection_name(22, 21069)
        self.assertIsNone(name)
        self.assertIn("does not belong", reason)

    def test_invalid_values_are_refused(self):
        for value in ("nope", 0, -5, 22008.5):
            with self.subTest(value=value):
                name, _reason = resolver.build_injection_name(22, value)
                self.assertIsNone(name)


class _ResolverTestBase(unittest.TestCase):
    def setUp(self):
        resolver.stop("test setup")
        self._wait_idle()
        resolver._handled_keys.clear()

        self.state = SharedState()
        self.state.phase = "GameStart"
        self.state.current_queue_id = 1750
        self.injection_manager = MagicMock()
        self.injection_manager.inject_skin_immediately.return_value = True
        self.historic = patch.object(
            resolver, "get_historic_skin_for_champion", return_value=22008
        )
        self.historic.start()
        self.addCleanup(self.historic.stop)
        self.settings = [
            patch.object(resolver, "enabled", return_value=True),
            patch.object(resolver, "ARENA_LATE_RESOLVE_INTERVAL_MS", 1),
            patch.object(resolver, "ARENA_LATE_RESOLVE_TIMEOUT_S", 0.5),
        ]
        for patcher in self.settings:
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        resolver.stop("test teardown")
        self._wait_idle()
        resolver._handled_keys.clear()

    def _wait_idle(self, timeout=2.0):
        deadline = time.monotonic() + timeout
        while resolver.is_active() and time.monotonic() < deadline:
            time.sleep(0.01)

    def _wait_for_injection(self, timeout=2.0):
        deadline = time.monotonic() + timeout
        while not self.injection_manager.inject_skin_immediately.called and time.monotonic() < deadline:
            time.sleep(0.01)

    def _start(self, session=GAMEFLOW_SESSION, phase="GameStart", previous="FINALIZATION"):
        api = _FakeApi(
            {
                resolver.ARENA_LATE_GAMEFLOW_PATH: session,
                resolver.ARENA_LATE_SUMMONER_PATH: {"summonerId": 3113557841716864},
            }
        )
        started = resolver.maybe_start(
            state=self.state,
            lcu=_lcu(api),
            injection_manager=self.injection_manager,
            phase=phase,
            previous_phase=previous,
        )
        return started, api


class LateInjectionTests(_ResolverTestBase):
    def test_the_historic_skin_of_the_resolved_champion_is_injected(self):
        started, _api = self._start()
        self.assertTrue(started)
        self._wait_for_injection()

        kwargs = self.injection_manager.inject_skin_immediately.call_args.kwargs
        self.assertEqual(
            self.injection_manager.inject_skin_immediately.call_args.args[0],
            "skin_22008",
        )
        self.assertEqual(kwargs["champion_id"], 22)
        # The resolver never touches the champion that the rest of Rose watches.
        self.assertIsNone(self.state.locked_champ_id)
        self._wait_idle()
        self.assertFalse(resolver.is_active())

    def test_no_historic_skin_means_no_injection(self):
        self.historic.stop()
        with patch.object(resolver, "get_historic_skin_for_champion", return_value=None):
            started, _api = self._start()
            self.assertTrue(started)
            self._wait_idle()

        self.injection_manager.inject_skin_immediately.assert_not_called()

    def test_a_known_champion_is_left_to_the_normal_flow(self):
        self.state.locked_champ_id = 22

        started, _api = self._start()

        self.assertFalse(started)
        self.injection_manager.inject_skin_immediately.assert_not_called()

    def test_swiftplay_is_skipped(self):
        self.state.is_swiftplay_mode = True

        started, _api = self._start()

        self.assertFalse(started)

    def test_in_progress_right_after_champ_select_is_accepted(self):
        started, _api = self._start(phase="InProgress", previous="ChampSelect")

        self.assertTrue(started)
        self._wait_for_injection()
        self.assertEqual(
            self.injection_manager.inject_skin_immediately.call_args.args[0],
            "skin_22008",
        )

    def test_in_progress_without_a_game_start_is_not_trusted(self):
        """Rose launched mid-match must not suddenly suspend the game."""
        for previous in (None, "Reconnect", "EndOfGame"):
            with self.subTest(previous=previous):
                started, _api = self._start(phase="InProgress", previous=previous)
                self.assertFalse(started)

    def test_the_champion_is_resolved_after_a_few_polls(self):
        waiting = {
            "gameData": {
                "gameId": 1610582965,
                "teamOne": [
                    {"championId": 0, "summonerId": 3113557841716864},
                ],
                "teamTwo": [],
            },
            "phase": "GameStart",
        }
        started, _api = self._start(session=[waiting, waiting, GAMEFLOW_SESSION])

        self.assertTrue(started)
        self._wait_for_injection()
        self.assertEqual(
            self.injection_manager.inject_skin_immediately.call_args.args[0],
            "skin_22008",
        )

    def test_the_champion_is_only_resolved_once_per_game(self):
        started, _api = self._start()
        self.assertTrue(started)
        self._wait_for_injection()
        self._wait_idle()

        started_again, _api = self._start()
        self.assertTrue(started_again)
        self._wait_idle()

        self.assertEqual(
            self.injection_manager.inject_skin_immediately.call_count, 1
        )

    def test_an_unresolvable_champion_times_out_without_injecting(self):
        self.injection_manager.reset_mock()
        with patch.object(resolver, "ARENA_LATE_RESOLVE_TIMEOUT_S", 0.15):
            started, _api = self._start(session=NO_CHAMPION_SESSION)
            self.assertTrue(started)
            self._wait_idle()

        self.injection_manager.inject_skin_immediately.assert_not_called()

    def test_leaving_the_game_stops_the_session(self):
        started, _api = self._start(session=NO_CHAMPION_SESSION)
        self.assertTrue(started)

        resolver.on_phase_change(
            "EndOfGame",
            "InProgress",
            state=self.state,
            lcu=None,
            injection_manager=self.injection_manager,
        )
        self._wait_idle()

        self.assertFalse(resolver.is_active())

    def test_lcu_reads_bypass_the_shared_cache(self):
        started, api = self._start()
        self.assertTrue(started)
        self._wait_for_injection()

        self.assertTrue(api.calls)
        self.assertTrue(all(use_cache is False for _, use_cache in api.calls))


class EnableSwitchTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.path = Path(temp_dir.name) / "config.ini"
        patcher = patch.object(config, "get_config_file_path", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        saved = (config._CONFIG, config._CONFIG_MTIME)
        self.addCleanup(lambda: setattr(config, "_CONFIG", saved[0]) or setattr(config, "_CONFIG_MTIME", saved[1]))
        config._CONFIG_MTIME = -1.0

    def test_enabled_by_default(self):
        self.assertTrue(resolver.enabled())

    def test_config_ini_can_turn_it_off(self):
        self.path.write_text("[Debug]\narena_late_injection = false\n", encoding="utf-8")
        os.utime(self.path, (time.time() + 10, time.time() + 10))

        self.assertFalse(resolver.enabled())

    def test_config_ini_can_turn_it_back_on(self):
        self.path.write_text("[Debug]\narena_late_injection = true\n", encoding="utf-8")
        os.utime(self.path, (time.time() + 10, time.time() + 10))

        self.assertTrue(resolver.enabled())

    def test_the_phase_hook_does_nothing_while_disabled(self):
        self.addCleanup(resolver.stop)
        self.path.write_text("[Debug]\narena_late_injection = false\n", encoding="utf-8")
        os.utime(self.path, (time.time() + 10, time.time() + 10))
        state = SharedState()
        state.phase = "GameStart"

        resolver.on_phase_change(
            "GameStart", "FINALIZATION", state=state, lcu=MagicMock()
        )

        self.assertFalse(resolver.is_active())


if __name__ == "__main__":
    unittest.main()
