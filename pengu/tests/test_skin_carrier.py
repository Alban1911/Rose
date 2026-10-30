import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from injection.retarget import carriers
from injection.tests.test_retarget import SKIN0, builtin_stub, make_bin, raw_wad
from pengu.communication.message_handler import MessageHandler


class SkinCarrierMessageTests(unittest.TestCase):
    """ROSE-SkinCarrier asks which owned skins can carry the hovered one, and saves the one picked"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        patcher = patch.object(carriers, "get_user_data_dir", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

        game = self.root / "game"
        (game / "DATA" / "FINAL" / "Champions").mkdir(parents=True)
        (game / "DATA" / "FINAL" / "Champions" / "Ahri.wad.client").write_bytes(raw_wad({
            "data/characters/ahri/skins/skin14.bin": make_bin([], [("Characters/Ahri/Skins/Skin14", [])]),
        }))
        # Rose's skin 20, built on the game's skin 14
        archive = self.root / "103020.fantome"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("WAD/Ahri.wad.client", raw_wad({SKIN0: builtin_stub()}))

        self.handler = MessageHandler.__new__(MessageHandler)
        self.sent = []
        self.handler._send_response = lambda message: self.sent.append(json.loads(message))
        self.handler.shared_state = SimpleNamespace(owned_skin_ids={103001, 103014}, selected_custom_mod=None)
        self.handler.injection_manager = MagicMock()
        self.handler.injection_manager.injector._resolve_zip.return_value = archive
        self.handler.injection_manager.injector.game_dir = game
        cache = SimpleNamespace(
            champion_id=103,
            chroma_id_map={},
            skins=[
                {"skinId": 103000, "skinName": "Ahri", "isBase": True, "chromaDetails": []},
                {"skinId": 103001, "skinName": "Dynasty Ahri", "chromaDetails": []},
                {"skinId": 103014, "skinName": "Star Guardian Ahri", "chromaDetails": []},
                {"skinId": 103020, "skinName": "Arcade Ahri", "chromaDetails": []},
            ],
        )
        self.handler.skin_scraper = SimpleNamespace(cache=cache)

    def test_the_owned_skins_are_offered_and_the_one_the_skin_is_built_on_is_marked(self):
        self.handler._handle_request_skin_carrier({"championId": 103, "skinId": 103020, "requestId": "r"})

        response = self.sent[-1]
        self.assertEqual(response["type"], "skin-carrier-response")
        self.assertTrue(response["applicable"])
        options = {option["id"]: option for option in response["options"]}
        self.assertEqual(sorted(options), [103001, 103014])
        self.assertIsNone(options[103001]["unavailableReason"])
        self.assertIn("skin14.bin", options[103014]["unavailableReason"])

    def test_an_owned_skin_plays_as_itself(self):
        self.handler._handle_request_skin_carrier({"championId": 103, "skinId": 103001})
        self.assertFalse(self.sent[-1]["applicable"])
        self.assertEqual(self.sent[-1]["options"], [])

    def test_an_unowned_chroma_of_an_owned_skin_can_take_a_carrier(self):
        # Star Guardian Ahri (owned), its chroma 103015 (not owned): the chroma is injected, from its own archive
        self.handler.skin_scraper.cache.chroma_id_map = {103015: {"id": 103015, "skinId": 103014}}
        self.handler._handle_request_skin_carrier({"championId": 103, "skinId": 103015})

        response = self.sent[-1]
        self.assertTrue(response["applicable"])
        self.assertEqual(response["carrierKey"], 103014)
        self.assertEqual(sorted(option["id"] for option in response["options"]), [103001, 103014])
        self.assertEqual(
            self.handler.injection_manager.injector._resolve_zip.call_args.kwargs["chroma_id"], 103015)

    def test_the_chroma_picked_in_roses_wheel_is_the_one_asked_about(self):
        # The client keeps the owned skin selected; Rose's wheel tells the chroma, Rose's chroma map whose it is
        self.handler.skin_scraper.cache.chroma_id_map = {103015: {"id": 103015, "skinId": 103014}}
        self.handler._handle_request_skin_carrier({"championId": 103, "skinId": 103014, "chromaId": 103015})
        response = self.sent[-1]
        self.assertEqual((response["askedSkinId"], response["chromaId"]), (103015, 103015))
        self.assertTrue(response["applicable"])

        # A chroma of another skin (stale wheel state) is ignored: the owned skin plays as itself
        self.handler._handle_request_skin_carrier({"championId": 103, "skinId": 103014, "chromaId": 103002})
        self.assertEqual(self.sent[-1]["askedSkinId"], 103014)
        self.assertFalse(self.sent[-1]["applicable"])

    def test_the_pick_is_saved_and_cleared(self):
        self.handler._handle_select_skin_carrier({"skinId": 103020, "carrierId": 103001, "requestId": "s"})
        self.assertTrue(self.sent[-1]["success"])
        self.assertEqual(carriers.get_carrier(103020), 103001)

        self.handler._handle_request_skin_carrier({"championId": 103, "skinId": 103020})
        self.assertEqual(self.sent[-1]["carrierId"], 103001)

        self.handler._handle_select_skin_carrier({"skinId": 103020, "carrierId": None})
        self.assertIsNone(carriers.get_carrier(103020))

    def test_another_champions_skin_is_refused(self):
        self.handler._handle_select_skin_carrier({"skinId": 103020, "carrierId": 238001})
        self.assertFalse(self.sent[-1]["success"])
        self.assertIsNone(carriers.get_carrier(103020))


if __name__ == "__main__":
    unittest.main()
