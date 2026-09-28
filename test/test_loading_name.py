import json
import struct
import tempfile
import unittest
from pathlib import Path

from injection.loadingname import loading_name


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
        game = self.root / 'game'
        wad_dir = game / 'DATA' / 'FINAL' / 'Localized'
        wad_dir.mkdir(parents=True)
        table = make_table({
            'game_character_displayname_Zed': 'Zed',
            'game_character_skin_displayname_Zed_1': 'Shockblade Zed',
        })
        (wad_dir / 'Global.en_US.wad.client').write_bytes(make_wad(table))

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

    def test_the_chat_keeps_the_champions_name(self):
        game = self.root / 'game'
        (game / 'DATA' / 'FINAL' / 'Localized').mkdir(parents=True)
        (game / 'DATA' / 'FINAL' / 'Localized' / 'Global.en_US.wad.client').write_bytes(make_wad(make_table({
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


def make_wad(data, path_hash=loading_name.TABLE_HASH):
    """A wad v3 holding one uncompressed entry."""
    header = bytearray(b'RW\x03\x03') + bytearray(256) + struct.pack('<Q', 0) + struct.pack('<I', 1)
    offset = len(header) + 32
    entry = struct.pack('<QIII', path_hash, offset, len(data), len(data))
    entry += bytes([0, 0]) + struct.pack('<H', 0) + struct.pack('<Q', 0)
    return bytes(header + entry + data)


if __name__ == '__main__':
    unittest.main()
