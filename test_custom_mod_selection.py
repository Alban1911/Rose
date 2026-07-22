import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from injection.mods.storage import ModStorageService, SkinModEntry
from pengu.communication.message_handler import MessageHandler
from threads.handlers.injection_trigger import InjectionTrigger
from ui.handlers.historic_mode_handler import HistoricModeHandler


class CustomModSelectionTests(unittest.TestCase):
    def make_handler(self, mods_root, entries, *, skin_scraper=None, injection_manager=None):
        storage = SimpleNamespace(
            mods_root=Path(mods_root),
            list_mods_for_champion=lambda champion_id: list(entries),
        )
        handler = object.__new__(MessageHandler)
        handler.shared_state = SimpleNamespace(
            selected_custom_mod=None,
            selected_other_mods=None,
            selected_other_mod=None,
            selected_map_mod=None,
            selected_font_mod=None,
            selected_announcer_mod=None,
            historic_mode_active=False,
            historic_skin_id=None,
            ui_skin_thread=None,
        )
        handler.mod_storage = storage
        handler.skin_scraper = skin_scraper
        handler.injection_manager = injection_manager
        handler.port = 50000
        handler._send_response = MagicMock()
        return handler

    def test_chroma_request_accepts_mod_stored_under_base_skin(self):
        handler = object.__new__(MessageHandler)
        handler.skin_scraper = SimpleNamespace(
            cache=SimpleNamespace(chroma_id_map={123456: {"skinId": 123400}})
        )

        self.assertEqual(handler._get_compatible_skin_ids(123456), {123456, 123400})

    def test_base_skin_custom_mod_does_not_need_skin_carrier(self):
        self.assertIsNone(
            InjectionTrigger._get_custom_skin_carrier_name(
                {"skin_id": 123000, "champion_id": 123}
            )
        )

    def test_non_base_custom_mod_uses_matching_skin_carrier(self):
        self.assertEqual(
            InjectionTrigger._get_custom_skin_carrier_name(
                {"skin_id": 123401, "champion_id": 123}
            ),
            "skin_123401",
        )
        self.assertEqual(
            InjectionTrigger._get_custom_skin_carrier_name(
                {"skin_id": 123401, "champion_id": 123},
                selected_chroma_id=123405,
            ),
            "chroma_123405",
        )

    def test_missing_skin_carrier_does_not_start_partial_overlay(self):
        injector = SimpleNamespace(
            mods_dir=Path("missing-carrier-mods"),
            _clean_mods_dir=MagicMock(),
            _clean_overlay_dir=MagicMock(),
            _resolve_zip=MagicMock(return_value=None),
            overlay_manager=SimpleNamespace(mk_run_overlay=MagicMock()),
        )
        manager = SimpleNamespace(
            injector=injector,
            _monitor_active=True,
            _stop_monitor=MagicMock(),
        )
        trigger = object.__new__(InjectionTrigger)
        trigger.injection_manager = manager
        trigger.state = SimpleNamespace(
            locked_champ_id=123,
            hovered_champ_id=None,
        )

        trigger._inject_custom_mod(
            {
                "skin_id": 123401,
                "champion_id": 123,
                "mod_name": "Custom",
                "mod_folder_name": "Custom",
                "mod_path": "missing-custom-mod",
            },
            base_skin_name="skin_123401",
        )

        injector.overlay_manager.mk_run_overlay.assert_not_called()

    def test_non_base_injection_puts_carrier_before_custom_mod(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            carrier_zip = root / "123401.zip"
            carrier_zip.touch()
            custom_source = root / "CustomSource"
            custom_source.mkdir()
            mods_dir = root / "injection-mods"
            overlay = MagicMock(return_value=0)
            injector = SimpleNamespace(
                mods_dir=mods_dir,
                _clean_mods_dir=MagicMock(),
                _clean_overlay_dir=MagicMock(),
                _resolve_zip=MagicMock(return_value=carrier_zip),
                _extract_zip_to_mod=lambda archive: (
                    (mods_dir / archive.stem).mkdir(parents=True, exist_ok=True)
                    or (mods_dir / archive.stem)
                ),
                overlay_manager=SimpleNamespace(mk_run_overlay=overlay),
            )
            manager = SimpleNamespace(
                injector=injector,
                _monitor_active=True,
                _stop_monitor=MagicMock(),
            )
            state = SimpleNamespace(
                locked_champ_id=123,
                hovered_champ_id=None,
                selected_custom_mod={
                    "skin_id": 123401,
                    "champion_id": 123,
                    "mod_name": "Custom",
                    "mod_folder_name": "Custom",
                    "mod_path": str(custom_source),
                    "relative_path": "skins/123401/Custom",
                },
                selected_map_mod=None,
                selected_font_mod=None,
                selected_announcer_mod=None,
                selected_other_mods=None,
                selected_other_mod=None,
                party_manager=None,
                phase="Lobby",
            )
            trigger = object.__new__(InjectionTrigger)
            trigger.injection_manager = manager
            trigger.state = state
            trigger._force_base_skin = MagicMock()

            def link_to_destination(source, destination, cache_dir):
                destination.mkdir(parents=True)

            with patch("threads.handlers.injection_trigger.get_injection_dir", return_value=root), patch(
                "threads.handlers.injection_trigger.link_or_extract",
                side_effect=link_to_destination,
            ), patch("utils.core.historic.write_historic_entry"):
                trigger._inject_custom_mod(
                    state.selected_custom_mod,
                    base_skin_name="skin_123401",
                )

            injected_names = overlay.call_args.args[0]
            self.assertEqual(injected_names[:2], ["123401", "Custom"])
            trigger._force_base_skin.assert_called_once_with(123000)

    def test_request_marks_only_compatible_mods(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_path = root / "skins" / "123400" / "BaseMod"
            other_path = root / "skins" / "123500" / "OtherMod"
            base_path.mkdir(parents=True)
            other_path.mkdir(parents=True)
            entries = [
                SkinModEntry(123, 123400, "BaseMod", base_path, 1.0),
                SkinModEntry(123, 123500, "OtherMod", other_path, 1.0),
            ]
            handler = self.make_handler(
                root,
                entries,
                skin_scraper=SimpleNamespace(
                    cache=SimpleNamespace(chroma_id_map={123456: {"skinId": 123400}})
                ),
            )

            handler._handle_request_skin_mods({"championId": 123, "skinId": 123456})

            response = json.loads(handler._send_response.call_args.args[0])
            available = {
                mod["modName"]: mod["availableForRequestedSkin"]
                for mod in response["mods"]
            }
            self.assertEqual(available, {"BaseMod": True, "OtherMod": False})
            self.assertEqual(set(response["compatibleSkinIds"]), {123456, 123400})

    def test_storage_discovers_all_skin_folders_touched_by_wad(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            mod_root = mods_root / "skins" / "161004" / "Infernal VFX"
            (mod_root / "WAD" / "Velkoz.wad.client" / "data" / "characters" / "velkoz" / "skins" / "skin04").mkdir(
                parents=True
            )
            (mod_root / "WAD" / "Velkoz.wad.client" / "data" / "characters" / "velkoz" / "skins" / "skin05").mkdir()
            (mod_root / "WAD" / "Velkoz.wad.client" / "data" / "characters" / "velkoz" / "skins" / "skin10").mkdir()

            storage = ModStorageService(mods_root=mods_root)
            entries = storage.list_mods_for_champion(161)

            self.assertEqual(len(entries), 1)
            self.assertEqual(
                entries[0].affected_skin_ids,
                (161004, 161005, 161010),
            )

    def test_champion_import_folder_uses_base_skin_and_discovers_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            mod_root = mods_root / "skins" / "161000" / "Infernal VFX"
            (mod_root / "WAD" / "Velkoz.wad.client" / "data" / "characters" / "velkoz" / "skins" / "skin04").mkdir(
                parents=True
            )
            (mod_root / "WAD" / "Velkoz.wad.client" / "data" / "characters" / "velkoz" / "skins" / "skin05").mkdir()

            storage = ModStorageService(mods_root=mods_root)
            entries = storage.list_mods_for_champion(161)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].skin_id, 161000)
            self.assertEqual(entries[0].affected_skin_ids, (161004, 161005))

    def test_chroma_only_metadata_excludes_base_skin_carrier(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            mod_root = mods_root / "skins" / "161000" / "Infernal VFX"
            (mod_root / "META").mkdir(parents=True)
            (mod_root / "META" / "info.json").write_text(
                json.dumps(
                    {
                        "Name": "Infernal Vel'Koz chroma VFX",
                        "Description": "All chromas",
                    }
                ),
                encoding="utf-8",
            )
            (mod_root / "WAD" / "Velkoz.wad.client" / "assets" / "InfernalV" / "characters" / "velkoz" / "skins" / "skin04").mkdir(
                parents=True
            )
            for suffix in range(5, 11):
                (mod_root / "WAD" / "Velkoz.wad.client" / "assets" / "InfernalV" / "characters" / "velkoz" / "skins" / f"skin{suffix:02d}").mkdir()

            storage = ModStorageService(mods_root=mods_root)
            entries = storage.list_mods_for_champion(161)

            self.assertEqual(entries[0].affected_skin_ids, (161005, 161006, 161007, 161008, 161009, 161010))

    def test_champion_import_opens_base_skin_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = ModStorageService(mods_root=Path(temp_dir) / "mods")
            handler = object.__new__(MessageHandler)
            handler.mod_storage = storage
            handler._send_response = MagicMock()

            with patch("pengu.communication.message_handler.os.startfile") as startfile:
                handler._handle_add_custom_mods_skin_selected(
                    {"action": "create", "championId": 161}
                )

            response = json.loads(handler._send_response.call_args.args[0])
            expected = storage.get_skin_dir(161000)
            self.assertTrue(response["success"])
            self.assertEqual(Path(response["path"]), expected)
            startfile.assert_called_once_with(str(expected))

    def test_request_exposes_only_mods_affecting_hovered_skin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mod_path = root / "skins" / "123400" / "AllChromas"
            mod_path.mkdir(parents=True)
            entries = [
                SkinModEntry(
                    123,
                    123400,
                    "AllChromas",
                    mod_path,
                    1.0,
                    affected_skin_ids=(123400, 123401, 123402),
                )
            ]
            handler = self.make_handler(root, entries)

            handler._handle_request_skin_mods({"championId": 123, "skinId": 123402})

            response = json.loads(handler._send_response.call_args.args[0])
            self.assertTrue(response["mods"][0]["availableForRequestedSkin"])
            self.assertEqual(response["mods"][0]["affectedSkinIds"], [123400, 123401, 123402])

            handler._handle_request_skin_mods({"championId": 123, "skinId": 123499})
            response = json.loads(handler._send_response.call_args.args[0])
            self.assertFalse(response["mods"][0]["availableForRequestedSkin"])

    def test_historic_mod_is_only_returned_for_an_affected_skin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mod_path = root / "skins" / "123000" / "AllChromas"
            mod_path.mkdir(parents=True)
            relative_path = "skins/123000/AllChromas"
            entries = [
                SkinModEntry(
                    123,
                    123000,
                    "AllChromas",
                    mod_path,
                    1.0,
                    affected_skin_ids=(123005, 123006),
                )
            ]
            handler = self.make_handler(root, entries)

            with patch(
                "utils.core.historic.get_historic_skin_for_champion",
                return_value=f"path:{relative_path}",
            ):
                handler._handle_request_skin_mods({"championId": 123, "skinId": 123000})
                base_response = json.loads(handler._send_response.call_args.args[-1])
                self.assertIsNone(base_response["historicMod"])

                handler._handle_request_skin_mods({"championId": 123, "skinId": 123006})
                chroma_response = json.loads(handler._send_response.call_args.args[-1])
                self.assertEqual(chroma_response["historicMod"], relative_path)

    def test_historic_custom_mod_activates_from_unaffected_base_skin(self):
        state = SimpleNamespace(
            historic_first_detection_done=False,
            locked_champ_id=123,
            historic_mode_active=False,
            historic_skin_id=None,
            ui_skin_thread=None,
        )
        entry = SkinModEntry(
            123,
            123000,
            "AllChromas",
            Path("skins/123000/AllChromas"),
            1.0,
            affected_skin_ids=(123005, 123006),
        )
        storage = SimpleNamespace(
            mods_root=Path(""),
            list_mods_for_champion=lambda champion_id: [entry],
        )

        with patch(
            "utils.core.historic.get_historic_skin_for_champion",
            return_value="path:skins/123000/AllChromas",
        ), patch(
            "injection.mods.storage.ModStorageService",
            return_value=storage,
        ):
            HistoricModeHandler(state).check_and_activate(123000)

        self.assertTrue(state.historic_mode_active)
        self.assertTrue(state.historic_first_detection_done)

    def test_selection_rejects_mod_from_another_skin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mod_path = root / "skins" / "1001" / "SharedMod"
            mod_path.mkdir(parents=True)
            entry = SkinModEntry(1, 1001, "SharedMod", mod_path, 1.0)
            handler = self.make_handler(root, [entry])

            handler._handle_select_skin_mod(
                {
                    "requestId": "wrong-skin",
                    "championId": 1,
                    "skinId": 1002,
                    "modId": "skins/1001/SharedMod",
                }
            )

            result = json.loads(handler._send_response.call_args.args[-1])
            self.assertFalse(result["success"])
            self.assertEqual(result["requestId"], "wrong-skin")
            self.assertIsNone(handler.shared_state.selected_custom_mod)

    def test_selection_reports_success_only_after_target_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mod_path = root / "skins" / "1001" / "SharedMod"
            mod_path.mkdir(parents=True)
            entry = SkinModEntry(1, 1001, "SharedMod", mod_path, 1.0)

            injection_root = root / "injection"
            injector = SimpleNamespace(
                mods_dir=injection_root,
                _clean_mods_dir=MagicMock(),
            )
            manager = SimpleNamespace(injector=injector)
            handler = self.make_handler(root, [entry], injection_manager=manager)

            def create_target(source, destination, cache_dir):
                destination.mkdir(parents=True)

            with patch("pengu.communication.message_handler.get_injection_dir", return_value=root), patch(
                "pengu.communication.message_handler.link_or_extract", side_effect=create_target
            ):
                handler._handle_select_skin_mod(
                    {
                        "requestId": "select-1",
                        "championId": 1,
                        "skinId": 1001,
                        "modId": "skins/1001/SharedMod",
                    }
                )

            result = json.loads(handler._send_response.call_args.args[-1])
            self.assertTrue(result["success"])
            self.assertEqual(result["requestId"], "select-1")
            self.assertEqual(result["targetSkinId"], 1001)
            self.assertEqual(handler.shared_state.selected_custom_mod["relative_path"], "skins/1001/SharedMod")

    def test_selection_uses_hovered_affected_skin_as_injection_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mod_path = root / "skins" / "1001" / "AllChromas"
            mod_path.mkdir(parents=True)
            entry = SkinModEntry(
                1,
                1001,
                "AllChromas",
                mod_path,
                1.0,
                affected_skin_ids=(1001, 1002),
            )

            injection_root = root / "injection"
            injector = SimpleNamespace(
                mods_dir=injection_root,
                _clean_mods_dir=MagicMock(),
            )
            manager = SimpleNamespace(injector=injector)
            handler = self.make_handler(root, [entry], injection_manager=manager)

            def create_target(source, destination, cache_dir):
                destination.mkdir(parents=True)

            with patch("pengu.communication.message_handler.get_injection_dir", return_value=root), patch(
                "pengu.communication.message_handler.link_or_extract", side_effect=create_target
            ):
                handler._handle_select_skin_mod(
                    {
                        "requestId": "select-affected",
                        "championId": 1,
                        "skinId": 1002,
                        "modId": "skins/1001/AllChromas",
                    }
                )

            self.assertEqual(
                handler.shared_state.selected_custom_mod["skin_id"],
                1002,
            )
            self.assertEqual(
                handler.shared_state.selected_custom_mod["storage_skin_id"],
                1001,
            )

    def test_stale_deselection_does_not_clear_new_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selected = {
                "skin_id": 1001,
                "champion_id": 1,
                "mod_name": "NewMod",
                "relative_path": "skins/1001/NewMod",
                "mod_folder_name": "NewMod",
            }
            handler = self.make_handler(root, [])
            handler.shared_state.selected_custom_mod = selected

            handler._handle_select_skin_mod(
                {
                    "requestId": "stale-deselect",
                    "championId": 1,
                    "skinId": 1001,
                    "modId": None,
                    "expectedModId": "skins/1001/OldMod",
                }
            )

            result = json.loads(handler._send_response.call_args.args[-1])
            self.assertFalse(result["success"])
            self.assertIs(handler.shared_state.selected_custom_mod, selected)

    def test_deselection_can_clear_previous_skin_after_navigation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            handler = self.make_handler(Path(temp_dir), [])
            handler.shared_state.selected_custom_mod = {
                "skin_id": 1001,
                "champion_id": 1,
                "mod_name": "OldMod",
                "relative_path": "skins/1001/OldMod",
                "mod_folder_name": "OldMod",
            }

            handler._handle_select_skin_mod(
                {
                    "requestId": "previous-skin",
                    "championId": 1,
                    "skinId": 1002,
                    "modId": None,
                    "expectedModId": "skins/1001/OldMod",
                }
            )

            result = json.loads(handler._send_response.call_args.args[-1])
            self.assertTrue(result["success"])
            self.assertIsNone(handler.shared_state.selected_custom_mod)


if __name__ == "__main__":
    unittest.main()
