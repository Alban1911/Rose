
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from injection.mods.ltk_ref import ltk_ref
from injection.mods.mod_facts import ModFacts
from injection.mods.mod_source import LtkEntry, RoseFile
from injection.mods.storage import ModStorageService
from pengu.communication.message_handler import MessageHandler

MOVED_ID = "5e9b2219-f49f-4cf1-bc7e-774fb43e1349"
LOST_ID = "d6f841c7-140b-4ac2-a11c-b37e18eb8006"
NIGHT_ID = "799b6c82-8324-4394-a0cf-ddebcd16eba7"
VOICE_ID = "1beee5a2-6fe1-49e1-ba94-9d601ead2a0f"
FACTS = ModFacts("0123456789abcdef0123456789abcdef", ("Ezreal",), False)
MISSING = "This mod is missing from LTK Manager - add it again"


def write_manifest(path, **mods):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "mods": mods}), encoding="utf-8")


class SavedLtkModSelectionTests(unittest.TestCase):
    """Ezreal has a skin mod LTK Manager holds and one it lost; the maps one of
    each and a pending one; the voiceovers one LTK Manager holds"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        self.storage = ModStorageService(root / "mods")
        write_manifest(self.storage.get_champion_dir(81) / ModStorageService.TARGET_METADATA, **{
            "Moved Ezreal": {"name": "Moved Ezreal", "targets": [81020], "ltkId": MOVED_ID, **FACTS.to_manifest()},
            "Lost Ezreal": {"name": "Lost Ezreal", "targets": [81020], "ltkId": LOST_ID, "missing": True},
        })
        maps = self.storage.mods_root / "maps"
        write_manifest(maps / ModStorageService.CATEGORY_METADATA, **{
            "Night": {"name": "Night", "path": "Night", "ltkId": NIGHT_ID, **FACTS.to_manifest()},
            "Lost": {"name": "Lost", "path": "Lost", "ltkId": LOST_ID, "missing": True},
            "Rift": {"name": "Rift", "path": "Rift"},
        })
        with zipfile.ZipFile(maps / "Rift.fantome", "w") as archive:
            archive.writestr("WAD/Map11.wad.client", b"map")
        write_manifest(self.storage.mods_root / "voiceover" / ModStorageService.CATEGORY_METADATA, **{
            "VO": {"name": "VO", "path": "VO", "ltkId": VOICE_ID},
        })

        self.mods_dir = root / "injection" / "mods"
        self.mods_dir.mkdir(parents=True)
        self.injector = SimpleNamespace(mods_dir=self.mods_dir, _clean_mods_dir=Mock())
        self.handler = MessageHandler.__new__(MessageHandler)
        self.handler.mod_storage = self.storage
        self.handler.injection_manager = SimpleNamespace(injector=self.injector)
        self.handler.skin_scraper = None
        self.handler.port = 50000
        self.handler.shared_state = SimpleNamespace(
            selected_custom_mod=None, selected_map_mod=None, selected_font_mod=None,
            selected_announcer_mod=None, selected_other_mods=[],
        )
        self.sent = []
        self.handler._send_response = lambda message: self.sent.append(json.loads(message))
        self.linked = []
        for target, kwargs in (
            ("injection.mods.mod_source.link_or_extract", {"side_effect": self.link}),
            ("injection.mods.mod_source.get_injection_dir", {"return_value": root / "injection"}),
            ("utils.core.mod_historic.write_historic_mod", {}),
            ("utils.core.mod_historic.clear_historic_mod", {}),
            ("utils.core.mod_historic.get_historic_mod", {"return_value": None}),
            ("utils.core.historic.get_historic_skin_for_champion", {"return_value": None}),
            ("pengu.communication.message_handler.get_config_option", {"return_value": "false"}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def link(self, source, dest, cache_dir=None):
        self.linked.append(Path(source).name)
        dest.write_bytes(b"linked")

    def select_skin(self, name):
        self.handler._handle_select_skin_mod({
            "championId": 81, "skinId": 81020, "modId": f"skins/81000/{name}.fantome",
        })
        return self.sent[-1]

    def test_a_skin_mod_ltk_manager_holds_is_selected_as_its_reference(self):
        result = self.select_skin("Moved Ezreal")

        self.assertTrue(result["success"])
        selected = self.handler.shared_state.selected_custom_mod
        self.assertEqual(selected["source"], LtkEntry(MOVED_ID, FACTS, missing=False))
        self.assertEqual(selected["relative_path"], "skins/81000/Moved Ezreal.fantome")
        self.assertEqual(self.linked, [])
        self.assertEqual(list(self.mods_dir.iterdir()), [])

    def test_a_skin_mod_ltk_manager_lost_is_refused(self):
        with self.assertLogs(level="WARNING"):
            result = self.select_skin("Lost Ezreal")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], MISSING)
        self.assertIsNone(self.handler.shared_state.selected_custom_mod)
        self.injector._clean_mods_dir.assert_not_called()

    def test_dismissing_a_skin_mod_ltk_manager_holds_leaves_the_mods_folder_alone(self):
        self.handler.shared_state.selected_custom_mod = {"champion_id": 81, "source": LtkEntry(MOVED_ID)}
        named_like_it = self.mods_dir / ltk_ref(MOVED_ID)
        named_like_it.write_bytes(b"not the mod")

        self.handler._handle_dismiss_custom_mod({})

        self.assertIsNone(self.handler.shared_state.selected_custom_mod)
        self.assertTrue(named_like_it.exists())

    def test_a_map_ltk_manager_holds_is_selected_as_its_reference(self):
        self.handler.handle_message(json.dumps({
            "type": "select-map", "mapId": "maps/Night.fantome", "mapData": {"id": "maps/Night.fantome"},
        }))

        selected = self.handler.shared_state.selected_map_mod
        self.assertEqual(selected["source"], LtkEntry(NIGHT_ID, FACTS))
        self.assertEqual((selected["mod_name"], selected["relative_path"]), ("Night", "maps/Night.fantome"))
        self.assertEqual(self.linked, [])

    def test_a_pending_map_is_still_linked(self):
        self.handler.handle_message(json.dumps({"type": "select-map", "mapId": "Rift", "mapData": {"name": "Rift"}}))

        selected = self.handler.shared_state.selected_map_mod
        self.assertEqual(selected["source"], RoseFile(self.storage.mods_root / "maps" / "Rift.fantome", "Rift"))
        self.assertEqual(self.linked, ["Rift.fantome"])

    def test_a_map_ltk_manager_lost_is_refused(self):
        with self.assertLogs(level="WARNING") as logs:
            self.handler.handle_message(json.dumps({"type": "select-map", "mapId": "maps/Lost.fantome"}))

        self.assertIsNone(self.handler.shared_state.selected_map_mod)
        self.assertIn(MISSING, "\n".join(logs.output))

    def test_a_saved_map_ltk_manager_lost_is_not_restored(self):
        maps = self.storage.list_mods_for_category("maps")

        with self.assertLogs(level="WARNING"):
            self.handler._auto_select_historic_mod("map", "maps/Lost.fantome", maps)

        self.assertIsNone(self.handler.shared_state.selected_map_mod)

    def test_another_mod_ltk_manager_holds_is_selected_as_its_reference(self):
        self.handler._handle_select_other({"otherId": "voiceover/VO.fantome", "otherData": {"id": "voiceover/VO.fantome"}})

        self.assertEqual([mod["source"] for mod in self.handler.shared_state.selected_other_mods],
                         [LtkEntry(VOICE_ID)])
        self.assertEqual(self.linked, [])

    def test_the_lists_say_where_each_mod_is(self):
        self.handler._handle_request_skin_mods({"championId": 81, "skinId": 81020})
        self.handler._handle_request_maps({})

        skins = {mod["modName"]: mod for mod in self.sent[0]["mods"]}
        self.assertEqual((skins["Moved Ezreal"]["ltkId"], skins["Moved Ezreal"]["missing"]), (MOVED_ID, False))
        self.assertFalse(skins["Moved Ezreal"]["pending"])
        self.assertTrue(skins["Lost Ezreal"]["missing"])
        maps = {mod["name"]: mod for mod in self.sent[1]["maps"]}
        self.assertEqual((maps["Lost"]["missing"], maps["Rift"]["pending"]), (True, True))
        self.assertEqual(maps["Night"]["ltkId"], NIGHT_ID)


if __name__ == "__main__":
    unittest.main()
