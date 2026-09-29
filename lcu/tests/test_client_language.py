import json
import unittest
from unittest.mock import Mock, patch

import requests

from lcu.features.client_language import ClientLanguageService, LanguageChangeError


def response(value=None, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(value).encode()
    return result


class ClientLanguageTests(unittest.TestCase):
    def setUp(self):
        self.lcu = Mock(ok=True, base="https://127.0.0.1:12345")
        self.current = "en_US"
        self.actual = "en_US"
        self.phase = "None"
        self.region = "BR"
        self.args = ["--riotclient-app-port=54321", "--riotclient-auth-token=test-secret"]
        self.lcu.s.request.side_effect = self.league_request
        self.lcu.s.get.side_effect = requests.ConnectionError()
        self.riot = Mock()
        self.riot.__enter__ = Mock(return_value=self.riot)
        self.riot.__exit__ = Mock(return_value=False)
        self.riot.request.side_effect = self.riot_request
        self.session_patch = patch("lcu.features.client_language.requests.Session", return_value=self.riot)
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)
        self.service = ClientLanguageService(self.lcu)
        self.reports = []

    def league_request(self, method, url, **kwargs):
        if url.endswith("/command-line-args"):
            return response(self.args)
        if url.endswith("/region-locale"):
            return response({"locale": self.actual, "region": self.region})
        if url.endswith("/gameflow-phase"):
            return response(self.phase)
        raise AssertionError(url)

    def riot_request(self, method, url, **kwargs):
        if "/available-product-locales/" in url:
            return response(["en_US", "pt_BR", "../../bad", "pt_BR"])
        if "/product-locales/" in url:
            if method == "PUT":
                self.current = kwargs["json"]
            return response(self.current)
        if "/product-launcher/" in url:
            if method == "POST":
                self.actual = self.current
            return response(status=204)
        raise AssertionError(url)

    def mutations(self):
        return [c for c in self.riot.request.call_args_list if c.args[0] != "GET"]

    def test_reads_available_languages_without_mutation(self):
        options = self.service.options()
        self.assertEqual(options["currentLocale"], "en_US")
        self.assertEqual([x["locale"] for x in options["languages"]], ["en_US", "pt_BR"])
        self.assertFalse(self.mutations())
        self.assertFalse(self.riot.trust_env)
        self.assertEqual(self.riot.auth, ("riot", "test-secret"))

    def test_saves_then_closes_launches_and_verifies_locale(self):
        self.service.change("pt_BR", self.reports.append)
        calls = self.mutations()
        self.assertEqual([c.args[0] for c in calls], ["PUT", "DELETE", "POST"])
        self.assertEqual(calls[0].kwargs["json"], "pt_BR")
        self.assertTrue(all("/league_of_legends/patchlines/live" in c.args[1] for c in calls))
        self.assertEqual(self.service.status["stage"], "complete")
        self.assertEqual(self.service.status["locale"], "pt_BR")
        self.assertFalse(self.service.status["busy"])

    def test_no_restart_for_already_active_locale(self):
        self.service.change("en_US")
        self.assertEqual(self.service.status["stage"], "complete")
        self.assertFalse(self.mutations())

    def test_restarts_when_preference_is_saved_but_not_active(self):
        self.current = "pt_BR"
        self.service.change("pt_BR")
        self.assertEqual([c.args[0] for c in self.mutations()], ["PUT", "DELETE", "POST"])

    def test_queue_game_and_unknown_phase_block_all_writes(self):
        for phase in ("Matchmaking", "ReadyCheck", "ChampSelect", "InProgress", "Reconnect", None):
            with self.subTest(phase=phase):
                self.phase = phase
                self.service.change("pt_BR")
                self.assertEqual(self.service.status["stage"], "error")
                self.assertFalse(self.mutations())

    def test_invalid_and_unavailable_locale_block_writes(self):
        for locale in (None, [], "../../bad", "xx_XX"):
            with self.subTest(locale=locale):
                self.service.change(locale)
                self.assertEqual(self.service.status["stage"], "error")
                self.assertFalse(self.mutations())

    def test_phase_change_after_saving_prevents_close(self):
        def riot_request(method, url, **kwargs):
            result = self.riot_request(method, url, **kwargs)
            if method == "PUT":
                self.phase = "Matchmaking"
            return result
        self.riot.request.side_effect = riot_request
        self.service.change("pt_BR")
        self.assertEqual([c.args[0] for c in self.mutations()], ["PUT"])
        self.assertIn("preference was saved", self.service.status["message"])

    def test_rejected_write_never_closes(self):
        self.riot.request.side_effect = lambda method, url, **kw: (
            response(status=403) if method == "PUT" else self.riot_request(method, url, **kw)
        )
        self.service.change("pt_BR")
        self.assertEqual([c.args[0] for c in self.mutations()], ["PUT"])
        self.assertIn("HTTP 403", self.service.status["message"])

    def test_close_timeout_never_launches_second_client(self):
        with patch.object(self.service, "_wait", return_value=False):
            self.service.change("pt_BR")
        self.assertEqual([c.args[0] for c in self.mutations()], ["PUT", "DELETE"])
        self.assertEqual(self.service.status["stage"], "error")

    def test_restart_failure_reports_saved_preference(self):
        self.riot.request.side_effect = lambda method, url, **kw: (
            response(status=409) if method == "POST" else self.riot_request(method, url, **kw)
        )
        self.service.change("pt_BR")
        self.assertEqual(self.service.status["stage"], "error")
        self.assertIn("preference was saved", self.service.status["message"])

    def test_no_success_until_running_client_confirms_language(self):
        with patch.object(self.service, "_wait", side_effect=[True, False]):
            self.service.change("pt_BR")
        self.assertEqual(self.service.status["stage"], "error")
        self.assertIn("not confirmed", self.service.status["message"])

    def test_concurrent_change_does_not_duplicate_requests(self):
        self.service._operation.acquire()
        try:
            self.service.change("pt_BR", self.reports.append)
        finally:
            self.service._operation.release()
        self.riot.request.assert_not_called()
        self.assertEqual(self.reports, [self.service.status])

    def test_missing_credentials_fail_without_requests_to_riot(self):
        self.args = []
        with self.assertRaises(LanguageChangeError):
            self.service.options()
        self.riot.request.assert_not_called()

    def test_unconfirmed_preference_never_closes(self):
        self.riot.request.side_effect = lambda method, url, **kw: (
            response(status=204) if method == "PUT" else self.riot_request(method, url, **kw)
        )
        self.service.change("pt_BR")
        self.assertEqual([c.args[0] for c in self.mutations()], ["PUT"])
        self.assertIn("did not confirm", self.service.status["message"])

    def test_shutdown_prevents_mutations(self):
        self.service.stopped = lambda: True
        self.service.change("pt_BR")
        self.assertFalse(self.mutations())
        self.assertEqual(self.service.status["stage"], "error")

    def test_network_error_does_not_expose_credentials(self):
        self.riot.request.side_effect = requests.ConnectionError("test-secret")
        self.service.change("pt_BR")
        self.assertEqual(self.service.status["stage"], "error")
        self.assertNotIn("test-secret", self.service.status["message"])

    def test_operation_can_be_retried_after_failure(self):
        self.phase = "InProgress"
        self.service.change("pt_BR")
        self.phase = "None"
        self.service.change("pt_BR")
        self.assertEqual(self.service.status["stage"], "complete")

    def test_pbe_targets_pbe_instead_of_live(self):
        self.region = "PBE"
        self.service.change("pt_BR")
        self.assertTrue(all("/patchlines/pbe" in c.args[1] for c in self.mutations()))

    def test_caches_outgoing_and_restores_before_riot_can_start_downloading(self):
        cache = Mock()
        cache.save.return_value = 3
        cache.restore.return_value = 3
        events = Mock()
        events.attach_mock(cache, "cache")
        events.attach_mock(self.riot.request, "riot")
        with patch.object(self.service, "_language_cache", return_value=cache):
            self.service.change("pt_BR", self.reports.append)
        calls = events.mock_calls
        save = next(i for i, c in enumerate(calls) if c[0] == "cache.save" and c.args == ("en_US",))
        restore = next(i for i, c in enumerate(calls) if c[0] == "cache.restore")
        write = next(i for i, c in enumerate(calls) if c[0] == "riot" and c.args[0] == "PUT")
        incoming = next(i for i, c in enumerate(calls) if c[0] == "cache.save" and c.args == ("pt_BR",))
        self.assertLess(save, restore)
        self.assertLess(restore, write)
        self.assertGreater(incoming, write)
        self.assertIn("Local cache reused", self.service.status["message"])
        self.assertEqual(self.service.status["stage"], "complete")

    def test_cache_failure_keeps_normal_language_change_and_reports_warning(self):
        cache = Mock()
        cache.save.side_effect = OSError("disk full")
        cache.restore.side_effect = OSError("permission denied")
        with patch.object(self.service, "_language_cache", return_value=cache):
            self.service.change("pt_BR")
        self.assertEqual([c.args[0] for c in self.mutations()], ["PUT", "DELETE", "POST"])
        self.assertEqual(self.service.status["stage"], "complete")
        self.assertIn("Could not save", self.service.status["message"])

    def test_queue_joined_while_caching_blocks_locale_write_and_restart(self):
        cache = Mock()
        def save(locale):
            self.phase = "Matchmaking"
            return 3
        cache.save.side_effect = save
        with patch.object(self.service, "_language_cache", return_value=cache):
            self.service.change("pt_BR")
        self.assertFalse(self.mutations())
        cache.restore.assert_not_called()

    def test_status_consumer_disconnect_does_not_abort_change(self):
        def disconnected(status):
            raise OSError("socket closed test-secret")

        self.service.change("pt_BR", disconnected)
        self.assertEqual([c.args[0] for c in self.mutations()], ["PUT", "DELETE", "POST"])
        self.assertEqual(self.service.status["stage"], "complete")
        self.assertNotIn("test-secret", self.service.status["message"])
        # A dead consumer must not break an overlapping request either.
        self.service._operation.acquire()
        try:
            self.service.change("pt_BR", disconnected)
        finally:
            self.service._operation.release()

    def test_slow_or_tls_rejecting_client_is_not_considered_closed(self):
        for failure in (requests.ReadTimeout("test-secret"), requests.ConnectTimeout(),
                        requests.exceptions.SSLError(), requests.RequestException()):
            with self.subTest(failure=type(failure).__name__):
                self.current, self.actual = "en_US", "en_US"
                self.riot.request.reset_mock()
                self.lcu.s.get.side_effect = failure
                with patch.object(self.service, "_wait", side_effect=lambda predicate, timeout: predicate()):
                    self.service.change("pt_BR")
                self.assertEqual([c.args[0] for c in self.mutations()], ["PUT", "DELETE"])
                self.assertEqual(self.service.status["stage"], "error")
                self.assertNotIn("test-secret", self.service.status["message"])

    def test_local_api_requests_refuse_redirects(self):
        self.riot.request.side_effect = lambda *args, **kwargs: response(status=302)
        self.service.change("pt_BR")
        self.assertEqual(self.service.status["stage"], "error")
        self.assertFalse(self.mutations())
        for call in self.riot.request.call_args_list + self.lcu.s.request.call_args_list:
            self.assertFalse(call.kwargs["allow_redirects"])
            self.assertEqual(call.kwargs["timeout"], 5)

    def test_invalid_ports_and_region_types_are_safe_errors(self):
        for port in ("65536", "0", "54321/path", "9" * 5000, "???"):
            with self.subTest(port=port[:20]):
                self.args = ["--riotclient-app-port=" + port, "--riotclient-auth-token=test-secret"]
                with self.assertRaises(LanguageChangeError):
                    self.service.options()
        self.args = ["--riotclient-app-port=54321", "--riotclient-auth-token=test-secret"]
        for region in (None, [], 123):
            with self.subTest(region=region):
                self.region = region
                with self.assertRaises(LanguageChangeError):
                    self.service.options()
        self.riot.request.assert_not_called()

    def test_shutdown_after_close_does_not_relaunch(self):
        def shut_down(predicate, timeout):
            self.service.stopped = lambda: True
            return True

        with patch.object(self.service, "_wait", side_effect=shut_down):
            self.service.change("pt_BR")
        self.assertEqual([c.args[0] for c in self.mutations()], ["PUT", "DELETE"])
        self.assertEqual(self.service.status["stage"], "error")
        self.assertIn("preference was saved", self.service.status["message"])

    def test_already_active_language_is_cached_without_restart(self):
        cache = Mock()
        cache.save.return_value = 3
        with patch.object(self.service, "_language_cache", return_value=cache):
            self.service.change("en_US")
        cache.save.assert_called_once_with("en_US")
        cache.restore.assert_not_called()
        self.assertFalse(self.mutations())


if __name__ == "__main__":
    unittest.main()
