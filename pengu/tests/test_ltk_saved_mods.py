
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from injection.mods.mod_facts import ModFacts
from injection.mods.mod_source import LtkEntry, RoseFile
from injection.mods.storage import ModStorageService
from pengu.communication.message_handler import MessageHandler

LOST_ID = "d6f841c7-140b-4ac2-a11c-b37e18eb8006"
NIGHT_ID = "799b6c82-8324-4394-a0cf-ddebcd16eba7"
VOICE_ID = "1beee5a2-6fe1-49e1-ba94-9d601ead2a0f"
FACTS = ModFacts(ships_language_table=False)
MISSING = "This mod is missing from LTK Manager - add it again"


def write_manifest(path, **mods):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "mods": mods}), encoding="utf-8")


class SavedLtkModSelectionTests(unittest.TestCase):
    """Ezreal has a custom skin, which is Rose's file; the maps one LTK
    Manager holds, one it lost and a pending one; the voiceovers one LTK
    Manager holds"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        self.storage = ModStorageService(root / "mods")
        write_manifest(self.storage.get_champion_dir(81) / ModStorageService.TARGET_METADATA, **{
            "Arcane Ezreal": {"name": "Arcane Ezreal", "targets": [81020]},
        })
        self.skin = self.storage.get_champion_dir(81) / "Arcane Ezreal.fantome"
        with zipfile.ZipFile(self.skin, "w") as archive:
            archive.writestr("WAD/Ezreal.wad.client", b"skin")
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

    def test_a_custom_skin_is_linked_from_its_file(self):
        result = self.select_skin("Arcane Ezreal")

        self.assertTrue(result["success"])
        selected = self.handler.shared_state.selected_custom_mod
        self.assertEqual(selected["source"], RoseFile(self.skin, "Arcane Ezreal"))
        self.assertEqual(selected["relative_path"], "skins/81000/Arcane Ezreal.fantome")
        self.assertEqual(self.linked, ["Arcane Ezreal.fantome"])

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
        self.handler._handle_request_one_mod("map", {})

        (skin,) = self.sent[0]["mods"]
        self.assertEqual(skin["modName"], "Arcane Ezreal")
        self.assertFalse({"ltkId", "missing", "pending"} & set(skin), "a custom skin is always Rose's file")
        maps = {mod["name"]: mod for mod in self.sent[1]["maps"]}
        self.assertEqual((maps["Lost"]["missing"], maps["Rift"]["pending"]), (True, True))
        self.assertEqual(maps["Night"]["ltkId"], NIGHT_ID)

    def test_each_one_mod_list_answers_under_its_own_name_and_restores_its_saved_pick(self):
        saved = {"map": "maps/Night.fantome"}
        with patch("utils.core.mod_historic.get_historic_mod", side_effect=saved.get) as historic:
            for message_type in ("request-maps", "request-fonts", "request-announcers"):
                self.handler.handle_message(json.dumps({"type": message_type}))

        self.assertEqual(historic.call_args_list, [call("map"), call("font"), call("announcer")])
        self.assertEqual([(response["type"], response["historicMod"]) for response in self.sent], [
            ("maps-response", "maps/Night.fantome"), ("fonts-response", None), ("announcers-response", None),
        ])
        self.assertEqual(sorted(mod["name"] for mod in self.sent[0]["maps"]), ["Lost", "Night", "Rift"])
        self.assertEqual((self.sent[1]["fonts"], self.sent[2]["announcers"]), ([], []))
        self.assertEqual(self.handler.shared_state.selected_map_mod["mod_name"], "Night")


if __name__ == "__main__":
    unittest.main()
