#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply the base-skin steps to a mod Rose holds (a .fantome archive or a folder).

What the steps fix is the base skin: the skin0.bin of each character a
champion WAD holds (WAD/<Champion>.wad.client), the bin LTK Manager's skinhack
rule judges and the one Rose plays. A mod's other skin bins (a whole champion
WAD ships them all) are left as they are: rebased, one would claim the base
skin's mesh paths and put its own mesh there.

The mod's WADs are read file by file (wad.py), never whole. The patched banks
and padded meshes go in the champion WAD. Files come from the mod first, so a
modder's own banks and meshes are the ones patched or moved, then from the
game's WADs in champions_dir. A mod that already matches is not written again,
and a champion whose game WAD cannot be read is left as it is.
"""

from __future__ import annotations

import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from injection.mods.mod_files import ModFiles
from utils.core.logging import get_logger

from . import audio
from .audio import PackageFiles
from .steps import ALL_STEPS, BaseSkinSteps, Findings
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

    def wad(self, name: str) -> Optional[ModWad]:
        """The WAD file *name*, its table read (None: stored compressed, and too big to unpack)."""
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

    def write(self, edited: Dict[str, ModWad]) -> None:
        """Replace the WAD files *edited* names by their new content. Every new
        file is written, beside the mod, before anything is replaced."""
        def temporary() -> Path:
            return self.path.with_name(f"{IMPORT_TEMP_PREFIX}{uuid.uuid4().hex}.tmp")

        if not self.files.is_archive:
            written: List[Tuple[Path, Path]] = []
            try:
                for name, wad in edited.items():
                    written.append((temporary(), self.path / name))
                    with open(written[-1][0], "wb") as out:
                        wad.write_to(out)
                self.close()
                for new, target in written:
                    new.replace(target)
            finally:
                for new, _ in written:
                    new.unlink(missing_ok=True)
            return
        by_member = {self.files.member(name).filename: wad for name, wad in edited.items()}
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
                    else:
                        with source.open(info) as stream, \
                                out.open(entry, "w", force_zip64=info.file_size >= 2 ** 31) as target:
                            shutil.copyfileobj(stream, target, _COPY_CHUNK)
            self.close()
            new.replace(self.path)
        except BaseException:
            new.unlink(missing_ok=True)
            raise


class _ModWadFile:
    __slots__ = ("name", "locale", "wad")

    def __init__(self, name: str, locale: Optional[str], wad: ModWad) -> None:
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
        wad_names: Dict[str, Tuple[str, Optional[str]]] = {}
        unpacked = False
        for name in mod.names():
            parts = name.split("/")
            if len(parts) == 2 and audio.same(parts[0], "WAD"):
                split = split_wad_name(parts[1])
                if split is not None:
                    wad_names[name] = split
            elif len(parts) > 2 and audio.same(parts[0], "WAD") and parts[1].lower().endswith(WAD_SUFFIX):
                unpacked = True
        if unpacked:
            log.info(f"[BASESKIN] {path.name}: unpacked WAD folders are not read, left as they are")

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
        if edited:
            mod.write(edited)
            result.changed = True
    return result


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
        extras = runner.finish()
    except (OSError, ValueError) as e:
        # The bins name banks that would not ship: nothing of this champion is written
        log.warning(f"[BASESKIN] {mod_name}: the patched sound banks of {stem} could not be built ({e}); "
                    f"{stem} is left as it is")
        result.complete = False
        return

    for (_, _, _, item, name_hash, data), new in zip(targets, rebased):
        if new != data:
            item.wad.put(name_hash, new)
    for extra in extras:
        if extra.locale is not None:
            # The steps never edit a localized bank (audio._Sidecar): this would be a bug
            log.warning(f"[BASESKIN] {mod_name}: {extra.path} ({extra.locale}) was edited; not added")
            continue
        mains[0].wad.put(path_hash(extra.path), extra.data)
    for item in mains:
        if item.wad.modified:
            edited[item.name] = item.wad

    result.findings.extend(runner.findings)
    result.complete = result.complete and runner.complete
