import struct
import tempfile
import unittest
from pathlib import Path

import xxhash

from injection.loadingname.loading_name import _read_entry, _xxh64
from injection.mods import skin_audio
from injection.mods.skin_audio import event_id


def fnv(name: str) -> int:
    h = 0x811C9DC5
    for c in name.lower().encode():
        h = ((h ^ c) * 0x01000193) & 0xFFFFFFFF
    return h


def string(text: str) -> bytes:
    data = text.encode()
    return struct.pack("<H", len(data)) + data


def field(name: str, kind: int, value: bytes) -> bytes:
    return struct.pack("<IB", fnv(name), kind) + value


def embed(cls: str, fields) -> bytes:
    body = struct.pack("<H", len(fields)) + b"".join(fields)
    return struct.pack("<II", fnv(cls), len(body)) + body


def string_list(items) -> bytes:
    body = struct.pack("<I", len(items)) + b"".join(string(i) for i in items)
    return struct.pack("<BI", 0x10, len(body)) + body


def bank_unit(name, paths, events=()) -> bytes:
    return embed("BankUnit", [
        field("name", 0x10, string(name)),
        field("bankPath", 0x80, string_list(paths)),
        field("events", 0x80, string_list(list(events))),
    ])


def skin_bin(units, tags=("Yasuo",), extra="tail") -> bytes:
    """A skin bin: one SkinCharacterDataProperties holding the audio, and one other entry."""
    unit_list = struct.pack("<I", len(units)) + b"".join(units)
    audio = embed("SkinAudioProperties", [
        field("tagEventList", 0x80, string_list(list(tags))),
        field("bankUnits", 0x81, struct.pack("<BI", 0x83, len(unit_list)) + unit_list),
    ])
    skin = [
        field("championSkinName", 0x10, string("Yasuo")),
        field("skinAudioProperties", 0x83, audio),
        field("skinScale", 0x0A, struct.pack("<f", 1.0)),
    ]
    entries = [
        (fnv("SkinCharacterDataProperties"), struct.pack("<IH", 0x1234, len(skin)) + b"".join(skin)),
        (fnv("Other"), struct.pack("<IH", 0x5678, 1) + field("note", 0x10, string(extra))),
    ]
    out = b"PROP" + struct.pack("<II", 3, 1) + string("DATA/Characters/Yasuo/Skins/Skin9.bin")
    out += struct.pack("<I", len(entries)) + b"".join(struct.pack("<I", t) for t, _ in entries)
    for _, body in entries:
        out += struct.pack("<I", len(body)) + body
    return out


def bank(events, aliases=()) -> bytes:
    """A Wwise events bank: each event plays one action (named after it); an alias (name, event) plays that
    event's action."""
    pairs = [(name, name) for name in events] + list(aliases)
    objects = b"".join(struct.pack("<BII", 4, 9, event_id(name)) + struct.pack("<BI", 1, event_id(source + "/a"))
                       for name, source in pairs)
    hirc = struct.pack("<I", len(pairs)) + objects
    bkhd = struct.pack("<II", 145, 1234)
    return b"BKHD" + struct.pack("<I", len(bkhd)) + bkhd + b"HIRC" + struct.pack("<I", len(hirc)) + hirc


def bank_events(data: bytes):
    """{event id: its action id} of a bank."""
    at = 8 + struct.unpack_from("<I", data, 4)[0] + 8
    out, p = {}, at + 4
    for _ in range(struct.unpack_from("<I", data, at)[0]):
        kind, size, oid = struct.unpack_from("<BII", data, p)
        if kind == 4:
            out[oid] = struct.unpack_from("<I", data, p + 10)[0]
        p += 5 + size
    return out


def wad(files) -> bytes:
    """A wad v3.4 of stored entries, sorted by path hash like the game's."""
    items = sorted((_xxh64(path.lower().encode()), data) for path, data in files.items())
    out = bytearray(b"RW\x03\x04" + bytes(264) + struct.pack("<I", len(items)))
    offset = len(out) + 32 * len(items)
    blobs = b""
    for path_hash, data in items:
        out += struct.pack("<QIIIBBHQ", path_hash, offset + len(blobs), len(data), len(data), 0, 0, 0,
                           xxhash.xxh3_64_intdigest(data))
        blobs += data
    return bytes(out + blobs)


SKIN0 = "data/characters/yasuo/skins/skin0.bin"
SKIN9 = "data/characters/yasuo/skins/skin9.bin"
SOUNDS = "ASSETS/Sounds/Wwise2016/SFX/Characters/Yasuo/Skins"
BASE_SFX = [f"{SOUNDS}/Base/Yasuo_Base_SFX_audio.bnk", f"{SOUNDS}/Base/Yasuo_Base_SFX_events.bnk"]
SKIN09_SFX = [f"{SOUNDS}/Skin09/Yasuo_Skin09_SFX_audio.bnk", f"{SOUNDS}/Skin09/Yasuo_Skin09_SFX_events.bnk"]
SKIN87_SFX = [f"{SOUNDS}/Skin87/Yasuo_Skin87_SFX_audio.bnk", f"{SOUNDS}/Skin87/Yasuo_Skin87_SFX_events.bnk"]
VO = ["ASSETS/Sounds/Wwise2016/VO/en_US/Characters/Yasuo/Skins/Skin09/Yasuo_Skin09_VO_audio.bnk"]
BASETAG = "ASSETS/Sounds/Wwise2016/VO/Characters/Yasuo/Skins/Skin56/Yasuo_Skin56_VO_basetag_events.bnk"

DASH_SKIN = "Play_sfx_YasuoSkin09_YasuoDashWrapper_cast"
DASH_BASE = "Play_sfx_Yasuo_YasuoDashWrapper_cast"
EQ_HIT_BASE = "Play_sfx_Yasuo_YasuoEQComboSoundHit_OnHit"
DASH_87 = "Play_sfx_YasuoSkin87_YasuoDashWrapper_cast"


class SkinAudioTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        self.game_dir = root / "Game"
        (self.game_dir / "DATA" / "FINAL" / "Champions").mkdir(parents=True)
        self.mod = root / "mods" / "157009"
        (self.mod / "WAD").mkdir(parents=True)
        self.mod_wad = self.mod / "WAD" / "Yasuo.wad.client"
        # Nightbringer Yasuo in the game: the default skin's banks and its own, played under its own tag
        self.game_files = {
            SKIN9: skin_bin([
                bank_unit("Yasuo_Base_SFX", BASE_SFX, [DASH_BASE, EQ_HIT_BASE]),
                bank_unit("Yasuo_Skin09_SFX", SKIN09_SFX, [DASH_SKIN]),
                bank_unit("Yasuo_Skin09_VO", VO),
            ], tags=("YasuoSkin09",)),
            BASE_SFX[1]: bank([DASH_BASE, EQ_HIT_BASE]),
            SKIN09_SFX[1]: bank([DASH_SKIN]),
        }
        self._game(self.game_files)
        # its package: another skin's sound effects, its own voice
        self.broken = skin_bin([
            bank_unit("Yasuo_Base_VO", VO),
            bank_unit("Yasuo_Base_SFX", SKIN87_SFX, ["Play_sfx_YasuoSkin87_YasuoDashWrapper_cast", DASH_BASE]),
        ])

    def _game(self, files):
        (self.game_dir / "DATA" / "FINAL" / "Champions" / "Yasuo.wad.client").write_bytes(wad(files))

    def _entry(self, path):
        return _read_entry(self.mod_wad, _xxh64(path.lower().encode()))

    def _units(self):
        return [(u.name, u.paths) for u in skin_audio.bank_units(self._entry(SKIN0))]

    def test_another_skins_sound_effects_become_the_skins_own(self):
        self.mod_wad.write_bytes(wad({SKIN0: self.broken}))

        self.assertEqual(skin_audio.repair(self.game_dir, self.mod, [157009]), ["Yasuo"])

        # the game's sound effect banks for skin 9; the voice the package had right is kept
        self.assertEqual(self._units(), [("Yasuo_Base_VO", VO), ("Yasuo_Base_SFX", BASE_SFX + SKIN09_SFX)])
        unit = skin_audio.bank_units(self._entry(SKIN0))[1]
        self.assertEqual(unit.events, [DASH_BASE, EQ_HIT_BASE, DASH_SKIN])
        # still played under the default skin's tag
        self.assertEqual(skin_audio.tag_events(self._entry(SKIN0)), ["Yasuo"])

    def test_the_default_skins_events_play_the_skins_sounds(self):
        self.mod_wad.write_bytes(wad({SKIN0: self.broken}))

        skin_audio.repair(self.game_dir, self.mod, [157009])

        skin_events = bank_events(self._entry(SKIN09_SFX[1]))
        base_events = bank_events(self._entry(BASE_SFX[1]))
        # the E plays Skin09's dash under the default name...
        self.assertEqual(skin_events[event_id(DASH_BASE)], skin_events[event_id(DASH_SKIN)])
        self.assertNotIn(event_id(DASH_BASE), base_events)
        # ...and what Skin09 has no sound of keeps the default skin's
        self.assertIn(event_id(EQ_HIT_BASE), base_events)
        self.assertNotIn(event_id(EQ_HIT_BASE), skin_events)

    def test_the_rest_of_the_package_is_kept(self):
        self.mod_wad.write_bytes(wad({SKIN0: self.broken, "assets/other.tex": b"texture"}))

        skin_audio.repair(self.game_dir, self.mod, [157009])

        self.assertEqual(self._entry("assets/other.tex"), b"texture")
        repaired = self._entry(SKIN0)
        self.assertTrue(repaired.endswith(string("tail")))
        self.assertEqual(repaired[:60], self.broken[:60])

    def test_the_rewritten_wad_is_valid(self):
        self.mod_wad.write_bytes(wad({SKIN0: self.broken, "assets/other.tex": b"texture"}))

        skin_audio.repair(self.game_dir, self.mod, [157009])

        data = self.mod_wad.read_bytes()
        count = struct.unpack_from("<I", data, 268)[0]
        hashes = []
        for i in range(count):
            path_hash, offset, packed, _, _, _, _, checksum = struct.unpack_from("<QIIIBBHQ", data, 272 + 32 * i)
            hashes.append(path_hash)
            self.assertEqual(checksum, xxhash.xxh3_64_intdigest(data[offset:offset + packed]))
        self.assertEqual(hashes, sorted(hashes))
        self.assertEqual(count, 4)  # skin0, the texture, and the two events banks

    def test_a_skin_playing_its_own_banks_is_left_alone(self):
        packed = wad({SKIN0: skin_bin([bank_unit("Yasuo_Base_SFX", BASE_SFX + SKIN09_SFX)])})
        self.mod_wad.write_bytes(packed)

        self.assertEqual(skin_audio.repair(self.game_dir, self.mod, [157009]), [])
        self.assertEqual(self.mod_wad.read_bytes(), packed)

    def test_a_bank_the_package_ships_itself_is_its_own(self):
        # a voice basetag bank built for the package, named after the skin it took the voice from
        packed = wad({SKIN0: skin_bin([bank_unit("Yasuo_Base_SFX", BASE_SFX + SKIN09_SFX),
                                       bank_unit("Yasuo_Base_VO", VO + [BASETAG])]),
                      BASETAG: bank([])})
        self.mod_wad.write_bytes(packed)

        self.assertEqual(skin_audio.repair(self.game_dir, self.mod, [157009]), [])
        self.assertEqual(self.mod_wad.read_bytes(), packed)

    def test_a_form_rose_builds_is_left_alone(self):
        # DJ Sona's genres are packages of their own, numbered 998 and 999: the game has no bin of them, and its
        # skin's bin does not describe them
        packed = wad({SKIN0: self.broken})
        self.mod_wad.write_bytes(packed)

        self.assertEqual(skin_audio.repair(self.game_dir, self.mod, [157998]), [])
        self.assertEqual(self.mod_wad.read_bytes(), packed)

    def test_nothing_changes_when_the_game_does_not_have_the_skin(self):
        files = dict(self.game_files)
        files["data/characters/yasuo/skins/skin1.bin"] = files.pop(SKIN9)
        self._game(files)
        packed = wad({SKIN0: self.broken})
        self.mod_wad.write_bytes(packed)

        self.assertEqual(skin_audio.repair(self.game_dir, self.mod, [157009]), [])
        self.assertEqual(self.mod_wad.read_bytes(), packed)

    def test_an_unreadable_skin_never_fails_the_injection(self):
        self.mod_wad.write_bytes(wad({SKIN0: b"PROP garbage"}))

        self.assertEqual(skin_audio.repair(self.game_dir, self.mod, [157009]), [])

    def test_the_default_skin_is_left_alone(self):
        packed = wad({SKIN0: self.broken})
        self.mod_wad.write_bytes(packed)

        self.assertEqual(skin_audio.repair(self.game_dir, self.mod, [157000]), [])
        self.assertEqual(self.mod_wad.read_bytes(), packed)

    def _genesis(self, effect_event):
        """Genesis Nightbringer Yasuo: skin 87 has its own sound effects, and its E dash effect names its sound
        after Nightbringer (skin 9), one of its tags. The package (right about its banks) keeps the default tag only
        and plays Skin87's events under the default skin's names."""
        skin87_bank = f"{SOUNDS}/Skin87/Yasuo_Skin87_SFX_events.bnk"
        files = dict(self.game_files)
        files.pop(SKIN9)  # the test bins link Skin9.bin, which the game's skin 87 does not
        files["data/characters/yasuo/skins/skin87.bin"] = skin_bin(
            [bank_unit("Yasuo_Skin87_SFX", SKIN87_SFX, [DASH_87])],
            tags=("Yasuo", "YasuoSkin09", "YasuoSkin87"), extra=effect_event)
        files[skin87_bank] = bank([DASH_87])
        self._game(files)
        self.mod = self.mod.with_name("157087")
        (self.mod / "WAD").mkdir(parents=True)
        self.mod_wad = self.mod / "WAD" / "Yasuo.wad.client"
        self.mod_wad.write_bytes(wad({
            SKIN0: skin_bin([bank_unit("Yasuo_Base_SFX", SKIN87_SFX, [DASH_87, DASH_BASE])]),
            skin87_bank: bank([DASH_87], aliases=[(DASH_BASE, DASH_87)]),
        }))
        return skin87_bank

    def test_an_event_named_after_a_dropped_tag_plays_the_skins_sound(self):
        skin87_bank = self._genesis(DASH_SKIN)

        self.assertEqual(skin_audio.repair(self.game_dir, self.mod, [157087]), ["Yasuo"])

        # the E dash effect's Nightbringer name plays Skin87's dash, as the game plays it
        events = bank_events(self._entry(skin87_bank))
        self.assertEqual(events[event_id(DASH_SKIN)], events[event_id(DASH_87)])
        self.assertIn(DASH_SKIN, skin_audio.bank_units(self._entry(SKIN0))[0].events)
        # the banks stay the package's, and the default skin's are not added
        self.assertEqual(self._units(), [("Yasuo_Base_SFX", SKIN87_SFX)])
        self.assertIsNone(self._entry(BASE_SFX[1]))

    def test_a_default_name_the_package_missed_plays_the_skins_sound(self):
        # the game plays the default skin's recall name as Skin87's recall; the package copied the dash only
        recall_87, recall_base = "Play_sfx_YasuoSkin87_Recall3D_buffactivate", "Play_sfx_Yasuo_Recall3D_buffactivate"
        skin87_bank = self._genesis(recall_base)
        files = dict(self.game_files)
        files.pop(SKIN9)
        files["data/characters/yasuo/skins/skin87.bin"] = skin_bin(
            [bank_unit("Yasuo_Skin87_SFX", SKIN87_SFX, [DASH_87, recall_87])],
            tags=("Yasuo", "YasuoSkin09", "YasuoSkin87"), extra=recall_base)
        files[skin87_bank] = bank([DASH_87, recall_87])
        self._game(files)
        self.mod_wad.write_bytes(wad({
            SKIN0: skin_bin([bank_unit("Yasuo_Base_SFX", SKIN87_SFX, [DASH_87, DASH_BASE])]),
            skin87_bank: bank([DASH_87, recall_87], aliases=[(DASH_BASE, DASH_87)]),
        }))

        self.assertEqual(skin_audio.repair(self.game_dir, self.mod, [157087]), ["Yasuo"])

        events = bank_events(self._entry(skin87_bank))
        self.assertEqual(events[event_id(recall_base)], events[event_id(recall_87)])

    def test_a_package_answering_every_name_is_left_alone(self):
        self._genesis("a note that names no event")
        packed = self.mod_wad.read_bytes()

        self.assertEqual(skin_audio.repair(self.game_dir, self.mod, [157087]), [])
        self.assertEqual(self.mod_wad.read_bytes(), packed)

    def test_another_character_of_the_champion_gets_its_dropped_tags_too(self):
        # a form (as Nidalee's cougar) plays the champion's banks under tags of its own
        form_event, form_skin_event = "Play_sfx_YasuoForm_Pounce_cast", "Play_sfx_YasuoFormSkin87_Pounce_cast"
        skin87_bank = self._genesis("names YasuoForm")
        files = dict(self.game_files)
        files.pop(SKIN9)
        files["data/characters/yasuo/skins/skin87.bin"] = skin_bin(
            [bank_unit("Yasuo_Skin87_SFX", SKIN87_SFX, [DASH_87, form_skin_event])],
            tags=("Yasuo", "YasuoSkin87"), extra="YasuoForm")
        files["data/characters/yasuoform/skins/skin87.bin"] = skin_bin(
            [], tags=("Yasuo", "YasuoForm", "YasuoSkin87", "YasuoFormSkin87"), extra=form_event)
        files[skin87_bank] = bank([DASH_87, form_skin_event])
        self._game(files)
        self.mod_wad.write_bytes(wad({
            SKIN0: skin_bin([bank_unit("Yasuo_Base_SFX", SKIN87_SFX, [DASH_87, DASH_BASE])]),
            "data/characters/yasuoform/skins/skin0.bin": skin_bin([], tags=("Yasuo", "YasuoForm")),
            skin87_bank: bank([DASH_87, form_skin_event], aliases=[(DASH_BASE, DASH_87)]),
        }))

        self.assertEqual(skin_audio.repair(self.game_dir, self.mod, [157087]), ["Yasuo"])

        events = bank_events(self._entry(skin87_bank))
        self.assertEqual(events[event_id(form_event)], events[event_id(form_skin_event)])

    def _nightbringer_voice(self):
        """Nightbringer Yasuo's voice: the game loads the default skin's voice bank next to Skin09's, the package
        Skin09's only, with its lines under the default skin's names (a basetag bank)."""
        base_vo = ["ASSETS/Sounds/Wwise2016/VO/en_US/Characters/Yasuo/Skins/Base/Yasuo_Base_VO_audio.bnk",
                   "ASSETS/Sounds/Wwise2016/VO/en_US/Characters/Yasuo/Skins/Base/Yasuo_Base_VO_events.bnk"]
        skin_vo_events = "ASSETS/Sounds/Wwise2016/VO/en_US/Characters/Yasuo/Skins/Skin09/Yasuo_Skin09_VO_events.bnk"
        basetag = "ASSETS/Sounds/Wwise2016/VO/Characters/Yasuo/Skins/Skin09/Yasuo_Skin09_VO_basetag_events.bnk"
        dash_line, yone_line = "Play_vo_Yasuo_YasuoEDash_cast3D", "Play_vo_Yasuo_FirstEncounter3DYone"
        files = dict(self.game_files)
        files[SKIN9] = skin_bin([
            bank_unit("Yasuo_Base_SFX", BASE_SFX + SKIN09_SFX),
            bank_unit("Yasuo_Base_VO", base_vo, [dash_line, yone_line]),
            bank_unit("Yasuo_Skin09_VO", VO + [skin_vo_events], ["Play_vo_YasuoSkin09_YasuoEDash_cast3D"]),
        ], tags=("YasuoSkin09",))
        self._game(files)
        # the voice banks are in the language's wad
        (self.game_dir / "DATA" / "FINAL" / "Champions" / "Yasuo.ko_KR.wad.client").write_bytes(wad({
            base_vo[1]: bank([dash_line, yone_line]),
            skin_vo_events: bank(["Play_vo_YasuoSkin09_YasuoEDash_cast3D"]),
        }))
        self.mod_wad.write_bytes(wad({
            SKIN0: skin_bin([bank_unit("Yasuo_Base_SFX", BASE_SFX + SKIN09_SFX),
                             bank_unit("Yasuo_Base_VO", VO + [skin_vo_events, basetag])]),
            basetag: bank([], aliases=[(dash_line, "Play_vo_YasuoSkin09_YasuoEDash_cast3D")]),
        }))
        return base_vo, basetag, dash_line, yone_line

    def test_a_bank_the_game_loads_for_the_skin_is_added(self):
        base_vo, basetag, dash_line, yone_line = self._nightbringer_voice()

        self.assertEqual(skin_audio.repair(self.game_dir, self.mod, [157009]), ["Yasuo"])

        voice = skin_audio.bank_units(self._entry(SKIN0))[1]
        self.assertEqual(voice.paths[:2], base_vo)
        # written next to the game's: the language's wad
        language_wad = self.mod_wad.with_name("Yasuo.ko_KR.wad.client")
        base_events = bank_events(_read_entry(language_wad, _xxh64(base_vo[1].lower().encode())))
        # the line the skin has no voice of plays the default skin's...
        self.assertIn(event_id(yone_line), base_events)
        # ...and the E line stays Nightbringer's: the default skin's would be loaded first and played instead
        self.assertNotIn(event_id(dash_line), base_events)
        self.assertIn(event_id(dash_line), bank_events(self._entry(basetag)))

    def test_without_a_game_folder_nothing_is_done(self):
        self.mod_wad.write_bytes(wad({SKIN0: self.broken}))

        self.assertEqual(skin_audio.repair(None, self.mod, [157009]), [])


if __name__ == "__main__":
    unittest.main()
