#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The skin sound mod: game banks a RoseBin skin lists, copied from the game's WADs."""

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

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


@pytest.fixture
def game(tmp_path, monkeypatch):
    game_dir = tmp_path / "Game"
    champions = game_dir / "DATA" / "FINAL" / "Champions"
    write_wad(champions / "Aatrox.wad.client", {SFX_FROM: SFX_DATA, "other.bin": b"x"})
    # Every language's WAD stores its voice lines under the en_US path
    write_wad(champions / "Aatrox.fr_FR.wad.client", {VO_FROM: b"voix"})
    write_wad(champions / "Aatrox.de_DE.wad.client", {VO_FROM: b"stimme"})
    monkeypatch.setattr(skin_sounds, "_client_locale", lambda game_dir: "fr_FR")
    return game_dir


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


def test_banks_are_copied_as_stored_to_their_new_paths(game, tmp_path):
    mods = tmp_path / "mods"
    name = skin_folder(mods, [copy(SFX_FROM, SFX_TO, False), copy(VO_FROM, VO_TO, True)])

    folder = build(game, mods, name)

    assert folder == f"{FOLDER_PREFIX}{name}"
    champion = wad_of(mods, folder, "Aatrox.wad.client")
    assert [entry.name_hash for entry in champion] == [path_hash(SFX_TO)]
    stored = champion.get(path_hash(SFX_TO))
    source = ModWad((game / "DATA" / "FINAL" / "Champions" / "Aatrox.wad.client").read_bytes())
    # The very bytes the game stores, still compressed
    assert stored.kind == KIND_ZSTD
    assert stored.payload == source.get(path_hash(SFX_FROM)).payload
    assert stored.data == SFX_DATA
    # The voice lines come in the client's language
    assert wad_of(mods, folder, "Aatrox.fr_FR.wad.client").get(path_hash(VO_TO)).data == b"voix"
    assert not (mods / folder / "WAD" / "Aatrox.de_DE.wad.client").exists()
    assert json.loads((mods / folder / "META" / "info.json").read_text(encoding="utf-8"))["Name"] == "Skin sounds"


def test_the_same_game_files_give_the_same_mod(game, tmp_path):
    # The countdown stages the mod in a folder of its own: the injection's
    # copy must fingerprint the same to keep the staged one installed
    copies = [copy(SFX_FROM, SFX_TO, False), copy(VO_FROM, VO_TO, True)]
    first, second = tmp_path / "staging", tmp_path / "mods"
    a = build(game, first, skin_folder(first, copies))
    b = build(game, second, skin_folder(second, copies))
    assert mod_fingerprint(first / a) == mod_fingerprint(second / b)
    # and building again over the old mod gives it again
    assert build(game, second, "Aatrox Skin 1") == b
    assert mod_fingerprint(second / b) == mod_fingerprint(first / a)


def test_an_archive_lists_its_banks_too(game, tmp_path):
    mods = tmp_path / "mods"
    mods.mkdir()
    manifest = json.dumps({"version": 1, "copies": [copy(SFX_FROM, SFX_TO, False)]})
    # In the mods folder an archive is linked without its extension
    with zipfile.ZipFile(mods / "Aatrox Skin 1", "w") as archive:
        archive.writestr("META/info.json", "{}")
        archive.writestr(MANIFEST, manifest)
    folder = build(game, mods, "Aatrox Skin 1")
    assert wad_of(mods, folder, "Aatrox.wad.client").get(path_hash(SFX_TO)).data == SFX_DATA


def test_a_language_the_skin_ships_itself_is_not_copied(game, tmp_path):
    mods = tmp_path / "mods"
    name = skin_folder(mods, [copy(SFX_FROM, SFX_TO, False), copy(VO_FROM, VO_TO, True, packaged=["fr_FR"])])
    folder = build(game, mods, name)
    assert (mods / folder / "WAD" / "Aatrox.wad.client").is_file()
    assert not (mods / folder / "WAD" / "Aatrox.fr_FR.wad.client").exists()


def test_without_the_clients_language_a_lone_locale_wad_is_used(game, tmp_path, monkeypatch):
    monkeypatch.setattr(skin_sounds, "_client_locale", lambda game_dir: None)
    mods = tmp_path / "mods"
    name = skin_folder(mods, [copy(VO_FROM, VO_TO, True)])
    # Two languages installed: which one plays can't be told
    assert build(game, mods, name) is None
    (game / "DATA" / "FINAL" / "Champions" / "Aatrox.de_DE.wad.client").unlink()
    folder = build(game, mods, name)
    assert wad_of(mods, folder, "Aatrox.fr_FR.wad.client").get(path_hash(VO_TO)).data == b"voix"


def test_a_skin_without_a_list_gets_no_mod(game, tmp_path):
    mods = tmp_path / "mods"
    assert build(game, mods, skin_folder(mods, None)) is None
    assert build(game, mods, skin_folder(mods, [], name="empty")) is None
    assert sorted(path.name for path in mods.iterdir()) == ["Aatrox Skin 1", "empty"]


def test_a_bank_missing_from_the_game_is_left_out(game, tmp_path):
    mods = tmp_path / "mods"
    gone = SFX_FROM.replace("Skin01", "Skin99")
    name = skin_folder(mods, [copy(gone, SFX_TO, False)])
    assert build(game, mods, name) is None
    assert not (mods / f"{FOLDER_PREFIX}{name}").exists()


def test_a_skin_ltk_manager_holds_gets_its_sound_mod_too(game, tmp_path, monkeypatch):
    # Rose deleted its own copy: the banks are listed in LTK Manager's archive
    ltk_id = "0f8fad5b-d9cb-469f-a165-70867728950e"
    archive = tmp_path / "ltk" / "aatrox-skin-1.fantome"
    archive.parent.mkdir()
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr(MANIFEST, json.dumps({"version": 1, "copies": [copy(SFX_FROM, SFX_TO, False)]}))
    entry = SimpleNamespace(slug="aatrox-skin-1", archive=archive)
    monkeypatch.setattr("injection.overlay.ltk_data.read_library_index", lambda: {ltk_id: entry})
    mods = tmp_path / "mods"
    mods.mkdir()

    built = sound_mods(game, mods, [], [ltk_id, "1d2c3b4a-0000-4000-8000-000000000000"])

    assert built == [f"{FOLDER_PREFIX}aatrox-skin-1"]
    assert wad_of(mods, built[0], "Aatrox.wad.client").get(path_hash(SFX_TO)).data == SFX_DATA


def test_sound_mods_are_built_once_per_skin(game, tmp_path):
    mods = tmp_path / "mods"
    name = skin_folder(mods, [copy(SFX_FROM, SFX_TO, False)])
    other = skin_folder(mods, None, name="ROSE-LoadingName")
    built = sound_mods(game, mods, [name, other])
    assert built == [f"{FOLDER_PREFIX}{name}"]
    # A sound mod already in the list is not built from again
    assert sound_mods(game, mods, [name, built[0]]) == []
    assert sound_mods(None, mods, [name]) == []
