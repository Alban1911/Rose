import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from party.network import ws_relay


def members_message(*summoner_ids):
    return json.dumps({
        "type": "members",
        "members": [{"summoner_id": sid, "summoner_name": f"P{sid}", "skin": None} for sid in summoner_ids],
    })


REPLACED = json.dumps({"type": "replaced"})


class FakeSocket:
    """A room connection: yields the messages given, records what is sent."""

    def __init__(self, incoming=()):
        self.sent = []
        self.closed = False
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


class ReplacedEventTests(unittest.TestCase):
    """The relay tells a connection when the same player joined the room on
    another one, and stops listening to it without closing it."""

    def setUp(self):
        self.relay = ws_relay.PartyRelay("a" * 32, 1, "Me")
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
        with patch.object(ws_relay, "RELAY_URL", "ws://relay.test"), \
                patch.object(ws_relay.websockets, "connect", connect):
            self.assertTrue(asyncio.run(self.relay._open(1.0)))

        self.relay.members = [{"summoner_id": 1}, {"summoner_id": 2}]
        asyncio.run(self.relay.send_state({"skin_id": 103001}))
        self.assertEqual([json.loads(m)["type"] for m in fresh.sent], ["join", "skin"])


if __name__ == "__main__":
    unittest.main()
