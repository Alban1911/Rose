#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply the base-skin steps to a mod Rose holds (a .fantome archive or a folder).

What the steps fix is the base skin: the skin0.bin of each character a
champion WAD holds (WAD/<Champion>.wad.client), the bin LTK Manager's skinhack
rule judges and the one Rose plays. A mod's other skin bins (a whole champion
WAD ships them all) are left as they are: rebased, one would claim the base
skin's mesh paths and put its own mesh there.

The mod's WADs are read file by file (wad.py), never whole. The patched and
moved banks and the rebuilt meshes go in the champion WAD, a voice bank the mod
ships moves inside its own locale WAD, and the game banks the skin now loads
from new paths are listed in META/rose_sounds.json, for Rose to copy from the
player's own WADs as it injects the skin (skin_sounds.py). Files come from the mod first, so a
modder's own banks and meshes are the ones patched or moved, then from the
game's WADs in champions_dir. A mod that already matches is not written again,
and a champion whose game WAD cannot be read is left as it is.

A mod can ship a WAD unpacked, as a folder (WAD/<Champion>.wad.client/<path>)
LTK Manager packs as it installs the mod. Its files are read the same way, by
the hash each is packed under (_FolderWad), and the fix keeps the folder: an
edited file is written back under its own name, a new one under its path.
"""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
import zipfile
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from injection.mods.mod_files import ModFiles
from utils.core.logging import get_logger

from . import audio
from .audio import PackageFiles
from .skin_sounds import MANIFEST as SOUND_MANIFEST
from .steps import ALL_STEPS, BaseSkinSteps, Findings, SoundCopy
from .wad import FileSource, GameWad, ModWad, WadError, path_hash

log = get_logger()

# What ModStorageService removes beside a stored mod at the next start (_recover_conversions)
IMPORT_TEMP_PREFIX = ".rose-import-"
WAD_SUFFIX = ".wad.client"
# A WAD the archive stores compressed is unpacked in memory to be read: not one bigger than this
MAX_INFLATED_WAD_BYTES = 1024 * 1024 * 1024
_COPY_CHUNK = 1024 * 1024


# --------------------------------------------------------------------------------------
# which characters a champion WAD holds
# --------------------------------------------------------------------------------------

_SUBCHARACTERS: Dict[str, Tuple[str, ...]] = {
    "anivia": ("aniviaegg", "aniviaiceblock"),
    "annie": ("annietibbers",),
    "aphelios": ("apheliosturret",),
    "aurora": ("auroraspirits",),
    "azir": ("azirsoldier", "azirsundisc", "azirtowerclicker", "azirultsoldier"),
    "bard": ("bardfollower", "bardhealthshrine", "bardpickup", "bardpickupnoicon", "bardportalclickable"),
    "belveth": ("belvethspore", "belvethvoidling"),
    "caitlyn": ("caitlyntrap",),
    "cassiopeia": ("cassiopeia_death",),
    "elise": ("elisespider", "elisespiderling"),
    "fiddlesticks": ("fiddlestickseffigy",),
    "fizz": ("fizzbait", "fizzshark"),
    "gangplank": ("gangplankbarrel",),
    "gnar": ("gnarbig",),
    "heimerdinger": ("heimertblue", "heimertyellow"),
    "illaoi": ("illaoiminion",),
    "irelia": ("ireliablades",),
    "ivern": ("ivernminion", "iverntotem"),
    "jarvaniv": ("jarvanivstandard", "jarvanivwall"),
    "jhin": ("jhintrap",),
    "jinx": ("jinxmine",),
    "kalista": ("kalistaaltar", "kalistaspawn"),
    "kindred": ("kindredjunglebountyminion", "kindredwolf"),
    "kled": ("kledmount", "kledrider"),
    "kogmaw": ("kogmawdead",),
    "lissandra": ("lissandrapassive",),
    "locke": ("locketotem",),
    "lulu": ("lulufaerie", "lulupolymorphcritter"),
    "lux": ("luxair", "luxdark", "luxfire", "luxice", "luxmagma", "luxmystic", "luxnature", "luxstorm", "luxwater"),
    "malzahar": ("malzaharvoidling",),
    "maokai": ("maokaisproutling",),
    "milio": ("miliominion",),
    "monkeyking": ("monkeykingclone", "monkeykingflying"),
    "naafiri": ("naafiripackmate",),
    "nasus": ("nasusult",),
    "nidalee": ("nidaleecougar", "nidaleespear"),
    "nunu": ("nunusnowball",),
    "olaf": ("olafaxe",),
    "orianna": ("oriannaball", "oriannanoball"),
    "ornn": ("ornnram",),
    "quinn": ("quinnvalor",),
    "rammus": ("rammusdbc", "rammuspb"),
    "reksai": ("reksaitunnel",),
    "senna": ("sennasoul",),
    "shaco": ("shacobox",),
    "shen": ("shenspirit",),
    "shyvana": ("shyvanadragon",),
    "sona": ("sonadjgenre01", "sonadjgenre02", "sonadjgenre03"),
    "swain": ("swaindemonform",),
    "syndra": ("syndraorbs", "syndrasphere"),
    "taliyah": ("taliyahwallchunk",),
    "teemo": ("teemomushroom",),
    "thresh": ("threshlantern",),
    "trundle": ("trundlewall",),
    "viego": ("viegosoul",),
    "viktor": ("viktorsingularity",),
    "yorick": ("yorickbigghoul", "yorickghoulmelee", "yorickwghoul", "yorickwinvisible"),
    "zac": ("zacrebirthbloblet",),
    "zed": ("zedshadow",),
    "zoe": ("zoeorbs",),
    "zyra": ("zyragraspingplant", "zyrapassive", "zyraseed", "zyrathornplant"),
}


def character_names(stem: str) -> List[str]:
    """The characters a champion WAD holds, main character first (RoseBin's character_names_to_process)."""
    internal = "".join(ch for ch in stem if ch not in "' .").lower()
    internal = {"wukong": "monkeyking", "renataglasc": "renata", "nunu&willump": "nunu"}.get(internal, internal)
    return [internal, *_SUBCHARACTERS.get(internal, ())]


def base_skin_bins(characters) -> Dict[int, str]:
    """Each character's skin0.bin path hash -> the character. A character not
    listed (an unknown summon) and every other bin (skinN.bin, root.bin...)
    are not base skins."""
    return {path_hash(f"data/characters/{character}/skins/skin0.bin"): character for character in characters}


def split_wad_name(file_name: str) -> Optional[Tuple[str, Optional[str]]]:
    """<stem>.wad.client / <stem>.<locale>.wad.client -> (stem, locale)."""
    base = audio.strip_suffix(file_name, WAD_SUFFIX)
    if not base:
        return None
    if "." in base:
        stem, locale = base.rsplit(".", 1)
        if audio.is_locale(locale) and stem and "." not in stem:
            return stem, audio.normalize_locale(locale)
        return None
    return base, None


_HASH_NAME = re.compile(r"[0-9a-fA-F]{16}")


def folder_file_hash(inner: str) -> int:
    """The hash a file of an unpacked WAD folder is packed under, from its
    path in the folder: its name when that is a path hash (16 hex digits,
    with an extension or not, at the folder's root: a WAD extractor's name
    for a file whose path it does not know), its path's otherwise. A legacy
    .modpkg's files are read the same way (utils.core.modpkg)."""
    inner = inner.replace("\\", "/").strip("/")
    stem = inner.split(".", 1)[0]
    if "/" not in inner and _HASH_NAME.fullmatch(stem):
        return int(stem, 16)
    return path_hash(inner)


# --------------------------------------------------------------------------------------
# a mod, as an archive or as a folder
# --------------------------------------------------------------------------------------

class _Mod:
    """A mod's files (ModFiles), its WADs read where they are, and written again."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.files = ModFiles(path)
        self._wads: List[ModWad] = []

    def __enter__(self) -> "_Mod":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        for wad in self._wads:
            wad.close()
        self._wads.clear()
        self.files.close()

    def names(self) -> List[str]:
        return self.files.files_under()

    def wad(self, name: str) -> Optional["_Wad"]:
        """The WAD *name*: a WAD file, its table read (None: stored
        compressed, and too big to unpack), or an unpacked WAD folder, named
        with a trailing slash ("WAD/Annie.wad.client/")."""
        if name.endswith("/"):
            return _FolderWad(self.files, name[:-1])
        span = self.files.span(name)
        if span is None:
            if self.files.size(name) > MAX_INFLATED_WAD_BYTES:
                return None
            wad = ModWad(self.files.read(name))
        else:
            source = FileSource(*span)
            try:
                wad = ModWad(source=source)
            except BaseException:
                source.close()
                raise
        self._wads.append(wad)
        return wad

    def write(self, edited: Dict[str, "_Wad"], files: Optional[Dict[str, bytes]] = None) -> None:
        """Write the WADs *edited* names again: a WAD file gets its new
        content, an unpacked WAD folder its edited and new files; and *files*
        ({path in the mod: content}, META/rose_sounds.json). Every new file is
        written, beside the mod, before anything is replaced."""
        def temporary() -> Path:
            return self.path.with_name(f"{IMPORT_TEMP_PREFIX}{uuid.uuid4().hex}.tmp")

        packed = {name: wad for name, wad in edited.items() if isinstance(wad, ModWad)}
        loose: Dict[str, bytes] = dict(files or {})
        for wad in edited.values():
            if isinstance(wad, _FolderWad):
                loose.update(wad.changes)
        if not self.files.is_archive:
            written: List[Tuple[Path, Path]] = []
            try:
                for name, wad in packed.items():
                    written.append((temporary(), self.path / name))
                    with open(written[-1][0], "wb") as out:
                        wad.write_to(out)
                for relative, data in loose.items():
                    written.append((temporary(), self.path / relative))
                    written[-1][0].write_bytes(data)
                self.close()
                for new, target in written:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    new.replace(target)
            finally:
                for new, _ in written:
                    new.unlink(missing_ok=True)
            return
        by_member = {self.files.member(name).filename: wad for name, wad in packed.items()}
        replaced: Dict[str, bytes] = {}
        added: List[Tuple[str, bytes]] = []
        for relative, data in loose.items():
            info = self.files.member(relative)
            if info is not None:
                replaced[info.filename] = data
            else:
                added.append((relative, data))
        new = temporary()
        try:
            with zipfile.ZipFile(self.path) as source, \
                    zipfile.ZipFile(new, "w", zipfile.ZIP_STORED, allowZip64=True) as out:
                for info in source.infolist():
                    entry = zipfile.ZipInfo(info.filename, info.date_time)
                    entry.external_attr = info.external_attr
                    if info.is_dir():
                        out.writestr(entry, b"")
                        continue
                    wad = by_member.get(info.filename)
                    # A WAD is already compressed inside: stored, as Rose keeps its archives
                    entry.compress_type = (
                        zipfile.ZIP_STORED if info.filename.lower().endswith(WAD_SUFFIX) else info.compress_type)
                    if wad is not None:
                        with out.open(entry, "w", force_zip64=wad.byte_size() >= 2 ** 31) as target:
                            wad.write_to(target)
                    elif info.filename in replaced:
                        out.writestr(entry, replaced[info.filename])
                    else:
                        with source.open(info) as stream, \
                                out.open(entry, "w", force_zip64=info.file_size >= 2 ** 31) as target:
                            shutil.copyfileobj(stream, target, _COPY_CHUNK)
                for relative, data in added:
                    out.writestr(zipfile.ZipInfo(relative, time.localtime()[:6]), data,
                                 compress_type=zipfile.ZIP_DEFLATED)
            self.close()
            new.replace(self.path)
        except BaseException:
            new.unlink(missing_ok=True)
            raise


class _FolderFile:
    """A file of an unpacked WAD folder, read when its content is asked for."""

    __slots__ = ("_wad", "relative")

    def __init__(self, wad: "_FolderWad", relative: str) -> None:
        self._wad = wad
        self.relative = relative

    @property
    def data(self) -> bytes:
        return self._wad.read(self.relative)


class _FolderWad:
    """A WAD the mod ships unpacked (WAD/<Champion>.wad.client/<path>), read
    and edited as the steps do a WAD file (ModWad): its files by the hash LTK
    Manager packs each under (folder_file_hash), read when asked for. The
    edits wait in *changes* ({path in the mod: content}) for _Mod.write: an
    edited file keeps its name, whether a path or a hash, and a new one is
    named by its path."""

    def __init__(self, files: ModFiles, folder: str) -> None:
        self.folder = folder
        self._files = files
        self._names: Dict[int, str] = {}
        for relative in files.files_under(folder):
            self._names.setdefault(folder_file_hash(relative[len(folder) + 1:]), relative)
        self.changes: Dict[str, bytes] = {}

    @property
    def modified(self) -> bool:
        return bool(self.changes)

    def close(self) -> None:
        pass  # its files are read through the mod's ModFiles

    def get(self, name_hash: int) -> Optional[_FolderFile]:
        relative = self._names.get(name_hash)
        return _FolderFile(self, relative) if relative is not None else None

    def __contains__(self, name_hash: int) -> bool:
        return name_hash in self._names

    def read(self, relative: str) -> bytes:
        if relative in self.changes:
            return self.changes[relative]
        try:
            return self._files.read(relative)
        except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile, zlib.error) as e:
            raise WadError(f"{relative} does not read: {e}") from e

    def put(self, name_hash: int, data: bytes) -> None:
        """Set the content of a file the folder holds (a new one needs its path: put_path)."""
        relative = self._names.get(name_hash)
        if relative is None:
            raise KeyError(f"{self.folder} holds no file {name_hash:016x}")
        self.changes[relative] = data

    def put_path(self, path: str, data: bytes) -> None:
        """Set the content of the file at *path*: the one the folder holds under its hash, or a new one."""
        relative = self._names.setdefault(path_hash(path), f"{self.folder}/{path.replace(chr(92), '/').lstrip('/')}")
        self.changes[relative] = data


_Wad = Union[ModWad, _FolderWad]


class _ModWadFile:
    __slots__ = ("name", "locale", "wad")

    def __init__(self, name: str, locale: Optional[str], wad: _Wad) -> None:
        self.name = name
        self.locale = locale
        self.wad = wad


class _Files(PackageFiles):
    """The files of one champion's WADs in a mod, for the steps."""

    def __init__(self, wads: List[_ModWadFile]) -> None:
        self._mains = [item for item in wads if item.locale is None]
        self._locales = [item for item in wads if item.locale is not None]

    def main_file(self, name_hash: int) -> Optional[bytes]:
        for item in self._mains:
            found = item.wad.get(name_hash)
            if found is not None:
                return found.data
        return None

    def has_main(self, name_hash: int) -> bool:
        return any(name_hash in item.wad for item in self._mains)

    def locale_files(self, name_hash: int):
        out = []
        for item in self._locales:
            found = item.wad.get(name_hash)
            if found is not None:
                out.append((item.locale, found.data))
        return out

    def read_path(self, path: str) -> Optional[bytes]:
        return self.main_file(path_hash(path))


# --------------------------------------------------------------------------------------
# the fix
# --------------------------------------------------------------------------------------

class FixResult:
    """What fixing a mod did.

    *changed*: the mod was written again. *complete*: every step could run;
    False when a game file could not be read or a step failed, so the mod
    should be checked again later. *game_wads*: the game's champion WADs it was
    checked against, {file name: [size, mtime_ns]}.
    """

    def __init__(self) -> None:
        self.changed = False
        self.complete = True
        self.findings = Findings()
        self.game_wads: Dict[str, List[int]] = {}
        # The game banks the skin now loads from new paths, for META/rose_sounds.json
        self.sound_copies: List[SoundCopy] = []

    @property
    def fixes(self) -> int:
        return self.findings.total


def fix_mod(path: Path, game_dir: Path, steps=ALL_STEPS) -> FixResult:
    """Make the base skin bins of the mod at *path* (an archive or a folder)
    match the base skin's identity (steps.py), writing the mod again only when
    something changed. Raises OSError/ValueError when the mod cannot be read or
    written; a step that cannot run is skipped with a warning, so the mod is
    never left half-fixed by it."""
    result = FixResult()
    path = Path(path)
    champions_dir = Path(game_dir) / "DATA" / "FINAL" / "Champions"
    if not champions_dir.is_dir():
        result.complete = False
        return result
    with _Mod(path) as mod:
        # WAD files by name, unpacked WAD folders by name and a trailing slash (_Mod.wad)
        wad_names: Dict[str, Tuple[str, Optional[str]]] = {}
        folders = set()
        for name in mod.names():
            parts = name.split("/")
            if len(parts) < 2 or not audio.same(parts[0], "WAD"):
                continue
            split = split_wad_name(parts[1])
            if split is None:
                continue
            if len(parts) == 2:
                wad_names[name] = split
            elif parts[1].casefold() not in folders:
                folders.add(parts[1].casefold())
                wad_names[f"{parts[0]}/{parts[1]}/"] = split

        stems: List[str] = []
        for stem, locale in wad_names.values():
            if locale is None and not any(audio.same(stem, known) for known in stems):
                game_wad = champions_dir / f"{stem}{WAD_SUFFIX}"
                try:
                    stat = game_wad.stat()
                except OSError:
                    continue  # not a champion WAD
                result.game_wads[game_wad.name] = [stat.st_size, stat.st_mtime_ns]
                stems.append(stem)

        edited: Dict[str, ModWad] = {}
        for stem in stems:
            members = [(name, locale) for name, (other, locale) in wad_names.items() if audio.same(other, stem)]
            _fix_champion(mod, path.name, stem, members, champions_dir, result, steps, edited)
        files: Dict[str, bytes] = {}
        manifest = _sound_manifest(mod.files, result.sound_copies)
        if manifest is not None:
            files[SOUND_MANIFEST] = manifest
        if edited or files:
            mod.write(edited, files)
            result.changed = True
    return result


def _sound_manifest(files: ModFiles, copies: List[SoundCopy]) -> Optional[bytes]:
    """META/rose_sounds.json listing *copies* after those the mod lists
    already (a copy to the same path replaces the old one), or None when
    that is what the mod holds. A check of a skin fixed before finds no bank
    to move: the list it holds stays."""
    if not copies:
        return None
    listed: List[dict] = []
    if files.is_file(SOUND_MANIFEST):
        try:
            document = json.loads(files.read(SOUND_MANIFEST).decode("utf-8"))
        except (OSError, ValueError) as e:
            log.warning(f"[BASESKIN] {SOUND_MANIFEST} unreadable, written again: {e}")
            document = None
        if isinstance(document, dict) and document.get("version") == 1 and isinstance(document.get("copies"), list):
            listed = [copy for copy in document["copies"] if isinstance(copy, dict)]
    new = [copy.to_json() for copy in copies]
    kept = [copy for copy in listed
            if not any(audio.same(str(copy.get("to", "")), item["to"]) for item in new)]
    if kept + new == listed:
        return None
    return json.dumps({"version": 1, "copies": kept + new}, indent=2, ensure_ascii=False).encode("utf-8")


def _fix_champion(mod: _Mod, mod_name: str, stem: str, members: List[Tuple[str, Optional[str]]],
                  champions_dir: Path, result: FixResult, steps, edited: Dict[str, ModWad]) -> None:
    characters = tuple(character_names(stem))
    base_bins = base_skin_bins(characters)

    def opened(locale_wads: bool) -> List[_ModWadFile]:
        out = []
        for name, locale in members:
            if (locale is not None) != locale_wads:
                continue
            wad = mod.wad(name)
            if wad is None:
                log.info(f"[BASESKIN] {mod_name}: {name} is stored compressed and too big to read, left as it is")
                continue
            out.append(_ModWadFile(name, locale, wad))
        return out

    mains = opened(False)
    if not any(name_hash in item.wad for item in mains for name_hash in base_bins):
        return  # no base skin: the locale WADs are not even opened
    wads = mains + opened(True)

    # The base skin bins, main character first so its mesh keeps a base path a sub-character shares
    targets = []
    for wad_index, item in enumerate(mains):
        for name_hash, character in base_bins.items():
            entry = item.wad.get(name_hash)
            if entry is None:
                continue
            try:
                data = entry.data
            except WadError as e:
                log.warning(f"[BASESKIN] {mod_name}: {character}'s skin0.bin does not read ({e}), left as it is")
                result.complete = False
                continue
            targets.append((characters.index(character), wad_index, character, item, name_hash, data))
    if not targets:
        return
    targets.sort(key=lambda target: target[:2])

    main_path = champions_dir / f"{stem}{WAD_SUFFIX}"
    try:
        game = GameWad(main_path)
    except (OSError, WadError) as e:
        # Without the base skin's own bin the steps would guess its tags and name: rather nothing
        log.warning(f"[BASESKIN] {mod_name}: the game's {main_path.name} could not be read ({e}); "
                    f"{stem} is left as it is for now")
        result.complete = False
        return

    files = _Files(wads)
    runner = BaseSkinSteps(game, main_path, files, files.read_path, set(steps))
    # All characters together: a sub-character's sounds can sit in banks the main character's bin loads
    rebased = runner.apply_all([(character, data) for _, _, character, _, _, data in targets])
    try:
        finished = runner.finish()
    except (OSError, ValueError) as e:
        # The bins name banks that would not ship: nothing of this champion is written
        log.warning(f"[BASESKIN] {mod_name}: the patched sound banks of {stem} could not be built ({e}); "
                    f"{stem} is left as it is")
        result.complete = False
        return

    # A voice bank the mod ships moves inside its own locale WAD
    locales = {item.locale: item for item in wads if item.locale is not None}
    for extra in finished.files:
        if extra.locale is None:
            continue
        if extra.locale not in locales:
            # Only a bank of the mod's own locale WADs moves; the merge never edits a localized one
            log.warning(f"[BASESKIN] {mod_name}: {extra.path} ({extra.locale}) has no locale WAD to go in; "
                        f"{stem} is left as it is")
            result.complete = False
            return

    for (_, _, _, item, name_hash, data), new in zip(targets, rebased):
        if new != data:
            item.wad.put(name_hash, new)
    for extra in finished.files:
        target = mains[0] if extra.locale is None else locales[extra.locale]
        target.wad.put_path(extra.path, extra.data)
    for item in wads:
        if item.wad.modified:
            edited[item.name] = item.wad

    result.sound_copies.extend(finished.sound_copies)
    result.findings.extend(runner.findings)
    result.complete = result.complete and runner.complete
