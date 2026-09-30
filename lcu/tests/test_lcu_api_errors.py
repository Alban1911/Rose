import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import requests

from lcu.core.lcu_api import LCUAPI


class RequestFailureTests(unittest.TestCase):
    """A request that failed again after reconnecting returned None with no
    trace, so callers acted on missing data without any hint why"""

    def setUp(self):
        session = MagicMock()
        session.get.side_effect = requests.exceptions.ConnectionError('client closed')
        session.patch.side_effect = requests.exceptions.ConnectionError('client closed')
        self.connection = SimpleNamespace(ok=True, base='https://127.0.0.1:1', session=session,
                                          refresh_if_needed=lambda force=False: None)
        self.api = LCUAPI(self.connection)

    def test_a_failed_get_is_logged(self):
        with self.assertLogs(level='DEBUG') as logs:
            self.assertIsNone(self.api.get('/lol-champ-select/v1/session', timeout=1.0, use_cache=False))
        self.assertTrue(any('GET /lol-champ-select/v1/session failed' in line for line in logs.output))


if __name__ == '__main__':
    unittest.main()
