import unittest

from pengu.core.http_handler import HTTPHandler
from utils.core.security import is_loopback_host


class HostHeaderTests(unittest.TestCase):
    """A rebound DNS name resolving to 127.0.0.1 is same-origin for the page,
    so the browser sends no Origin: the Host header is the only tell"""

    def setUp(self):
        self.handler = HTTPHandler(50000)

    def test_foreign_host_is_forbidden(self):
        status, _, _ = self.handler.handle_request("/port", {"Host": "evil.example:50000"})
        self.assertEqual(status, 403)

    def test_loopback_hosts_are_served(self):
        for host in ("127.0.0.1:50000", "localhost:50000", "[::1]:50000"):
            with self.subTest(host=host):
                status, _, body = self.handler.handle_request("/port", {"Host": host})
                self.assertEqual(status, 200)
                self.assertEqual(body, b"50000")

    def test_missing_host_is_unchanged(self):
        status, _, _ = self.handler.handle_request("/port", {})
        self.assertEqual(status, 200)

    def test_is_loopback_host(self):
        for host in ("127.0.0.1", "127.0.0.1:50000", "localhost", "LocalHost:1", "::1", "[::1]", "[::1]:50000"):
            with self.subTest(host=host):
                self.assertTrue(is_loopback_host(host))
        for host in (None, "", "evil.example", "evil.example:50000", "127.0.0.1.evil.example", "[::1", "localhost.evil.example:80"):
            with self.subTest(host=host):
                self.assertFalse(is_loopback_host(host))


if __name__ == "__main__":
    unittest.main()
