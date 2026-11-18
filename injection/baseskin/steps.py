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
3. its SKN/SKL: the model and skeleton the skin uses are rebuilt so they are
   byte-distinct from the game's own (the SKL gets an unused null_bone root
   joint, the SKN an unused copy of its last vertex: mesh.py), stored under the
   base skin's paths, and skinMeshProperties points at those paths;
4. championSkinName: the base skin's own name (Aatrox, AmumuBase, Default...),
   which varies per champion and is never derived;
5. its bank paths: every bank at a Skin<n> path moves, unchanged, to a base
   path (Skins/Skin12/Talon_Skin12_SFX_audio.bnk ->
   Skins/Base/Talon_Base_SFX_audio.bnk), numbered (Talon_Base2_SFX_...) when
   the skin still loads a bank at that path. A bank keeps its id, which is how
   the client links banks, so only the path changes. A bank the mod ships or
   the merge patches ships at the new path, a voice bank in its own locale
   WAD; a game bank is listed in META/rose_sounds.json (SoundCopy) and copied
   from the player's WADs as the skin is injected (skin_sounds.py);
6. its bank units' event lists: names with a Skin<n> tag are unlisted (the
   merge lists the base-tag alias of each).

A skin that already matches changes nothing: every step checks first. Ported
from RoseBin (tools/rosebin/src/rebase.rs), which applies the same steps to the
skins Rose ships.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional, Sequence, Set, Tuple

from utils.core.logging import get_logger

from . import audio, mesh
from .audio import AudioBanks, MergeContext, PackageFiles, SharedUnit, SharedUnitEdit
from .propbin import Bin, Entry, Value, fnv1a_lower
from .wad import GameWad, path_hash

log = get_logger()

SKIN_DATA_CLASS = audio.SKIN_DATA_CLASS
PROP_SKIN_MESH = fnv1a_lower("skinMeshProperties")
PROP_SKELETON = fnv1a_lower("skeleton")
PROP_SIMPLE_SKIN = fnv1a_lower("simpleSkin")
PROP_CHAMPION_SKIN_NAME = fnv1a_lower("championSkinName")
MESH_FIELDS = (PROP_SKELETON, PROP_SIMPLE_SKIN)

ALL_STEPS = frozenset({"audio", "banks", "mesh", "name", "bankpaths", "eventnames"})
# One line per bin would fill the log of a mod that ships a hundred identical bins
MAX_NOTES = 40

Reader = Callable[[str], Optional[bytes]]


class MeshFile:
    """A mesh/skeleton file at a base skin path. *ship* is False for one the
    mod already holds as it should be: it only keeps the path from another
    character of the package."""

    __slots__ = ("path", "source", "data", "ship", "added")

    def __init__(self, path: str, source: str, data: bytes, ship: bool = True, added: str = "") -> None:
        self.path = path
        self.source = source   # the skin's own path it was copied from
        self.data = data
        self.ship = ship
        self.added = added     # what the rebuild added (null joint, null vertex)


class SoundCopy:
    """A game bank the skin loads from a new path but the mod does not ship:
    Rose copies it from the player's own game WADs as it injects the skin (the
    file as the WAD stores it, at *to*, in a mod of its own: skin_sounds.py).
    *localized*: from the locale WAD of the player's language rather than the
    champion WAD. *packaged_locales*: the languages whose copy the mod ships."""

    __slots__ = ("wad", "localized", "source", "to", "packaged_locales")

    def __init__(self, wad: str, localized: bool, source: str, to: str, packaged_locales: List[str]) -> None:
        self.wad = wad
        self.localized = localized
        self.source = source
        self.to = to
        self.packaged_locales = packaged_locales

    def to_json(self) -> dict:
        return {"wad": self.wad, "localized": self.localized, "from": self.source, "to": self.to,
                "packagedLocales": list(self.packaged_locales)}


class _BankMove:
    """A bank moved off its Skin<n> path. *copies*: (locale, data) of where its
    file is, data None for the game's (Rose copies it); empty for a bank the
    merge creates, which finish takes from it."""

    __slots__ = ("source", "to", "localized", "copies")

    def __init__(self, source: str, to: str, localized: bool,
                 copies: List[Tuple[Optional[str], Optional[bytes]]]) -> None:
        self.source = source
        self.to = to
        self.localized = localized
        self.copies = copies


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
    return the rebuilt files to ship there (mesh.rebuild).

    *read* looks a file up by path (the mod first, then the game's WAD);
    *read_mod* only in the mod. *shipped* are the files earlier characters of
    the package already put at base paths: the same file is reused, and a field
    whose base path holds a different file keeps its own path. Raises
    ValueError when a file the bin references cannot be found or rebuilt.

    A field already at the base path is left alone when the mod ships no file
    there (the game's own serves), or when the file it ships is already
    rebuilt; one an older Rose padded is rebuilt from what it was before.
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
            if current is None or mesh.is_rebuilt(current):
                result.files.append(MeshFile(base_path, skin_path, current or b"", ship=False))
                continue
            data, added = _rebuilt(base_path, mesh.strip_padding(current))
            result.files.append(MeshFile(base_path, skin_path, data, added=added))
            continue
        data = read(skin_path)
        if data is None:
            raise ValueError(f"{skin_path} not found")
        data, added = _rebuilt(skin_path, data)
        result.files.append(MeshFile(base_path, skin_path, data, added=added))
        targets.append((field, base_path))
    if not targets:
        return result
    mesh_field = entry.find_field(PROP_SKIN_MESH)
    mesh_props = mesh_field.value.as_embed() if mesh_field is not None else None
    if mesh_props is None:
        raise ValueError("skinMeshProperties disappeared while rebasing")
    for field, path in targets:
        current = mesh_props.find_field(field)
        if current is None or current.value.as_string() != path:
            mesh_props.set_field(field, Value.string(path))
            result.changed = True
    return result


def _rebuilt(path: str, data: bytes) -> Tuple[bytes, str]:
    try:
        return mesh.rebuild(data)
    except mesh.MeshError as e:
        raise ValueError(f"{path}: {e}") from e


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
        self.bank_moves = 0
        self.event_names_unlisted = 0
        self.notes: List[str] = []

    @property
    def total(self) -> int:
        return (len(self.names) + len(self.meshes) + self.audio_merges + self.unit_renames
                + self.bank_moves + self.event_names_unlisted)

    def extend(self, other: "Findings") -> None:
        self.names.extend(other.names)
        self.meshes.extend(other.meshes)
        self.audio_merges += other.audio_merges
        self.unit_renames += other.unit_renames
        self.bank_moves += other.bank_moves
        self.event_names_unlisted += other.event_names_unlisted
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
        self._files = files or PackageFiles()
        self.audio = AudioBanks(game, main_path, files)
        self.meshes: List[MeshFile] = []
        self._bank_moves: List[_BankMove] = []
        # Lowercased bank paths the bins list and keep: a moved bank may not take one
        self._kept_banks: Set[str] = set()
        # The champion WAD's name without .wad.client (Aatrox)
        self.wad_stem = audio.strip_suffix(main_path.name, ".wad.client") or main_path.name
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
        # Last: the shared unit edits find units by their bank paths, and list
        # aliases in other bins' units
        if "bankpaths" in self.steps:
            self._move_bank_paths(characters, out)
        if "eventnames" in self.steps:
            for index, character in enumerate(characters):
                edited = _edit_entry(out[index], character, audio.unlist_skin_event_names)
                if edited is not None:
                    out[index], count = edited
                    self.findings.event_names_unlisted += count
                    self._note(f"eventnames: {character}: {count} Skin<n> event names unlisted")
        return out

    def _move_bank_paths(self, characters: Sequence[str], bins: List[bytes]) -> None:
        """Point every bank path with a Skin<n> segment at a base path. The
        bank gets there unchanged (finish): a game bank through Rose, which
        copies it from the player's WADs (SoundCopy), voice banks in the
        player's language; a bank the mod ships or the merge patches in the mod."""
        for bin_data in bins:
            try:
                entry = Bin(bin_data).find_entry(SKIN_DATA_CLASS)
            except ValueError:
                continue
            for path in audio.bank_paths_of(entry):
                if audio.base_bank_path(path, 1) is None:
                    self._kept_banks.add(audio.lower(path))
        for index, character in enumerate(characters):
            moved: List[Tuple[str, str]] = []

            def rename(path: str) -> Optional[str]:
                if audio.base_bank_path(path, 1) is None:
                    return None
                target = self._bank_target(character, path)
                if target is not None:
                    moved.append((path, target))
                return target

            edited = _edit_entry(bins[index], character, lambda entry: audio.rewrite_bank_paths(entry, rename))
            if edited is None:
                continue
            bins[index] = edited[0]
            self.findings.bank_moves += len(moved)
            for source, target in moved:
                self._note(f"bankpaths: {character}: {source.rsplit('/', 1)[-1]} -> {target.rsplit('/', 1)[-1]}")

    def _bank_copies(self, source: str) -> List[Tuple[Optional[str], Optional[bytes]]]:
        """The copies of the bank at *source*: the mod's own files (data),
        which ship, and the game's (None), which Rose copies."""
        if not audio.is_localized_path(source):
            if self._files.has_main(path_hash(source)):
                data = self.read(source)
                return [(None, data)] if data is not None else []
            in_game = self.game is not None and self.game.has_path(source)
            return [(None, None)] if in_game else []
        return list(self.audio.localized_copies(source))

    def _bank_target(self, character: str, source: str) -> Optional[str]:
        """The base path the bank at *source* moves to, the same for every bin
        of the skin. None keeps it where it is: no file to move."""
        for known in self._bank_moves:
            if audio.same(known.source, source):
                return known.to
        created = self.audio.creates(source)
        try:
            copies = [] if created else self._bank_copies(source)
        except (OSError, ValueError) as e:
            log.warning(f"[BASESKIN] {character}: {source} unreadable, its bank path is kept: {e}")
            self.complete = False
            return None
        if not copies and not created:
            self._note(f"bankpaths: {character}: {source} not found, its bank path is kept")
            return None
        # Taken: a bank the skin keeps loading, or another move's target
        for number in range(1, 100):
            candidate = audio.base_bank_path(source, number)
            if candidate is None:
                return None
            if audio.lower(candidate) in self._kept_banks:
                continue
            if any(audio.same(known.to, candidate) for known in self._bank_moves):
                continue
            self._bank_moves.append(_BankMove(source, candidate, audio.is_localized_path(source), copies))
            return candidate
        return None

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
                            self._note(f"mesh: {character}: {file.path} (+{file.added})")
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

    def finish(self) -> "Finished":
        """The patched banks, moved banks and rebuilt meshes the mod must
        ship, and the game banks Rose copies. A patched bank that moved ships
        at its new path only. Raises what AudioBanks.into_patched raises."""
        moves = self._bank_moves
        shipped: List[Tuple[int, Optional[str]]] = []  # (move index, locale) shipped as a patched bank
        files: List[ExtraFile] = []
        for bank in self.audio.into_patched():
            index = next((i for i, known in enumerate(moves) if audio.same(known.source, bank.path)), None)
            path = bank.path
            if index is not None:
                shipped.append((index, bank.locale))
                path = moves[index].to
            files.append(ExtraFile(bank.locale, path, bank.data))
        sound_copies: List[SoundCopy] = []
        for index, known in enumerate(moves):
            created = not known.copies
            patched = any(moved == index for moved, _ in shipped)
            from_game = False
            packaged_locales: List[str] = []
            for locale, data in known.copies:
                if (index, locale) in shipped:
                    continue
                if data is None:
                    from_game = True
                    continue
                if locale is not None:
                    packaged_locales.append(locale)
                files.append(ExtraFile(locale, known.to, data))
            if from_game:
                sound_copies.append(SoundCopy(self.wad_stem, known.localized, known.source, known.to,
                                              packaged_locales))
            if created and not patched:
                log.warning(f"[BASESKIN] {known.source} was not created; nothing ships at {known.to}")
        files.extend(ExtraFile(None, item.path, item.data) for item in self.meshes if item.ship)
        return Finished(files, sound_copies)


class Finished:
    """What BaseSkinSteps.finish leaves the mod to ship: *files*, and the game
    banks Rose copies (*sound_copies*, for META/rose_sounds.json)."""

    __slots__ = ("files", "sound_copies")

    def __init__(self, files: List[ExtraFile], sound_copies: List[SoundCopy]) -> None:
        self.files = files
        self.sound_copies = sound_copies


def _edit_entry(bin_data: bytes, character: str, edit: Callable[[Entry], object]) -> Optional[Tuple[bytes, int]]:
    """Run *edit* on the bin's skin entry: (the bin written again, what *edit*
    returned) when it returned something true, None when it changed nothing or
    the bin does not read."""
    try:
        bin_file = Bin(bin_data)
        entry = bin_file.find_entry(SKIN_DATA_CLASS)
    except ValueError as e:
        log.warning(f"[BASESKIN] {character}: skin bin unreadable: {e}")
        return None
    if entry is None:
        return None
    result = edit(entry)
    if not result:
        return None
    return bin_file.write(), result
