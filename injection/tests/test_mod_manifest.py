import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from injection.mods import storage
from injection.mods.storage import ModStorageService


class UnreadableManifestTests(unittest.TestCase):
    """An unreadable category manifest looked empty: its mods vanished with
    no trace, and importing a mod rewrote it with that mod alone"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.service = ModStorageService(self.root / 'mods')
        self.manifest = self.root / 'mods' / ModStorageService.CATEGORY_MAPS / ModStorageService.CATEGORY_METADATA
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        self.archive = self.root / 'Summoner Rift.fantome'
        with zipfile.ZipFile(self.archive, 'w') as zf:
            zf.writestr('WAD/Map11.wad.client', b'data')
        storage._reported_manifests.clear()

    def test_importing_does_not_overwrite_an_unreadable_manifest(self):
        corrupt = '{"version": 1, "mods": {"Old Map": {"name": "Old Map"'
        self.manifest.write_text(corrupt, encoding='utf-8')

        with self.assertLogs(level='WARNING'), self.assertRaises(ValueError):
            self.service.import_category_mod_file(ModStorageService.CATEGORY_MAPS, self.archive)

        self.assertEqual(self.manifest.read_text(encoding='utf-8'), corrupt)

    def test_importing_with_no_manifest_still_creates_it(self):
        self.service.import_category_mod_file(ModStorageService.CATEGORY_MAPS, self.archive)

        mods = json.loads(self.manifest.read_text(encoding='utf-8'))['mods']
        self.assertEqual(list(mods), ['Summoner Rift'])

    def test_an_unreadable_manifest_is_reported_once(self):
        self.manifest.write_text('not json', encoding='utf-8')
        with self.assertLogs(level='WARNING') as logs:
            for _ in range(3):
                self.assertIsNone(ModStorageService._load_manifest(self.manifest))
        self.assertEqual(len(logs.output), 1)


class SkinManifestWriteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = ModStorageService(self.root / 'mods')
        self.champion_dir = self.service.get_champion_dir(1)
        self.champion_dir.mkdir(parents=True)
        self.manifest = self.champion_dir / self.service.TARGET_METADATA
        self.original = json.dumps({
            'version': 1, 'championId': 1, 'targets': [],
            'mods': {'old': {'name': 'old', 'targets': [1002], 'displayName': 'Old alias'}},
        })
        self.manifest.write_text(self.original, encoding='utf-8')
        self.archive = self.root / 'new.fantome'
        with zipfile.ZipFile(self.archive, 'w') as zf:
            zf.writestr('WAD/Annie.wad.client', b'mod')

    def test_transient_read_failure_does_not_replace_valid_skin_metadata(self):
        read_text = Path.read_text

        def read(path, *args, **kwargs):
            if path == self.manifest:
                raise PermissionError('temporary read lock')
            return read_text(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read), self.assertRaises(ValueError):
            self.service.set_champion_target_ids(1, [1001], mod_name='new')
        self.assertEqual(self.manifest.read_text(encoding='utf-8'), self.original)

    def test_failed_skin_import_rolls_back_promoted_folder_only(self):
        existing = self.champion_dir / 'old'
        existing.mkdir()
        (existing / 'asset').write_bytes(b'keep')
        with patch.object(self.service, 'set_champion_target_ids', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                self.service.import_mod_file(1, self.archive, [1001])
        self.assertEqual(sorted(p.name for p in self.champion_dir.iterdir()), ['old', self.service.TARGET_METADATA])
        self.assertEqual((existing / 'asset').read_bytes(), b'keep')
        self.assertEqual(self.manifest.read_text(encoding='utf-8'), self.original)

    def test_missing_manifest_can_be_created(self):
        self.manifest.unlink()
        self.service.import_mod_file(1, self.archive, [1001])
        self.assertEqual(len(json.loads(self.manifest.read_text(encoding='utf-8'))['mods']), 1)

    def test_import_with_unreadable_manifest_preserves_old_mods_and_removes_new_folder(self):
        with patch.object(self.service, '_load_manifest', return_value=None):
            with self.assertRaises(ValueError):
                self.service.import_mod_file(1, self.archive, [1001])
        self.assertEqual(list(self.champion_dir.iterdir()), [self.manifest])
        self.assertEqual(self.manifest.read_text(encoding='utf-8'), self.original)

    def test_unreadable_legacy_manifest_does_not_create_replacement(self):
        legacy = self.champion_dir / self.service.LEGACY_TARGET_METADATA
        self.manifest.replace(legacy)
        read_text = Path.read_text

        def read(path, *args, **kwargs):
            if path == legacy:
                raise PermissionError('temporary read lock')
            return read_text(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read), self.assertRaises(ValueError):
            self.service.import_mod_file(1, self.archive, [1001])
        self.assertFalse(self.manifest.exists())
        self.assertEqual(list(self.champion_dir.iterdir()), [legacy])
        self.assertEqual(legacy.read_text(encoding='utf-8'), self.original)

    def test_valid_legacy_manifest_is_preserved_when_importing(self):
        legacy = self.champion_dir / self.service.LEGACY_TARGET_METADATA
        self.manifest.replace(legacy)
        self.service.import_mod_file(1, self.archive, [1001])
        mods = json.loads(self.manifest.read_text(encoding='utf-8'))['mods']
        self.assertEqual(mods['old']['displayName'], 'Old alias')
        self.assertEqual(len(mods), 2)


if __name__ == '__main__':
    unittest.main()
