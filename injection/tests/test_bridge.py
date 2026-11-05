import json
import socket
import threading
import time
import unittest
from unittest.mock import patch

from injection.tools import bridge

REAL_TOKEN_CANDIDATES = bridge.token_candidates  # before TokenTestCase patches it
from injection.tools.bridge import (
    BridgeCommandError,
    BridgeUnavailable,
    LtkBridge,
    discover_port,
    find_bridge,
)


class FakeBridgeServer:
    """A one-request-per-connection server speaking the LTKBridge protocol"""

    def __init__(self, responder, answer=True):
        self.responder = responder
        self.answer = answer
        self.requests = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                buf = b""
                while b"\n" not in buf:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                if not buf:
                    continue
                request = json.loads(buf.split(b"\n", 1)[0].decode("utf-8", "replace"))
                self.requests.append(request)
                if self.answer:
                    conn.sendall((json.dumps(self.responder(request)) + "\n").encode("utf-8"))

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def hello_responder(request, pid=1234):
    if request.get("cmd") == "hello":
        return {"ok": True, "service": "LTKBridge", "pid": pid}
    return {"ok": False, "error": "unsupported"}


def dead_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class TokenTestCase(unittest.TestCase):
    """The published token is the one the tests' bridges expect"""

    token = "tok"

    def setUp(self):
        token_patch = patch.object(bridge, "read_token", side_effect=lambda: self.token)
        token_patch.start()
        self.addCleanup(token_patch.stop)
        # Never this PC's own published tokens
        candidates_patch = patch.object(bridge, "token_candidates", return_value=[])
        candidates_patch.start()
        self.addCleanup(candidates_patch.stop)


class BridgeRequestTests(TokenTestCase):
    def setUp(self):
        super().setUp()
        self.server = FakeBridgeServer(hello_responder)
        self.addCleanup(self.server.close)

    def test_hello_returns_the_service_identity(self):
        answer = LtkBridge(self.server.port).hello()

        self.assertTrue(answer["ok"])
        self.assertEqual(answer["service"], "LTKBridge")
        self.assertEqual(self.server.requests, [{"cmd": "hello"}])

    def test_ok_commands_raise_when_the_bridge_refuses(self):
        server = FakeBridgeServer(lambda request: {"ok": False, "error": "boom"})
        self.addCleanup(server.close)

        with self.assertRaises(BridgeCommandError) as caught:
            LtkBridge(server.port).toggle("some-mod", True)

        self.assertIn("boom", str(caught.exception))

    def test_unreachable_port_reports_bridge_unavailable(self):
        with self.assertRaises(BridgeUnavailable):
            LtkBridge(dead_port()).hello()

    def test_alive_is_false_when_nothing_answers(self):
        self.assertFalse(LtkBridge(dead_port()).alive())

    def test_commands_carry_the_token_and_hello_does_not(self):
        LtkBridge(self.server.port).hello()
        LtkBridge(self.server.port).request({"cmd": "status"})

        self.assertNotIn("token", self.server.requests[0])
        self.assertEqual(self.server.requests[1]["token"], "tok")

    def test_a_refused_token_is_read_again_once(self):
        tokens = iter(["old", "new"])
        server = FakeBridgeServer(
            lambda request: {"ok": True} if request.get("token") == "new"
            else {"ok": False, "error": "unauthorized: missing or wrong token"}
        )
        self.addCleanup(server.close)

        with patch.object(bridge, "read_token", side_effect=lambda: next(tokens)):
            answer = LtkBridge(server.port).request({"cmd": "status"})

        self.assertTrue(answer["ok"])
        self.assertEqual([r["token"] for r in server.requests], ["old", "new"])

    def test_every_published_token_is_tried_when_the_first_is_stale(self):
        """#443: a stale token.txt was read first while the running bridge had
        published its token elsewhere: every command was refused"""
        server = FakeBridgeServer(
            lambda request: {"ok": True} if request.get("token") == "live"
            else {"ok": False, "error": "unauthorized: missing or wrong token"}
        )
        self.addCleanup(server.close)

        with patch.object(bridge, "read_token", return_value="stale"), \
                patch.object(bridge, "token_candidates",
                             return_value=[("a\\token.txt", "stale"), ("HKCU\\Software\\LTKBridge", "live")]):
            client = LtkBridge(server.port)
            first = client.request({"cmd": "status"})
            second = client.request({"cmd": "status"})

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual([r["token"] for r in server.requests], ["stale", "live", "live"])

    def test_no_working_token_returns_the_refusal(self):
        server = FakeBridgeServer(lambda request: {"ok": False, "error": "unauthorized: missing or wrong token"})
        self.addCleanup(server.close)

        with patch.object(bridge, "read_token", return_value="a"), \
                patch.object(bridge, "token_candidates", return_value=[("x", "a"), ("y", "b")]):
            answer = LtkBridge(server.port).request({"cmd": "status"})

        self.assertFalse(answer["ok"])
        self.assertEqual([r["token"] for r in server.requests], ["a", "b"])

    def test_published_tokens_are_listed_once_each(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            (Path(first) / "token.txt").write_text("stale\n", encoding="ascii")
            (Path(second) / "token.txt").write_text("live\n", encoding="ascii")
            dirs = [Path(first), Path(second), Path(first) / "missing"]
            with patch.object(bridge, "_bridge_dirs", return_value=dirs):
                found = REAL_TOKEN_CANDIDATES()  # the class patches the module's copy

        tokens = [token for _, token in found]
        self.assertEqual(tokens[:2], ["stale", "live"])  # files first, in their order
        self.assertEqual(len(tokens), len(set(tokens)))

    def test_a_command_without_an_answer_is_not_sent_again(self):
        # An import whose answer is lost may still have run: sending it
        # again would install a second copy
        server = FakeBridgeServer(lambda request: {"ok": True}, answer=False)
        self.addCleanup(server.close)

        with self.assertRaises(BridgeUnavailable):
            LtkBridge(server.port).import_fantome(r"C:\mods\skin.fantome")

        self.assertEqual(len(server.requests), 1)

    def test_wait_for_bridge_returns_when_the_port_comes_up(self):
        with patch.object(bridge, "find_bridge", return_value=(self.server.port, {"pid": 1234})):
            waited = LtkBridge.wait_for_bridge(timeout=5)

        self.assertEqual(waited.port, self.server.port)
        self.assertEqual(waited.pid, 1234)

    def test_wait_for_bridge_gives_up_when_nothing_comes_up(self):
        with patch.object(bridge, "find_bridge", return_value=None):
            with self.assertRaises(BridgeUnavailable):
                LtkBridge.wait_for_bridge(timeout=0.2)

    def test_wait_for_bridge_stops_when_cancelled(self):
        began = time.monotonic()
        with patch.object(bridge, "find_bridge", return_value=None):
            with self.assertRaises(BridgeUnavailable):
                LtkBridge.wait_for_bridge(timeout=30, cancelled=lambda: True)

        self.assertLess(time.monotonic() - began, 2)

    def test_kill_tolerates_the_connection_dropping(self):
        # The manager answers kill by exiting, so the reply may never arrive
        server = FakeBridgeServer(hello_responder)
        port = server.port
        server.close()

        answer = LtkBridge(port).kill()

        self.assertTrue(answer["ok"])


class DiscoverPortTests(unittest.TestCase):
    def test_the_registry_port_is_used_when_the_bridge_answers(self):
        server = FakeBridgeServer(hello_responder)
        self.addCleanup(server.close)

        with patch.object(bridge, "_port_from_registry", return_value=server.port):
            port = discover_port()

        self.assertEqual(port, server.port)

    def test_a_bridge_in_another_process_is_skipped(self):
        server = FakeBridgeServer(hello_responder)
        self.addCleanup(server.close)

        with patch.object(bridge, "_port_from_registry", return_value=server.port), \
                patch.object(bridge, "_port_from_file", return_value=None), \
                patch.object(bridge, "_listening_ports", return_value=[]):
            self.assertIsNone(find_bridge(expected_pid=9999))
            self.assertEqual(find_bridge(expected_pid=1234)[0], server.port)

    def test_the_range_is_scanned_at_once(self):
        # Windows takes about a second to refuse each closed loopback port:
        # tried one after another, twenty of them took eight seconds
        server = FakeBridgeServer(hello_responder)
        self.addCleanup(server.close)
        closed = [dead_port() for _ in range(5)]

        began = time.monotonic()
        listening = bridge._listening_ports(closed + [server.port])

        self.assertEqual(listening, [server.port])
        self.assertLess(time.monotonic() - began, 1.0)

    def test_a_stale_registry_port_falls_through_to_a_scan(self):
        server = FakeBridgeServer(hello_responder)
        self.addCleanup(server.close)
        stale = server.port + 1000  # nothing answers there

        with patch.object(bridge, "_port_from_registry", return_value=stale), \
                patch.object(bridge, "_port_from_file", return_value=None), \
                patch.object(bridge, "PORT_RANGE_START", server.port), \
                patch.object(bridge, "PORT_RANGE_END", server.port + 1):
            port = discover_port()

        self.assertEqual(port, server.port)

    def test_nothing_answers_returns_none(self):
        with patch.object(bridge, "_port_from_registry", return_value=None), \
                patch.object(bridge, "_port_from_file", return_value=None), \
                patch.object(bridge, "_probe", return_value=None):
            self.assertIsNone(discover_port())


class CommandShapeTests(TokenTestCase):
    """Rose sends the commands the LTF controller protocol defines"""

    def setUp(self):
        super().setUp()
        self.server = FakeBridgeServer(lambda request: {"ok": True, "library": []})
        self.addCleanup(self.server.close)
        self.bridge = LtkBridge(self.server.port)

    def test_import_sends_the_path_and_name(self):
        self.bridge.import_fantome(r"C:\mods\skin.fantome", name="My Skin")

        request = self.server.requests[-1]
        self.assertEqual(request["cmd"], "import")
        self.assertEqual(request["path"], r"C:\mods\skin.fantome")
        self.assertEqual(request["name"], "My Skin")
        self.assertNotIn("gamePath", request)  # the archive is installed as it is

    def test_import_bytes_sends_base64_data(self):
        self.bridge.import_fantome_bytes(b"fantome-bytes", name="My Skin")

        request = self.server.requests[-1]
        self.assertEqual(request["cmd"], "import")
        self.assertEqual(request["data_b64"], "ZmFudG9tZS1ieXRlcw==")
        self.assertEqual(request["name"], "My Skin")

    def test_toggle_and_uninstall_send_the_target(self):
        self.bridge.toggle("mod-id", False)
        self.bridge.uninstall("mod-id")

        self.assertEqual(self.server.requests[-2], {"cmd": "toggle", "target": "mod-id", "enabled": False, "token": "tok"})
        self.assertEqual(self.server.requests[-1], {"cmd": "uninstall", "target": "mod-id", "token": "tok"})

    def test_library_reads_the_installed_mods(self):
        entries = [{"id": "one", "displayName": "Skin"}]

        with patch.object(self.bridge, "list_mods", return_value={"ok": True, "library": entries}):
            self.assertEqual(self.bridge.library(), entries)

    def test_a_broken_library_answer_raises(self):
        # An empty list would read as "nothing installed"
        with patch.object(self.bridge, "list_mods", return_value={"ok": False, "raw": {"error": "CDP busy"}}):
            with self.assertRaises(BridgeCommandError):
                self.bridge.library()

    def test_a_failed_command_names_the_nested_error(self):
        server = FakeBridgeServer(
            lambda request: {"ok": False, "response": {"ok": False, "error": {"code": "BUSY", "message": "patcher busy"}}}
        )
        self.addCleanup(server.close)

        with self.assertRaises(BridgeCommandError) as caught:
            LtkBridge(server.port).start_patcher()

        self.assertIn("patcher busy", str(caught.exception))

    def test_a_patcher_refusal_names_its_kind_and_ltk_wording(self):
        """LTK's patcher errors carry a kind, not a message: "PATCHER" alone
        told nobody that League was set to run as administrator (#430)"""
        refusals = {
            "LEAGUE_ELEVATED": ({"kind": "LEAGUE_ELEVATED"}, "League is set to run as administrator"),
            "MANAGER_ELEVATED": ({"kind": "MANAGER_ELEVATED"}, "LTK Manager is running as administrator"),
            "DLL_UNAVAILABLE": ({"kind": "DLL_UNAVAILABLE", "reason": "NETWORK"}, "no patcher DLL is available: NETWORK"),
            "INJECTION_FAILED (HOST)": (
                {"kind": "INJECTION_FAILED", "stage": "HOST", "message": "host stdout closed"}, "host stdout closed"
            ),
        }
        for kind, (error, wording) in refusals.items():
            with self.subTest(kind=kind):
                server = FakeBridgeServer(lambda request, error=error: {
                    "ok": False, "response": {"ok": False, "error": {"code": "PATCHER", "error": error}},
                })
                self.addCleanup(server.close)

                with self.assertRaises(BridgeCommandError) as caught:
                    LtkBridge(server.port).start_patcher()

                self.assertIn(f"PATCHER {kind}: ", str(caught.exception))
                self.assertIn(wording, str(caught.exception))

    def test_other_ltk_errors_keep_their_fields(self):
        self.assertEqual(bridge._error_text({"ok": False, "error": {"code": "IO", "detail": "disk full"}}), "IO: disk full")
        self.assertEqual(bridge._error_text({"ok": False, "error": {"code": "MOD_NOT_FOUND", "id": "x"}}),
                         'MOD_NOT_FOUND {"id": "x"}')
        self.assertEqual(bridge._error_text({"ok": False, "error": "cdp unavailable"}), "cdp unavailable")

    def test_patcher_commands(self):
        self.bridge.start_patcher()
        self.bridge.stop_patcher()
        self.bridge.patcher_status()

        self.assertEqual([r["cmd"] for r in self.server.requests], ["start_patcher", "stop_patcher", "patcher_status"])


if __name__ == "__main__":
    unittest.main()
