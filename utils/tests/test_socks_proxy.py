"""A SOCKS system proxy must not fail Rose's downloads (#454)."""

import unittest

import requests
from requests.adapters import HTTPAdapter


class SocksProxyTests(unittest.TestCase):
    def test_requests_can_go_through_a_socks_proxy(self):
        # Without PySocks this raises InvalidSchema("Missing dependencies for
        # SOCKS support"), which failed every skin download behind a SOCKS proxy
        try:
            manager = HTTPAdapter().proxy_manager_for("socks5h://127.0.0.1:1080")
        except requests.exceptions.InvalidSchema as e:
            self.fail(f"SOCKS proxies are unsupported: {e}")

        self.assertEqual(type(manager).__name__, "SOCKSProxyManager")


if __name__ == "__main__":
    unittest.main()
