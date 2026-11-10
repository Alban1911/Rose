import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from analytics.core import get_machine_id
from analytics.core import install_id as install_id_module
from analytics.core.analytics_client import AnalyticsClient
from analytics.core.preference import set_analytics_opted_in
from config import ANALYTICS_PING_INTERVAL_S


class InstallIdTests(unittest.TestCase):
    def tearDown(self):
        install_id_module._install_id_cache = None

    def test_id_is_persisted_and_reused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            with patch.object(install_id_module, "get_user_data_dir", return_value=data_dir):
                first_id = install_id_module.get_install_id()
                install_id_module._install_id_cache = None
                second_id = install_id_module.get_install_id()

            self.assertEqual(first_id, second_id)
            self.assertEqual(first_id, get_machine_id())
            self.assertTrue((data_dir / "analytics_install_id.txt").exists())


class AnalyticsClientTests(unittest.TestCase):
    @patch("analytics.core.analytics_client.get_install_id", return_value="00000000-0000-4000-8000-000000000000")
    @patch("analytics.core.analytics_client.requests.post")
    def test_ping_contains_pseudonymous_install_data(self, post, get_install_id):
        response = Mock()
        response.status_code = 204
        post.return_value = response

        client = AnalyticsClient(
            server_url="https://rosekeys.site/",
            timeout=2,
            enabled=True,
        )

        self.assertTrue(client.send_ping("1.2.10"))
        post.assert_called_once()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload, {
            "install_id": "00000000-0000-4000-8000-000000000000",
            "app_version": "1.2.10",
            "event": "heartbeat",
        })
        self.assertNotIn("machine_id", payload)

    @patch("analytics.core.analytics_client.requests.post")
    def test_config_ini_opt_out_disables_pings(self, post):
        for value in ("false", "0", "Off", " no "):
            with self.subTest(value=value), \
                    patch("analytics.core.preference.get_config_option", return_value=value):
                self.assertFalse(AnalyticsClient().send_ping("1.2.14"))
        post.assert_not_called()

    @patch("analytics.core.analytics_client.get_install_id", return_value="00000000-0000-4000-8000-000000000000")
    @patch("analytics.core.analytics_client.requests.post")
    def test_missing_config_option_keeps_analytics_enabled(self, post, get_install_id):
        post.return_value = Mock(status_code=204)
        with patch("analytics.core.preference.get_config_option", return_value=None):
            self.assertTrue(AnalyticsClient().send_ping("1.2.14"))

    @patch("analytics.core.analytics_client.get_install_id", return_value="00000000-0000-4000-8000-000000000000")
    @patch("analytics.core.analytics_client.requests.post")
    def test_opting_out_while_rose_runs_stops_the_next_ping(self, post, get_install_id):
        post.return_value = Mock(status_code=204)
        client = AnalyticsClient()
        with patch("analytics.core.preference.get_config_option", side_effect=["true", "false"]):
            self.assertTrue(client.send_ping("1.2.14"))
            self.assertFalse(client.send_ping("1.2.14"))
        post.assert_called_once()

    def test_presence_interval_is_15_minutes(self):
        self.assertEqual(ANALYTICS_PING_INTERVAL_S, 900)


class AnalyticsPreferenceTests(unittest.TestCase):
    def test_choice_is_saved_in_the_general_section(self):
        with patch("analytics.core.preference.set_config_option") as set_option:
            set_analytics_opted_in(False)
            set_analytics_opted_in(True)
        self.assertEqual(
            [c.args for c in set_option.call_args_list],
            [("General", "analytics_enabled", "false"), ("General", "analytics_enabled", "true")],
        )


if __name__ == "__main__":
    unittest.main()
