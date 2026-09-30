import unittest
from types import SimpleNamespace
from unittest.mock import patch

from state import SharedState
from threads.handlers import champ_thread
from threads.handlers.champ_thread import ChampThread


class ChampionLockErrorTests(unittest.TestCase):
    """The lock check swallowed every error: a malformed session meant the
    lock went unnoticed, with nothing in the log"""

    def test_a_repeated_lock_check_error_is_logged_once(self):
        state = SharedState()
        state.phase = 'ChampSelect'
        # An action that is not an object breaks the lock parsing on every loop
        lcu = SimpleNamespace(ok=True, hovered_champion_id=1, my_selection={},
                              session={'localPlayerCellId': 0, 'actions': [[42]]})
        thread = ChampThread(lcu, state, interval=0)
        loops = []

        def sleep(_seconds):
            loops.append(1)
            if len(loops) >= 3:
                state.stop = True

        with patch.object(champ_thread.time, 'sleep', side_effect=sleep), \
                patch.object(champ_thread, 'log') as log:
            thread.run()

        self.assertEqual(len(loops), 3)
        log.exception.assert_called_once()
        self.assertIn('Champion lock check failed', log.exception.call_args[0][0])


if __name__ == '__main__':
    unittest.main()
