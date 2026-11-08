import json
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image

from injection.mods.storage import ModStorageService, SkinModEntry
from pengu.communication.message_handler import (
    MessageHandler,
    _mod_thumbnail_details,
)

LTK_ID = "5e9b2219-f49f-4cf1-bc7e-774fb43e1349"
OLD_PNG = b"\x89PNG\r\n\x1a\nold"
NEW_PNG = b"\x89PNG\r\n\x1a\nnew"


class ChampionModImageHandlerTests(unittest.TestCase):
    def setUp(self):
        self.handler = MessageHandler.__new__(MessageHandler)
        self.sent = []
        self.handler._send_response = lambda message: self.sent.append(json.loads(message))
        self.handler.mod_storage = MagicMock()
        self.handler.mod_storage.MAX_MOD_IMAGE_BYTES = 5 * 1024 * 1024
        self.handler.mod_storage.set_champion_mod_image.return_value = Path(
            "C:/mods/skins/1000/Example/META/image.png"
        )

    @staticmethod
    def _png_file(path):
        image = Image.new("RGB", (2, 2), "red")
        image.save(path, format="PNG")

    def test_selected_png_is_saved_and_success_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "preview.png"
            self._png_file(path)
            with patch("pengu.communication.message_handler._choose_mod_image_file", return_value=path):
                self.handler._handle_set_champion_mod_image({
                    "championId": 1,
                    "relativePath": "skins/1000/Example",
                })

        self.handler.mod_storage.set_champion_mod_image.assert_called_once()
        self.assertEqual(self.sent[-1]["type"], "champion-mod-image-updated")
        self.assertTrue(self.sent[-1]["success"])

    def test_invalid_image_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "not-a-png.png"
            path.write_bytes(b"not png")
            with patch("pengu.communication.message_handler._choose_mod_image_file", return_value=path):
                with self.assertLogs(level="ERROR"):
                    self.handler._handle_set_champion_mod_image({
                        "championId": 1,
                        "relativePath": "skins/1000/Example",
                    })

        self.handler.mod_storage.set_champion_mod_image.assert_not_called()
        self.assertFalse(self.sent[-1]["success"])
        self.assertIn("PNG", self.sent[-1]["error"])

    def test_cancelled_picker_is_reported_as_cancelled(self):
        with patch("pengu.communication.message_handler._choose_mod_image_file", return_value=None):
            self.handler._handle_set_champion_mod_image({
                "championId": 1,
                "relativePath": "skins/1000/Example",
            })
        self.assertTrue(self.sent[-1]["cancelled"])
        self.handler.mod_storage.set_champion_mod_image.assert_not_called()

    def test_manage_rows_mark_folders_and_archives_as_image_editable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mod_folder = root / "skins" / "1000" / "folder"
            mod_folder.mkdir(parents=True)
            archive = root / "skins" / "1000" / "archive.fantome"
            archive.write_bytes(b"archive")
            handler = MessageHandler.__new__(MessageHandler)
            handler.mod_storage = SimpleNamespace(mods_root=root)
            handler.port = 50000
            entries = [
                SkinModEntry(1, 1000, name, path, 0, "", (1001,), stored=path)
                for name, path in (("folder", mod_folder), ("archive", archive))
            ]

            payload = [handler._champion_mod_payload(entry) for entry in entries]

        self.assertTrue(payload[0]["imageEditable"])
        self.assertTrue(payload[1]["imageEditable"])


class ModThumbnailCacheTests(unittest.TestCase):
    def test_image_url_changes_when_the_mod_image_is_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            mods_root = Path(temporary)
            mod_folder = mods_root / "skins" / "1000" / "Example"
            meta = mod_folder / "META"
            meta.mkdir(parents=True)
            image_path = meta / "image.png"
            image_path.write_bytes(b"old")
            os.utime(image_path, ns=(1_000_000_000, 1_000_000_000))
            image_files = (image_path, meta / "image.webp")
            first_relative, first_url = _mod_thumbnail_details(image_files, mods_root, 50000)

            image_path.write_bytes(b"new image")
            os.utime(image_path, ns=(2_000_000_000, 2_000_000_000))
            second_relative, second_url = _mod_thumbnail_details(image_files, mods_root, 50000)

        self.assertEqual(first_relative, "skins/1000/Example/META/image.png")
        self.assertEqual(second_relative, first_relative)
        self.assertNotEqual(first_url, second_url)
        self.assertIn("?v=", second_url)



class SavedModImageTests(unittest.TestCase):
    """A saved mod's preview image is shown from where it is set (SavedMod.image_paths)"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.storage = ModStorageService(Path(temp_dir.name) / "mods")
        self.champion = self.storage.get_champion_dir(1)
        self.champion.mkdir(parents=True)
        self.handler = MessageHandler.__new__(MessageHandler)
        self.handler.mod_storage = self.storage
        self.handler.port = 50000

    def save(self, **entry):
        (self.champion / ModStorageService.TARGET_METADATA).write_text(json.dumps({"version": 1, "mods": {
            "Example": {"name": "Example", "targets": [1001], **entry},
        }}), encoding="utf-8")

    def folder_copy(self):
        meta = self.champion / "Example" / "META"
        meta.mkdir(parents=True)
        (meta / "image.png").write_bytes(OLD_PNG)
        return meta / "image.png"

    def thumbnail(self):
        (entry,) = self.storage.list_mods_for_champion(1)
        return self.handler._champion_mod_payload(entry)["thumbnailRelativePath"]

    def test_a_mod_ltk_manager_holds_shows_the_image_beside_its_manifest(self):
        self.save(ltkId=LTK_ID)
        (self.champion / "Example.png").write_bytes(OLD_PNG)

        self.assertEqual(self.thumbnail(), "skins/1000/Example.png")

    def test_a_new_image_shows_for_a_mod_ltk_manager_holds_whose_folder_copy_is_left(self):
        """The folder copy is a leftover about to go: its META is not where the image is"""
        self.save(ltkId=LTK_ID)
        self.folder_copy()
        (self.champion / "Example.png").write_bytes(OLD_PNG)

        written = self.storage.set_champion_mod_image(1, "skins/1000/Example.fantome", NEW_PNG)

        self.assertEqual(written, self.champion / "Example.png")
        self.assertEqual(written.read_bytes(), NEW_PNG)
        self.assertEqual(self.thumbnail(), "skins/1000/Example.png")

    def test_a_pending_folder_mod_keeps_its_image_in_its_meta(self):
        self.save()
        meta_image = self.folder_copy()

        written = self.storage.set_champion_mod_image(1, "skins/1000/Example", NEW_PNG)

        self.assertEqual(written, meta_image)
        self.assertEqual(meta_image.read_bytes(), NEW_PNG)
        self.assertEqual(self.thumbnail(), "skins/1000/Example/META/image.png")


if __name__ == "__main__":
    unittest.main()
