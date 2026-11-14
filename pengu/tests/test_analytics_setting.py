import json
import unittest
from unittest.mock import patch

from pengu.communication import message_handler


class AnalyticsSettingTests(unittest.TestCase):
    def setUp(self):
        self.handler = object.__new__(message_handler.MessageHandler)
        self.sent = []
        self.handler._send_response = self.sent.append
        for patcher in (
            patch.object(message_handler, "get_config_float", return_value=1.0),
            patch.object(message_handler, "get_config_option", return_value=""),
            patch.object(message_handler, "set_config_option"),
            patch.object(message_handler, "is_registered_for_autostart", return_value=False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.handler._compute_diagnostics_errors = lambda: []

    def save(self, **fields):
        self.handler._handle_settings_save({"threshold": 1.0, "monitorAutoResumeTimeout": 60, **fields})
        return json.loads(self.sent[-1])

    def test_settings_show_the_saved_choice(self):
        with patch.object(message_handler, "analytics_opted_in", return_value=False):
            self.handler._handle_settings_request({})
        self.assertIs(json.loads(self.sent[-1])["analyticsEnabled"], False)

    def test_opting_out_and_back_in_is_saved(self):
        for opted_in, wanted in ((True, False), (False, True)):
            with self.subTest(wanted=wanted), \
                    patch.object(message_handler, "analytics_opted_in", return_value=opted_in), \
                    patch.object(message_handler, "set_analytics_opted_in") as set_choice:
                self.assertTrue(self.save(analyticsEnabled=wanted)["success"])
                set_choice.assert_called_once_with(wanted)

    def test_unchanged_or_missing_choice_is_left_alone(self):
        for fields in ({"analyticsEnabled": True}, {}):
            with self.subTest(fields=fields), \
                    patch.object(message_handler, "analytics_opted_in", return_value=True), \
                    patch.object(message_handler, "set_analytics_opted_in") as set_choice:
                self.assertTrue(self.save(**fields)["success"])
                set_choice.assert_not_called()


if __name__ == "__main__":
    unittest.main()
