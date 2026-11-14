import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlsplit

from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatusCode, SecurityError

from party.network import ws_relay


def members_message(*summoner_ids):
    return json.dumps({
        "type": "members",
        "members": [
            {"summoner_id": str(sid), "summoner_name": f"P{sid}", "member_key": f"{sid:064x}", "skin": None}
            for sid in summoner_ids
        ],
    })


REPLACED = json.dumps({"type": "replaced"})


class FakeSocket:
    """A room connection: yields the messages given, records what is sent."""

    def __init__(self, incoming=()):
        self.sent = []
        self.closed = False
        self.response_headers = Headers({"X-Rose-Party-Protocol": "2"})
        self._incoming = list(incoming)

    async def send(self, message):
        self.sent.append(message)

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._incoming:
            raise StopAsyncIteration
        return self._incoming.pop(0)


class RelayHandshakeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch.object(ws_relay, "RELAY_URL", "ws://127.0.0.1:8080"))
        self.room = "a" * 32
        self.summoner = (1 << 64) - 1
        self.key = b"k" * 32
        self.name = "José #NA"
        self.relay = ws_relay.PartyRelay(self.room, self.summoner, self.name, self.key)
        self.socket = FakeSocket()

    async def test_upgrade_authenticates_the_member_without_a_join_message(self):
        with patch.object(ws_relay, "_RelayConnect", return_value=self._return_socket()) as connect:
            self.assertTrue(await self.relay._open(1))
        query = parse_qs(urlsplit(connect.call_args.args[0]).query)
        headers = connect.call_args.kwargs["extra_headers"]
        self.assertEqual(query, {"key": [self.room], "v": [ws_relay.APP_VERSION], "p": ["2"]})
        self.assertRegex(headers["Authorization"], r"^Bearer [0-9a-f]{64}$")
        self.assertEqual(headers["X-Rose-Summoner-Id"], str(self.summoner))
        self.assertEqual(unquote(headers["X-Rose-Summoner-Name"]), self.name)
        self.assertEqual(self.socket.sent, [])

    async def _return_socket(self):
        return self.socket

    async def test_credential_is_stable_across_rooms_but_scoped_to_the_relay(self):
        other = ws_relay.PartyRelay("b" * 32, self.summoner, self.name, self.key)
        different_key = ws_relay.PartyRelay(self.room, self.summoner, self.name, b"x" * 32)

        async def authorization(relay):
            with patch.object(ws_relay, "_RelayConnect", return_value=self._return_socket()) as connect:
                self.assertTrue(await relay._open(1))
            return connect.call_args.kwargs["extra_headers"]["Authorization"]

        header = await authorization(self.relay)
        self.assertEqual(header, await authorization(other))
        self.assertNotEqual(header, await authorization(different_key))
        with patch.object(ws_relay, "RELAY_URL", "ws://127.0.0.1:8081"):
            self.assertNotEqual(header, await authorization(self.relay))

    async def test_an_unconfirmed_upgrade_is_closed(self):
        self.socket.response_headers = Headers()
        with patch.object(ws_relay, "_RelayConnect", return_value=self._return_socket()):
            self.assertFalse(await self.relay._open(1))
        self.assertTrue(self.socket.closed)
        self.assertEqual(self.socket.sent, [])
        self.assertIn("does not support authenticated connections", self.relay.last_error)

    async def test_identity_refusal_reports_another_installation_and_can_be_retried(self):
        async def reject(url, **kwargs):
            raise InvalidStatusCode(403, Headers())

        with patch.object(ws_relay, "_RelayConnect", reject):
            self.assertFalse(await self.relay._open(1))
        self.assertFalse(self.relay.permanently_refused)
        self.assertIn("from another Rose installation", self.relay.last_error)

    async def test_credentials_require_tls_away_from_loopback(self):
        with patch.object(ws_relay, "RELAY_URL", "ws://relay.test"), \
                patch.object(ws_relay, "_RelayConnect") as connect:
            self.assertFalse(await self.relay._open(1))
        connect.assert_not_called()

    def test_redirects_do_not_forward_the_credential(self):
        connect = ws_relay._RelayConnect.__new__(ws_relay._RelayConnect)
        with self.assertRaises(SecurityError):
            connect.handle_redirect("wss://elsewhere.test/room")

    async def test_received_decimal_ids_preserve_all_bits_and_our_own_identity(self):
        self.socket._incoming = [members_message(self.summoner)]
        await self.relay._receive(self.socket)
        self.assertEqual(self.relay.members[0]["summoner_id"], self.summoner)
        self.assertIsInstance(self.relay.members[0]["summoner_id"], int)
        self.assertFalse(self.relay._others_present())


class ReplacedEventTests(unittest.TestCase):
    """The relay tells a connection when the same player joined the room on
    another one, and stops listening to it without closing it."""

    def setUp(self):
        self.relay = ws_relay.PartyRelay("a" * 32, 1, "Me", b"k" * 32)
        self.connection_changes = []
        self.relay.set_callbacks(
            on_connection_changed=lambda relay: self.connection_changes.append(
                (relay.connected, relay.stopped, list(relay.members))
            ),
        )
        self.opens = 0

        async def open_(timeout):
            self.opens += 1
            self.relay._closing = True  # a reconnect attempt ends the test
            return False

        async def keepalive(ws):
            pass

        async def sleep(seconds):
            pass

        self.relay._open = open_
        self.relay._keepalive = keepalive
        self.enterContext(patch.object(ws_relay.asyncio, "sleep", sleep))

    def connect(self, socket):
        self.relay._ws = socket
        self.relay._connected = True

    def test_receiving_stops_at_the_replaced_event(self):
        socket = FakeSocket([members_message(1, 2), REPLACED, members_message(1, 2, 3)])
        self.connect(socket)

        asyncio.run(self.relay._receive(socket))

        self.assertEqual(len(socket._incoming), 1)  # nothing after it is read
        self.assertEqual([m["summoner_id"] for m in self.relay.members], [1, 2])

    def test_a_replaced_connection_stops_reconnecting_and_forgets_the_room(self):
        socket = FakeSocket([members_message(1, 2), REPLACED])
        self.connect(socket)

        asyncio.run(self.relay._run())

        self.assertEqual(self.opens, 0)
        self.assertTrue(self.relay.stopped)
        self.assertFalse(self.relay.connected)
        self.assertEqual(self.relay.members, [])
        self.assertEqual(self.connection_changes, [(False, True, [])])
        self.assertTrue(socket.closed)
        # The room already dropped us: no leave message
        self.assertNotIn("leave", [json.loads(m).get("type") for m in socket.sent])

    def test_nothing_is_published_once_replaced(self):
        socket = FakeSocket([REPLACED])
        self.connect(socket)
        self.relay.members = [{"summoner_id": 1}, {"summoner_id": 2}]

        asyncio.run(self.relay._receive(socket))
        asyncio.run(self.relay.send_state({"skin_id": 103001}))

        self.assertEqual(socket.sent, [])

    def test_a_connection_that_just_drops_still_reconnects(self):
        socket = FakeSocket([members_message(1, 2)])
        self.connect(socket)

        asyncio.run(self.relay._run())

        self.assertEqual(self.opens, 1)
        self.assertFalse(self.relay.stopped)
        self.assertEqual([m["summoner_id"] for m in self.relay.members], [1, 2])  # kept while reconnecting

    def test_older_relays_closing_with_the_reason_still_stop_it(self):
        socket = SimpleNamespace(close_reason="replaced")

        async def receive(ws):
            pass

        self.relay._receive = receive
        self.relay.members = [{"summoner_id": 2}]
        self.connect(socket)

        asyncio.run(self.relay._run())

        self.assertEqual(self.opens, 0)
        self.assertTrue(self.relay.stopped)
        self.assertEqual(self.relay.members, [])

    def test_a_new_connection_after_resume_is_listened_to_again(self):
        socket = FakeSocket([REPLACED])
        self.connect(socket)
        asyncio.run(self.relay._receive(socket))

        fresh = FakeSocket()

        async def connect(url, **kwargs):
            return fresh

        del self.relay._open  # the real one
        with patch.object(ws_relay, "RELAY_URL", "ws://127.0.0.1"), \
                patch.object(ws_relay, "_RelayConnect", connect):
            self.assertTrue(asyncio.run(self.relay._open(1.0)))

        self.relay.members = [{"summoner_id": 1}, {"summoner_id": 2}]
        asyncio.run(self.relay.send_state({"skin_id": 103001}))
        self.assertEqual([json.loads(m)["type"] for m in fresh.sent], ["skin"])


if __name__ == "__main__":
    unittest.main()
