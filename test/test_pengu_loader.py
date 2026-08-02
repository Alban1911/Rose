import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from config import WS_NO_CLIENT_RETRY_DELAY
from injection.mods.storage import ModStorageService
from pengu.communication.message_handler import MessageHandler
from threads.websocket.websocket_connection import WebSocketConnection

from pengu.integration import activation, runtime, session
from pengu.integration.models import ActivationErrorKind, ActivationStage, PenguStatus

from pengu.integration.registry import (
    DEBUGGER_VALUE,
    IFEO_PATH,
    KEY_CREATE_SUB_KEY,
    KEY_QUERY_VALUE,
    KEY_SET_VALUE,
    TARGET_NAME,
    FakeRegistryApi,
)


class DirectPenguIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.core = self.root / "core.dll"
        self.core.write_bytes(b"test core")
        self.target_path = IFEO_PATH + "\\" + TARGET_NAME

        self.registry = FakeRegistryApi()
        self.registry.values[IFEO_PATH] = {}

        self.session_file = self.root / "state" / "pengu_session.json"
        self.active_flag = self.root / "state" / "pengu_active.flag"

        self.patches = [
            patch.object(runtime, "prepare_runtime", return_value=self.root),
            patch.object(runtime, "get_runtime_dir", return_value=self.root),
            patch.object(runtime, "get_core_path", return_value=self.core),
            patch.object(runtime, "write_pengu_config", return_value=b""),
            patch.object(runtime, "snapshot_rose_config", return_value=b""),
            patch.object(runtime, "write_rose_config", return_value=b""),
            patch.object(runtime, "restore_rose_config"),
            patch.object(activation, "is_league_running", return_value=False),
            patch.object(session, "SESSION_FILE", self.session_file),
            patch.object(session, "ACTIVE_FLAG", self.active_flag),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_debugger_command_and_path_parser(self):
        command = activation.build_debugger_command(Path(r"C:\Rose\Pengu Loader\core.dll"))
        self.assertEqual(command, r'rundll32 "C:\Rose\Pengu Loader\core.dll", #6000')
        self.assertFalse(command.endswith(" "))
        self.assertEqual(
            activation.extract_quoted_path(command),
            r"C:\Rose\Pengu Loader\core.dll",
        )
        self.assertIsNone(activation.extract_quoted_path("not-rundll32 command"))

    def test_activation_uses_exact_access_masks(self):
        result = activation.activate(r"C:\League", registry=self.registry)
        self.assertTrue(result)

        self.assertIn((IFEO_PATH, KEY_CREATE_SUB_KEY), self.registry.access_log)
        self.assertIn((self.target_path, KEY_SET_VALUE), self.registry.access_log)
        self.assertIn((self.target_path, KEY_QUERY_VALUE), self.registry.access_log)

        self.assertNotIn((IFEO_PATH, KEY_SET_VALUE), self.registry.access_log)
        self.assertEqual(
            self.registry.values[self.target_path][DEBUGGER_VALUE],
            f'rundll32 "{self.core}", #6000',
        )

    def test_deactivation_deletes_only_debugger(self):
        activation.activate(r"C:\League", registry=self.registry)
        self.registry.values[self.target_path]["RoseSentinel"] = "preserve-me"

        result = activation.deactivate(registry=self.registry)

        self.assertTrue(result)
        self.assertIn(self.target_path, self.registry.values)
        self.assertNotIn(DEBUGGER_VALUE, self.registry.values[self.target_path])
        self.assertEqual(
            self.registry.values[self.target_path]["RoseSentinel"],
            "preserve-me",
        )
        self.assertIn((self.target_path, KEY_SET_VALUE), self.registry.access_log)

    def test_missing_debugger_is_idempotent(self):
        self.registry.values[self.target_path] = {"RoseSentinel": "preserve-me"}

        result = activation.deactivate(registry=self.registry)

        self.assertTrue(result)
        self.assertEqual(self.registry.values[self.target_path]["RoseSentinel"], "preserve-me")

    def test_foreign_debugger_is_not_overwritten(self):
        foreign = r'rundll32 "C:\Other\core.dll", #6000'
        self.registry.values[self.target_path] = {
            DEBUGGER_VALUE: foreign,
            "RoseSentinel": "preserve-me",
        }

        result = activation.activate(r"C:\League", registry=self.registry)

        self.assertFalse(result)
        self.assertEqual(result.error_kind, ActivationErrorKind.CONFLICT)
        self.assertEqual(self.registry.values[self.target_path][DEBUGGER_VALUE], foreign)
        self.assertEqual(self.registry.values[self.target_path]["RoseSentinel"], "preserve-me")

    def test_registry_failure_stops_before_config_write(self):
        self.registry.failures["RegSetValueExW"] = 5

        result = activation.activate(r"C:\League", registry=self.registry)

        self.assertFalse(result)
        self.assertEqual(result.stage, ActivationStage.SET_DEBUGGER)
        runtime.write_rose_config.assert_not_called()

    def test_config_failure_rolls_back_registry_activation(self):
        runtime.write_rose_config.side_effect = OSError("config write failed")

        result = activation.activate(r"C:\League", registry=self.registry)

        self.assertFalse(result)
        self.assertEqual(result.stage, ActivationStage.WRITE_ROSE_CONFIG)
        self.assertEqual(self.registry.values.get(self.target_path, {}), {})
        runtime.restore_rose_config.assert_called_once()

    def test_activation_creates_owned_session(self):
        result = activation.activate_on_start(
            r"C:\League",
            registry=self.registry,
        )

        self.assertTrue(result)
        state = session.read_session()
        self.assertIsNotNone(state)
        self.assertFalse(state["pengu_was_active_before_rose"])
        self.assertTrue(state["rose_activated_pengu"])

    def test_startup_restarts_running_league_after_activation(self):
        activation.is_league_running.return_value = True
        with patch.object(activation, "restart_client", return_value=True) as restart:
            result = activation.activate_on_start(
                r"C:\League",
                registry=self.registry,
            )

        self.assertTrue(result)
        restart.assert_called_once_with(None)
        self.addCleanup(session.clear_session)

    def test_websocket_waits_quietly_when_league_is_closed(self):
        connection = WebSocketConnection(Mock(), Mock(stop=False))
        with patch.object(connection._stop_event, "wait", return_value=False) as wait:
            with self.assertLogs(level="INFO") as logs:
                self.assertFalse(connection._wait_before_retry("LCU lockfile is not ready"))
                self.assertFalse(connection._wait_before_retry("LCU lockfile is not ready"))

        self.assertEqual(wait.call_count, 2)
        self.assertEqual(wait.call_args_list[0].args, (WS_NO_CLIENT_RETRY_DELAY,))
        self.assertEqual(wait.call_args_list[1].args, (WS_NO_CLIENT_RETRY_DELAY,))
        self.assertEqual(
            sum("League Client is not running" in message for message in logs.output),
            1,
        )
        self.assertFalse(any("retrying in" in message for message in logs.output))
    def test_preexisting_rose_activation_is_preserved(self):
        self.registry.values[self.target_path] = {
            DEBUGGER_VALUE: f'rundll32 "{self.core}", #6000'
        }

        result = activation.activate_on_start(
            r"C:\League",
            registry=self.registry,
        )

        self.assertTrue(result)
        state = session.read_session()
        self.assertTrue(state["pengu_was_active_before_rose"])
        self.assertFalse(state["rose_activated_pengu"])

        restored = activation.restore_after_rose(registry=self.registry)
        self.assertTrue(restored)
        self.assertIn(DEBUGGER_VALUE, self.registry.values[self.target_path])

    def test_deactivation_config_failure_rolls_back_registry(self):
        activation.activate(r"C:\League", registry=self.registry)
        runtime.write_rose_config.side_effect = OSError("config write failed")

        result = activation.deactivate(registry=self.registry)

        self.assertFalse(result)
        self.assertEqual(result.stage, ActivationStage.WRITE_ROSE_CONFIG)
        self.assertFalse(result.config_updated)
        self.assertEqual(
            self.registry.values[self.target_path][DEBUGGER_VALUE],
            f'rundll32 "{self.core}", #6000',
        )
        runtime.restore_rose_config.assert_called_once()

    def test_deactivation_verification_failure_rolls_back_registry(self):
        activation.activate(r"C:\League", registry=self.registry)

        with patch.object(
            activation,
            "get_status",
            side_effect=[PenguStatus.ACTIVE, PenguStatus.UNKNOWN],
        ):
            result = activation.deactivate(registry=self.registry)

        self.assertFalse(result)
        self.assertEqual(result.stage, ActivationStage.VERIFY_STATE)
        self.assertEqual(result.error_kind, ActivationErrorKind.OTHER)
        self.assertTrue(result.registry_active)
        self.assertFalse(result.config_updated)
        self.assertIn(DEBUGGER_VALUE, self.registry.values[self.target_path])
        runtime.restore_rose_config.assert_called_once()

    def test_cleanup_deactivates_owned_session(self):
        activation.activate_on_start(r"C:\League", registry=self.registry)

        result = activation.restore_after_rose(registry=self.registry)

        self.assertTrue(result)
        self.assertFalse(session.recovery_present())
        self.assertNotIn(DEBUGGER_VALUE, self.registry.values[self.target_path])

    def test_direct_integration_contains_no_process_launcher(self):
        for path in Path("pengu/integration").glob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("subprocess", source)
            self.assertNotIn("PENGU_EXE", source)

    def test_restart_uses_lcu_post(self):
        response = Mock(status_code=200)
        lcu = Mock(ok=True)
        lcu.post.return_value = response

        self.assertTrue(activation.restart_client(lcu))
        lcu.post.assert_called_once_with(
            "/riotclient/kill-and-restart-ux",
            timeout=5.0,
        )

    def test_plugin_listing_and_toggle_state(self):
        plugin_dir = self.root / "plugins" / "ExamplePlugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "index.js").write_text("plugin", encoding="utf-8")

        self.assertEqual(
            runtime.list_plugins(self.root),
            [{"name": "ExamplePlugin", "enabled": True}],
        )
        self.assertTrue(runtime.set_plugin_enabled("ExamplePlugin", False, self.root))
        self.assertTrue((plugin_dir / "index.js_").exists())
        self.assertFalse((plugin_dir / "index.js").exists())

        self.assertTrue(runtime.set_plugin_enabled("ExamplePlugin", True, self.root))
        self.assertTrue((plugin_dir / "index.js").exists())
        self.assertFalse((plugin_dir / "index.js_").exists())
        self.assertFalse(runtime.set_plugin_enabled("..\\ExamplePlugin", False, self.root))

    def test_refresh_client_message_restarts_lcu(self):
        handler = MessageHandler(
            None,
            None,
            None,
            None,
            None,
            mod_storage=Mock(),
        )
        with patch(
            "pengu.communication.message_handler.restart_client",
            return_value=True,
        ) as restart:
            handler.handle_message(
                '{"type": "refresh-client"}'
            )

        restart.assert_called_once_with()

    def test_runtime_sync_preserves_user_state(self):
        source = self.root / "source"
        destination = self.root / "destination"
        (source / "plugins" / "Bundled").mkdir(parents=True)
        (source / "plugins" / "Disabled").mkdir(parents=True)
        (source / "plugins" / "Bundled" / "index.js").write_text("new", encoding="utf-8")
        (source / "plugins" / "Disabled" / "index.js_").write_text("disabled", encoding="utf-8")
        (source / "core.dll").write_bytes(b"new core")
        (source / "config").write_text("LeaguePath=C:\\\\new\n", encoding="utf-8")
        (source / "datastore").write_text("bundled", encoding="utf-8")

        (destination / "plugins" / "User").mkdir(parents=True)
        (destination / "plugins" / "Disabled").mkdir(parents=True)
        (destination / "plugins" / "User" / "index.js").write_text("user", encoding="utf-8")
        (destination / "plugins" / "Disabled" / "index.js").write_text("user-enabled", encoding="utf-8")
        (destination / "plugins" / "Disabled" / "index.js_").write_text("user-disabled", encoding="utf-8")
        (destination / "config").write_text("LeaguePath=C:\\\\old\nCustom=keep\n", encoding="utf-8")
        (destination / "datastore").write_text("user datastore", encoding="utf-8")

        runtime._copy_tree(source, destination)

        self.assertEqual((destination / "config").read_text(encoding="utf-8"), "LeaguePath=C:\\\\old\nCustom=keep\n")
        self.assertEqual((destination / "datastore").read_text(encoding="utf-8"), "user datastore")
        self.assertTrue((destination / "plugins" / "User" / "index.js").exists())
        self.assertFalse((destination / "plugins" / "Disabled" / "index.js").exists())
        self.assertTrue((destination / "plugins" / "Disabled" / "index.js_").exists())

    def test_packaging_no_longer_requires_loader_executable(self):
        spec = Path("Rose.spec").read_text(encoding="utf-8")
        build = Path("scripts/build_pyinstaller.py").read_text(encoding="utf-8")
        self.assertNotIn("Source-built Pengu Loader.exe is missing", spec)
        self.assertNotIn("build_pengu_loader()", build)
        self.assertIn("core.dll", spec)




class CustomModStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.storage = ModStorageService(self.root / "mods")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_list_and_delete_custom_mods_cleans_metadata_and_history(self):
        skin_dir = self.root / "mods" / "skins" / "123000" / "SkinMod"
        skin_dir.mkdir(parents=True)
        (skin_dir / "content.wad.client").write_bytes(b"skin")
        (skin_dir.parent / "rose_mod_targets.json").write_text(
            '{"version": 1, "mods": {"hash": {"name": "SkinMod", "targets": [123001]}}}',
            encoding="utf-8",
        )

        map_dir = self.root / "mods" / "maps" / "MapMod"
        map_dir.mkdir(parents=True)
        (map_dir / "map.wad.client").write_bytes(b"map")
        (map_dir.parent / "rose_category_mods.json").write_text(
            '{"version": 1, "category": "maps", "mods": {"MapMod": {"name": "MapMod", "path": "MapMod"}}}',
            encoding="utf-8",
        )

        user_dir = self.root / "user"
        user_dir.mkdir()
        (user_dir / "historic.json").write_text(
            '{"123": "path:skins/123000/SkinMod"}',
            encoding="utf-8",
        )
        (user_dir / "mod_historic.json").write_text(
            '{"map": "maps/MapMod"}',
            encoding="utf-8",
        )

        with patch("utils.core.historic.get_user_data_dir", return_value=user_dir), patch(
            "utils.core.mod_historic.get_user_data_dir", return_value=user_dir
        ):
            mods = self.storage.list_all_mods()
            self.assertEqual(
                {entry["id"] for entry in mods},
                {"skins/123000/SkinMod", "maps/MapMod"},
            )

            self.storage.delete_mod("skins/123000/SkinMod")
            self.assertFalse(skin_dir.exists())
            self.assertNotIn("SkinMod", (skin_dir.parent / "rose_mod_targets.json").read_text(encoding="utf-8"))
            self.assertEqual((user_dir / "historic.json").read_text(encoding="utf-8"), "{}")

            self.storage.delete_mod("maps/MapMod")
            self.assertFalse(map_dir.exists())
            self.assertNotIn("MapMod", (map_dir.parent / "rose_category_mods.json").read_text(encoding="utf-8"))
            self.assertEqual((user_dir / "mod_historic.json").read_text(encoding="utf-8"), "{}")

    def test_delete_rejects_traversal_and_metadata_paths(self):
        mod_dir = self.root / "mods" / "maps" / "SafeMod"
        mod_dir.mkdir(parents=True)
        (mod_dir.parent / "rose_category_mods.json").write_text(
            '{"mods": {"SafeMod": {"name": "SafeMod"}}}',
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            self.storage.delete_mod("../outside")
        with self.assertRaises(ValueError):
            self.storage.delete_mod("maps/rose_category_mods.json")
        self.assertTrue(mod_dir.exists())

if __name__ == "__main__":
    unittest.main()