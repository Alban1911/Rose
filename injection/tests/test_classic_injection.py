import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from injection import classic
from injection.core import injector as injector_module
from injection.core.injector import SkinInjector
from injection.mods.mod_manager import ModManager
from injection.mods.zip_resolver import ZipResolver


class ClassicIdTests(unittest.TestCase):
    def test_classic_ids(self):
        self.assertEqual(classic.to_regular_skin_id(60103052), 103052)
        self.assertEqual(classic.to_regular_skin_id(103052), 103052)
        self.assertIsNone(classic.to_regular_skin_id(None))
        self.assertEqual(classic.to_classic_champion_id(103), 60103)
        self.assertEqual(classic.to_classic_champion_id(60103), 60103)
        self.assertIsNone(classic.to_classic_champion_id(None))

    def test_jade_is_rift_classic(self):
        self.assertTrue(classic.is_classic_game_mode('JADE'))
        self.assertFalse(classic.is_classic_game_mode('CLASSIC'))
        self.assertFalse(classic.is_classic_game_mode(None))


class ClassicInjectionTests(unittest.TestCase):
    """Rift Classic games inject the stored Classic skins (%LOCALAPPDATA%/Rose/classic)"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        skins_dir, classic_dir = root / 'skins', root / 'classic'
        self._fantome(skins_dir / '1' / '1001' / '1001.fantome', 'regular')
        # LeagueSkins' layout: classic/<Classic champion>/<regular ID, or Classic ID for Classic-only skins>
        self._fantome(classic_dir / '60001' / '1001' / '1001.fantome', 'classic')
        self._fantome(classic_dir / '60001' / '60001301' / '60001301.fantome', 'classic')
        self._fantome(classic_dir / '60001' / '60001301' / '60001302' / '60001302.fantome', 'classic')
        self._fantome(classic_dir / '60103' / '103001' / '103052' / '103052.fantome', 'classic')
        # The repository's older tree under regular champion IDs is not used
        self._fantome(classic_dir / '1' / '1005' / '1005.fantome', 'classic')

        # Only what inject_skin uses: no game or tools detection
        self.injector = SkinInjector.__new__(SkinInjector)
        self.injector.zips_dir, self.injector.classic_dir = skins_dir, classic_dir
        self.injector.zip_resolver = ZipResolver(skins_dir)
        self.injector.classic_resolver = ZipResolver(classic_dir)
        self.injector.mod_manager = ModManager(root / 'mods')
        # No game files: the loading screen name is skipped
        self.injector.game_dir, self.injector.mods_dir = root / 'game', root / 'mods'
        self.injector.last_injection_timing = None

        run_overlay = patch.object(SkinInjector, '_mk_run_overlay', return_value=0)
        self.run_overlay = run_overlay.start()
        self.addCleanup(run_overlay.stop)
        reporter = patch.object(injector_module, 'report_issue')
        self.report_issue = reporter.start()
        self.addCleanup(reporter.stop)
        self.party = MagicMock(return_value=['party_42'])

    @staticmethod
    def _fantome(path, library):
        path.parent.mkdir(parents=True)
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('META/info.json', json.dumps({'Library': library}))

    def _injected(self):
        mods = self.run_overlay.call_args.args[0]
        info = self.injector.mod_manager.mods_dir / mods[0] / 'META' / 'info.json'
        return mods, json.loads(info.read_text())['Library']

    def test_classic_game_injects_the_stored_classic_skin(self):
        self.assertTrue(self.injector.inject_skin(
            'skin_60001001', champion_id=60001, extra_mods_callback=self.party, classic=True,
        ))
        # Friends' skins come along (the party hook takes them from the Classic library)
        self.assertEqual(self._injected(), (['1001', 'party_42'], 'classic'))

    def test_a_friends_classic_skin_is_found_like_ours(self):
        archive = self.injector._resolve_zip(
            'skin_60103001', chroma_id=60103052, champion_id=60103, classic=True,
        )
        self.assertEqual(archive.parent.name, '103052')
        self.assertEqual(self.injector._resolve_zip('skin_60001301', champion_id=60001, classic=True).name,
                         '60001301.fantome')

    def test_classic_chroma(self):
        self.assertTrue(self.injector.inject_skin(
            'chroma_60103052', chroma_id=60103052, champion_id=60103, classic=True,
        ))
        self.assertEqual(self._injected(), (['103052'], 'classic'))

    def test_skins_only_in_rift_classic(self):
        self.assertTrue(self.injector.inject_skin('skin_60001301', champion_id=60001, classic=True))
        self.assertEqual(self._injected(), (['60001301'], 'classic'))
        self.assertTrue(self.injector.inject_skin(
            'chroma_60001302', chroma_id=60001302, champion_id=60001, classic=True,
        ))
        self.assertEqual(self._injected(), (['60001302'], 'classic'))

    def test_regular_games_still_inject_the_regular_skin(self):
        self.assertTrue(self.injector.inject_skin('skin_1001', champion_id=1, extra_mods_callback=self.party))
        self.assertEqual(self._injected(), (['1001', 'party_42'], 'regular'))

    def test_skin_without_a_classic_version_is_reported(self):
        self.assertFalse(self.injector.inject_skin('skin_60001005', champion_id=60001, classic=True))
        self.run_overlay.assert_not_called()
        self.assertIn('Rift Classic', self.report_issue.call_args.args[2])


if __name__ == '__main__':
    unittest.main()
