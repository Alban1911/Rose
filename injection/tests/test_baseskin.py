"""A custom skin is made to match the base skin's identity: its sound banks and
bank units, its SKN/SKL padding and its championSkinName (injection.baseskin).

The audio cases are those of RoseBin's audio.rs, which builds the packages Rose
ships: the two must keep producing the same bins.
"""

import hashlib
import os
import shutil
import struct
import tempfile
import tracemalloc
import unittest
import zipfile
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import zstandard

from injection.baseskin import audio, fix_mod, library
from injection.baseskin import steps
from injection.baseskin.audio import AudioBanks, MergeContext, SharedUnit
from injection.baseskin.bnk import Bank, wwise_hash
from injection.baseskin.package import character_names, split_wad_name
from injection.baseskin.propbin import (
    EMBED, HASH, LIST, POINTER, STRING, Bin, Embed, Entry, Field, Value, build, entry_types, fnv1a_lower,
)
from injection.baseskin.wad import BytesSource, FileSource, GameWad, ModWad, WadError, path_hash
from injection.mods.mod_facts import archive_index_hash
from injection.mods.storage import ModStorageService
from party.discovery import custom_mods

SKIN_DATA = fnv1a_lower("SkinCharacterDataProperties")
H = fnv1a_lower


# --------------------------------------------------------------------------------------
# builders
# --------------------------------------------------------------------------------------

def strings(values):
    return Value(LIST, [Value.string(v) for v in values], STRING)


def unit(name, bank_paths, events):
    return Value(POINTER, Embed(H("BankUnit"), [
        Field(H("name"), Value.string(name)),
        Field(H("bankPath"), strings(bank_paths)),
        Field(H("events"), strings(events)),
    ]))


def audio_embed(tags, units):
    return Value(EMBED, Embed(H("SkinAudioProperties"), [
        Field(H("tagEventList"), strings(tags)),
        Field(H("bankUnits"), Value(LIST, units, POINTER)),
    ]))


def mesh_embed(skeleton, skin):
    return Value(EMBED, Embed(H("SkinMeshDataProperties"), [
        Field(H("skeleton"), Value.string(skeleton)),
        Field(H("simpleSkin"), Value.string(skin)),
    ]))


def skin_entry(tags=("Aatrox",), units=(), name="Aatrox", skeleton=None, skin=None, path="Characters/Aatrox/Skins/Skin0"):
    fields = [Field(H("championSkinName"), Value.string(name))]
    if skeleton is not None:
        fields.append(Field(H("skinMeshProperties"), mesh_embed(skeleton, skin)))
    fields.append(Field(H("skinAudioProperties"), audio_embed(list(tags), list(units))))
    return Entry(SKIN_DATA, H(path), fields)


def bank_bytes(events):
    """A v145 bank with one Action per action id, then the events."""
    action_ids = []
    for _, actions in events:
        for action in actions:
            if action not in action_ids:
                action_ids.append(action)
    hirc = struct.pack("<I", len(action_ids) + len(events))
    for action in action_ids:
        hirc += bytes([3]) + struct.pack("<II", 6, action) + bytes([0x03, 0x04])
    for name, actions in events:
        hirc += bytes([4]) + struct.pack("<II", 5 + 4 * len(actions), wwise_hash(name)) + bytes([len(actions)])
        hirc += b"".join(struct.pack("<I", action) for action in actions)
    return (b"BKHD" + struct.pack("<IIII", 12, 145, 0x1234, wwise_hash("French(France)"))
            + b"HIRC" + struct.pack("<I", len(hirc)) + hirc)


def bank(events):
    return Bank.parse(bank_bytes(events))


def banks_with(entries):
    banks = AudioBanks(None, Path("Aatrox.wad.client"))
    banks._locale_wads = []
    for path, locale, content in entries:
        banks._banks.setdefault(path.lower(), []).append(audio._BankCopy(locale, path, content))
    return banks


def tags_of(entry):
    return audio.tag_event_list(entry)


def units_of(entry):
    return audio.read_units(entry.find_field(audio.PROP_SKIN_AUDIO).value.as_embed())


def patched(banks, path, locale=None):
    found = [item for item in banks.into_patched() if item.path == path and item.locale == locale]
    assert found, f"{path} ({locale}) was not patched"
    return Bank.parse(found[0].data)


def merge(entry, character, banks, context=None):
    return audio.merge_skin_audio_tags(entry, character, banks, context or MergeContext())


SFX = "ASSETS/Sounds/Aatrox_Skin33_SFX_events.bnk"
VO = "ASSETS/Sounds/VO/en_US/Aatrox_Skin33_VO_events.bnk"
BASE = "ASSETS/Sounds/Aatrox_Base_SFX_events.bnk"


# --------------------------------------------------------------------------------------
# bins and banks
# --------------------------------------------------------------------------------------

class PropBinTests(unittest.TestCase):
    def test_an_untouched_bin_writes_back_as_it_came(self):
        data = build([skin_entry(), Entry(H("Other"), 7, [Field(1, Value(5, struct.pack("<H", 9)))])])
        self.assertEqual(Bin(data).write(), data)
        reader = Bin(data)
        reader.find_entry(SKIN_DATA)
        self.assertEqual(reader.write(), data)  # read but not changed

    def test_only_the_entry_that_changed_is_written_again(self):
        other = Entry(H("Other"), 7, [Field(1, Value(5, struct.pack("<H", 9)))])
        data = build([other, skin_entry(name="AatroxSkin01")])
        bin_file = Bin(data)
        bin_file.find_entry(SKIN_DATA).set_field(H("championSkinName"), Value.string("Aatrox"))
        written = bin_file.write()
        self.assertNotEqual(written, data)
        self.assertEqual(Bin(written).find_entry(SKIN_DATA).find_field(H("championSkinName")).value.v, "Aatrox")
        # The other entry's bytes are copied as they were
        start, end = Bin(data)._locate()[0]
        self.assertEqual(written[start:end], data[start:end])

    def test_values_of_every_kind_round_trip(self):
        embed = Embed(H("Thing"), [
            Field(1, Value(HASH, struct.pack("<I", 5))),
            Field(2, Value(0x81, [Value(HASH, struct.pack("<I", 1))], HASH)),
            Field(3, Value(0x85, Value(STRING, "x"), STRING)),
            Field(4, Value(0x85, None, STRING)),
            Field(5, Value(0x86, [(Value(STRING, "k"), Value(3, b"\x07"))], STRING, 3)),
            Field(6, Value(0x0B, struct.pack("<ff", 1.5, float("nan")))),
        ])
        data = build([Entry(H("Container"), 9, [Field(10, Value(EMBED, embed)), Field(11, Value(POINTER, None))])])
        bin_file = Bin(data)
        bin_file.find_entry(H("Container"))
        self.assertEqual(bin_file.write(), data)
        self.assertEqual(_rewritten(data), data)

    def test_a_wide_static_material_name_keeps_its_place(self):
        material = Entry(0xFF9D3409, 1, [
            Field(0x8D39BDE6, Value(HASH, struct.pack("<Q", 0x3677AC7E7BBDDDF0))),
            Field(7, Value(3, b"\x01")),
        ])
        data = build([material])
        parsed = Bin(data).find_entry(0xFF9D3409)
        self.assertEqual([field.name_hash for field in parsed.fields], [0x8D39BDE6, 7])
        self.assertEqual(_rewritten(data), data)

    def test_bool_tagged_bytes_above_one_are_left_as_the_mod_wrote_them(self):
        data = build([Entry(H("Thing"), 1, [Field(1, Value(1, b"\x03"))])])
        bin_file = Bin(data)
        self.assertEqual(bin_file.find_entry(H("Thing")).fields[0].value.v, b"\x03")
        self.assertEqual(bin_file.write(), data)

    def test_a_file_that_is_not_a_bin_lists_no_types(self):
        self.assertEqual(entry_types(b"RW\x03\x04"), [])
        self.assertEqual(entry_types(build([skin_entry()])), [SKIN_DATA])


def _rewritten(data):
    """The file written again from its entries' values, not from the bytes they came as."""
    bin_file = Bin(data)
    return build([bin_file.find_entry(type_hash) for type_hash in bin_file.types], bin_file.version)


class BankTests(unittest.TestCase):
    def test_the_hash_matches_a_known_event_id(self):
        # From Aatrox_Skin33_VO_events.bnk
        self.assertEqual(wwise_hash("Play_vo_AatroxSkin33_Kill3DRekSaiSkin26"), 0x06254AE4)
        self.assertEqual(wwise_hash("PLAY_VO_AATROXSKIN33_KILL3DREKSAISKIN26"), 0x06254AE4)

    def test_a_bank_nobody_edited_writes_back_identical(self):
        data = bank_bytes([("Play_sfx_AatroxSkin33_Q", [0xDDCCBBAA]), ("Play_sfx_Aatrox_W", [1, 2])])
        self.assertEqual(Bank.parse(data).write(), data)

    def test_events_can_be_read_added_and_rewired(self):
        content = bank([("Play_sfx_AatroxSkin33_Q", [5]), ("Play_sfx_Aatrox_W", [1, 2])])
        skin, base_q, base_w = (wwise_hash(n) for n in ("Play_sfx_AatroxSkin33_Q", "Play_sfx_Aatrox_Q", "Play_sfx_Aatrox_W"))
        actions = content.event_actions(skin)
        self.assertEqual(actions, [5])
        self.assertFalse(content.has_event(base_q))
        content.add_event(base_q, actions)
        self.assertEqual(content.set_event_actions(base_w, actions), 1)
        again = Bank.parse(content.write())
        self.assertEqual((again.event_actions(base_q), again.event_actions(base_w), again.event_actions(skin)),
                         ([5], [5], [5]))

    def test_extracted_events_carry_their_actions_and_a_new_header(self):
        content = bank([("Play_sfx_AatroxSkin33_Q", [0x11])])
        source, alias, missing = (wwise_hash(n) for n in ("Play_sfx_AatroxSkin33_Q", "Play_sfx_Aatrox_Q", "Play_sfx_Gone"))
        extracted, count = content.extract_events(0xABCD, 0x1111, [(alias, source), (alias, source), (wwise_hash("x"), missing)])
        self.assertEqual(count, 1)
        data = extracted.write()
        self.assertEqual(struct.unpack_from("<III", data, 8), (145, 0xABCD, 0x1111))
        again = Bank.parse(data)
        self.assertEqual(again.event_actions(alias), [0x11])
        self.assertFalse(again.has_event(source))

    def test_a_newer_bank_counts_actions_as_a_variable_length_integer(self):
        from injection.baseskin import bnk
        for value in (0, 1, 127, 128, 300, 16383, 16384):
            encoded = bnk._write_var_uint(value)
            self.assertEqual(bnk._read_var_uint(encoded), (value, len(encoded)))


# --------------------------------------------------------------------------------------
# the audio merge
# --------------------------------------------------------------------------------------

class AudioMergeTests(unittest.TestCase):
    def test_skin_tag_events_get_base_aliases(self):
        entry = skin_entry(["Aatrox", "AatroxSkin33"], [
            unit("Aatrox_Skin33_SFX", ["x_audio.bnk", SFX],
                 ["Play_sfx_AatroxSkin33_AatroxQ_OnCast", "Play_sfx_Aatrox_Skin33_Homeguard3D_loop_anim"]),
            unit("Aatrox_Skin33_VO", [VO], ["Play_vo_AatroxSkin33_AatroxQ_cast3D"]),
        ])
        banks = banks_with([
            (SFX, None, bank([("Play_sfx_AatroxSkin33_AatroxQ_OnCast", [10, 11]),
                              ("Play_sfx_Aatrox_Skin33_Homeguard3D_loop_anim", [12])])),
            (VO, "fr_FR", bank([("Play_vo_AatroxSkin33_AatroxQ_cast3D", [20])])),
        ])

        report = merge(entry, "aatrox", banks)

        self.assertEqual(report.removed_tags, ["AatroxSkin33"])
        self.assertEqual((report.events_added, report.events_replaced, report.events_missing), (1, 0, 0))
        self.assertEqual((report.events_language_neutral, report.events_shadowed), (1, 0))
        self.assertEqual(tags_of(entry), ["Aatrox"])
        units = units_of(entry)
        self.assertEqual(units[0].events, [
            "Play_sfx_AatroxSkin33_AatroxQ_OnCast", "Play_sfx_Aatrox_Skin33_Homeguard3D_loop_anim",
            "Play_sfx_Aatrox_AatroxQ_OnCast"])
        self.assertEqual(units[1].events, ["Play_vo_AatroxSkin33_AatroxQ_cast3D", "Play_vo_Aatrox_AatroxQ_cast3D"])
        # The VO unit also loads the language-neutral bank, right after its own
        sidecar = audio.sidecar_path(VO)
        self.assertEqual(sidecar, "ASSETS/Sounds/VO/Aatrox_Skin33_VO_basetag_events.bnk")
        paths = [v.v for v in entry.find_field(audio.PROP_SKIN_AUDIO).value.as_embed()
                 .find_field(audio.PROP_BANK_UNITS).value.v[1].as_embed().find_field(audio.PROP_BANK_PATH).value.v]
        self.assertEqual(paths, [VO, sidecar])

        shipped = banks.into_patched()
        self.assertEqual(len(shipped), 2, "the localized bank itself is never shipped")
        self.assertTrue(all(item.locale is None for item in shipped))
        sfx = patched(banks, SFX)
        self.assertEqual(sfx.event_actions(wwise_hash("Play_sfx_Aatrox_AatroxQ_OnCast")), [10, 11])
        # The originals stay, so direct references from animation bins still work
        self.assertEqual(sfx.event_actions(wwise_hash("Play_sfx_AatroxSkin33_AatroxQ_OnCast")), [10, 11])
        neutral = patched(banks, sidecar)
        self.assertEqual(neutral.event_actions(wwise_hash("Play_vo_Aatrox_AatroxQ_cast3D")), [20])
        self.assertFalse(neutral.has_event(wwise_hash("Play_vo_AatroxSkin33_AatroxQ_cast3D")))
        data = next(item.data for item in shipped if item.path == sidecar)
        self.assertEqual(struct.unpack_from("<II", data, 12),
                         (wwise_hash("Aatrox_Skin33_VO_basetag_events"), wwise_hash("SFX")))

    def test_a_localized_base_bank_defining_the_alias_is_left_alone(self):
        base_vo = "ASSETS/Sounds/VO/en_US/Akali_Base_VO_events.bnk"
        skin_vo = "ASSETS/Sounds/VO/en_US/Akali_Skin61_VO_events.bnk"
        entry = skin_entry(["Akali", "AkaliSkin61"], [
            unit("Akali_Base_VO", [base_vo], ["Play_vo_Akali_AkaliE_cast3D"]),
            unit("Akali_Skin61_VO", [skin_vo], ["Play_vo_AkaliSkin61_AkaliE_cast3D"]),
        ])
        banks = banks_with([
            (base_vo, "fr_FR", bank([("Play_vo_Akali_AkaliE_cast3D", [1])])),
            (skin_vo, "fr_FR", bank([("Play_vo_AkaliSkin61_AkaliE_cast3D", [61])])),
        ])
        report = merge(entry, "akali", banks)
        self.assertEqual((report.events_language_neutral, report.events_shadowed), (1, 1))
        self.assertEqual(units_of(entry)[0].events, ["Play_vo_Akali_AkaliE_cast3D"])
        self.assertEqual(len(banks.into_patched()), 1)
        neutral = patched(banks, audio.sidecar_path(skin_vo))
        self.assertEqual(neutral.event_actions(wwise_hash("Play_vo_Akali_AkaliE_cast3D")), [61])

    def test_sidecar_paths_drop_the_locale_folder_and_keep_events_in_the_name(self):
        self.assertEqual(
            audio.sidecar_path("ASSETS/Sounds/Wwise2016/VO/en_US/Characters/Aatrox/Skins/Skin01/Aatrox_Skin01_VO_events.bnk"),
            "ASSETS/Sounds/Wwise2016/VO/Characters/Aatrox/Skins/Skin01/Aatrox_Skin01_VO_basetag_events.bnk")

    def test_existing_base_events_move_into_the_skin_bank(self):
        entry = skin_entry(["Aatrox", "AatroxSkin09"], [
            unit("Aatrox_Base_SFX", [BASE], ["Play_sfx_Aatrox_Recall3D_buffactivate", "Play_sfx_Aatrox_AatroxW_OnCast"]),
            unit("Aatrox_Skin09_SFX", [SFX], ["Play_sfx_AatroxSkin09_Recall3D_buffactivate"]),
        ])
        banks = banks_with([
            (BASE, None, bank([("Play_sfx_Aatrox_Recall3D_buffactivate", [1]), ("Play_sfx_Aatrox_AatroxW_OnCast", [2])])),
            (SFX, None, bank([("Play_sfx_AatroxSkin09_Recall3D_buffactivate", [90])])),
        ])
        report = merge(entry, "aatrox", banks)
        self.assertEqual((report.events_added, report.events_replaced), (0, 1))
        # The name moves from the base unit to the skin unit
        self.assertEqual(units_of(entry)[0].events, ["Play_sfx_Aatrox_AatroxW_OnCast"])
        self.assertEqual(units_of(entry)[1].events,
                         ["Play_sfx_AatroxSkin09_Recall3D_buffactivate", "Play_sfx_Aatrox_Recall3D_buffactivate"])
        recall = wwise_hash("Play_sfx_Aatrox_Recall3D_buffactivate")
        # The base bank no longer defines the id, so no two banks share it, and the skin bank defines it
        # next to its own actions
        self.assertFalse(patched(banks, BASE).has_event(recall))
        self.assertEqual(patched(banks, BASE).event_actions(wwise_hash("Play_sfx_Aatrox_AatroxW_OnCast")), [2])
        self.assertEqual(patched(banks, SFX).event_actions(recall), [90])

    def test_no_event_points_at_another_banks_actions(self):
        entry = skin_entry(["Aatrox", "AatroxSkin01"], [
            unit("Aatrox_Base_SFX", [BASE], ["Play_sfx_Aatrox_Q", "Play_sfx_Aatrox_W"]),
            unit("Aatrox_Skin01_SFX", [SFX], ["Play_sfx_AatroxSkin01_Q", "Play_sfx_AatroxSkin01_E"]),
        ])
        banks = banks_with([
            (BASE, None, bank([("Play_sfx_Aatrox_Q", [1]), ("Play_sfx_Aatrox_W", [2])])),
            (SFX, None, bank([("Play_sfx_AatroxSkin01_Q", [11]), ("Play_sfx_AatroxSkin01_E", [13])])),
        ])
        merge(entry, "aatrox", banks)
        for path, own in ((BASE, [1, 2]), (SFX, [11, 13])):
            content = banks.copies(path)[0].bank
            for name in ("Play_sfx_Aatrox_Q", "Play_sfx_Aatrox_W", "Play_sfx_Aatrox_E"):
                actions = content.event_actions(wwise_hash(name))
                if actions is not None:
                    self.assertTrue(all(a in own for a in actions), f"{name} in {path} -> {actions}")
        skin = banks.copies(SFX)[0].bank
        self.assertEqual(skin.event_actions(wwise_hash("Play_sfx_Aatrox_Q")), [11])
        self.assertEqual(skin.event_actions(wwise_hash("Play_sfx_Aatrox_E")), [13])
        self.assertFalse(banks.copies(BASE)[0].bank.has_event(wwise_hash("Play_sfx_Aatrox_Q")))

    def test_later_tags_win_and_odd_tags_merge_too(self):
        entry = skin_entry(["Gangplank_Base", "Gangplank", "GangplankSkin08"], [
            unit("GP", [SFX], ["Play_sfx_Gangplank_Base_Idle", "Play_sfx_Gangplank_Base_Walk",
                               "Play_sfx_Gangplank_Walk", "Play_sfx_GangplankSkin08_Walk"])])
        banks = banks_with([(SFX, None, bank([
            ("Play_sfx_Gangplank_Base_Idle", [1]), ("Play_sfx_Gangplank_Base_Walk", [2]),
            ("Play_sfx_Gangplank_Walk", [3]), ("Play_sfx_GangplankSkin08_Walk", [8])]))])
        report = merge(entry, "gangplank", banks)
        self.assertEqual(report.base_tag, "Gangplank")
        self.assertEqual(report.removed_tags, ["Gangplank_Base", "GangplankSkin08"])
        self.assertEqual(tags_of(entry), ["Gangplank"])
        sfx = patched(banks, SFX)
        # Idle had no Gangplank_ version, so it gets an alias; Walk: GangplankSkin08 beats both lower tags
        self.assertEqual(sfx.event_actions(wwise_hash("Play_sfx_Gangplank_Idle")), [1])
        self.assertEqual(sfx.event_actions(wwise_hash("Play_sfx_Gangplank_Walk")), [8])

    def test_skins_without_extra_tags_are_left_alone(self):
        entry = skin_entry(["Aatrox"], [unit("Aatrox_Base_SFX", [BASE], ["Play_sfx_Aatrox_Q"])])
        banks = banks_with([])
        self.assertIsNone(merge(entry, "aatrox", banks))
        self.assertEqual(banks.into_patched(), [])

    def test_a_list_without_the_base_tag_gets_the_character_name(self):
        entry = skin_entry(["DariusSkin64"], [unit("D", [SFX], ["Play_sfx_DariusSkin64_Q"])])
        banks = banks_with([(SFX, None, bank([("Play_sfx_DariusSkin64_Q", [64])]))])
        report = merge(entry, "darius", banks)
        self.assertEqual(report.events_added, 1)
        self.assertEqual(tags_of(entry), ["darius"])
        self.assertEqual(patched(banks, SFX).event_actions(wwise_hash("Play_sfx_Darius_Q")), [64])

    def test_events_missing_from_banks_are_counted_not_fatal(self):
        entry = skin_entry(["Aatrox", "AatroxSkin33"], [unit("A", [SFX], ["Play_sfx_AatroxSkin33_Gone"])])
        report = merge(entry, "aatrox", banks_with([(SFX, None, bank([]))]))
        self.assertEqual((report.events_added, report.events_missing), (0, 1))
        self.assertEqual(tags_of(entry), ["Aatrox"])

    def test_the_merged_list_is_the_game_base_skins(self):
        entry = skin_entry(["Nidalee", "NidaleeCougarSkin01"], [unit("N", [SFX], ["Play_sfx_NidaleeCougarSkin01_Q"])])
        banks = banks_with([(SFX, None, bank([("Play_sfx_NidaleeCougarSkin01_Q", [3])]))])
        merge(entry, "nidaleecougar", banks, MergeContext(base_tags=["Nidalee", "NidaleeCougar"]))
        self.assertEqual(tags_of(entry), ["Nidalee", "NidaleeCougar"])
        # Aliases are named under the last base tag, which outranks the others
        self.assertEqual(patched(banks, SFX).event_actions(wwise_hash("Play_sfx_NidaleeCougar_Q")), [3])

    def test_a_sub_character_without_units_aliases_in_the_main_characters_banks(self):
        main_bank = "ASSETS/Sounds/Elise_Skin01_SFX_events.bnk"
        shared = [SharedUnit(0, audio.Unit(["Play_sfx_EliseSkin01_Spider_Q"], main_bank))]
        entry = skin_entry(["EliseSpider", "EliseSkin01"], [], path="Characters/EliseSpider/Skins/Skin0")
        banks = banks_with([(main_bank, None, bank([("Play_sfx_EliseSkin01_Spider_Q", [4])]))])
        report = merge(entry, "elisespider", banks, MergeContext(base_tags=["EliseSpider"], shared_units=shared))
        self.assertTrue(report.uses_shared_units)
        self.assertEqual(len(report.shared_edits), 1)
        self.assertEqual((report.shared_edits[0].owner, report.shared_edits[0].events_bank), (0, main_bank))
        self.assertEqual(report.shared_edits[0].edit.list, ["Play_sfx_EliseSpider_Spider_Q"])
        self.assertEqual(patched(banks, main_bank).event_actions(wwise_hash("Play_sfx_EliseSpider_Spider_Q")), [4])

    def test_events_a_unit_lists_under_another_tag_are_found_in_its_bank(self):
        # Mel skin 1 lists Play_sfx_Mel_Dance3D_leadin while its bank defines the Skin01 name
        entry = skin_entry(["Mel", "MelSkin01"], [unit("Mel_Skin01_SFX", [SFX], ["Play_sfx_Mel_Dance3D_leadin"])])
        banks = banks_with([(SFX, None, bank([("Play_sfx_MelSkin01_Dance3D_leadin", [9])]))])
        report = merge(entry, "mel", banks)
        self.assertEqual(report.events_from_banks, 1)
        self.assertEqual(patched(banks, SFX).event_actions(wwise_hash("Play_sfx_Mel_Dance3D_leadin")), [9])

    def test_event_names_and_bin_paths_are_read_from_raw_bins(self):
        name = b"Play_sfx_Aatrox_Q_OnCast"
        # Strings are a 16-bit length then printable ASCII; a space is not printable, a length under 4 is too short
        raw = (b"\x00\x01" + struct.pack("<H", len(name)) + name + b"\x09"
               + struct.pack("<H", 4) + b"abcd" + struct.pack("<H", 9) + b"has space"
               + struct.pack("<H", 3) + b"abc")
        self.assertEqual(audio.bin_strings(raw), [name.decode(), "abcd"])
        self.assertTrue(audio.is_event_name("Play_sfx_AatroxSkin33_AatroxQ_OnCast"))
        self.assertTrue(audio.is_event_name("Play_VO_Aatrox_Q_cast"))
        self.assertFalse(audio.is_event_name("Play_music_Aatrox_Q_cast"))
        self.assertFalse(audio.is_event_name("Play_sfx_Aatrox"))

    def test_locale_names_are_recognized(self):
        self.assertTrue(all(audio.is_locale(v) for v in ("en_US", "fr_FR", "zh_TW", "fr_fr")))
        self.assertFalse(any(audio.is_locale(v) for v in ("VO", "en-US", "english", "en_USA")))
        self.assertEqual(audio.normalize_locale("fr_fr"), "fr_FR")


class BankUnitTests(unittest.TestCase):
    def names(self, entry):
        return [(audio._unit_name(v.as_embed()), audio.string_list(v.as_embed(), audio.PROP_BANK_PATH),
                 audio.string_list(v.as_embed(), audio.PROP_EVENTS)) for v in
                entry.find_field(audio.PROP_SKIN_AUDIO).value.as_embed().find_field(audio.PROP_BANK_UNITS).value.v]

    def test_skin_bank_units_are_renamed_to_base(self):
        entry = skin_entry(units=[unit("Aatrox_Skin01_SFX", ["a.bnk"], []), unit("Aatrox_Skin01_VO", ["b.bnk"], []),
                                  unit("Aatrox_Base_Music", ["m.bnk"], [])])
        report = audio.rebase_bank_units(entry)
        self.assertEqual([name for name, _, _ in self.names(entry)], ["Aatrox_Base_SFX", "Aatrox_Base_VO", "Aatrox_Base_Music"])
        self.assertEqual(report.renamed, [("Aatrox_Skin01_SFX", "Aatrox_Base_SFX"), ("Aatrox_Skin01_VO", "Aatrox_Base_VO")])
        self.assertEqual(report.merged, [])

    def test_clashing_bank_units_are_merged_into_the_base_unit(self):
        entry = skin_entry(units=[unit("Aatrox_Base_SFX", ["base.bnk"], ["Play_sfx_Aatrox_Q"]),
                                  unit("Aatrox_Skin01_SFX", ["base.bnk", "skin.bnk"], ["Play_sfx_Aatrox_Q", "Play_sfx_Aatrox_W"])])
        report = audio.rebase_bank_units(entry)
        self.assertEqual(self.names(entry), [("Aatrox_Base_SFX", ["base.bnk", "skin.bnk"], ["Play_sfx_Aatrox_Q", "Play_sfx_Aatrox_W"])])
        self.assertEqual(report.merged, [("Aatrox_Skin01_SFX", "Aatrox_Base_SFX")])

    def test_units_without_a_skin_segment_are_left_alone(self):
        entry = skin_entry(units=[unit("Aatrox_Base_SFX", ["a.bnk"], []), unit("Aatrox_Music", ["m.bnk"], [])])
        before = self.names(entry)
        self.assertIsNone(audio.rebase_bank_units(entry))
        self.assertEqual(self.names(entry), before)

    def test_base_unit_names_replace_only_skin_segments(self):
        self.assertEqual(audio.base_unit_name("Aatrox_Skin01_SFX"), "Aatrox_Base_SFX")
        self.assertEqual(audio.base_unit_name("Skin5_Skin12_VO"), "Base_Base_VO")
        self.assertEqual(audio.base_unit_name("Aatrox_Skinny_SFX"), None)
        self.assertEqual(audio.base_unit_name("Aatrox_Skin_SFX"), None)
        self.assertEqual(audio.base_unit_name("Aatrox_Base_SFX"), None)


# --------------------------------------------------------------------------------------
# the model and the name
# --------------------------------------------------------------------------------------

SKIN_SKL = "ASSETS/Characters/Aatrox/Skins/Skin01/Aatrox_Skin01.skl"
SKIN_SKN = "ASSETS/Characters/Aatrox/Skins/Skin01/Aatrox_Skin01.skn"
BASE_SKL = "ASSETS/Characters/Aatrox/Skins/Base/Aatrox.skl"
BASE_SKN = "ASSETS/Characters/Aatrox/Skins/Base/Aatrox.skn"


class MeshAndNameTests(unittest.TestCase):
    def files(self, **contents):
        return lambda path: contents.get(path)

    def test_the_skin_mesh_ships_padded_at_the_base_paths(self):
        base = skin_entry(name="Aatrox", skeleton=BASE_SKL, skin=BASE_SKN)
        entry = skin_entry(name="AatroxSkin01", skeleton=SKIN_SKL, skin=SKIN_SKN)
        read = self.files(**{SKIN_SKL: b"skl-data", SKIN_SKN: b"skn-data"})

        rebase = steps.rebase_skin_mesh(entry, base, read, [])

        self.assertEqual(steps.mesh_paths(entry), [BASE_SKL, BASE_SKN])
        self.assertEqual([(f.path, f.data) for f in rebase.files],
                         [(BASE_SKL, b"skl-data" + bytes(16)), (BASE_SKN, b"skn-data" + bytes(16))])

    def test_a_missing_mesh_file_is_an_error(self):
        base = skin_entry(skeleton=BASE_SKL, skin=BASE_SKN)
        entry = skin_entry(skeleton=SKIN_SKL, skin=SKIN_SKN)
        with self.assertRaises(ValueError):
            steps.rebase_skin_mesh(entry, base, self.files(), [])

    def test_a_bin_without_mesh_paths_is_left_alone(self):
        base = skin_entry(skeleton=BASE_SKL, skin=BASE_SKN)
        entry = skin_entry()
        rebase = steps.rebase_skin_mesh(entry, base, self.files(), [])
        self.assertEqual((rebase.files, rebase.changed), ([], False))

    def test_a_sub_character_keeps_its_own_mesh_when_the_base_path_is_taken(self):
        # Nasus skin 5: Nasus and his ult form share Base/Nasus.skn but have different skin meshes
        base = skin_entry(name="BaseNasus", skeleton=BASE_SKL, skin=BASE_SKN)
        read = self.files(**{SKIN_SKL: b"main-skl", SKIN_SKN: b"main-skn",
                             "ult.skl": b"ult-skl", "ult.skn": b"ult-skn"})
        main = steps.rebase_skin_mesh(skin_entry(name="NasusSkin05", skeleton=SKIN_SKL, skin=SKIN_SKN), base, read, [])
        self.assertEqual(len(main.files), 2)
        ult_entry = skin_entry(name="Skin05NasusUlt", skeleton="ult.skl", skin="ult.skn")
        ult = steps.rebase_skin_mesh(ult_entry, base, read, main.files)
        self.assertEqual(ult.files, [])
        self.assertEqual(len(ult.kept), 2)
        self.assertEqual(steps.mesh_paths(ult_entry), ["ult.skl", "ult.skn"])

    def test_a_sub_character_on_the_same_mesh_shares_the_base_file(self):
        base = skin_entry(skeleton=BASE_SKL, skin=BASE_SKN)
        read = self.files(**{SKIN_SKL: b"skl", SKIN_SKN: b"skn"})
        main = steps.rebase_skin_mesh(skin_entry(skeleton=SKIN_SKL, skin=SKIN_SKN), base, read, [])
        sub_entry = skin_entry(skeleton=SKIN_SKL, skin=SKIN_SKN)
        sub = steps.rebase_skin_mesh(sub_entry, base, read, main.files)
        self.assertEqual((sub.files, sub.kept), ([], []))
        self.assertEqual(steps.mesh_paths(sub_entry), [BASE_SKL, BASE_SKN])

    def test_a_mesh_already_at_the_base_path_and_padded_is_a_match(self):
        base = skin_entry(skeleton=BASE_SKL, skin=BASE_SKN)
        entry = skin_entry(skeleton=BASE_SKL, skin=BASE_SKN)
        mod = self.files(**{BASE_SKL: b"skl" + bytes(16), BASE_SKN: b"skn" + bytes(16)})
        rebase = steps.rebase_skin_mesh(entry, base, mod, [], mod)
        self.assertEqual([file for file in rebase.files if file.ship], [])
        self.assertFalse(rebase.changed)

    def test_a_mesh_at_the_base_path_that_is_not_padded_gets_the_padding(self):
        base = skin_entry(skeleton=BASE_SKL, skin=BASE_SKN)
        entry = skin_entry(skeleton=BASE_SKL, skin=BASE_SKN)
        mod = self.files(**{BASE_SKL: b"skl", BASE_SKN: b"skn"})
        rebase = steps.rebase_skin_mesh(entry, base, mod, [], mod)
        self.assertEqual([(f.path, f.data) for f in rebase.files if f.ship],
                         [(BASE_SKL, b"skl" + bytes(16)), (BASE_SKN, b"skn" + bytes(16))])

    def test_a_base_path_the_mod_does_not_ship_uses_the_games_own(self):
        base = skin_entry(skeleton=BASE_SKL, skin=BASE_SKN)
        entry = skin_entry(skeleton=BASE_SKL, skin=BASE_SKN)
        rebase = steps.rebase_skin_mesh(entry, base, self.files(**{BASE_SKL: b"game"}), [], self.files())
        self.assertEqual([file for file in rebase.files if file.ship], [])

    def test_the_champion_skin_name_comes_from_the_base_bin(self):
        # Base names are not derivable from the champion name
        base = skin_entry(name="AmumuBase", skeleton=BASE_SKL, skin=BASE_SKN)
        entry = skin_entry(name="AmumuSkin05", skeleton=SKIN_SKL, skin=SKIN_SKN)
        self.assertEqual(steps.rebase_skin_name(entry, base), ("AmumuSkin05", "AmumuBase"))
        self.assertEqual(steps.skin_name(entry), "AmumuBase")
        self.assertEqual(steps.mesh_paths(entry), [SKIN_SKL, SKIN_SKN])  # nothing else moves

    def test_a_skin_name_that_is_already_the_base_one_is_a_match(self):
        base = skin_entry(name="Aatrox")
        entry = skin_entry(name="Aatrox")
        self.assertIsNone(steps.rebase_skin_name(entry, base))


# --------------------------------------------------------------------------------------
# a whole mod
# --------------------------------------------------------------------------------------

def wad_bytes(files):
    wad = ModWad(b"RW\x03\x04" + bytes(264) + struct.pack("<I", 0))
    for path, data in files.items():
        wad.put(path_hash(path), data)
    return wad.to_bytes()


def hand_written_wad(entries):
    """A WAD as League's tools write one: [(path, type byte, payload, size)], in order."""
    out = bytearray(b"RW\x03\x04" + bytes(264) + struct.pack("<I", len(entries)))
    offset = 272 + 32 * len(entries)
    for path, type_byte, payload, size in entries:
        out += struct.pack("<QIII", path_hash(path), offset, len(payload), size)
        out += bytes([type_byte, 0, 0, 0]) + struct.pack("<Q", 0x1122334455667788)
        offset += len(payload)
    for _, _, payload, _ in entries:
        out += payload
    return bytes(out)


TEX = "ASSETS/Characters/Aatrox/Skins/Skin33/Aatrox_Skin33_TX_CM.tex"


def sub_chunked(raw_head, rest):
    """A type 4 payload starting with a raw sub-chunk, then a zstd one, as League's tools write a texture."""
    return raw_head + zstandard.ZstdCompressor().compress(rest)


class WadTests(unittest.TestCase):
    HEAD, REST = b"TEX\x00" + bytes(range(60)), b"pixels" * 500

    def texture_wad(self, *more):
        payload = sub_chunked(self.HEAD, self.REST)
        return hand_written_wad([(TEX, 0x24, payload, len(self.HEAD) + len(self.REST)), *more])

    def test_a_sub_chunked_file_that_starts_raw_decompresses(self):
        self.assertEqual(ModWad(self.texture_wad()).get(path_hash(TEX)).data, self.HEAD + self.REST)

    def test_raw_sub_chunks_between_frames_are_copied_through(self):
        frames = zstandard.ZstdCompressor()
        payload = frames.compress(b"a" * 300) + b"raw-middle" + frames.compress(b"b" * 300)
        wad = ModWad(hand_written_wad([(TEX, 0x34, payload, 610)]))
        self.assertEqual(wad.get(path_hash(TEX)).data, b"a" * 300 + b"raw-middle" + b"b" * 300)

    def test_bytes_that_do_not_decompress_are_a_wad_error_the_steps_skip(self):
        wad = ModWad(hand_written_wad([(TEX, 0x03, b"\x28\xb5\x2f\xfd" + b"not a frame", 100)]))
        with self.assertRaises(WadError):
            wad.get(path_hash(TEX)).data
        self.assertTrue(issubclass(WadError, ValueError))

    def test_a_file_that_inflates_far_past_its_table_is_cut_off_not_built(self):
        zeros = bytes(24 * 1024 * 1024)
        bombs = {
            "gzip": (0x01, zlib.compress(zeros, 9, wbits=31)),
            "zstd": (0x03, zstandard.ZstdCompressor().compress(zeros)),
            "chunked": (0x14, b"RAW!" + zstandard.ZstdCompressor().compress(zeros)),
        }
        del zeros
        for name, (type_byte, payload) in bombs.items():
            with self.subTest(name):
                wad = ModWad(hand_written_wad([(TEX, type_byte, payload, 64)]))
                tracemalloc.start()
                try:
                    with self.assertRaises(WadError):
                        wad.get(path_hash(TEX)).data
                    peak = tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
                self.assertLess(peak, 8 * 1024 * 1024)

    def test_the_games_wad_reads_sub_chunked_files(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "Aatrox.wad.client"
            path.write_bytes(self.texture_wad())
            self.assertEqual(GameWad(path).read_path(TEX), self.HEAD + self.REST)

    def test_files_nobody_edited_are_written_back_as_they_came(self):
        original = self.texture_wad(("data/x.bin", 0x00, b"PROPdata", 8))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mod.wad.client"
            path.write_bytes(original)
            wad = ModWad(source=FileSource(path))
            wad.put(path_hash("data/new.bin"), b"new")
            written = ModWad(wad.to_bytes())
            wad.close()
        before = ModWad(original)
        for old, new in zip(before, written.files[:2]):
            self.assertEqual((new.payload, new.kind, new.chunking, new.checksum),
                             (old.payload, old.kind, old.chunking, old.checksum))
        self.assertEqual(written.get(path_hash(TEX)).data, self.HEAD + self.REST)
        self.assertEqual(written.get(path_hash("data/new.bin")).data, b"new")

    def test_a_wad_is_read_file_by_file(self):
        reads = []

        class Counted(BytesSource):
            def read_at(self, offset, count):
                reads.append(count)
                return super().read_at(offset, count)

        data = self.texture_wad(("data/x.bin", 0x00, b"PROPdata", 8))
        wad = ModWad(source=Counted(data))
        self.assertEqual(wad.get(path_hash("data/x.bin")).data, b"PROPdata")
        self.assertEqual(sum(reads), 272 + 2 * 32 + 8)


class _GameAndMod(unittest.TestCase):
    """A fake game folder with Aatrox's base skin, and a custom skin 33 mod."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.game = self.root / "Game"
        champions = self.game / "DATA" / "FINAL" / "Champions"
        champions.mkdir(parents=True)
        base_bin = build([skin_entry(["Aatrox"], [unit("Aatrox_Base_SFX", [BASE], ["Play_sfx_Aatrox_Q"])],
                                     name="Aatrox", skeleton=BASE_SKL, skin=BASE_SKN)])
        (champions / "Aatrox.wad.client").write_bytes(wad_bytes({
            "data/characters/aatrox/skins/skin0.bin": base_bin,
            SKIN_SKL: b"game-skl", SKIN_SKN: b"game-skn",
            BASE_SKL: b"base-skl", BASE_SKN: b"base-skn",
            BASE: bank_bytes([("Play_sfx_Aatrox_Q", [1])]),
        }))
        self.skin_bin = build([skin_entry(
            ["Aatrox", "AatroxSkin33"], [unit("Aatrox_Skin33_SFX", [SFX], ["Play_sfx_AatroxSkin33_Q"])],
            name="AatroxSkin33", skeleton=SKIN_SKL, skin=SKIN_SKN)])
        self.skin_bank = bank_bytes([("Play_sfx_AatroxSkin33_Q", [33])])
        self.archive = self.root / "custom.fantome"
        self.write_mod({
            "data/characters/aatrox/skins/skin0.bin": self.skin_bin,
            SKIN_SKL: b"custom-skl", SKIN_SKN: b"custom-skn",
            SFX: self.skin_bank,
        })

    def write_mod(self, files, name="Aatrox.wad.client"):
        with zipfile.ZipFile(self.archive, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("META/info.json", '{"Name": "custom"}')
            archive.writestr(f"WAD/{name}", wad_bytes(files))

    def mod_files(self, archive_path=None, member="WAD/Aatrox.wad.client"):
        with zipfile.ZipFile(archive_path or self.archive) as archive:
            return {f.name_hash: f.data for f in ModWad(archive.read(member))}, archive.namelist()


SKIN5_SKL = "ASSETS/Characters/Aatrox/Skins/Skin05/Aatrox_Skin05.skl"
SKIN5_SKN = "ASSETS/Characters/Aatrox/Skins/Skin05/Aatrox_Skin05.skn"
SKIN0_BIN = "data/characters/aatrox/skins/skin0.bin"


class FixModTests(_GameAndMod):
    def test_a_custom_skin_is_made_to_match_the_base_skin(self):
        result = fix_mod(self.archive, self.game)

        self.assertTrue(result.changed)
        self.assertTrue(result.complete)
        self.assertGreater(result.fixes, 0)
        files, names = self.mod_files()
        self.assertEqual(names, ["META/info.json", "WAD/Aatrox.wad.client"])
        skin = Bin(files[path_hash("data/characters/aatrox/skins/skin0.bin")]).find_entry(SKIN_DATA)
        # championSkinName
        self.assertEqual(steps.skin_name(skin), "Aatrox")
        # SKN/SKL: the skin's own files under the base paths, padded, and the bin points there
        self.assertEqual(steps.mesh_paths(skin), [BASE_SKL, BASE_SKN])
        self.assertEqual(files[path_hash(BASE_SKL)], b"custom-skl" + bytes(16))
        self.assertEqual(files[path_hash(BASE_SKN)], b"custom-skn" + bytes(16))
        # tags and bank units
        self.assertEqual(tags_of(skin), ["Aatrox"])
        self.assertEqual([u.events for u in units_of(skin)], [["Play_sfx_AatroxSkin33_Q", "Play_sfx_Aatrox_Q"]])
        self.assertEqual(audio._unit_name(skin.find_field(audio.PROP_SKIN_AUDIO).value.as_embed()
                                          .find_field(audio.PROP_BANK_UNITS).value.v[0].as_embed()), "Aatrox_Base_SFX")
        # the bank holds the base name, with the skin's actions
        self.assertEqual(Bank.parse(files[path_hash(SFX)]).event_actions(wwise_hash("Play_sfx_Aatrox_Q")), [33])

    def test_a_skin_that_already_matches_is_not_written_again(self):
        fix_mod(self.archive, self.game)
        fixed = self.archive.read_bytes()

        again = fix_mod(self.archive, self.game)

        self.assertFalse(again.changed)
        self.assertEqual(self.archive.read_bytes(), fixed)

    def test_the_archive_keeps_its_other_files_and_stores_the_wad(self):
        fix_mod(self.archive, self.game)
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(archive.read("META/info.json"), b'{"Name": "custom"}')
            self.assertEqual(archive.getinfo("WAD/Aatrox.wad.client").compress_type, zipfile.ZIP_STORED)
        self.assertEqual(list(self.root.glob(".rose-import-*")), [])

    def test_a_voice_over_bank_gets_its_alias_in_the_champion_wad_not_in_the_locale_wad(self):
        vo = "ASSETS/Sounds/VO/fr_FR/Aatrox_Skin33_VO_events.bnk"
        skin = build([skin_entry(["Aatrox", "AatroxSkin33"], [unit("Aatrox_Skin33_VO", [vo], ["Play_vo_AatroxSkin33_Q"])],
                                 name="AatroxSkin33")])
        locale_wad = wad_bytes({vo: bank_bytes([("Play_vo_AatroxSkin33_Q", [20])])})
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("WAD/Aatrox.wad.client", wad_bytes({SKIN0_BIN: skin}))
            archive.writestr("WAD/Aatrox.fr_FR.wad.client", locale_wad)
        result = fix_mod(self.archive, self.game)
        self.assertTrue(result.changed)
        with zipfile.ZipFile(self.archive) as archive:
            main = {f.name_hash: f.data for f in ModWad(archive.read("WAD/Aatrox.wad.client"))}
            # A localized bank is never edited: it must work in every language
            self.assertEqual(archive.read("WAD/Aatrox.fr_FR.wad.client"), locale_wad)
        # The alias goes in a language-neutral bank of the champion WAD
        sidecar = audio.sidecar_path(vo)
        self.assertEqual(Bank.parse(main[path_hash(sidecar)]).event_actions(wwise_hash("Play_vo_Aatrox_Q")), [20])

    def test_only_the_base_skin_bin_is_rebased(self):
        """A mod holding the champion's whole WAD, skin5.bin before skin0.bin in its table"""
        skin5 = build([skin_entry(["Aatrox", "AatroxSkin5"], [], name="AatroxSkin5", skeleton=SKIN5_SKL,
                                  skin=SKIN5_SKN, path="Characters/Aatrox/Skins/Skin5")])
        root = build([skin_entry(["Aatrox", "AatroxSkin5"], [], name="AatroxSkin5",
                                 path="Characters/Aatrox/Skins/Root")])
        self.write_mod({
            "data/characters/aatrox/skins/skin5.bin": skin5,
            "data/characters/aatrox/skins/root.bin": root,
            SKIN0_BIN: self.skin_bin,
            SKIN5_SKL: b"skin5-skl", SKIN5_SKN: b"skin5-skn",
            SKIN_SKL: b"custom-skl", SKIN_SKN: b"custom-skn",
            SFX: self.skin_bank,
        })
        self.assertTrue(fix_mod(self.archive, self.game).changed)
        files, _ = self.mod_files()
        # The base skin's mesh is the base skin bin's own: not skin 5's
        self.assertEqual(files[path_hash(BASE_SKN)], b"custom-skn" + bytes(16))
        self.assertEqual(files[path_hash(BASE_SKL)], b"custom-skl" + bytes(16))
        self.assertEqual(files[path_hash("data/characters/aatrox/skins/skin5.bin")], skin5)
        self.assertEqual(files[path_hash("data/characters/aatrox/skins/root.bin")], root)

    def test_a_character_the_champion_is_not_known_to_hold_is_left_alone(self):
        summon = build([skin_entry(["Aatrox", "AatroxSkin33"], [], name="AatroxSkin33", skeleton=SKIN_SKL,
                                   skin=SKIN_SKN, path="Characters/AatroxMinion/Skins/Skin0")])
        self.write_mod({SKIN0_BIN: self.skin_bin, "data/characters/aatroxminion/skins/skin0.bin": summon,
                        SKIN_SKL: b"custom-skl", SKIN_SKN: b"custom-skn", SFX: self.skin_bank})
        fix_mod(self.archive, self.game)
        files, _ = self.mod_files()
        self.assertEqual(files[path_hash("data/characters/aatroxminion/skins/skin0.bin")], summon)

    def test_a_champion_whose_game_wad_does_not_read_is_left_as_it_is(self):
        (self.game / "DATA" / "FINAL" / "Champions" / "Aatrox.wad.client").write_bytes(b"half written by a patch")
        before = self.archive.read_bytes()
        result = fix_mod(self.archive, self.game)
        self.assertFalse(result.changed)
        self.assertFalse(result.complete)  # tried again later
        self.assertEqual(self.archive.read_bytes(), before)

    def test_a_mod_holding_sub_chunked_textures_is_fixed_and_keeps_them(self):
        texture = sub_chunked(b"TEX\x00" + bytes(40), b"pixels" * 100)
        wad = hand_written_wad([
            (SKIN0_BIN, 0x00, self.skin_bin, len(self.skin_bin)),
            (SKIN_SKL, 0x00, b"custom-skl", 10), (SKIN_SKN, 0x00, b"custom-skn", 10),
            (SFX, 0x00, self.skin_bank, len(self.skin_bank)),
            (TEX, 0x24, texture, 44 + 600),
        ])
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("WAD/Aatrox.wad.client", wad)
        self.assertTrue(fix_mod(self.archive, self.game).changed)
        with zipfile.ZipFile(self.archive) as archive:
            fixed = ModWad(archive.read("WAD/Aatrox.wad.client"))
        self.assertEqual(fixed.get(path_hash(TEX)).payload, texture)
        self.assertIn(path_hash(BASE_SKN), fixed)

    def test_wad_paths_are_found_whatever_their_case_or_a_leading_slash(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("/wad/Aatrox.wad.client", wad_bytes({
                SKIN0_BIN: self.skin_bin, SKIN_SKL: b"custom-skl", SKIN_SKN: b"custom-skn", SFX: self.skin_bank}))
        self.assertTrue(fix_mod(self.archive, self.game).changed)
        files, names = self.mod_files(member="/wad/Aatrox.wad.client")
        self.assertEqual(names, ["/wad/Aatrox.wad.client"])
        self.assertEqual(files[path_hash(BASE_SKN)], b"custom-skn" + bytes(16))

    def test_a_mod_with_no_champion_skin_is_left_alone(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("WAD/Map11.wad.client", wad_bytes({"assets/x.tex": b"tex"}))
        before = self.archive.read_bytes()
        self.assertFalse(fix_mod(self.archive, self.game).changed)
        self.assertEqual(self.archive.read_bytes(), before)

    def test_a_game_folder_without_champions_changes_nothing(self):
        before = self.archive.read_bytes()
        self.assertFalse(fix_mod(self.archive, self.root / "elsewhere").changed)
        self.assertEqual(self.archive.read_bytes(), before)

    def test_unpacked_wad_folders_are_left_alone(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("WAD/Aatrox.wad.client/data/characters/aatrox/skins/skin0.bin", self.skin_bin)
        before = self.archive.read_bytes()
        self.assertFalse(fix_mod(self.archive, self.game).changed)
        self.assertEqual(self.archive.read_bytes(), before)

    def folder_mod(self):
        folder = self.root / "folder-mod"
        (folder / "WAD").mkdir(parents=True)
        (folder / "WAD" / "Aatrox.wad.client").write_bytes(wad_bytes({
            SKIN0_BIN: self.skin_bin, SKIN_SKL: b"c-skl", SKIN_SKN: b"c-skn", SFX: self.skin_bank}))
        return folder

    def test_a_mod_stored_as_a_folder_is_fixed_in_place(self):
        folder = self.folder_mod()
        self.assertTrue(fix_mod(folder, self.game).changed)
        files = {f.name_hash: f.data for f in ModWad((folder / "WAD" / "Aatrox.wad.client").read_bytes())}
        self.assertEqual(files[path_hash(BASE_SKN)], b"c-skn" + bytes(16))
        self.assertFalse(fix_mod(folder, self.game).changed)
        self.assertEqual(sorted(path.name for path in (folder / "WAD").iterdir()), ["Aatrox.wad.client"])
        self.assertEqual(list(self.root.glob(".rose-import-*")), [])

    def test_a_folder_mod_that_cannot_be_written_is_left_as_it_was(self):
        folder = self.folder_mod()
        before = (folder / "WAD" / "Aatrox.wad.client").read_bytes()
        with patch.object(ModWad, "write_to", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                fix_mod(folder, self.game)
        self.assertEqual((folder / "WAD" / "Aatrox.wad.client").read_bytes(), before)
        self.assertEqual(list(self.root.rglob(".rose-import-*")), [])


class StepsTests(_GameAndMod):
    def test_a_bin_no_step_changes_comes_back_as_it_came(self):
        main_path = self.game / "DATA" / "FINAL" / "Champions" / "Aatrox.wad.client"
        game = GameWad(main_path)
        base_bin = game.read_path(SKIN0_BIN)
        runner = steps.BaseSkinSteps(game, main_path)
        self.assertIs(runner.apply_all([("aatrox", base_bin)])[0], base_bin)
        self.assertEqual(runner.findings.total, 0)


class StoredSkinsTests(_GameAndMod):
    """The skins already in the mods storage are fixed while the client is idle (library.py)."""

    def setUp(self):
        super().setUp()
        self.storage = ModStorageService(mods_root=self.root / "mods")
        library._retried.clear()
        self.addCleanup(library._retried.clear)
        self.stored, _, _ = self.storage.import_mod_file(266, self.archive, [266033])
        self.picked_hash = hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def run_pass(self, stop=lambda: False):
        return library.fix_stored_skins(self.storage, self.game, stop)

    def checks(self):
        return patch.object(library, "fix_mod", wraps=library.fix_mod)

    def test_a_skin_stored_before_rose_fixed_skins_is_fixed_once(self):
        self.assertEqual(self.run_pass(), 1)
        files, _ = self.mod_files(self.stored)
        self.assertEqual(files[path_hash(BASE_SKN)], b"custom-skn" + bytes(16))
        with self.checks() as fix:
            self.assertEqual(self.run_pass(), 0)
        fix.assert_not_called()

    def test_a_patch_of_the_champion_wad_has_the_skin_checked_again(self):
        self.run_pass()
        champion_wad = self.game / "DATA" / "FINAL" / "Champions" / "Aatrox.wad.client"
        stat = champion_wad.stat()
        os.utime(champion_wad, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10 ** 9))
        with self.checks() as fix:
            self.assertEqual(self.run_pass(), 0)  # nothing new to fix, but checked
        fix.assert_called_once()

    def test_the_pass_stops_when_the_client_leaves_the_idle_phases(self):
        before = self.stored.read_bytes()
        self.assertEqual(self.run_pass(stop=lambda: True), 0)
        self.assertEqual(self.stored.read_bytes(), before)

    def test_a_skin_that_failed_is_tried_again_at_the_next_start_not_at_every_lobby(self):
        with patch.object(library, "fix_mod", side_effect=OSError("in use")) as fix:
            self.run_pass()
            self.run_pass()
        self.assertEqual(fix.call_count, 1)
        library._retried.clear()  # Rose starts again
        with self.checks() as fix:
            self.assertEqual(self.run_pass(), 1)
        fix.assert_called_once()

    def test_the_manifest_follows_the_rewritten_skin(self):
        """A renamed skin is found by its archive's index, so it must be the skin's as it is now"""
        self.run_pass()
        entry = ModStorageService.manifest_entry(self.stored)
        self.assertEqual(entry["indexHash"], archive_index_hash(self.stored))
        self.assertNotIn("folderHash", entry)
        self.assertNotIn("wadHashes", entry)
        renamed = self.stored.rename(self.stored.with_name("renamed.fantome"))
        self.assertEqual(self.storage.saved_mod(renamed.relative_to(self.storage.mods_root).as_posix()).target_skin_ids,
                         (266033,))

    def test_party_mode_shares_the_file_as_it_was_picked(self):
        """A friend's copy, fixed by another Rose or not at all, is the same file as it was picked"""
        shared = self.picked_hash[:16]
        entry = ModStorageService.manifest_entry(self.stored)
        self.assertEqual(entry["sourceHash"], self.picked_hash)
        self.assertNotIn("sourceHashes", entry, "nothing hashed but the file picked")
        self.run_pass()
        self.assertNotEqual(hashlib.sha256(self.stored.read_bytes()).hexdigest(), self.picked_hash, "rewritten")
        self.assertEqual(custom_mods.shared_hashes(self.stored), (None, shared))
        with patch.object(custom_mods, "get_mods_root", return_value=self.storage.mods_root), \
                patch.object(custom_mods, "mod_hashes", side_effect=AssertionError("hashed")):
            self.assertEqual(custom_mods.find_local_mod(266, legacy_hash=shared), "skins/266000/custom.fantome")
            self.assertIsNone(custom_mods.find_local_mod(266, legacy_hash="0" * 16))

    def test_a_renamed_skin_stays_listed_once_the_fix_rewrote_it(self):
        """Matched to its entry by its content, which the rewrite changes: the
        entry must follow the rewrite, or the skin is listed no more"""
        renamed = self.stored.rename(self.stored.with_name("renamed.fantome"))

        self.assertEqual(self.run_pass(), 1)

        listed = self.storage.saved_mod(renamed.relative_to(self.storage.mods_root).as_posix())
        self.assertIsNotNone(listed, "gone from the listing")
        self.assertEqual(listed.target_skin_ids, (266033,))

    def test_a_skin_nobody_registered_keeps_what_party_mode_shares_through_its_first_rewrite(self):
        """A skin an older Rose kept in a per-skin folder, listed by the folder's skin alone"""
        legacy = self.storage.get_skin_dir(266033) / "legacy.fantome"
        legacy.parent.mkdir(parents=True)
        shutil.copyfile(self.archive, legacy)
        content, legacy_hash = custom_mods.mod_hashes(legacy)

        self.run_pass()

        self.assertNotEqual(custom_mods.mod_hashes(legacy)[0], content, "rewritten")
        self.assertEqual(ModStorageService.manifest_entry(legacy)["sourceHashes"],
                         {"content": content, "legacy": legacy_hash})
        self.assertEqual(custom_mods.shared_hashes(legacy), (content, legacy_hash))
        self.assertEqual(self.storage.saved_mod("skins/266033/legacy.fantome").target_skin_ids, (266033,))

    def test_new_targets_keep_what_party_mode_shares(self):
        self.storage.set_champion_target_ids(266, [266001], mod_name="custom")
        self.assertEqual(ModStorageService.manifest_entry(self.stored)["sourceHash"], self.picked_hash)
        self.assertEqual(custom_mods.shared_hashes(self.stored), (None, self.picked_hash[:16]))

    def test_the_pass_starts_when_the_client_is_idle_and_stops_when_it_is_not(self):
        manager = SimpleNamespace(injector=SimpleNamespace(game_dir=self.game), _injection_in_progress=False)
        state = SimpleNamespace(phase="ChampSelect")
        with patch.object(library, "fix_stored_skins", return_value=0) as run, \
                patch("injection.mods.storage.ModStorageService"):
            library.on_phase("ChampSelect", manager, state)
            run.assert_not_called()
            state.phase = "Lobby"
            library.on_phase("Lobby", manager, state)
            library._pass_thread.join(10)
        run.assert_called_once()
        stop = run.call_args.args[2]
        self.assertFalse(stop())
        state.phase = "Matchmaking"
        self.assertTrue(stop())

    def test_the_pass_runs_on_the_home_screen(self):
        """The phase thread keeps the home screen as None in the shared state"""
        manager = SimpleNamespace(injector=SimpleNamespace(game_dir=self.game), _injection_in_progress=False)
        state = SimpleNamespace(phase=None)
        for phase in (None, "None"):
            with patch.object(library, "fix_stored_skins", return_value=0) as run, \
                    patch("injection.mods.storage.ModStorageService"):
                library.on_phase(phase, manager, state)
                library._pass_thread.join(10)
            run.assert_called_once()
            self.assertFalse(run.call_args.args[2](), "stopped on the home screen")


class PackageHelpersTests(unittest.TestCase):
    def test_wad_names_split_into_stem_and_locale(self):
        self.assertEqual(split_wad_name("Aatrox.wad.client"), ("Aatrox", None))
        self.assertEqual(split_wad_name("Jinx.en_us.wad.client"), ("Jinx", "en_US"))
        self.assertIsNone(split_wad_name("Jinx.foo.wad.client"))
        self.assertIsNone(split_wad_name("notes.txt"))

    def test_characters_of_a_champion_wad_start_with_the_main_one(self):
        self.assertEqual(character_names("Nasus"), ["nasus", "nasusult"])
        self.assertEqual(character_names("Wukong"), ["monkeyking", "monkeykingclone", "monkeykingflying"])
        self.assertEqual(character_names("Ezreal"), ["ezreal"])
        self.assertEqual(character_names("Kai'Sa"), ["kaisa"])


if __name__ == "__main__":
    unittest.main()
