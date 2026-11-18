#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Copy the sound banks a skin loads from new paths out of the player's own game WADs.

RoseBin moves every bank a skin loads from a Skin<n> path to a base path
(Skins/Skin12/Talon_Skin12_SFX_audio.bnk -> Skins/Base/Talon_Base_SFX_audio.bnk),
unchanged: the client links banks by the id inside them, not by their path.
It ships the banks it patches, but not the game's own: a skin's SFX would make
every package megabytes bigger, and its voice lines come in every language.
The skin lists those in META/rose_sounds.json:

    {"version": 1, "copies": [{"wad": "Aatrox", "localized": true,
      "from": ".../Skin01/Aatrox_Skin01_VO_audio.wpk", "to": ".../Base/Aatrox_Base_VO_audio.wpk",
      "packagedLocales": []}, ...]}

and this builds a mod of its own that carries each one at its "to" path, as
the game's WAD stores it (nothing is decompressed): a champion WAD bank from
the player's <wad>.wad.client, a localized (voice) one from the WAD of the
language the client plays in, <wad>.<locale>.wad.client, unless the skin ships
that language's copy itself (packagedLocales). The game's locale WADs keep the
en_US path for every language, so "from" and "to" name en_US whatever the
language.

The mod is built where the injection prepares its mods, the countdown's
staging included (OverlayManager._install_mods): the same game files give the
same mod, so the injection finds the staged one installed. Copying Aatrox
skin 1's banks (16.5 MB, its own voice lines) takes a few tens of
milliseconds.
"""

from __future__ import annotations

import json
import shutil
import struct
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from injection.mods.mod_files import ModFiles
from utils.core.logging import get_logger

from .wad import FileSource, GameWad, ModWad, path_hash

log = get_logger()

MANIFEST = "META/rose_sounds.json"
FOLDER_PREFIX = "ROSE-SkinSounds-"
_EMPTY_WAD = b"RW\x03\x04" + bytes(264) + struct.pack("<I", 0)


def _client_locale(game_dir: Path) -> Optional[str]:
    from injection.loadingname.loading_name import _client_locale as client_locale
    return client_locale(game_dir)


def read_copies(mod: Path) -> List[dict]:
    """The banks a mod (folder or archive) lists in META/rose_sounds.json ([] for none)."""
    with ModFiles(Path(mod)) as files:
        if not files.is_file(MANIFEST):
            return []
        manifest = json.loads(files.read(MANIFEST).decode("utf-8"))
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        log.warning(f"[SOUNDS] {Path(mod).name}: unknown {MANIFEST} version, skipped")
        return []
    copies = manifest.get("copies")
    if not isinstance(copies, list):
        return []
    return [
        copy for copy in copies
        if isinstance(copy, dict) and all(isinstance(copy.get(key), str) for key in ("wad", "from", "to"))
    ]


def _champions_dir(game_dir: Path) -> Path:
    return Path(game_dir) / "DATA" / "FINAL" / "Champions"


def _locale_of(wad: str, file_name: str) -> Optional[str]:
    """fr_FR for <wad>.fr_FR.wad.client, None for any other name."""
    lower = file_name.lower()
    prefix, suffix = f"{wad.lower()}.", ".wad.client"
    if not (lower.startswith(prefix) and lower.endswith(suffix)):
        return None
    locale = file_name[len(prefix):-len(suffix)]
    return locale if len(locale) == 5 and locale[2] == "_" and locale.replace("_", "").isalpha() else None


def locale_wad(game_dir: Path, wad: str) -> Optional[Path]:
    """The locale WAD of *wad* the game reads: the client's language's, or the
    only one installed when the client's language can't be told."""
    found = [path for path in _champions_dir(game_dir).glob(f"{wad}.*.wad.client")
             if _locale_of(wad, path.name)]
    locale = _client_locale(Path(game_dir))
    if locale:
        return next((path for path in found if _locale_of(wad, path.name).lower() == locale.lower()), None)
    return found[0] if len(found) == 1 else None


def _source_wad(game_dir: Path, copy: dict) -> Tuple[Optional[Path], str]:
    """(game WAD to copy from or None, why not)."""
    wad = copy["wad"]
    if not copy.get("localized"):
        path = _champions_dir(game_dir) / f"{wad}.wad.client"
        return (path, "") if path.is_file() else (None, f"{path.name} not found")
    path = locale_wad(game_dir, wad)
    if path is None:
        return None, f"no locale WAD of {wad} for the client's language"
    packaged = {str(locale).lower() for locale in copy.get("packagedLocales") or ()}
    if _locale_of(wad, path.name).lower() in packaged:
        return None, ""  # the skin ships this language's copy itself
    return path, ""


def build(game_dir: Path, mods_dir: Path, mod_name: str) -> Optional[str]:
    """Write the sound mod of the mod *mod_name* (a folder or archive in
    *mods_dir*) and return its folder name; None when it lists no banks or
    none could be copied. Never raises: without the mod, the skin plays with
    the banks it lists missing."""
    started = time.perf_counter()
    try:
        copies = read_copies(Path(mods_dir) / mod_name)
        if not copies:
            return None
        groups: Dict[Path, List[dict]] = {}
        for copy in copies:
            source, why = _source_wad(game_dir, copy)
            if source is None:
                if why:
                    log.warning(f"[SOUNDS] {mod_name}: {copy['to'].rsplit('/', 1)[-1]} not copied: {why}")
                continue
            groups.setdefault(source, []).append(copy)
        if not groups:
            return None

        folder = f"{FOLDER_PREFIX}{mod_name}"
        target = Path(mods_dir) / folder
        if target.exists():
            shutil.rmtree(target)
        (target / "WAD").mkdir(parents=True)
        copied = total = 0
        for source, items in groups.items():
            game = GameWad(source)
            handle = FileSource(source)
            try:
                wad = ModWad(_EMPTY_WAD)
                stored = []
                for copy in items:
                    entry = game.stored_file(copy["from"], handle, path_hash(copy["to"]))
                    if entry is None:
                        log.warning(f"[SOUNDS] {mod_name}: {copy['from']} not in {source.name}")
                        continue
                    stored.append(entry)
                # Sorted by hash, as the game's own WADs are
                for entry in sorted(stored, key=lambda entry: entry.name_hash):
                    wad.add(entry)
                    total += entry.packed
                if not wad.files:
                    continue
                with open(target / "WAD" / source.name, "wb") as out:
                    wad.write_to(out)
                copied += len(wad.files)
            finally:
                handle.close()
        if not copied:
            shutil.rmtree(target, ignore_errors=True)
            return None
        info = {"Author": "Rose", "Name": "Skin sounds", "Description": mod_name, "Version": "1.0.0"}
        (target / "META").mkdir()
        (target / "META" / "info.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
        log.info(f"[SOUNDS] {mod_name}: copied {copied} sound bank(s), {total / 1e6:.1f} MB, "
                 f"from the game in {(time.perf_counter() - started) * 1000:.0f} ms")
        return folder
    except Exception as e:  # a bad archive, manifest or WAD: the injection goes on without the mod
        log.warning(f"[SOUNDS] {mod_name}: skipped: {e}")
        return None


def sound_mods(game_dir: Optional[Path], mods_dir: Path, names: Sequence[str]) -> List[str]:
    """Build the sound mod of each mod among *names* (folders or archives in
    *mods_dir*) that lists banks to copy; their folder names, to install
    with them."""
    if game_dir is None:
        return []
    built: List[str] = []
    for name in names:
        if name.startswith(FOLDER_PREFIX):
            continue
        folder = build(Path(game_dir), Path(mods_dir), name)
        if folder and folder not in names and folder not in built:
            built.append(folder)
    return built
