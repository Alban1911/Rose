import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import requests

from lcu.features.lcu_skin_selection import LCUSkinSelection


def _failed_response():
    response = requests.Response()
    response.status_code = 500
    response._content = b'boom'
    return response


class FailedPatchLoggingTests(unittest.TestCase):
    """requests.Response is falsy for 4xx/5xx, so a rejected PATCH was logged
    as status=None with no response, hiding the real status and body"""

    def setUp(self):
        self.api = MagicMock()
        self.api.patch.return_value = _failed_response()
        self.selection = LCUSkinSelection(self.api, SimpleNamespace(ok=True))

    def _assert_failure_logged(self, call):
        with self.assertLogs('tracer', level='WARNING') as logs:
            self.assertFalse(call())
        self.assertTrue(any('status=500' in line and 'boom' in line for line in logs.output))

    def test_set_selected_skin_logs_real_status_and_body(self):
        self._assert_failure_logged(lambda: self.selection.set_selected_skin(1, 2))

    def test_set_my_selection_skin_logs_real_status_and_body(self):
        self._assert_failure_logged(lambda: self.selection.set_my_selection_skin(2))


if __name__ == '__main__':
    unittest.main()
