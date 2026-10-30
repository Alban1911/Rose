import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import xxhash
import zstandard

from injection.retarget import carriers, retarget


def name_hash(name):
    return retarget._name_hash(name)


def path_hash(path):
    return retarget._path_hash(path)


# Bin fields, encoded the way PROP v3 stores them
def string_field(field, text):
    data = text.encode('utf-8')
    return struct.pack('<IBH', name_hash(field), 16, len(data)) + data


def hash_field(field, value):
    return struct.pack('<IBI', name_hash(field), 17, name_hash(value))


def link_field(field, value):
    return struct.pack('<IBI', name_hash(field), 0x84, name_hash(value))


def embed_field(field, fields):
    body = struct.pack('<H', len(fields)) + b''.join(fields)
    return struct.pack('<IBI', name_hash(field), 0x83, 0xABCDEF01) + struct.pack('<I', len(body)) + body


def map_field(field, pairs):
    """A map of hash keys to links."""
    body = struct.pack('<I', len(pairs)) + b''.join(
        struct.pack('<II', name_hash(key), name_hash(value)) for key, value in pairs)
    return struct.pack('<IBBB', name_hash(field), 0x86, 17, 0x84) + struct.pack('<I', len(body)) + body


def make_bin(links, entries):
    """A PROP v3 bin linking these bins, with these (name, fields) entries."""
    out = bytearray(b'PROP') + struct.pack('<II', 3, len(links))
    for link in links:
        data = link.encode('utf-8')
        out += struct.pack('<H', len(data)) + data
    out += struct.pack('<I', len(entries))
    out += b''.join(struct.pack('<I', 0x9B67E9F6) for _ in entries)
    for name, fields in entries:
        body = struct.pack('<IH', name_hash(name), len(fields)) + b''.join(fields)
        out += struct.pack('<I', len(body)) + body
    return bytes(out)


def raw_wad(entries):
    """A wad v3 with these {path: data} entries stored uncompressed."""
    items = sorted((path_hash(path), data) for path, data in entries.items())
    header = bytearray(b'RW\x03\x04') + bytearray(256) + struct.pack('<Q', 0) + struct.pack('<I', len(items))
    offset = len(header) + 32 * len(items)
    table, blobs = bytearray(), bytearray()
    for item_hash, data in items:
        table += struct.pack('<QIIIBBHQ', item_hash, offset, len(data), len(data), 0, 0, 0, 0)
        blobs += data
        offset += len(data)
    return bytes(header + table + blobs)


def bin_names(data):
    """(entry names, every hash and link field's value) of a bin."""
    parsed = retarget._Bin(data)
    keys, key_offsets, at = [], set(), parsed.body_start
    count = struct.unpack_from('<I', data, at)[0]
    at += 4 + 4 * count
    for _ in range(count):
        size, key = struct.unpack_from('<II', data, at)
        keys.append(key)
        key_offsets.add(at + 4)
        at += 4 + size
    values = [struct.unpack_from('<I', data, offset)[0] for offset in parsed.names if offset not in key_offsets]
    return keys, values


SKIN0 = 'data/characters/ahri/skins/skin0.bin'


def builtin_stub():
    """What Rose's skins are: skin 14's data under skin 0's names, linking the game's own bin of skin 14."""
    return make_bin(['DATA/Characters/Ahri/Skins/Skin14.bin'], [
        ('Characters/Ahri/Skins/Skin0', [
            string_field('skinClassification', 'skin'),
            embed_field('skinAnimationProperties', [
                link_field('animationGraphData', 'Characters/Ahri/Animations/Skin14'),
            ]),
            link_field('mResourceResolver', 'Characters/Ahri/Skins/Skin14/Resources'),
            hash_field('skinParent', 'Characters/Ahri/Skins/Skin14'),
        ]),
        ('Characters/Ahri/Skins/Skin0/Resources', [
            map_field('resourceMap', [('Ahri_Q', 'Characters/Ahri/Skins/Skin0/Particles/Ahri_Base_Q')]),
        ]),
    ])


class RetargetTestCase(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        # The game's own bins: skin 14, and its chroma 15 linking it
        self.game = self.root / 'game'
        champions = self.game / 'DATA' / 'FINAL' / 'Champions'
        champions.mkdir(parents=True)
        (champions / 'Ahri.wad.client').write_bytes(raw_wad({
            'data/characters/ahri/skins/skin14.bin': make_bin([], [('Characters/Ahri/Skins/Skin14', [])]),
            'data/characters/ahri/skins/skin15.bin': make_bin(
                ['DATA/Characters/Ahri/Skins/Skin14.bin'], [('Characters/Ahri/Skins/Skin15', [])]),
        }))

    def fantome(self, entries, name='skin.fantome', wad='Ahri.wad.client'):
        path = self.root / name
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr(f'WAD/{wad}', raw_wad(entries))
            archive.writestr('META/info.json', json.dumps({'Name': 'skin'}))
        return path


class BinRenameTests(RetargetTestCase):
    def test_a_builtin_skin_moves_to_the_slot_and_keeps_reading_its_own_content(self):
        plan = retarget.plan_retarget(self.fantome({SKIN0: builtin_stub()}), 1, self.game)

        self.assertEqual((plan.source_number, plan.target_number), (0, 1))
        entries = plan.wads['Ahri.wad.client']
        self.assertEqual(list(entries), [path_hash('data/characters/ahri/skins/skin1.bin')])
        renamed = entries[path_hash('data/characters/ahri/skins/skin1.bin')]
        keys, values = bin_names(renamed)
        self.assertEqual(keys, [name_hash('Characters/Ahri/Skins/Skin1'), name_hash('Characters/Ahri/Skins/Skin1/Resources')])
        # the references to the original skin and to shared particles stay as they are
        self.assertIn(name_hash('Characters/Ahri/Skins/Skin14/Resources'), values)
        self.assertIn(name_hash('Characters/Ahri/Animations/Skin14'), values)
        self.assertIn(name_hash('Characters/Ahri/Skins/Skin14'), values)
        self.assertIn(name_hash('Characters/Ahri/Skins/Skin0/Particles/Ahri_Base_Q'), values)
        self.assertEqual(retarget.bin_links(renamed), ['DATA/Characters/Ahri/Skins/Skin14.bin'])

    def test_references_to_the_skins_own_entries_follow_it(self):
        stub = make_bin([], [
            ('Characters/Ahri/Skins/Skin0', [
                link_field('mResourceResolver', 'Characters/Ahri/Skins/Skin0/Resources'),
            ]),
            ('Characters/Ahri/Skins/Skin0/Resources', []),
        ])
        plan = retarget.plan_retarget(self.fantome({SKIN0: stub}), 7, self.game)
        _, values = bin_names(plan.wads['Ahri.wad.client'][path_hash('data/characters/ahri/skins/skin7.bin')])
        self.assertEqual(values, [name_hash('Characters/Ahri/Skins/Skin7/Resources')])

    def test_shipped_animations_move_with_the_skin(self):
        stub = make_bin(['DATA/Characters/Ahri/Animations/Skin0.bin', 'DATA/Characters/Ahri/Animations/Skin14.bin'], [
            ('Characters/Ahri/Skins/Skin0', [
                embed_field('skinAnimationProperties', [
                    link_field('animationGraphData', 'Characters/Ahri/Animations/Skin0'),
                ]),
            ]),
        ])
        animations = make_bin([], [('Characters/Ahri/Animations/Skin0', [])])
        plan = retarget.plan_retarget(self.fantome({
            SKIN0: stub, 'data/characters/ahri/animations/skin0.bin': animations,
        }), 3, self.game)

        entries = plan.wads['Ahri.wad.client']
        skin = entries[path_hash('data/characters/ahri/skins/skin3.bin')]
        self.assertEqual(bin_names(skin)[1], [name_hash('Characters/Ahri/Animations/Skin3')])
        # only the link to the mod's own animations moves: the game's skin 14 stays
        self.assertEqual(retarget.bin_links(skin), [
            'DATA/Characters/Ahri/Animations/Skin3.bin', 'DATA/Characters/Ahri/Animations/Skin14.bin'])
        moved = entries[path_hash('data/characters/ahri/animations/skin3.bin')]
        self.assertEqual(bin_names(moved)[0], [name_hash('Characters/Ahri/Animations/Skin3')])

    def test_without_its_animations_the_skin_keeps_the_games(self):
        stub = make_bin([], [('Characters/Ahri/Skins/Skin0', [
            link_field('animationGraphData', 'Characters/Ahri/Animations/Skin0'),
        ])])
        plan = retarget.plan_retarget(self.fantome({SKIN0: stub}), 3, self.game)
        entries = plan.wads['Ahri.wad.client']
        self.assertEqual(len(entries), 1)
        self.assertEqual(bin_names(entries[path_hash('data/characters/ahri/skins/skin3.bin')])[1],
                         [name_hash('Characters/Ahri/Animations/Skin0')])

    def test_an_unknown_field_type_skips_its_entry_but_keeps_its_name(self):
        unknown = struct.pack('<IB', name_hash('weird'), 0xB5) + b'\x00' * 6
        stub = make_bin([], [
            ('Characters/Ahri/Skins/Skin0', [link_field('mResourceResolver', 'Characters/Ahri/Skins/Skin0/Resources')]),
            ('Characters/Ahri/Skins/Skin0/Materials/Odd', [unknown]),
            ('Characters/Ahri/Skins/Skin0/Resources', []),
        ])
        plan = retarget.plan_retarget(self.fantome({SKIN0: stub}), 2, self.game)
        keys, values = bin_names(plan.wads['Ahri.wad.client'][path_hash('data/characters/ahri/skins/skin2.bin')])
        self.assertEqual(keys[0], name_hash('Characters/Ahri/Skins/Skin2'))
        self.assertEqual(keys[2], name_hash('Characters/Ahri/Skins/Skin2/Resources'))
        self.assertIn(name_hash('Characters/Ahri/Skins/Skin2/Resources'), values)


class SlotSafetyTests(RetargetTestCase):
    def test_the_slot_a_skin_is_built_on_is_refused(self):
        with self.assertRaisesRegex(retarget.RetargetError, 'skin14.bin'):
            retarget.plan_retarget(self.fantome({SKIN0: builtin_stub()}), 14, self.game)

    def test_a_bin_reached_through_the_games_links_is_refused_too(self):
        chroma = make_bin(['DATA/Characters/Ahri/Skins/Skin15.bin'], [('Characters/Ahri/Skins/Skin0', [])])
        source = self.fantome({SKIN0: chroma})
        with self.assertRaisesRegex(retarget.RetargetError, 'skin14.bin'):
            retarget.plan_retarget(source, 14, self.game)
        self.assertEqual(retarget.plan_retarget(source, 16, self.game).target_number, 16)

    def test_without_the_game_files_nothing_is_moved(self):
        with self.assertRaisesRegex(retarget.RetargetError, 'champion files'):
            retarget.plan_retarget(self.fantome({SKIN0: builtin_stub()}), 1, self.root / 'nowhere')

    def test_a_mod_with_several_skins_needs_to_be_told_which(self):
        source = self.fantome({
            SKIN0: builtin_stub(),
            'data/characters/ahri/skins/skin14.bin': make_bin([], [('Characters/Ahri/Skins/Skin14', [])]),
        })
        with self.assertRaisesRegex(retarget.RetargetError, 'several skins'):
            retarget.plan_retarget(source, 1, self.game)
        self.assertEqual(retarget.plan_retarget(source, 1, self.game, source_number=0).source_number, 0)

    def test_a_mod_already_built_for_the_slot_is_left_alone(self):
        with self.assertRaisesRegex(retarget.RetargetError, 'already'):
            retarget.plan_retarget(self.fantome({SKIN0: builtin_stub()}), 0, self.game)


class ModFormatTests(RetargetTestCase):
    def test_a_folder_of_loose_files_named_by_hash_or_path(self):
        mod = self.root / 'mod'
        wad = mod / 'WAD' / 'Ahri.wad.client'
        (wad / 'data' / 'characters' / 'ahri' / 'animations').mkdir(parents=True)
        (wad / f'{path_hash(SKIN0):016x}.bin').write_bytes(builtin_stub())
        (wad / 'data' / 'characters' / 'ahri' / 'animations' / 'skin0.bin').write_bytes(
            make_bin([], [('Characters/Ahri/Animations/Skin0', [])]))
        plan = retarget.plan_retarget(mod, 1, self.game)
        self.assertEqual(sorted(plan.wads['Ahri.wad.client']), sorted([
            path_hash('data/characters/ahri/skins/skin1.bin'),
            path_hash('data/characters/ahri/animations/skin1.bin'),
        ]))

    def test_the_written_mod_is_a_sorted_compressed_wad_with_checksums(self):
        plan = retarget.plan_retarget(self.fantome({SKIN0: builtin_stub()}), 1, self.game)
        mods = self.root / 'mods'
        self.assertEqual(plan.write(mods), retarget.MOD_FOLDER)

        meta = json.loads((mods / retarget.MOD_FOLDER / 'META' / 'info.json').read_text(encoding='utf-8'))
        self.assertIn('skin 1', meta['Description'])
        data = (mods / retarget.MOD_FOLDER / 'WAD' / 'Ahri.wad.client').read_bytes()
        self.assertEqual(data[:4], b'RW\x03\x04')
        count = struct.unpack_from('<I', data, 268)[0]
        rows = [struct.unpack_from('<QIIIBBHQ', data, 272 + 32 * i) for i in range(count)]
        self.assertEqual([row[0] for row in rows], sorted(row[0] for row in rows))
        item_hash, offset, stored, size, kind, _, _, checksum = rows[0]
        blob = data[offset:offset + stored]
        self.assertEqual(kind, 3)
        self.assertEqual(checksum, xxhash.xxh3_64_intdigest(blob))
        self.assertEqual(zstandard.ZstdDecompressor().decompress(blob, max_output_size=size),
                         plan.wads['Ahri.wad.client'][item_hash])

    def test_each_party_member_gets_a_folder_of_their_own(self):
        plan = retarget.plan_retarget(self.fantome({SKIN0: builtin_stub()}), 1, self.game)
        self.assertEqual(plan.write(self.root / 'mods', 'party_42_slot'), 'party_42_slot')
        self.assertTrue((self.root / 'mods' / 'party_42_slot' / 'WAD' / 'Ahri.wad.client').is_file())


class CompanionTests(RetargetTestCase):
    def test_a_companion_carrying_the_skin_moves_with_it(self):
        champions = self.game / 'DATA' / 'FINAL' / 'Champions'
        (champions / 'Annie.wad.client').write_bytes(raw_wad({}))
        main = make_bin([], [('Characters/Annie/Skins/Skin0', [
            string_field('summon', 'ASSETS/Characters/AnnieTibbers/Skins/Skin31/Tibbers.skn'),
        ])])
        tibbers = make_bin([], [('Characters/AnnieTibbers/Skins/Skin0', [])])
        plan = retarget.plan_retarget(self.fantome({
            'data/characters/annie/skins/skin0.bin': main,
            'data/characters/annietibbers/skins/skin0.bin': tibbers,
        }, wad='Annie.wad.client'), 5, self.game)

        entries = plan.wads['Annie.wad.client']
        moved = entries[path_hash('data/characters/annietibbers/skins/skin5.bin')]
        self.assertEqual(bin_names(moved)[0], [name_hash('Characters/AnnieTibbers/Skins/Skin5')])
        self.assertIn(path_hash('data/characters/annie/skins/skin5.bin'), entries)


class CarrierTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        data_dir = patch.object(carriers, 'get_user_data_dir', return_value=Path(temp_dir.name))
        data_dir.start()
        self.addCleanup(data_dir.stop)
        # Ahri's skin 14 and its chroma 15; skin 1 and its chroma 7
        self.chroma_map = {103015: {'id': 103015, 'skinId': 103014}, 103007: {'id': 103007, 'skinId': 103001}}

    def test_a_carrier_is_saved_per_skin_and_cleared_by_the_default_skin(self):
        carriers.set_carrier(103014, 103001)
        self.assertEqual(carriers.get_carrier(103014), 103001)
        carriers.set_carrier(103014, 103000)
        self.assertIsNone(carriers.get_carrier(103014))

    def test_a_carrier_must_be_the_same_champions(self):
        with self.assertRaises(ValueError):
            carriers.set_carrier(103014, 238001)

    def test_a_chroma_runs_on_its_skins_carrier_while_it_is_still_owned(self):
        carriers.set_carrier(103014, 103007)
        owned = {103001, 103007}
        self.assertEqual(carriers.resolve_carrier(103015, owned, self.chroma_map), 103007)
        self.assertEqual(carriers.resolve_carrier(103014, owned, self.chroma_map), 103007)
        # a chroma whose skin is no longer owned can't be picked in the client
        self.assertIsNone(carriers.resolve_carrier(103014, {103007}, self.chroma_map))
        self.assertIsNone(carriers.resolve_carrier(103002, owned, self.chroma_map))

    def test_the_options_are_the_owned_skins_and_their_owned_chromas(self):
        skins = [
            {'skinId': 103000, 'skinName': 'Ahri', 'isBase': True, 'chromaDetails': []},
            {'skinId': 103001, 'skinName': 'Dynasty Ahri', 'chromaDetails': [
                {'id': 103007, 'name': 'Ruby', 'colors': ['#f00']},
                {'id': 103008, 'name': 'Pearl', 'colors': ['#fff']},
            ]},
            {'skinId': 103014, 'skinName': 'Star Guardian Ahri', 'chromaDetails': [{'id': 103015, 'name': 'Rose'}]},
        ]
        options = carriers.carrier_options(skins, {103001, 103007, 103015}, self.chroma_map,
                                           check=lambda carrier: 'built on it' if carrier == 103007 else None)
        self.assertEqual([option['id'] for option in options], [103001, 103007])
        self.assertEqual(options[1]['parentId'], 103001)
        self.assertTrue(options[1]['chroma'])
        self.assertEqual(options[1]['unavailableReason'], 'built on it')
        self.assertIsNone(options[0]['unavailableReason'])


if __name__ == '__main__':
    unittest.main()
