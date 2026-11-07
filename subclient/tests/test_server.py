import base64
import json
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from subclient.server import COOKIE, SubclientServer, is_read_request, screen_wamp


class PolicyTests(unittest.TestCase):
    def test_only_reads_reach_the_real_client(self):
        self.assertTrue(is_read_request("GET"))
        self.assertTrue(is_read_request("head"))
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertFalse(is_read_request(method))

    def test_wamp_subscriptions_pass_and_calls_are_refused(self):
        self.assertEqual(screen_wamp('[5,"OnJsonApiEvent"]'), (True, None))
        self.assertEqual(screen_wamp('[6,"OnJsonApiEvent"]'), (True, None))
        forward, reply = screen_wamp('[2,"call-1","PostLolChampSelectV1SessionActionsByIdComplete"]')
        self.assertFalse(forward)
        self.assertEqual(json.loads(reply)[:2], [4, "call-1"])
        self.assertEqual(screen_wamp('[7,"topic",{}]'), (False, None))
        self.assertEqual(screen_wamp("not json"), (False, None))


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.upstream_calls = 0

        async def no_client():
            self.upstream_calls += 1
            return None

        server = SubclientServer(endpoint=no_client, league_dir=Path(tmp.name), plugins_dir=Path(tmp.name),
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

    async def test_the_key_becomes_a_cookie(self):
        response = await self.client.get("/bootstrap.html?key=secret", allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertEqual(response.cookies[COOKIE].value, "secret")
        self.assertEqual(response.cookies[COOKIE]["samesite"], "Strict")

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


if __name__ == "__main__":
    unittest.main()
