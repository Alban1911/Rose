import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from injection.loadingname import loading_name as m
from test.test_loading_name import make_table, make_wad


class LocaleIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.game = self.root / 'game'
        self.localized = self.game / 'DATA/FINAL/Localized'
        self.localized.mkdir(parents=True)
        self.mod = self.root / 'skin'
        (self.mod / 'WAD').mkdir(parents=True)
        (self.mod / 'WAD/Zed.wad.client').touch()
        self.mods = self.root / 'mods'

    def add(self, locale, champion, skin, unrelated):
        texts = {'game_character_displayname_Zed': champion,
                 'game_character_displayname_Yasuo': unrelated}
        if skin is not None:
            texts['game_character_skin_displayname_Zed_1'] = skin
        (self.localized / f'Global.{locale}.wad.client').write_bytes(make_wad(make_table(texts)))

    def output(self, locale):
        return self.mods / m.MOD_FOLDER / 'WAD' / f'Global.{locale}.wad.client' / m.TABLE_PATH.relative_to('RAW')

    def test_two_languages_never_share_their_table(self):
        self.add('en_US', 'Zed', 'Shockblade Zed', 'Yasuo')
        self.add('zh_CN', '影流之主', '冲击之刃 劫', '疾风剑豪')
        self.assertEqual(m.build(self.game, self.mods, self.mod, 238001), m.MOD_FOLDER)
        for locale, skin, other in [('en_US', 'Shockblade Zed', 'Yasuo'), ('zh_CN', '冲击之刃 劫', '疾风剑豪')]:
            table = self.output(locale).read_bytes()
            self.assertEqual(m._text_of(table, m._key_hash('game_character_displayname_Zed')), skin)
            self.assertEqual(m._text_of(table, m._key_hash('game_character_displayname_Yasuo')), other)
        self.assertFalse((self.mods / m.MOD_FOLDER / m.TABLE_PATH).exists())

    def test_missing_translation_does_not_fall_back_to_another_language(self):
        self.add('en_US', 'Zed', 'Shockblade Zed', 'Yasuo')
        self.add('zh_CN', '影流之主', None, '疾风剑豪')
        self.assertIsNone(m.build(self.game, self.mods, self.mod, 238001))
        self.assertFalse(self.output('en_US').exists())
        self.assertFalse(self.output('zh_CN').exists())

    def test_chinese_only_installation_keeps_chinese(self):
        self.add('zh_CN', '影流之主', '冲击之刃 劫', '疾风剑豪')
        self.assertEqual(m.build(self.game, self.mods, self.mod, 238001), m.MOD_FOLDER)
        self.assertIn('疾风剑豪'.encode(), self.output('zh_CN').read_bytes())

    def test_failed_packing_is_not_silently_accepted(self):
        self.add('zh_CN', '影流之主', '冲击之刃 劫', '疾风剑豪')
        m.build(self.game, self.mods, self.mod, 238001)
        with patch.object(m.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaises(RuntimeError):
                m.repair_locale_overlays(self.game, self.mods, self.root / 'overlay', Path('mod-tools.exe'))

    def test_each_packer_call_is_scoped_and_only_its_locale_is_copied(self):
        self.add('en_US', 'Zed', 'Shockblade Zed', 'Yasuo')
        self.add('zh_CN', '影流之主', '冲击之刃 劫', '疾风剑豪')
        m.build(self.game, self.mods, self.mod, 238001)
        def pack(command, **kwargs):
            folders = list((Path(command[2]) / m.MOD_FOLDER / 'WAD').iterdir())
            self.assertEqual(len(folders), 1)
            table = (folders[0] / m.TABLE_PATH.relative_to('RAW')).read_bytes()
            out = Path(command[3]) / 'DATA/FINAL/Localized'
            out.mkdir(parents=True)
            for locale in ('en_US', 'zh_CN'):
                (out / f'Global.{locale}.wad.client').write_bytes(make_wad(table))
            return SimpleNamespace(returncode=0)
        overlay = self.root / 'overlay'
        with patch.object(m.subprocess, 'run', side_effect=pack) as runner:
            m.repair_locale_overlays(self.game, self.mods, overlay, Path('mod-tools.exe'))
        self.assertEqual(runner.call_count, 2)
        for locale in ('en_US', 'zh_CN'):
            actual = m._read_table(overlay / 'DATA/FINAL/Localized' / f'Global.{locale}.wad.client')
            self.assertEqual(actual, self.output(locale).read_bytes())

    def test_wrong_table_from_successful_packer_is_rejected(self):
        self.add('zh_CN', '影流之主', '冲击之刃 劫', '疾风剑豪')
        m.build(self.game, self.mods, self.mod, 238001)
        def bad_pack(command, **kwargs):
            out = Path(command[3]) / 'DATA/FINAL/Localized'
            out.mkdir(parents=True)
            (out / 'Global.zh_CN.wad.client').write_bytes(make_wad(make_table({})))
            return SimpleNamespace(returncode=0)
        with patch.object(m.subprocess, 'run', side_effect=bad_pack):
            with self.assertRaises(RuntimeError):
                m.repair_locale_overlays(self.game, self.mods, self.root / 'overlay', Path('mod-tools.exe'))
