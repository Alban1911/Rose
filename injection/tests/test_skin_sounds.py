#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The skin sound mod: game banks a skin lists, copied from the game's WADs."""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from injection.baseskin import skin_sounds
from injection.baseskin.skin_sounds import FOLDER_PREFIX, MANIFEST, build, sound_mods
from injection.baseskin.wad import KIND_ZSTD, ModWad, path_hash
from injection.mods.fingerprint import mod_fingerprint

SFX_FROM = "ASSETS/Sounds/Wwise2016/SFX/Characters/Aatrox/Skins/Skin01/Aatrox_Skin01_SFX_audio.bnk"
SFX_TO = "ASSETS/Sounds/Wwise2016/SFX/Characters/Aatrox/Skins/Base/Aatrox_Base2_SFX_audio.bnk"
VO_FROM = "ASSETS/Sounds/Wwise2016/VO/en_US/Characters/Aatrox/Skins/Skin01/Aatrox_Skin01_VO_audio.wpk"
VO_TO = "ASSETS/Sounds/Wwise2016/VO/en_US/Characters/Aatrox/Skins/Base/Aatrox_Base_VO_audio.wpk"

SFX_DATA = b"sfx-bank " * 500  # compresses: the game WAD stores it as zstd


def write_wad(path: Path, files: dict) -> None:
    wad = ModWad(b"RW\x03\x04" + bytes(264) + (0).to_bytes(4, "little"))
    for file_path, data in files.items():
        wad.put_path(file_path, data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wad.to_bytes())


def copy(source, target, localized, packaged=()):
    return {"wad": "Aatrox", "localized": localized, "from": source, "to": target, "packagedLocales": list(packaged)}


def skin_folder(mods: Path, copies, name="Aatrox Skin 1") -> str:
    meta = mods / name / "META"
    meta.mkdir(parents=True)
    (meta / "info.json").write_text('{"Name": "Aatrox Skin 1"}', encoding="utf-8")
    if copies is not None:
        (meta / "rose_sounds.json").write_text(json.dumps({"version": 1, "copies": copies}), encoding="utf-8")
    return name


def wad_of(mods: Path, folder: str, name: str) -> ModWad:
    return ModWad((mods / folder / "WAD" / name).read_bytes())


class SkinSoundsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.game = self.tmp / "Game"
        champions = self.game / "DATA" / "FINAL" / "Champions"
        write_wad(champions / "Aatrox.wad.client", {SFX_FROM: SFX_DATA, "other.bin": b"x"})
        # Every language's WAD stores its voice lines under the en_US path
        write_wad(champions / "Aatrox.fr_FR.wad.client", {VO_FROM: b"voix"})
        write_wad(champions / "Aatrox.de_DE.wad.client", {VO_FROM: b"stimme"})
        self.locale = patch.object(skin_sounds, "_client_locale", lambda game_dir: "fr_FR")
        self.locale.start()
        self.addCleanup(self.locale.stop)

    def mods(self, name="mods"):
        return self.tmp / name

    def test_banks_are_copied_as_stored_to_their_new_paths(self):
        mods = self.mods()
        name = skin_folder(mods, [copy(SFX_FROM, SFX_TO, False), copy(VO_FROM, VO_TO, True)])

        folder = build(self.game, mods, name)

        self.assertEqual(folder, f"{FOLDER_PREFIX}{name}")
        champion = wad_of(mods, folder, "Aatrox.wad.client")
        self.assertEqual([entry.name_hash for entry in champion], [path_hash(SFX_TO)])
        stored = champion.get(path_hash(SFX_TO))
        source = ModWad((self.game / "DATA" / "FINAL" / "Champions" / "Aatrox.wad.client").read_bytes())
        # The very bytes the game stores, still compressed
        self.assertEqual(stored.kind, KIND_ZSTD)
        self.assertEqual(stored.payload, source.get(path_hash(SFX_FROM)).payload)
        self.assertEqual(stored.data, SFX_DATA)
        # The voice lines come in the client's language
        self.assertEqual(wad_of(mods, folder, "Aatrox.fr_FR.wad.client").get(path_hash(VO_TO)).data, b"voix")
        self.assertFalse((mods / folder / "WAD" / "Aatrox.de_DE.wad.client").exists())
        info = json.loads((mods / folder / "META" / "info.json").read_text(encoding="utf-8"))
        self.assertEqual(info["Name"], "Skin sounds")

    def test_the_same_game_files_give_the_same_mod(self):
        # The countdown stages the mod in a folder of its own: the injection's
        # copy must fingerprint the same to keep the staged one installed
        copies = [copy(SFX_FROM, SFX_TO, False), copy(VO_FROM, VO_TO, True)]
        first, second = self.mods("staging"), self.mods()
        a = build(self.game, first, skin_folder(first, copies))
        b = build(self.game, second, skin_folder(second, copies))
        self.assertEqual(mod_fingerprint(first / a), mod_fingerprint(second / b))
        # and building again over the old mod gives it again
        self.assertEqual(build(self.game, second, "Aatrox Skin 1"), b)
        self.assertEqual(mod_fingerprint(second / b), mod_fingerprint(first / a))

    def test_an_archive_lists_its_banks_too(self):
        mods = self.mods()
        mods.mkdir()
        manifest = json.dumps({"version": 1, "copies": [copy(SFX_FROM, SFX_TO, False)]})
        # In the mods folder an archive is linked without its extension
        with zipfile.ZipFile(mods / "Aatrox Skin 1", "w") as archive:
            archive.writestr("META/info.json", "{}")
            archive.writestr(MANIFEST, manifest)
        folder = build(self.game, mods, "Aatrox Skin 1")
        self.assertEqual(wad_of(mods, folder, "Aatrox.wad.client").get(path_hash(SFX_TO)).data, SFX_DATA)

    def test_a_language_the_skin_ships_itself_is_not_copied(self):
        mods = self.mods()
        name = skin_folder(mods, [copy(SFX_FROM, SFX_TO, False), copy(VO_FROM, VO_TO, True, packaged=["fr_FR"])])
        folder = build(self.game, mods, name)
        self.assertTrue((mods / folder / "WAD" / "Aatrox.wad.client").is_file())
        self.assertFalse((mods / folder / "WAD" / "Aatrox.fr_FR.wad.client").exists())

    def test_without_the_clients_language_a_lone_locale_wad_is_used(self):
        mods = self.mods()
        name = skin_folder(mods, [copy(VO_FROM, VO_TO, True)])
        with patch.object(skin_sounds, "_client_locale", lambda game_dir: None):
            # Two languages installed: which one plays can't be told
            self.assertIsNone(build(self.game, mods, name))
            (self.game / "DATA" / "FINAL" / "Champions" / "Aatrox.de_DE.wad.client").unlink()
            folder = build(self.game, mods, name)
        self.assertEqual(wad_of(mods, folder, "Aatrox.fr_FR.wad.client").get(path_hash(VO_TO)).data, b"voix")

    def test_a_skin_without_a_list_gets_no_mod(self):
        mods = self.mods()
        self.assertIsNone(build(self.game, mods, skin_folder(mods, None)))
        self.assertIsNone(build(self.game, mods, skin_folder(mods, [], name="empty")))
        self.assertEqual(sorted(path.name for path in mods.iterdir()), ["Aatrox Skin 1", "empty"])

    def test_a_bank_missing_from_the_game_is_left_out(self):
        mods = self.mods()
        gone = SFX_FROM.replace("Skin01", "Skin99")
        name = skin_folder(mods, [copy(gone, SFX_TO, False)])
        self.assertIsNone(build(self.game, mods, name))
        self.assertFalse((mods / f"{FOLDER_PREFIX}{name}").exists())

    def test_sound_mods_are_built_once_per_skin(self):
        mods = self.mods()
        name = skin_folder(mods, [copy(SFX_FROM, SFX_TO, False)])
        other = skin_folder(mods, None, name="ROSE-LoadingName")
        built = sound_mods(self.game, mods, [name, other])
        self.assertEqual(built, [f"{FOLDER_PREFIX}{name}"])
        # A sound mod already in the list is not built from again
        self.assertEqual(sound_mods(self.game, mods, [name, built[0]]), [])
        self.assertEqual(sound_mods(None, mods, [name]), [])


if __name__ == "__main__":
    unittest.main()
