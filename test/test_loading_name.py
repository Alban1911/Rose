import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from injection.loadingname import loading_name
from injection.mods.mod_facts import ModFacts


def make_table(texts):
    """An RST v5 table with these keys, the way the game stores them."""
    entries, body = [], bytearray()
    for key, text in sorted(texts.items(), key=lambda kv: loading_name._key_hash(kv[0])):
        entries.append(loading_name._key_hash(key) | (len(body) << 38))
        body += text.encode('utf-8') + b'\0'
    out = bytearray(b'RST\x05')
    out += struct.pack('<I', len(entries))
    for entry in entries:
        out += struct.pack('<Q', entry)
    return bytes(out + body)


class LoadingNameTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def test_skin_id_comes_from_the_name_the_injector_was_given(self):
        self.assertEqual(loading_name.parse_skin_id('Shockblade Zed 238001', 238), 238001)
        self.assertEqual(loading_name.parse_skin_id('Shockblade_Zed_238001'), 238001)

    def test_a_chroma_takes_its_skins_name(self):
        chroma = Path('skins') / '893' / '893011' / '893016' / '893016.fantome'

        self.assertEqual(loading_name.parent_skin_id(chroma, 893016), 893011)

    def test_a_skin_keeps_its_own_name(self):
        skin = Path('skins') / '893' / '893011' / '893011.fantome'

        self.assertEqual(loading_name.parent_skin_id(skin, 893011), 893011)

    def test_a_file_stored_anywhere_else_keeps_the_id_it_was_given(self):
        for elsewhere in (
            Path('skins') / '99' / 'Lux Elementalist Air.fantome',  # a form, found by name
            Path('mods') / '893016.fantome',
            Path('skins') / '893' / '238001' / '893016' / '893016.fantome',  # another champion's skin
        ):
            self.assertEqual(loading_name.parent_skin_id(elsewhere, 893016), 893016)

    def test_a_number_in_the_skins_own_name_is_not_taken_for_an_id(self):
        self.assertEqual(loading_name.parse_skin_id('Worlds 2016 Zed', 238), 0)
        self.assertEqual(loading_name.parse_skin_id('Worlds 2016 Zed 238010', 238), 238010)

    def test_the_champion_is_read_from_the_wads_the_skin_carries(self):
        mod = self.root / 'mod'
        (mod / 'WAD').mkdir(parents=True)
        (mod / 'WAD' / 'Zed.wad.client').touch()
        (mod / 'WAD' / 'Global.wad.client').touch()
        self.assertEqual(loading_name.champion_aliases(mod), ['Zed'])

    def test_the_champions_text_becomes_the_skins_and_the_rest_is_untouched(self):
        table = make_table({
            'game_character_displayname_Zed': 'Zed',
            'game_character_displayname_Yasuo': 'Yasuo',
            'game_character_skin_displayname_Zed_1': 'Shockblade Zed',
        })
        patched = loading_name._with_text(
            table, loading_name._key_hash('game_character_displayname_Zed'), 'Shockblade Zed')

        def text(key):
            return loading_name._text_of(patched, loading_name._key_hash(key))

        self.assertEqual(text('game_character_displayname_Zed'), 'Shockblade Zed')
        self.assertEqual(text('game_character_displayname_Yasuo'), 'Yasuo')
        self.assertEqual(text('game_character_skin_displayname_Zed_1'), 'Shockblade Zed')

    def test_an_accented_name_survives_the_round_trip(self):
        table = make_table({'game_character_displayname_Zed': 'Zed'})
        key = loading_name._key_hash('game_character_displayname_Zed')
        self.assertEqual(loading_name._text_of(loading_name._with_text(table, key, 'Lâmina do Trovão'), key),
                         'Lâmina do Trovão')

    def test_the_mod_is_one_loose_file_plus_its_meta(self):
        # A French game: its table goes in the mod (an en_US one takes string overrides)
        game = self.root / 'game'
        wad_dir = game / 'DATA' / 'FINAL' / 'Localized'
        wad_dir.mkdir(parents=True)
        table = make_table({
            'game_character_displayname_Zed': 'Zed',
            'game_character_skin_displayname_Zed_1': 'Shockblade Zed',
        })
        (wad_dir / 'Global.fr_FR.wad.client').write_bytes(make_wad(table))

        mod = self.root / 'mod'
        (mod / 'WAD').mkdir(parents=True)
        (mod / 'WAD' / 'Zed.wad.client').touch()
        mods = self.root / 'mods'
        mods.mkdir()

        name = loading_name.build(game, mods, mod, 238001)
        self.assertEqual(name, loading_name.MOD_FOLDER)
        written = (mods / name / loading_name.TABLE_PATH).read_bytes()
        self.assertEqual(
            loading_name._text_of(written, loading_name._key_hash('game_character_displayname_Zed')),
            'Shockblade Zed')
        meta = json.loads((mods / name / 'META' / 'info.json').read_text(encoding='utf-8'))
        self.assertEqual(meta['Description'], 'Shockblade Zed')

    def _zed_game(self, language='fr_FR'):
        game = self.root / 'game'
        wad_dir = game / 'DATA' / 'FINAL' / 'Localized'
        wad_dir.mkdir(parents=True)
        (wad_dir / f'Global.{language}.wad.client').write_bytes(make_wad(make_table({
            'game_character_displayname_Zed': 'Zed',
            'game_character_skin_displayname_Zed_1': 'Shockblade Zed',
        })))
        mod = self.root / 'mod'
        (mod / 'WAD').mkdir(parents=True)
        (mod / 'WAD' / 'Zed.wad.client').touch()
        mods = self.root / 'mods'
        mods.mkdir()
        return game, mods, mod

    def _other_mod(self, name):
        other = self.root / 'mods' / name
        (other / 'WAD').mkdir(parents=True)
        return other

    def test_nothing_is_built_next_to_a_mod_that_carries_the_language_table(self):
        # LTK Manager keeps one mod's table: with that one, the champion's name would print as its key (#420)
        game, mods, mod = self._zed_game()
        font = self._other_mod('Font')
        (font / 'WAD' / 'Global.en_US.wad.client').write_bytes(make_wad(b'RSTtable'))

        self.assertIsNone(loading_name.build(game, mods, mod, 238001, other_mods=[font]))
        self.assertFalse((mods / loading_name.MOD_FOLDER).exists())

    def test_a_language_table_in_a_wad_folder_or_raw_counts_too(self):
        loose = self._other_mod('Loose')
        table = loose / 'WAD' / 'Global.ko_KR.wad.client' / 'data' / 'menu' / 'ko_kr'
        table.mkdir(parents=True)
        (table / 'lol.stringtable').write_bytes(b'RST')
        hashed = self._other_mod('Hashed')
        (hashed / 'WAD' / 'Global.en_US.wad.client').mkdir()
        (hashed / 'WAD' / 'Global.en_US.wad.client' / f'{loading_name.TABLE_HASH:016x}.stringtable').write_bytes(b'RST')
        raw = self.root / 'mods' / 'Raw' / 'RAW' / 'DATA' / 'Menu' / 'en_US'
        raw.mkdir(parents=True)
        (raw / 'lol.stringtable').write_bytes(b'RST')

        for mod in (loose, hashed, self.root / 'mods' / 'Raw'):
            self.assertTrue(loading_name.ships_language_table(mod), mod.name)

    def test_other_mods_without_the_table_change_nothing(self):
        game, mods, mod = self._zed_game()
        font = self._other_mod('Font')
        (font / 'WAD' / 'Global.en_US.wad.client').write_bytes(make_wad(b'font', path_hash=0x1234))
        announcer = self._other_mod('Announcer')
        (announcer / 'WAD' / 'Map11.en_US.wad.client').write_bytes(b'not read')

        self.assertEqual(
            loading_name.build(game, mods, mod, 238001, other_mods=[font, announcer]), loading_name.MOD_FOLDER)

    def _game_with_languages(self, names, locale=None):
        """A game folder with these language wads, each naming the skin in its own language."""
        game = self.root / 'League of Legends' / 'Game'
        wad_dir = game / 'DATA' / 'FINAL' / 'Localized'
        wad_dir.mkdir(parents=True)
        for language, skin_name in names.items():
            (wad_dir / f'Global.{language}.wad.client').write_bytes(make_wad(make_table({
                'game_character_displayname_Zed': 'Zed',
                'game_character_skin_displayname_Zed_1': skin_name,
            })))
        if locale:
            config = game.parent / 'Config'
            config.mkdir()
            (config / 'LeagueClientSettings.yaml').write_text(
                'install:\n'
                '    gameflow-spectate-reconnect-info: null\n'
                '    globals:\n'
                f'        locale: "{locale}"\n'
                '        region: "TW"\n'
                '    patcher:\n'
                '        locales:\n'
                '        - "en_US"\n', encoding='utf-8')
        mod = self.root / 'mod'
        (mod / 'WAD').mkdir(parents=True)
        (mod / 'WAD' / 'Zed.wad.client').touch()
        mods = self.root / 'mods'
        mods.mkdir()
        return game, mods, mod

    def test_the_table_comes_from_the_clients_language(self):
        """#353: the first wad by name turned a Chinese match into another language"""
        game, mods, mod = self._game_with_languages(
            {'ko_KR': '전격 칼날 제드', 'zh_TW': '電刃 劫'}, locale='zh_TW')
        name = loading_name.build(game, mods, mod, 238001)
        table = (mods / name / loading_name.TABLE_PATH).read_bytes()
        self.assertEqual(loading_name._text_of(table, loading_name._key_hash('game_character_displayname_Zed')),
                         '電刃 劫')

    def test_several_languages_and_no_known_locale_build_nothing(self):
        game, mods, mod = self._game_with_languages({'en_US': 'Shockblade Zed', 'zh_MY': '影刃 劫'})
        self.assertIsNone(loading_name.build(game, mods, mod, 238001))
        self.assertFalse((mods / loading_name.MOD_FOLDER).exists())

    def test_a_locale_without_its_wad_falls_back_to_a_lone_wad_only(self):
        game, mods, mod = self._game_with_languages({'zh_MY': '影刃 劫'}, locale='zh_TW')
        self.assertEqual(loading_name.build(game, mods, mod, 238001), loading_name.MOD_FOLDER)

    def test_the_locale_is_read_under_globals(self):
        game, _, _ = self._game_with_languages({'en_US': 'x'}, locale='zh_TW')
        self.assertEqual(loading_name._client_locale(game), 'zh_TW')
        self.assertIsNone(loading_name._client_locale(self.root / 'nowhere' / 'Game'))

    def test_a_base_skin_builds_nothing(self):
        self.assertIsNone(loading_name.build(self.root, self.root, self.root, 238000))

    def test_wad_paths_hash_like_the_game(self):
        self.assertEqual(loading_name._xxh64(b'data/menu/en_us/lol.stringtable'), loading_name.TABLE_HASH)
        self.assertEqual(loading_name._xxh64(b'data/characters/yasuo/yasuo.bin'), 0xA98BC980AE8AE765)
        self.assertEqual(loading_name._xxh64(b''), 0xEF46DB3751D8E999)

    def test_the_record_points_at_a_key_of_the_same_length(self):
        key = b'game_character_displayname_Zed'
        record = b'\x01\x02' + struct.pack('<H', len(key)) + key + b'\x03'
        patched = loading_name._with_own_record_key(record, 'zed')
        self.assertEqual(len(patched), len(record))
        self.assertIn(struct.pack('<H', len(key)) + b'rose_character_displayname_Zed', patched)
        self.assertIsNone(loading_name._with_own_record_key(b'nothing here', 'Zed'))

    def _game_with_zed_record(self, language):
        game = self.root / 'game'
        (game / 'DATA' / 'FINAL' / 'Localized').mkdir(parents=True)
        (game / 'DATA' / 'FINAL' / 'Localized' / f'Global.{language}.wad.client').write_bytes(make_wad(make_table({
            'game_character_displayname_Zed': 'Zed',
            'game_character_skin_displayname_Zed_1': 'Shockblade Zed',
        })))
        key = b'game_character_displayname_Zed'
        record = struct.pack('<H', len(key)) + key
        (game / 'DATA' / 'FINAL' / 'Champions').mkdir(parents=True)
        (game / 'DATA' / 'FINAL' / 'Champions' / 'Zed.wad.client').write_bytes(
            make_wad(record, loading_name._xxh64(b'data/characters/zed/zed.bin')))
        mod = self.root / 'mod'
        (mod / 'WAD').mkdir(parents=True)
        (mod / 'WAD' / 'Zed.wad.client').touch()
        mods = self.root / 'mods'
        mods.mkdir()
        return game, mods, mod

    def test_an_en_us_game_gets_string_overrides_not_a_table(self):
        # LTK Manager rejects a mod's en_US lol.stringtable on an install that has one (#420)
        game, mods, mod = self._game_with_zed_record('en_US')

        name = loading_name.build(game, mods, mod, 238001)

        self.assertEqual(name, loading_name.MOD_FOLDER)
        self.assertFalse((mods / name / loading_name.TABLE_PATH).exists())
        meta = json.loads((mods / name / 'META' / 'info.json').read_text(encoding='utf-8'))
        self.assertEqual(meta['Layers']['base']['StringOverrides'], {'en_us': {
            'game_character_displayname_Zed': 'Shockblade Zed',
            'rose_character_displayname_Zed': 'Zed',
        }})
        written = (mods / name / 'RAW' / 'data' / 'characters' / 'zed' / 'zed.bin').read_bytes()
        self.assertIn(b'rose_character_displayname_Zed', written)

    def test_an_english_table_next_to_the_clients_language_builds_nothing(self):
        # The mod's table is rejected and the overrides find no table of the client's language:
        # pointed at a key of its own, the name over the head would print that key
        game, mods, mod = self._game_with_languages(
            {'en_US': 'Shockblade Zed', 'zh_TW': '電刃 劫'}, locale='zh_TW')

        self.assertIsNone(loading_name.build(game, mods, mod, 238001))
        self.assertFalse((mods / loading_name.MOD_FOLDER).exists())

    def test_without_the_clients_language_an_en_us_game_takes_overrides(self):
        # LTK Manager targets en_us when it cannot read the client's language either
        game, mods, mod = self._game_with_zed_record('en_US')
        self.assertTrue(loading_name._uses_string_overrides(game))
        self.assertIsNone(loading_name._client_locale(game))

    def test_another_mods_table_does_not_stop_string_overrides(self):
        game, mods, mod = self._game_with_zed_record('en_US')
        font = self.root / 'mods' / 'Font'
        (font / 'WAD').mkdir(parents=True)
        (font / 'WAD' / 'Global.en_US.wad.client').write_bytes(make_wad(b'RSTtable'))

        self.assertEqual(loading_name.build(game, mods, mod, 238001, other_mods=[font]), loading_name.MOD_FOLDER)

    def test_a_transformed_champion_keeps_its_name_too(self):
        # Elise's spider and Nidalee's cougar read the champion's name key from records of their own (#427)
        game, mods, mod = self._game_with_zed_record('fr_FR')
        key = b'game_character_displayname_Zed'
        record = struct.pack('<H', len(key)) + key
        (game / 'DATA' / 'FINAL' / 'Champions' / 'Zed.wad.client').write_bytes(make_wad_entries({
            loading_name._xxh64(b'data/characters/zed/zed.bin'): record,
            loading_name._xxh64(b'data/characters/zedshadow/zedshadow.bin'): b'	' + record,
        }))

        name = loading_name.build(game, mods, mod, 238001)

        shadow = (mods / name / 'RAW' / 'data' / 'characters' / 'zedshadow' / 'zedshadow.bin').read_bytes()
        self.assertEqual(shadow, b'	' + struct.pack('<H', len(key)) + b'rose_character_displayname_Zed')
        self.assertTrue((mods / name / 'RAW' / 'data' / 'characters' / 'zed' / 'zed.bin').exists())

    def _archive(self, path, files, compression=zipfile.ZIP_STORED):
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, 'w', compression) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        return path

    def test_a_skin_archive_is_read_without_unpacking_it(self):
        # Rose links a skin's .fantome into the mods folder as it is, named without an extension
        game, mods, _ = self._game_with_zed_record('fr_FR')
        key = b'game_character_displayname_Zed'
        skins_record = b'skin:' + struct.pack('<H', len(key)) + key
        skin = self._archive(mods / 'Shockblade Zed', {
            'META/info.json': '{}',
            'wad/zed.WAD.client': make_wad(skins_record, loading_name._xxh64(b'data/characters/zed/zed.bin')),
        }, zipfile.ZIP_DEFLATED)

        self.assertEqual(loading_name.champion_aliases(skin), ['zed'])
        name = loading_name.build(game, mods, mods / 'Shockblade Zed', 238001)

        written = (mods / name / 'RAW' / 'data' / 'characters' / 'zed' / 'zed.bin').read_bytes()
        self.assertEqual(written, b'skin:' + struct.pack('<H', len(key)) + b'rose_character_displayname_Zed')

    def test_an_archive_that_carries_the_language_table_counts(self):
        game, mods, mod = self._zed_game()
        packed = self._archive(self.root / 'mods' / 'Font', {
            'WAD/Global.en_US.wad.client': make_wad(b'RSTtable'),
        })
        raw = self._archive(self.root / 'mods' / 'Raw', {'RAW/DATA/Menu/en_US/lol.stringtable': b'RST'})
        other = self._archive(self.root / 'mods' / 'Announcer', {
            'WAD/Global.en_US.wad.client': make_wad(b'font', path_hash=0x1234),
        }, zipfile.ZIP_DEFLATED)

        self.assertTrue(loading_name.ships_language_table(packed))
        self.assertTrue(loading_name.ships_language_table(raw))
        self.assertFalse(loading_name.ships_language_table(other))
        self.assertIsNone(loading_name.build(game, mods, mod, 238001, other_mods=[packed]))

    def test_a_skin_ltk_manager_holds_has_its_record_read_from_ltk_managers_archive(self):
        game, mods, _ = self._game_with_zed_record('fr_FR')
        key = b'game_character_displayname_Zed'
        skins_record = b'skin:' + struct.pack('<H', len(key)) + key
        archive = self._archive(self.root / 'ltk' / 'shockblade-zed.fantome', {
            'META/info.json': '{}',
            'WAD/Zed.wad.client': make_wad(skins_record, loading_name._xxh64(b'data/characters/zed/zed.bin')),
        })
        opened = []
        skin = loading_name.LtkSkin(('Zed',), lambda: opened.append(archive) or archive)

        self.assertIsNone(loading_name.build(game, mods, skin, 238002))
        self.assertEqual(opened, [])
        name = loading_name.build(game, mods, skin, 238001)

        written = (mods / name / 'RAW' / 'data' / 'characters' / 'zed' / 'zed.bin').read_bytes()
        self.assertEqual(written, b'skin:' + struct.pack('<H', len(key)) + b'rose_character_displayname_Zed')
        self.assertEqual(opened, [archive])

    def test_without_ltk_managers_archive_the_games_record_is_used(self):
        game, mods, _ = self._game_with_zed_record('fr_FR')
        key = b'game_character_displayname_Zed'
        packed = self.root / 'ltk' / 'shockblade-zed.modpkg'
        packed.parent.mkdir()
        packed.write_bytes(b'modpkg')
        for archive in (None, packed):
            with self.subTest(archive=archive):
                name = loading_name.build(game, mods, loading_name.LtkSkin(('Zed',), lambda: archive), 238001)

                written = (mods / name / 'RAW' / 'data' / 'characters' / 'zed' / 'zed.bin').read_bytes()
                self.assertEqual(written, struct.pack('<H', len(key)) + b'rose_character_displayname_Zed')

    def test_the_facts_of_a_mod_ltk_manager_holds_tell_whether_it_carries_the_text_table(self):
        game, mods, mod = self._zed_game()

        self.assertIsNone(loading_name.build(game, mods, mod, 238001, other_mods=[ModFacts(None, (), True)]))
        self.assertEqual(loading_name.build(game, mods, mod, 238001, other_mods=[ModFacts(None, ('Ahri',), False)]),
                         loading_name.MOD_FOLDER)

    def test_the_chat_keeps_the_champions_name(self):
        game = self.root / 'game'
        (game / 'DATA' / 'FINAL' / 'Localized').mkdir(parents=True)
        (game / 'DATA' / 'FINAL' / 'Localized' / 'Global.fr_FR.wad.client').write_bytes(make_wad(make_table({
            'game_character_displayname_Zed': 'Zed',
            'game_character_skin_displayname_Zed_1': 'Shockblade Zed',
        })))
        key = b'game_character_displayname_Zed'
        record = struct.pack('<H', len(key)) + key
        (game / 'DATA' / 'FINAL' / 'Champions').mkdir(parents=True)
        (game / 'DATA' / 'FINAL' / 'Champions' / 'Zed.wad.client').write_bytes(
            make_wad(record, loading_name._xxh64(b'data/characters/zed/zed.bin')))

        mod = self.root / 'mod'
        (mod / 'WAD').mkdir(parents=True)
        (mod / 'WAD' / 'Zed.wad.client').touch()
        mods = self.root / 'mods'
        mods.mkdir()

        name = loading_name.build(game, mods, mod, 238001)
        table = (mods / name / loading_name.TABLE_PATH).read_bytes()
        self.assertEqual(loading_name._text_of(table, loading_name._key_hash('game_character_displayname_Zed')),
                         'Shockblade Zed')
        self.assertEqual(loading_name._text_of(table, loading_name._key_hash('rose_character_displayname_Zed')),
                         'Zed')
        written = (mods / name / 'RAW' / 'data' / 'characters' / 'zed' / 'zed.bin').read_bytes()
        self.assertEqual(written, struct.pack('<H', len(key)) + b'rose_character_displayname_Zed')


def make_wad_entries(entries):
    """A wad v3 holding these uncompressed entries ({path hash: data})."""
    header = bytearray(b'RW') + bytearray(256) + struct.pack('<Q', 0) + struct.pack('<I', len(entries))
    offset = len(header) + 32 * len(entries)
    toc, body = bytearray(), bytearray()
    for path_hash, data in entries.items():
        toc += struct.pack('<QIII', path_hash, offset + len(body), len(data), len(data))
        toc += bytes([0, 0]) + struct.pack('<H', 0) + struct.pack('<Q', 0)
        body += data
    return bytes(header + toc + body)


def make_wad(data, path_hash=loading_name.TABLE_HASH):
    """A wad v3 holding one uncompressed entry."""
    header = bytearray(b'RW\x03\x03') + bytearray(256) + struct.pack('<Q', 0) + struct.pack('<I', 1)
    offset = len(header) + 32
    entry = struct.pack('<QIII', path_hash, offset, len(data), len(data))
    entry += bytes([0, 0]) + struct.pack('<H', 0) + struct.pack('<Q', 0)
    return bytes(header + entry + data)


if __name__ == '__main__':
    unittest.main()
