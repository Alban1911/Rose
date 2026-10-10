import tempfile
import unittest
import zipfile
from pathlib import Path

from injection.mods.storage import ModStorageService


class CategoriesWithModsTests(unittest.TestCase):
    """Manage Mods only offers the categories that have a mod added"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.service = ModStorageService(self.root / 'mods')

    def _archive(self, name):
        archive = self.root / name
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr('WAD/Asset.wad.client', b'data')
        return archive

    def test_no_mods_means_no_categories(self):
        self.assertEqual(self.service.categories_with_mods(), [])

    def test_lists_categories_in_menu_order(self):
        self.service.import_category_mod_file('vfx', self._archive('Sparkles.fantome'))
        self.service.import_category_mod_file('maps', self._archive('Summoner Rift.fantome'))
        self.service.import_mod_file(81, self._archive('Arcane Ezreal.fantome'), [81020])

        self.assertEqual(self.service.categories_with_mods(), ['skins', 'maps', 'vfx'])

    def test_a_category_leaves_once_its_last_mod_is_deleted(self):
        self.service.import_category_mod_file('maps', self._archive('Summoner Rift.fantome'))
        self.service.delete_category_mod('maps', 'Summoner Rift')

        self.assertEqual(self.service.categories_with_mods(), [])

    def test_an_empty_champion_folder_is_not_a_skin_mod(self):
        self.service.get_champion_dir(81).mkdir(parents=True)

        self.assertEqual(self.service.categories_with_mods(), [])


if __name__ == '__main__':
    unittest.main()
