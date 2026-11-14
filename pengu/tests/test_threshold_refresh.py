import unittest
from unittest.mock import Mock, patch

from pengu.communication import message_handler


class ThresholdRefreshTests(unittest.TestCase):
    def setUp(self):
        self.handler = object.__new__(message_handler.MessageHandler)
        self.handler.injection_manager = Mock()
        self.handler._send_response = Mock()
        self.handler._send_settings_save_success = Mock()
        self.handler._send_settings_save_error = Mock()

    def test_apply_recommended_refreshes_the_running_injector(self):
        stats = {"recommended_threshold_ms": 1500}
        with patch("injection.config.base_skin_tracker.get_stats", return_value=stats), \
                patch("config.set_config_option"):
            self.handler._handle_diagnostics_apply_recommended({})

        self.handler.injection_manager.refresh_injection_threshold.assert_called_once_with()

    def test_settings_save_refreshes_the_running_injector(self):
        with patch.object(message_handler, "set_config_option"), \
                patch.object(message_handler, "is_registered_for_autostart", return_value=False):
            self.handler._handle_settings_save({"threshold": 1.5})

        self.handler.injection_manager.refresh_injection_threshold.assert_called_once_with()
        self.handler._send_settings_save_success.assert_called_once_with()

    def test_settings_save_still_succeeds_when_the_refresh_fails(self):
        self.handler.injection_manager.refresh_injection_threshold.side_effect = RuntimeError("boom")
        with patch.object(message_handler, "set_config_option"), \
                patch.object(message_handler, "is_registered_for_autostart", return_value=False):
            self.handler._handle_settings_save({"threshold": 1.5})

        self.handler._send_settings_save_success.assert_called_once_with()
        self.handler._send_settings_save_error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
