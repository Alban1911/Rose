import json
import ssl
import unittest
from unittest.mock import AsyncMock, patch

from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatusCode

from party.network import relay_addresses, ws_relay


class FakeSocket:
    """A room connection that confirms protocol 2."""

    def __init__(self):
        self.response_headers = Headers({"X-Rose-Party-Protocol": "2"})
        self.closed = False

    async def send(self, message):
        pass

    async def close(self):
        self.closed = True


class FakeTcp:
    def __init__(self, address):
        self.address = address
        self.closed = False

    def close(self):
        self.closed = True


class RelayAddressFallbackTests(unittest.IsolatedAsyncioTestCase):
    """A network can block the relay at some of its addresses only (Spanish
    ISPs during LaLiga matches): Rose tries each of them."""

    def setUp(self):
        self.enterContext(patch.object(ws_relay, "RELAY_URL", "wss://relay.test"))
        self.enterContext(patch.object(ws_relay, "_ssl_contexts", lambda: ["store-1", "store-2"]))
        self.enterContext(patch.dict(relay_addresses._preferred, clear=True))
        self.system = AsyncMock(return_value=["198.51.100.1", "198.51.100.2"])
        self.doh = AsyncMock(return_value=[])
        self.enterContext(patch.object(relay_addresses, "system_addresses", self.system))
        self.enterContext(patch.object(relay_addresses, "doh_addresses", self.doh))
        # address -> exception raised when connecting to it
        self.tcp_failures = {}
        # address -> exceptions raised by successive handshakes on it
        self.handshake_failures = {}
        self.tcp_attempts = []
        self.handshakes = []
        self.relay = ws_relay.PartyRelay("a" * 32, 1, "Me", b"k" * 32)

        async def open_socket(address, port, timeout):
            self.tcp_attempts.append(address)
            if address in self.tcp_failures:
                raise self.tcp_failures[address]
            return FakeTcp(address)

        async def connect(url, **kwargs):
            self.handshakes.append(kwargs)
            failures = self.handshake_failures.get(getattr(kwargs.get("sock"), "address", None))
            if failures:
                raise failures.pop(0)
            return FakeSocket()

        self.enterContext(patch.object(relay_addresses, "open_socket", open_socket))
        self.enterContext(patch.object(ws_relay, "_RelayConnect", connect))

    async def test_a_blocked_address_falls_back_to_the_next_one_and_is_skipped_next_time(self):
        self.tcp_failures["198.51.100.1"] = ConnectionRefusedError(10061, "refused")

        self.assertTrue(await self.relay._open(1))
        self.assertEqual(self.tcp_attempts, ["198.51.100.1", "198.51.100.2"])
        self.assertEqual(self.handshakes[0]["sock"].address, "198.51.100.2")
        self.assertEqual(self.handshakes[0]["ssl"], "store-1")
        self.doh.assert_not_awaited()

        self.tcp_attempts.clear()
        self.assertTrue(await ws_relay.PartyRelay("b" * 32, 1, "Me", b"k" * 32)._open(1))
        self.assertEqual(self.tcp_attempts, ["198.51.100.2"])

    async def test_doh_addresses_are_tried_when_no_system_address_connects(self):
        for address in self.system.return_value:
            self.tcp_failures[address] = TimeoutError()
        self.doh.return_value = ["198.51.100.2", "203.0.113.7"]

        self.assertTrue(await self.relay._open(1))
        self.assertEqual(self.tcp_attempts, ["198.51.100.1", "198.51.100.2", "203.0.113.7"])
        self.assertEqual(self.handshakes[-1]["sock"].address, "203.0.113.7")

    async def test_a_name_that_does_not_resolve_anywhere_reports_dns(self):
        self.system.side_effect = OSError(11001, "getaddrinfo failed")

        self.assertFalse(await self.relay._open(1))
        self.doh.assert_awaited_once()
        self.assertIn("could not find the party server's address", self.relay.last_error)
        self.assertIn("WARP", self.relay.last_error)

    async def test_no_address_accepting_a_connection_reports_a_block(self):
        for address in self.system.return_value:
            self.tcp_failures[address] = ConnectionRefusedError(10061, "refused")

        self.assertFalse(await self.relay._open(1))
        self.assertIn("your network blocks the party server", self.relay.last_error)
        self.assertEqual(self.handshakes, [])

    async def test_cut_handshakes_report_filtering(self):
        for address in self.system.return_value:
            self.handshake_failures[address] = [ConnectionResetError(10054, "reset")]

        self.assertFalse(await self.relay._open(1))
        self.assertIn("network error (reset)", self.relay.last_error)
        self.assertIn("may be filtering the party server", self.relay.last_error)

    async def test_an_answer_from_the_relay_stops_trying_other_addresses(self):
        self.handshake_failures["198.51.100.1"] = [InvalidStatusCode(409, Headers())]

        self.assertFalse(await self.relay._open(1))
        self.assertEqual(self.tcp_attempts, ["198.51.100.1"])
        self.doh.assert_not_awaited()
        self.assertEqual(self.relay.last_error, "this party is full (10 players max)")

    async def test_each_trust_store_gets_its_own_connection_and_failed_ones_are_closed(self):
        failure = ssl.SSLCertVerificationError("certificate verify failed")
        failure.verify_message = "certificate has expired"
        self.handshake_failures["198.51.100.1"] = [failure]

        self.assertTrue(await self.relay._open(1))
        first, second = self.handshakes
        self.assertEqual((first["ssl"], second["ssl"]), ("store-1", "store-2"))
        self.assertTrue(first["sock"].closed)
        self.assertFalse(second["sock"].closed)
        self.assertEqual(self.tcp_attempts, ["198.51.100.1", "198.51.100.1"])

    async def test_a_remembered_address_that_fails_is_forgotten(self):
        relay_addresses.remember_address("relay.test", 443, "203.0.113.9")
        self.tcp_failures["203.0.113.9"] = ConnectionRefusedError(10061, "refused")

        self.assertTrue(await self.relay._open(1))
        self.assertEqual(self.tcp_attempts, ["203.0.113.9", "198.51.100.1"])
        self.assertEqual(relay_addresses.preferred_address("relay.test", 443), "198.51.100.1")

    async def test_an_ip_relay_url_is_connected_to_directly(self):
        with patch.object(ws_relay, "RELAY_URL", "wss://198.51.100.5"):
            self.assertTrue(await self.relay._open(1))
        self.system.assert_not_awaited()
        self.assertNotIn("sock", self.handshakes[0])


class DohAnswerTests(unittest.TestCase):
    def answer(self, records, status=0):
        return json.dumps({"Status": status, "Answer": records}).encode()

    def test_only_global_addresses_of_the_asked_type_are_kept(self):
        payload = self.answer([
            {"name": "relay.test", "type": 5, "data": "relay.cdn.test."},
            {"name": "relay.test", "type": 1, "data": "104.21.42.132"},
            {"name": "relay.test", "type": 1, "data": "0.0.0.0"},
            {"name": "relay.test", "type": 1, "data": "10.0.0.1"},
            {"name": "relay.test", "type": 1, "data": "not an address"},
            {"name": "relay.test", "type": 28, "data": "2606:4700:3030::6815:2a84"},
        ])
        self.assertEqual(relay_addresses._parse_doh_answer(payload, 1), ["104.21.42.132"])
        self.assertEqual(relay_addresses._parse_doh_answer(payload, 28), ["2606:4700:3030::6815:2a84"])

    def test_failed_or_malformed_answers_give_nothing(self):
        record = [{"type": 1, "data": "104.21.42.132"}]
        self.assertEqual(relay_addresses._parse_doh_answer(self.answer(record, status=3), 1), [])
        self.assertEqual(relay_addresses._parse_doh_answer(b"<html>blocked</html>", 1), [])
        self.assertEqual(relay_addresses._parse_doh_answer(b"[]", 1), [])


if __name__ == "__main__":
    unittest.main()
