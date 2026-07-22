import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from analytics.core import get_machine_id
from analytics.core import install_id as install_id_module
from analytics.core.analytics_client import AnalyticsClient
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

    def test_presence_interval_is_15_minutes(self):
        self.assertEqual(ANALYTICS_PING_INTERVAL_S, 900)


if __name__ == "__main__":
    unittest.main()
