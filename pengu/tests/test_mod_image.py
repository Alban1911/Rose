import json
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from pengu.communication.message_handler import (
    MessageHandler,
    _mod_thumbnail_details,
)


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
            first_relative, first_url = _mod_thumbnail_details(mod_folder, mods_root, 50000)

            image_path.write_bytes(b"new image")
            os.utime(image_path, ns=(2_000_000_000, 2_000_000_000))
            second_relative, second_url = _mod_thumbnail_details(mod_folder, mods_root, 50000)

        self.assertEqual(first_relative, "skins/1000/Example/META/image.png")
        self.assertEqual(second_relative, first_relative)
        self.assertNotEqual(first_url, second_url)
        self.assertIn("?v=", second_url)


if __name__ == "__main__":
    unittest.main()
