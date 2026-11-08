import asyncio
import base64
import json
import tempfile
import unittest
from pathlib import Path

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from subclient.server import LcuEndpoint, SubclientServer, is_read_request, screen_wamp


class PolicyTests(unittest.TestCase):
    def test_only_reads_reach_the_real_client(self):
        self.assertTrue(is_read_request("GET"))
        self.assertTrue(is_read_request("head"))
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertFalse(is_read_request(method))

    def test_wamp_subscriptions_pass_and_calls_are_refused(self):
        self.assertEqual(screen_wamp('[5,"OnJsonApiEvent"]'), (True, '[5, "OnJsonApiEvent"]'))
        self.assertEqual(screen_wamp('[6,"OnJsonApiEvent"]'), (True, '[6, "OnJsonApiEvent"]'))
        forward, reply = screen_wamp('[2,"call-1","PostLolChampSelectV1SessionActionsByIdComplete"]')
        self.assertFalse(forward)
        self.assertEqual(json.loads(reply)[:2], [4, "call-1"])
        self.assertEqual(screen_wamp('[7,"topic",{}]'), (False, None))
        self.assertEqual(screen_wamp("not json"), (False, None))

    def test_only_whole_numbers_are_message_types(self):
        for message in ('[true,"OnJsonApiEvent"]', '[5.0,"OnJsonApiEvent"]', '["5","OnJsonApiEvent"]'):
            self.assertEqual(screen_wamp(message), (False, None))


class FakeLcuEndpoint(LcuEndpoint):
    """The real client's API, served over plain HTTP by a test server."""

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/"


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.upstream_calls = 0

        async def no_client():
            self.upstream_calls += 1
            return None

        plugins = Path(tmp.name) / "plugins"
        (plugins / "ROSE-UI").mkdir(parents=True)
        (plugins / "ROSE-UI" / "index.js").write_text("ui", encoding="utf-8")
        (Path(tmp.name) / "secret.txt").write_text("secret", encoding="utf-8")
        self.server = server = SubclientServer(
            endpoint=no_client, league_dir=Path(tmp.name), plugins_dir=plugins,
            bridge_port_file=Path(tmp.name) / "bridge_port.txt", token="secret", title="t")
        app = server.make_app()
        app.on_startup.clear()
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.auth = {"Authorization": "Basic " + base64.b64encode(b"riot:secret").decode()}

    async def test_requests_need_the_key(self):
        response = await self.client.get("/lol-gameflow/v1/gameflow-phase")
        self.assertEqual(response.status, 401)
        response = await self.client.get("/bootstrap.html?key=wrong", allow_redirects=False)
        self.assertEqual(response.status, 401)
        response = await self.client.get("/bootstrap.html?key=%C3%A9", allow_redirects=False)
        self.assertEqual(response.status, 401)

    async def test_garbled_credentials_are_refused_not_crashed_on(self):
        for header in (b"Authorization: Basic \xff\xfe", b"Cookie: " + self.server.cookie.encode() + b"=\xff"):
            reader, writer = await asyncio.open_connection(self.client.host, self.client.port)
            writer.write(b"GET /lol-gameflow/v1/gameflow-phase HTTP/1.1\r\nHost: x\r\n" + header + b"\r\n\r\n")
            await writer.drain()
            status = await reader.readline()
            writer.close()
            await writer.wait_closed()
            self.assertIn(b" 401 ", status, header)

    async def test_the_key_becomes_this_subclients_cookie(self):
        response = await self.client.get("/bootstrap.html?key=secret", allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertEqual(response.cookies[self.server.cookie].value, "secret")
        self.assertEqual(response.cookies[self.server.cookie]["samesite"], "Strict")
        other = SubclientServer(endpoint=None, league_dir=Path("."), plugins_dir=Path("."),
                                bridge_port_file=Path("."), token="other", title="t")
        self.assertNotEqual(other.cookie, self.server.cookie)

    async def test_websockets_from_other_pages_are_refused(self):
        upgrade = {**self.auth, "Upgrade": "websocket", "Connection": "Upgrade"}
        response = await self.client.get("/", headers={**upgrade, "Origin": "http://127.0.0.1:1"})
        self.assertEqual(response.status, 403)
        own = f"http://{self.client.host}:{self.client.port}"
        response = await self.client.get("/", headers={**upgrade, "Origin": own})
        self.assertEqual(response.status, 503)  # reached the proxy, which found no client

    async def test_only_this_worktrees_plugin_files_are_served(self):
        response = await self.client.get("/rose-plugins/ROSE-UI/index.js", headers=self.auth)
        self.assertEqual(await response.text(), "ui")
        for path in ("/rose-plugins/..%2fsecret.txt", "/rose-plugins/ROSE-UI/..%2f..%2fsecret.txt"):
            response = await self.client.get(path, headers=self.auth)
            self.assertEqual(response.status, 404, path)

    async def test_writes_never_reach_the_real_client(self):
        response = await self.client.patch("/lol-champ-select/v1/session/my-selection", headers=self.auth, json={})
        self.assertEqual(response.status, 403)
        response = await self.client.post("/telemetry/v1/events/screen_load", headers=self.auth, json={})
        self.assertEqual(response.status, 204)
        self.assertEqual(self.upstream_calls, 0)

    async def test_reads_without_a_client_fail_instead_of_looking_elsewhere(self):
        response = await self.client.get("/lol-gameflow/v1/gameflow-phase", headers=self.auth)
        self.assertEqual(response.status, 503)
        self.assertEqual(self.upstream_calls, 1)


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    """Against a fake real client."""

    async def asyncSetUp(self):
        self.seen_headers = None
        self.seen_messages = []
        self.lcu_socket_closed = asyncio.Event()

        async def api(request):
            self.seen_headers = dict(request.headers)
            return web.json_response({"phase": "ChampSelect"}, headers={"Set-Cookie": "lcu=1", "X-Riot": "1"})

        async def events(request):
            socket = web.WebSocketResponse(protocols=("wamp",))
            await socket.prepare(request)
            async for message in socket:
                self.seen_messages.append(message.data)
            self.lcu_socket_closed.set()
            return socket

        async def breaks_off(request):
            response = web.StreamResponse(headers={"Content-Length": "100"})
            await response.prepare(request)
            await response.write(b"partial")
            request.transport.close()
            return response

        lcu = web.Application()
        lcu.router.add_get("/", events)
        lcu.router.add_get("/lol-gameflow/v1/session", api)
        lcu.router.add_get("/lol-game-data/assets/big.png", breaks_off)
        self.lcu = TestServer(lcu)
        await self.lcu.start_server()
        self.addAsyncCleanup(self.lcu.close)
        endpoint = FakeLcuEndpoint(pid=1, port=self.lcu.port, password="lcu-password")
        self.lcu_auth = endpoint.authorization

        async def real_client():
            return endpoint

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        server = SubclientServer(endpoint=real_client, league_dir=Path(tmp.name), plugins_dir=Path(tmp.name),
                                 bridge_port_file=Path(tmp.name) / "bridge_port.txt", token="secret", title="t")
        app = server.make_app()
        app.on_startup.clear()
        server._session = aiohttp.ClientSession(auto_decompress=False)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.auth = {"Authorization": "Basic " + base64.b64encode(b"riot:secret").decode()}

    async def test_reads_go_out_with_the_real_clients_password_only(self):
        response = await self.client.get("/lol-gameflow/v1/session", headers={**self.auth, "Cookie": "x=1"})
        self.assertEqual(await response.json(), {"phase": "ChampSelect"})
        self.assertEqual(self.seen_headers["Authorization"], self.lcu_auth)
        self.assertNotIn("Cookie", self.seen_headers)
        self.assertNotIn("Set-Cookie", response.headers)
        self.assertNotIn("X-Riot", response.headers)

    async def test_a_reply_cut_off_by_the_real_client_is_cut_off_here_too(self):
        with self.assertNoLogs("aiohttp.server", level="ERROR"):
            response = await self.client.get("/lol-game-data/assets/big.png", headers=self.auth)
            with self.assertRaises(aiohttp.ClientPayloadError):
                await response.read()

    async def test_calls_on_the_event_socket_get_an_error_and_stay_here(self):
        async with self.client.ws_connect("/", headers=self.auth, protocols=("wamp",)) as socket:
            await socket.send_str('[2,"call-1","PostLolLobbyV2Lobby"]')
            reply = json.loads(await asyncio.wait_for(socket.receive_str(), 5))
            self.assertEqual(reply[:2], [4, "call-1"])
            await socket.send_str('[5,"OnJsonApiEvent"]')
        await asyncio.wait_for(self.lcu_socket_closed.wait(), 5)  # closing the UI's socket closes the real one
        self.assertEqual(self.seen_messages, ['[5, "OnJsonApiEvent"]'])


if __name__ == "__main__":
    unittest.main()
