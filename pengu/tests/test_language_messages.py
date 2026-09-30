import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lcu.features.client_language import LanguageChangeError
from pengu.communication.message_handler import MessageHandler


class LanguageMessageTests(unittest.TestCase):
    def setUp(self):
        self.state = SimpleNamespace(stop=False)
        self.handler = MessageHandler(
            self.state, Mock(), Mock(), Mock(), Mock(),
            skin_scraper=SimpleNamespace(lcu=Mock()), mod_storage=Mock(),
        )
        self.service = Mock()
        self.service.status = {"busy": False, "stage": "idle", "message": ""}
        self.service.options.return_value = {
            "currentLocale": "pt_BR", "languages": [{"locale": "ko_KR", "name": "Korean"}]
        }
        self.handler.language_service = self.service
        self.messages = []
        self.handler._send_response = lambda message: self.messages.append(json.loads(message))
        self.release = threading.Event()
        self.workers = []
        real_thread = threading.Thread

        def thread(*args, **kwargs):
            worker = real_thread(*args, **kwargs)
            self.workers.append(worker)
            return worker

        self.thread_patch = patch(
            "pengu.communication.message_handler.threading.Thread", side_effect=thread
        )
        self.thread_patch.start()
        self.addCleanup(self.thread_patch.stop)
        self.addCleanup(self.finish_workers)

    def finish_workers(self):
        self.release.set()
        for worker in self.workers:
            worker.join(5)
            self.assertFalse(worker.is_alive(), "Language worker did not finish")

    def send(self, message_type, **payload):
        self.handler.handle_message(json.dumps({"type": message_type, **payload}))

    def test_options_keep_bridge_responsive_and_deduplicate_requests(self):
        started = threading.Event()

        def options():
            started.set()
            self.release.wait(5)
            return {"currentLocale": "pt_BR", "languages": []}

        self.service.options.side_effect = options
        self.send("language-options-request")
        self.assertTrue(started.wait(5))
        self.send("language-options-request")
        with patch.object(self.handler, "_handle_language_save") as menu_language:
            self.send("language-save", language="fr")
            menu_language.assert_called_once()
        self.assertEqual(len(self.workers), 1)
        self.finish_workers()
        self.assertEqual(self.messages[-1]["type"], "language-options")
        self.assertFalse(self.handler._language_options_lock.locked())

    def test_reconnect_gets_retained_busy_status_without_fetching_options(self):
        self.service.status = {"busy": True, "stage": "restarting", "message": "Restarting League"}
        self.send("language-options-request")
        self.assertEqual(self.messages, [{"type": "language-status", **self.service.status}])
        self.service.options.assert_not_called()
        self.assertFalse(self.workers)

    def test_option_failure_is_sanitized_and_retry_is_possible(self):
        self.service.options.side_effect = RuntimeError("private local API credentials")
        self.send("language-options-request")
        self.finish_workers()
        self.assertNotIn("private", json.dumps(self.messages))
        self.assertIn("error", self.messages[-1])
        self.service.options.side_effect = LanguageChangeError("Open League first.")
        self.send("language-options-request")
        self.finish_workers()
        self.assertEqual(self.messages[-1]["error"], "Open League first.")

    def test_changes_are_serialized_without_blocking_message_routing(self):
        started = threading.Event()

        def change(locale, report):
            self.service.status = {"busy": True, "stage": "caching", "message": "Caching"}
            started.set()
            self.release.wait(5)
            report({"busy": False, "stage": "complete", "locale": locale})

        self.service.change.side_effect = change
        self.send("language-change", locale="ko_KR")
        self.assertTrue(started.wait(5))
        self.send("language-change", locale="en_US")
        self.assertEqual(len(self.workers), 1)
        self.finish_workers()
        self.service.change.assert_called_once()
        self.assertEqual(self.messages[-1]["locale"], "ko_KR")
        self.assertFalse(self.handler._language_change_lock.locked())

    def test_missing_lcu_returns_user_facing_errors(self):
        self.handler.language_service = None
        self.send("language-options-request")
        self.send("language-change", locale="ko_KR")
        self.assertIn("error", self.messages[0])
        self.assertEqual(self.messages[1]["stage"], "error")
        self.assertFalse(self.workers)

    def test_disconnected_frontend_does_not_interrupt_status_reporting(self):
        self.handler._send_response = Mock(side_effect=RuntimeError("event loop closed"))
        self.handler._send_language_status({"busy": True, "stage": "restarting"})

    def test_failed_thread_start_releases_locks_and_reports_error(self):
        with patch("pengu.communication.message_handler.threading.Thread",
                   return_value=Mock(start=Mock(side_effect=RuntimeError("thread unavailable")))):
            self.send("language-options-request")
            self.send("language-change", locale="ko_KR")
        self.assertFalse(self.handler._language_options_lock.locked())
        self.assertFalse(self.handler._language_change_lock.locked())
        self.assertIn("error", self.messages[-2])
        self.assertEqual(self.messages[-1]["stage"], "error")


if __name__ == "__main__":
    unittest.main()
