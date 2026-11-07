import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.core import mod_historic


class CategoryHistoryWriteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'mod_historic.json'
        patcher = patch.object(mod_historic, '_mod_historic_file_path', return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def read(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def test_combined_write_groups_deduplicates_and_removes_stale_categories(self):
        self.path.write_text(json.dumps({
            'map': 'maps/Map', 'font': 'fonts/Font', 'announcer': 'announcers/Voice',
            'vfx': ['vfx/Old'], 'ui': ['ui/Deleted'], 'others': ['others/Old'],
        }), encoding='utf-8')
        mod_historic.write_historic_mod('other', ['vfx/New', 'vfx/New', 'sfx/Sound'])
        self.assertEqual(self.read(), {
            'map': 'maps/Map', 'font': 'fonts/Font', 'announcer': 'announcers/Voice',
            'vfx': ['vfx/New'], 'sfx': ['sfx/Sound'],
        })

    def test_empty_combined_write_clears_categories_and_keeps_single_mods(self):
        self.path.write_text(json.dumps({'map': 'maps/Map', 'vfx': ['vfx/Old'], 'ui': ['ui/Old']}), encoding='utf-8')
        mod_historic.write_historic_mod('other', [])
        self.assertEqual(self.read(), {'map': 'maps/Map'})

    def test_direct_category_write_keeps_other_categories(self):
        mod_historic.write_historic_mod('ui', ['ui/Menu'])
        mod_historic.write_historic_mod('vfx', ['vfx/Old'])
        mod_historic.write_historic_mod('vfx', ['vfx/New', 'vfx/New'])
        self.assertEqual(self.read(), {'ui': ['ui/Menu'], 'vfx': ['vfx/New']})

    def test_legacy_single_path_is_grouped_without_others_duplicate(self):
        mod_historic.write_historic_mod('other', 'vfx/Effect')
        self.assertEqual(self.read(), {'vfx': ['vfx/Effect']})


if __name__ == '__main__':
    unittest.main()
