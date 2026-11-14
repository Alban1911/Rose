import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pengu.processing.skin_mapping import SkinMapping


class SkinMappingTests(unittest.TestCase):
    """A Swiftplay skin name missing from the mapping (wrong locale folder or
    a skin newer than the resources) fell back to the first substring match,
    so "Dimension Breaker Jinx" resolved to Sion's base skin"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name) / "resources" / "en"
        folder.mkdir(parents=True)
        (folder / "skin_ids.json").write_text(json.dumps({
            "14000": "Sion",
            "222000": "Jinx",
            "222037": "Arcane Enemy Jinx",
        }), encoding="utf-8")
        patcher = patch("pengu.processing.skin_mapping.get_user_data_dir", return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.mapping = SkinMapping(SimpleNamespace(current_language="en"))

    def test_an_exact_name_is_found(self):
        self.assertEqual(self.mapping.find_skin_id_by_name(" Arcane Enemy jinx "), 222037)

    def test_an_unknown_name_does_not_match_another_champion(self):
        self.assertIsNone(self.mapping.find_skin_id_by_name("Dimension Breaker Jinx"))


if __name__ == "__main__":
    unittest.main()
