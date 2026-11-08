#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The four things a custom skin must match to run as the base skin.

Rose plays a chosen skin as the champion's base skin (skin 0). The game and
LTK Manager's patcher treat a base skin that is another skin's data as a
"skinhack", so the skin is given the base skin's identity, taken from the
character's game skin0.bin:

1. its sound banks: the skin-tagged events are merged into the base tag, so the
   skin's sounds play under the names the base skin asks for (audio.py);
2. its bank units: Aatrox_Skin01_SFX becomes Aatrox_Base_SFX (audio.py);
3. its SKN/SKL: the model and skeleton the skin uses are copied under the base
   skin's paths with 16 trailing zero bytes (ignored by the readers, but they make
   the files byte-distinct from the game's own), and skinMeshProperties points
   at those paths;
4. championSkinName: the base skin's own name (Aatrox, AmumuBase, Default...),
   which varies per champion and is never derived.

A skin that already matches changes nothing: every step checks first. Ported
from RoseBin (tools/rosebin/src/rebase.rs), which applies the same steps to the
skins Rose ships.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional, Sequence, Set, Tuple

from utils.core.logging import get_logger

from . import audio
from .audio import AudioBanks, MergeContext, PackageFiles, SharedUnit, SharedUnitEdit
from .propbin import Bin, Entry, Value, fnv1a_lower
from .wad import GameWad

log = get_logger()

SKIN_DATA_CLASS = audio.SKIN_DATA_CLASS
PROP_SKIN_MESH = fnv1a_lower("skinMeshProperties")
PROP_SKELETON = fnv1a_lower("skeleton")
PROP_SIMPLE_SKIN = fnv1a_lower("simpleSkin")
PROP_CHAMPION_SKIN_NAME = fnv1a_lower("championSkinName")
MESH_FIELDS = (PROP_SKELETON, PROP_SIMPLE_SKIN)

# Trailing zero bytes appended to every SKN/SKL
MESH_PADDING = 16
_PADDING = bytes(MESH_PADDING)

ALL_STEPS = frozenset({"audio", "banks", "mesh", "name"})
# One line per bin would fill the log of a mod that ships a hundred identical bins
MAX_NOTES = 40

Reader = Callable[[str], Optional[bytes]]


class MeshFile:
    """A mesh/skeleton file at a base skin path. *ship* is False for one the
    mod already holds as it should be: it only keeps the path from another
    character of the package."""

    __slots__ = ("path", "source", "data", "ship")

    def __init__(self, path: str, source: str, data: bytes, ship: bool = True) -> None:
        self.path = path
        self.source = source   # the skin's own path it was copied from
        self.data = data
        self.ship = ship


class ExtraFile:
    """A file a package needs besides its skin bins."""

    __slots__ = ("locale", "path", "data")

    def __init__(self, locale: Optional[str], path: str, data: bytes) -> None:
        self.locale = locale   # None for the champion WAD, or the locale WAD it belongs in
        self.path = path
        self.data = data


class MeshRebase:
    def __init__(self) -> None:
        self.files: List[MeshFile] = []
        # (skin path, base path) left as is: an earlier character of the package
        # already ships a different file at that base path
        self.kept: List[Tuple[str, str]] = []
        self.changed = False


def skin_name(entry: Optional[Entry]) -> Optional[str]:
    field = entry.find_field(PROP_CHAMPION_SKIN_NAME) if entry is not None else None
    return field.value.as_string() if field is not None else None


def mesh_paths(entry: Optional[Entry]) -> List[Optional[str]]:
    """[skeleton, simpleSkin] from SkinCharacterDataProperties."""
    field = entry.find_field(PROP_SKIN_MESH) if entry is not None else None
    mesh = field.value.as_embed() if field is not None else None
    paths: List[Optional[str]] = []
    for name_hash in MESH_FIELDS:
        found = mesh.find_field(name_hash) if mesh is not None else None
        path = found.value.as_string() if found is not None else None
        paths.append(path if path else None)
    return paths


def rebase_skin_mesh(
    entry: Entry,
    base: Entry,
    read: Reader,
    shipped: Sequence[MeshFile],
    read_mod: Optional[Reader] = None,
) -> MeshRebase:
    """Point the entry's skeleton/simpleSkin at the base skin's paths and
    return the padded files to ship there.

    *read* looks a file up by path (the mod first, then the game's WAD);
    *read_mod* only in the mod. *shipped* are the files earlier characters of
    the package already put at base paths: the same file is reused, and a field
    whose base path holds a different file keeps its own path. Raises
    ValueError when a file the bin references cannot be found.

    A field already at the base path is left alone when the mod ships no file
    there (the game's own serves), or when the file it ships is already padded.
    """
    result = MeshRebase()
    skin_paths = mesh_paths(entry)
    base_paths = mesh_paths(base)
    targets: List[Tuple[int, str]] = []
    for field, skin_path, base_path in zip(MESH_FIELDS, skin_paths, base_paths):
        if skin_path is None or base_path is None:
            continue
        existing = next((item for item in shipped if audio.same(item.path, base_path)), None)
        if existing is not None:
            if audio.same(existing.source, skin_path):
                targets.append((field, base_path))
            else:
                result.kept.append((skin_path, base_path))
            continue
        if audio.same(skin_path, base_path):
            current = read_mod(base_path) if read_mod is not None else None
            if current is None or current.endswith(_PADDING):
                result.files.append(MeshFile(base_path, skin_path, current or b"", ship=False))
                continue
            result.files.append(MeshFile(base_path, skin_path, current + _PADDING))
            continue
        data = read(skin_path)
        if data is None:
            raise ValueError(f"{skin_path} not found")
        result.files.append(MeshFile(base_path, skin_path, data + _PADDING))
        targets.append((field, base_path))
    if not targets:
        return result
    mesh_field = entry.find_field(PROP_SKIN_MESH)
    mesh = mesh_field.value.as_embed() if mesh_field is not None else None
    if mesh is None:
        raise ValueError("skinMeshProperties disappeared while rebasing")
    for field, path in targets:
        current = mesh.find_field(field)
        if current is None or current.value.as_string() != path:
            mesh.set_field(field, Value.string(path))
            result.changed = True
    return result


def rebase_skin_name(entry: Entry, base: Entry) -> Optional[Tuple[str, str]]:
    """Set championSkinName to the base skin's. (old, new) when it changed."""
    base_name = skin_name(base)
    if base_name is None:
        return None
    old = skin_name(entry) or ""
    if old == base_name:
        return None
    entry.set_field(PROP_CHAMPION_SKIN_NAME, Value.string(base_name))
    return old, base_name


class Findings:
    """What the steps changed, for the log and for the import window."""

    def __init__(self) -> None:
        self.names: List[Tuple[str, str]] = []
        self.meshes: List[str] = []
        self.audio_merges = 0
        self.unit_renames = 0
        self.notes: List[str] = []

    @property
    def total(self) -> int:
        return len(self.names) + len(self.meshes) + self.audio_merges + self.unit_renames

    def extend(self, other: "Findings") -> None:
        self.names.extend(other.names)
        self.meshes.extend(other.meshes)
        self.audio_merges += other.audio_merges
        self.unit_renames += other.unit_renames
        self.notes.extend(other.notes[:max(0, MAX_NOTES - len(self.notes))])


class BaseSkinSteps:
    """The base-skin steps for one package. Apply it to all the package's
    character bins at once (apply_all), main character first:

    - the main character's mesh wins a base path that a sub-character shares
      (Wukong's clone, Nasus's ult form, Zyra's plants use the champion's base
      mesh path with a skin mesh of their own);
    - a sub-character lists no bank units: its skin sounds sit in the banks the
      main character's bin loads, and the main bin lists its aliases.
    """

    def __init__(self, game: Optional[GameWad], main_path: Path, files: Optional[PackageFiles] = None,
                 read_mod: Optional[Reader] = None, steps: Set[str] = ALL_STEPS) -> None:
        self.game = game
        self.steps = steps
        self._read_mod = read_mod
        self.audio = AudioBanks(game, main_path, files)
        self.meshes: List[MeshFile] = []
        self.findings = Findings()
        # False once a step could not run (a file it needed did not read): worth another try later
        self.complete = True

    def read(self, path: str) -> Optional[bytes]:
        """A file by path: the mod's own, else the game's."""
        data = self._read_mod(path) if self._read_mod is not None else None
        if data is None and self.game is not None:
            data = self.game.read_path(path)
        return data

    def _base_entry(self, character: str) -> Optional[Entry]:
        """The character's game skin0.bin entry, or None if the WAD has none."""
        if self.game is None:
            return None
        path = f"data/characters/{character}/skins/skin0.bin"
        try:
            data = self.game.read_path(path)
            return Bin(data).find_entry(SKIN_DATA_CLASS) if data is not None else None
        except (OSError, ValueError) as e:
            log.warning(f"[BASESKIN] base skin bin unreadable for {character}: {e}")
            self.complete = False
            return None

    def apply_all(self, bins: Sequence[Tuple[str, bytes]]) -> List[bytes]:
        """Run every enabled step on the (character, bin) pairs of one skin,
        main character first, and return the bins in the same order. A step
        that fails is skipped with a warning, so the bins always come back usable."""
        shared_units: List[SharedUnit] = []
        shared_edits: List[SharedUnitEdit] = []
        characters: List[str] = []
        out: List[bytes] = []
        for index, (character, bin_data) in enumerate(bins):
            bin_data, edits = self._apply_one(bin_data, character, index, shared_units)
            shared_edits.extend(edits)
            characters.append(character)
            out.append(bin_data)
        # Aliases a sub-character put in banks another bin loads are listed by that bin's units
        for owner in range(len(out)):
            owned = [edit for edit in shared_edits if edit.owner == owner]
            if owned:
                out[owner] = audio.apply_shared_unit_edits(out[owner], characters[owner], owned)
        return out

    def _apply_one(self, bin_data: bytes, character: str, index: int,
                   shared_units: List[SharedUnit]) -> Tuple[bytes, List[SharedUnitEdit]]:
        """The steps for the bin at *index*. Its bank units join *shared_units*
        for the bins after it; the changes its merge made to earlier bins' units
        are returned. A bin no step changed comes back as it came, not written
        again."""
        try:
            bin_file = Bin(bin_data)
            entry = bin_file.find_entry(SKIN_DATA_CLASS)
        except ValueError as e:
            log.warning(f"[BASESKIN] {character}: skin bin unreadable: {e}")
            return bin_data, []
        if entry is None:
            return bin_data, []
        base = self._base_entry(character)
        edits: List[SharedUnitEdit] = []
        changed = False

        if "audio" in self.steps:
            try:
                # The names the character's game bins list or post: unit lists do
                # not always name what their banks hold
                known = audio.known_event_names(self.game, character) if self.game is not None else None
                context = MergeContext(audio.tag_event_list(base), shared_units, known)
                report = audio.merge_skin_audio_tags(entry, character, self.audio, context)
            except (ValueError, OSError) as e:
                log.warning(f"[BASESKIN] audio tag merge skipped for {character}: {e}")
                self.complete = False
            else:
                if report is not None:
                    edits = report.shared_edits
                    changed = True
                    self.findings.audio_merges += 1
                    self._note(f"audio: {character}: {report.summary()}")
        # Read before the rename, which can fold a skin unit into a base unit
        # and hide which bank is the skin's
        shared_units.extend(audio.shared_units_of(entry, index))
        if "banks" in self.steps:
            units = audio.rebase_bank_units(entry)
            if units is not None:
                changed = True
                self.findings.unit_renames += 1
                self._note(f"banks: {character}: {units.summary()}")
        if base is not None:
            if "mesh" in self.steps:
                try:
                    rebase = rebase_skin_mesh(entry, base, self.read, self.meshes, self._read_mod)
                except ValueError as e:
                    log.warning(f"[BASESKIN] mesh rebase skipped for {character}: {e}")
                    self.complete = False
                else:
                    changed = changed or rebase.changed
                    for file in rebase.files:
                        if file.ship:
                            self.findings.meshes.append(file.path)
                            self._note(f"mesh: {character}: {file.path} (+{MESH_PADDING} bytes)")
                    for skin_path, base_path in rebase.kept:
                        self._note(f"mesh: {character}: keeps {skin_path}; {base_path} holds another character's mesh")
                    self.meshes.extend(rebase.files)
            if "name" in self.steps:
                renamed = rebase_skin_name(entry, base)
                if renamed is not None:
                    changed = True
                    self.findings.names.append(renamed)
                    self._note(f"name: {character}: championSkinName {renamed[0]} -> {renamed[1]}")
        return (bin_file.write() if changed else bin_data), edits

    def _note(self, text: str) -> None:
        if len(self.findings.notes) < MAX_NOTES:
            self.findings.notes.append(text)

    def finish(self) -> List[ExtraFile]:
        """The patched banks and padded meshes the package must ship."""
        files = [ExtraFile(bank.locale, bank.path, bank.data) for bank in self.audio.into_patched()]
        files.extend(ExtraFile(None, mesh.path, mesh.data) for mesh in self.meshes if mesh.ship)
        return files
