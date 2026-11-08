#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge a skin's audio tags into the champion's base tag, and rename its bank units.

A skin's skinAudioProperties.tagEventList is a priority chain such as
{"Aatrox", "AatroxSkin33"}. When the game asks for Play_sfx_Aatrox_AatroxQ_OnCast,
the last tag with a matching event wins, so skin 33 plays
Play_sfx_AatroxSkin33_AatroxQ_OnCast. A skin that runs as the base skin keeps
only the base tag, so for every event reached through another tag the base tag's
name becomes a new Event in the winner's own bank, with the winner's Actions,
listed in the winner's bank unit. An Event never points at another bank's
Actions: the client resolves them as its bank loads, so they would be missing
whenever the other bank loads later.

When another bank already defines the base name (usually the shared
<Champ>_Base bank) its Event is removed, and the name from its unit's list: two
loaded banks defining one id leave the client keeping only one of them, so the
skin's sound could lose to the base's. The original skin-tagged events are kept,
because animation and VFX bins also post them by their full names.

The merged list is the tagEventList of the champion's game skin0.bin, so a
character keeps the tags its base skin falls back on (Nidalee's cougar keeps
{"Nidalee", "NidaleeCougar"}). Aliases are named under the last of them.

Sub-characters (Nidalee's cougar, Elise's spider, Annie's Tibbers...) list no
bank units: their skin-tagged events sit in the banks the champion's bin loads,
and an event is found by its id among every bank loaded. Their merge reads the
bank units of the skin's other bins (SharedUnit), puts its aliases in those
banks, and hands back the unit list changes (SharedUnitEdit) for the bin that
owns the units.

Ported from RoseBin (tools/rosebin/src/audio.rs), which builds the packages
Rose ships; the two must keep producing the same bins.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from utils.core.logging import get_logger

from .bnk import Bank, BankError, wwise_hash
from .propbin import Bin, Embed, Entry, Value, LIST, STRING, fnv1a_lower
from .wad import GameWad, path_hash

log = get_logger()

SKIN_DATA_CLASS = fnv1a_lower("SkinCharacterDataProperties")
PROP_SKIN_AUDIO = fnv1a_lower("skinAudioProperties")
PROP_TAG_EVENT_LIST = fnv1a_lower("tagEventList")
PROP_BANK_UNITS = fnv1a_lower("bankUnits")
PROP_BANK_PATH = fnv1a_lower("bankPath")
PROP_EVENTS = fnv1a_lower("events")
PROP_NAME = fnv1a_lower("name")

# Highest skin number looked up in a champion WAD
MAX_SKIN_NUMBER = 200


class AudioError(ValueError):
    """A bank or bin the merge could not use."""


# --------------------------------------------------------------------------------------
# text helpers (names are compared the way the game does: ASCII case-insensitively)
# --------------------------------------------------------------------------------------

_ASCII_LOWER = {code: code + 32 for code in range(ord("A"), ord("Z") + 1)}


def lower(text: str) -> str:
    # str.lower() is exactly an ASCII lowercase for ASCII text; other text only
    # has its ASCII letters lowered, as the game compares names
    return text.lower() if text.isascii() else text.translate(_ASCII_LOWER)


def same(a: str, b: str) -> bool:
    return a == b or lower(a) == lower(b)


def strip_prefix(value: str, prefix: str) -> Optional[str]:
    return value[len(prefix):] if same(value[:len(prefix)], prefix) and len(value) >= len(prefix) else None


def strip_suffix(value: str, suffix: str) -> Optional[str]:
    if len(value) < len(suffix) or not same(value[len(value) - len(suffix):], suffix):
        return None
    return value[:len(value) - len(suffix)]


def is_locale(value: str) -> bool:
    return (
        len(value) == 5 and value[2] == "_"
        and value[:2].isascii() and value[:2].isalpha()
        and value[3:].isascii() and value[3:].isalpha()
    )


def normalize_locale(locale: str) -> str:
    """fr_fr -> fr_FR, as the game names its WADs."""
    return f"{locale[:2].lower()}_{locale[3:].upper()}"


def tag_start(name: str) -> Optional[int]:
    """Where the tag starts in an event name: after <Action>_<category>_."""
    first = name.find("_")
    if first < 0:
        return None
    second = name.find("_", first + 1)
    if second < 0:
        return None
    return second + 1 if second + 1 < len(name) else None


def string_list(embed: Embed, field: int) -> List[str]:
    found = embed.find_field(field)
    items = found.value.as_list() if found is not None else None
    return [item.v for item in items if item.ty == STRING] if items else []


def dedup_ignore_case(paths: Sequence[str]) -> List[str]:
    seen: Set[str] = set()
    out = []
    for path in paths:
        key = lower(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


# --------------------------------------------------------------------------------------
# what a merge reads and reports
# --------------------------------------------------------------------------------------

class Unit:
    """A bank unit of a skin: the events it lists and its events bank."""

    __slots__ = ("events", "events_bank")

    def __init__(self, events: List[str], events_bank: Optional[str]) -> None:
        self.events = events
        self.events_bank = events_bank


class SharedUnit:
    """A bank unit listed by another character bin of the same skin."""

    __slots__ = ("owner", "unit")

    def __init__(self, owner: int, unit: Unit) -> None:
        self.owner = owner
        self.unit = unit


class UnitEdit:
    """Changes to one bank unit's lists."""

    __slots__ = ("unlist", "list", "bank_paths")

    def __init__(self) -> None:
        self.unlist: List[str] = []      # names whose Event left the unit's bank
        self.list: List[str] = []        # alias names added to the unit's bank
        self.bank_paths: List[str] = []  # language-neutral banks to load after the unit's events bank


class SharedUnitEdit:
    """A UnitEdit for a unit of another bin. *events_bank* finds the unit again
    after the bank unit rename, which can change its name or fold it into another."""

    __slots__ = ("owner", "events_bank", "edit")

    def __init__(self, owner: int, events_bank: str, edit: UnitEdit) -> None:
        self.owner = owner
        self.events_bank = events_bank
        self.edit = edit


class KnownNames:
    """Event names the game's bins for one character list or post, and the tags
    of its skins.

    A bank unit's events list does not always name what its bank holds (Mel
    skin 1 lists Play_sfx_Mel_Dance3D_leadin while its bank defines
    Play_sfx_MelSkin01_Dance3D_leadin). The client finds an event by the id of
    the name it composes, so the merge tries each known name's suffix under
    each of the skin's tags against the events its banks really hold.
    """

    __slots__ = ("names", "tags")

    def __init__(self, names: List[str], tags: List[str]) -> None:
        self.names = names
        self.tags = tags


class MergeContext:
    __slots__ = ("base_tags", "shared_units", "known")

    def __init__(self, base_tags: Optional[List[str]] = None, shared_units: Sequence[SharedUnit] = (),
                 known: Optional[KnownNames] = None) -> None:
        self.base_tags = base_tags      # tagEventList of the character's game skin0.bin
        self.shared_units = shared_units
        self.known = known


class MergeReport:
    def __init__(self) -> None:
        self.base_tag = ""
        self.kept_tags: List[str] = []
        self.removed_tags: List[str] = []
        self.uses_shared_units = False
        self.shared_edits: List[SharedUnitEdit] = []
        self.events_added = 0
        self.events_replaced = 0
        self.events_language_neutral = 0
        self.events_shadowed = 0
        self.events_missing = 0
        self.events_from_banks = 0
        self.events_dropped_tags = 0

    def summary(self) -> str:
        kept = ", ".join(tag for tag in self.kept_tags if tag)
        text = (f"merged {', '.join(self.removed_tags)} into {kept} ({self.events_added} events added, "
                f"{self.events_replaced} taken over from other banks")
        if self.uses_shared_units:
            text += ", in banks another character's bin loads"
        if self.events_language_neutral:
            text += f", {self.events_language_neutral} voice in a language-neutral bank"
        if self.events_shadowed:
            text += f", {self.events_shadowed} also in a localized base bank"
        if self.events_from_banks:
            text += f", {self.events_from_banks} found in banks under no listed name"
        if self.events_dropped_tags:
            text += f", {self.events_dropped_tags} under dropped tags"
        if self.events_missing:
            text += f", {self.events_missing} not found in banks"
        return text + ")"


class PatchedBank:
    """A bank that was modified or created and must ship in the mod."""

    __slots__ = ("locale", "path", "data")

    def __init__(self, locale: Optional[str], path: str, data: bytes) -> None:
        self.locale = locale
        self.path = path
        self.data = data


# --------------------------------------------------------------------------------------
# the banks
# --------------------------------------------------------------------------------------

class _BankCopy:
    __slots__ = ("locale", "path", "bank", "modified")

    def __init__(self, locale: Optional[str], path: str, bank: Bank) -> None:
        self.locale = locale
        self.path = path
        self.bank = bank
        self.modified = False


class _Sidecar:
    """Alias events for one localized (VO) events bank.

    A localized bank only exists for the languages installed here, so it is
    never patched. Its Events and Actions are the same in every language, so the
    aliases and copies of their Actions go in a new events bank in the
    champion WAD. Its Actions keep the source bank's id, so they find their
    sounds in whichever language's bank the client loads.
    """

    __slots__ = ("source_path", "path", "events")

    def __init__(self, source_path: str, path: str) -> None:
        self.source_path = source_path
        self.path = path
        self.events: List[Tuple[int, int]] = []  # (alias_id, source_id)


class PackageFiles:
    """The files of the mod being fixed: they come before the game's. Locale
    files are those of a mod's <Champ>.<locale>.wad.client."""

    def main_file(self, name_hash: int) -> Optional[bytes]:
        return None

    def locale_files(self, name_hash: int) -> List[Tuple[str, bytes]]:
        return []


def sidecar_path(source: str) -> str:
    """.../VO/en_US/.../Aatrox_Skin01_VO_events.bnk -> .../VO/.../Aatrox_Skin01_VO_basetag_events.bnk:
    no locale folder, and _events kept so the client reads its events."""
    segments = [segment for segment in source.split("/") if not is_locale(segment)]
    name = segments.pop() if segments else ""
    stem = strip_suffix(name, "_events.bnk")
    if stem is None:
        stem = strip_suffix(name, ".bnk")
    if stem is None:
        stem = name
    segments.append("")
    return "/".join(segments) + f"{stem}_basetag_events.bnk"


def find_locale_wads(main_path: Path) -> List[Tuple[str, GameWad]]:
    """The <Champ>.<locale>.wad.client files next to the champion WAD, by locale."""
    directory = main_path.parent
    stem = strip_suffix(main_path.name, ".wad.client")
    if stem is None:
        return []
    found: Dict[str, GameWad] = {}
    try:
        names = sorted(directory.iterdir())
    except OSError:
        return []
    for entry in names:
        rest = strip_prefix(entry.name, f"{stem}.")
        locale = strip_suffix(rest, ".wad.client") if rest is not None else None
        if locale is None or not is_locale(locale):
            continue
        try:
            found[normalize_locale(locale)] = GameWad(entry)
        except (OSError, ValueError) as e:
            raise AudioError(f"failed to read WAD {entry}: {e}") from e
    return sorted(found.items())


class AudioBanks:
    """Event banks read from the game's WADs (or the mod's), shared by every
    character bin of one skin so that a bank touched twice is patched cumulatively."""

    def __init__(self, main: Optional[GameWad], main_path: Path, overlay: Optional[PackageFiles] = None) -> None:
        self.main = main
        self.main_path = main_path   # the champion WAD; its <stem>.<locale>.wad.client siblings hold VO
        self.overlay = overlay or PackageFiles()
        self._locale_wads: Optional[List[Tuple[str, GameWad]]] = None
        self._banks: Dict[str, List[_BankCopy]] = {}   # by lowercased bank path
        self.sidecars: Dict[str, _Sidecar] = {}        # by lowercased source bank path

    def copies(self, path: str) -> List[_BankCopy]:
        return self._banks.get(lower(path), [])

    def is_localized(self, path: str) -> bool:
        return any(copy.locale is not None for copy in self.copies(path))

    def load(self, path: str) -> bool:
        """Load a bank into the cache; False when no WAD has it."""
        key = lower(path)
        if key in self._banks:
            return True
        name_hash = path_hash(path)
        sources: Dict[Optional[str], bytes] = {}
        main_data = self.overlay.main_file(name_hash)
        if main_data is None and self.main is not None:
            main_data = self.main.read_path(path)
        if main_data is not None:
            sources[None] = main_data
        else:
            if self._locale_wads is None:
                self._locale_wads = find_locale_wads(self.main_path)
            for locale, wad in self._locale_wads:
                data = wad.read_path(path)
                if data is not None:
                    sources[locale] = data
            # A mod's own locale WADs override the game's
            for locale, data in self.overlay.locale_files(name_hash):
                sources[locale] = data
        if not sources:
            return False
        copies = []
        for locale in sorted(sources, key=lambda item: (item is not None, item or "")):
            try:
                bank = Bank.parse(sources[locale])
            except BankError as e:
                raise AudioError(f"{path} ({locale}): {e}" if locale else f"{path}: {e}") from e
            copies.append(_BankCopy(locale, path, bank))
        self._banks[key] = copies
        return True

    def into_patched(self) -> List[PatchedBank]:
        """The banks that were modified or created, in a stable order."""
        patched: List[PatchedBank] = []
        for key in sorted(self.sidecars):
            sidecar = self.sidecars[key]
            copies = self._banks.get(lower(sidecar.source_path))
            if not copies:
                continue
            file_name = sidecar.path.rsplit("/", 1)[-1]
            file_stem = strip_suffix(file_name, ".bnk")
            if file_stem is None:
                file_stem = sidecar.path
            try:
                bank, count = copies[0].bank.extract_events(
                    wwise_hash(file_stem), wwise_hash("SFX"), sidecar.events)
            except BankError as e:
                raise AudioError(f"{sidecar.source_path}: {e}") from e
            if count > 0:
                patched.append(PatchedBank(None, sidecar.path, bank.write()))
        for copies in self._banks.values():
            for copy in copies:
                if copy.modified:
                    patched.append(PatchedBank(copy.locale, copy.path, copy.bank.write()))
        patched.sort(key=lambda item: (item.locale is not None, item.locale or "", item.path))
        return patched


# --------------------------------------------------------------------------------------
# the names a character's game bins list or post
# --------------------------------------------------------------------------------------

_KNOWN_CACHE: Dict[tuple, KnownNames] = {}
# A string: a 16-bit length (4..255) then that many printable ASCII bytes. Only a
# length byte followed by 0 and a printable byte can start one.
_STRING_START = re.compile(rb"(?=[\x04-\xff]\x00[\x21-\x7e])")


def bin_strings(data: bytes) -> List[str]:
    """The length-prefixed ASCII strings of a PROP bin (other values are stepped
    over a byte at a time)."""
    out: List[str] = []
    at = 0
    size = len(data)
    for match in _STRING_START.finditer(data):
        start = match.start()
        if start < at:
            continue
        length = data[start]
        end = start + 2 + length
        if end <= size:
            chunk = data[start + 2:end]
            if chunk.isascii() and all(0x21 <= byte <= 0x7E for byte in chunk):
                out.append(chunk.decode("ascii"))
                at = end
    return out


def is_event_name(name: str) -> bool:
    """<Action>_<sfx|vo>_<tag>_<rest>, the way bins and bank units name events."""
    parts = name.split("_", 2)
    if len(parts) < 3:
        return False
    action, category, rest = parts
    return (
        bool(action) and action.isascii() and action.isalpha()
        and lower(category) in ("sfx", "vo")
        and "_" in rest
    )


def tag_event_list(entry: Optional[Entry]) -> Optional[List[str]]:
    """A skin bin's tagEventList, or None when it has none."""
    if entry is None:
        return None
    field = entry.find_field(PROP_SKIN_AUDIO)
    audio = field.value.as_embed() if field is not None else None
    if audio is None or audio.find_field(PROP_TAG_EVENT_LIST) is None:
        return None
    return string_list(audio, PROP_TAG_EVENT_LIST)


def known_event_names(wad: GameWad, character: str) -> KnownNames:
    """KnownNames of *character* in *wad*: every skin<n>.bin, and the bins they
    reference that the WAD holds (animations, linked bins). Read once per WAD and character."""
    try:
        stat = wad.path.stat()
        key = (str(wad.path), stat.st_mtime_ns, stat.st_size, character.lower())
    except OSError:
        key = (str(wad.path), 0, 0, character.lower())
    known = _KNOWN_CACHE.get(key)
    if known is None:
        known = _collect_known_names(wad, character)
        _KNOWN_CACHE[key] = known
    return known


def _collect_known_names(wad: GameWad, character: str) -> KnownNames:
    names: Dict[str, str] = {}
    tags: List[str] = []
    # (path, whether it is a skin bin, whose references are followed); taken from the end
    queue: List[Tuple[str, bool]] = [
        (path, True)
        for path in (f"data/characters/{character}/skins/skin{n}.bin" for n in range(MAX_SKIN_NUMBER + 1))
        if wad.has_path(path)
    ]
    seen: Set[str] = set()
    while queue:
        path, is_skin = queue.pop()
        if lower(path) in seen:
            continue
        seen.add(lower(path))
        try:
            data = wad.read_path(path)
        except (OSError, ValueError):
            continue
        if data is None:
            continue
        if is_skin:
            try:
                listed = tag_event_list(Bin(data).find_entry(SKIN_DATA_CLASS))
            except ValueError:
                listed = None
            for tag in listed or []:
                if tag and not any(same(known, tag) for known in tags):
                    tags.append(tag)
        for string in bin_strings(data):
            if is_event_name(string):
                names.setdefault(lower(string), string)
            elif (
                is_skin
                and strip_suffix(string, ".bin") is not None
                and strip_prefix(string, "data/") is not None
                and lower(string) not in seen
                and wad.has_path(string)
            ):
                queue.append((string, False))
    return KnownNames(sorted(names.values()), tags)


# --------------------------------------------------------------------------------------
# bank units
# --------------------------------------------------------------------------------------

def read_units(audio: Embed) -> List[Unit]:
    field = audio.find_field(PROP_BANK_UNITS)
    values = field.value.as_list() if field is not None else None
    units = []
    for value in values or []:
        unit = value.as_embed()
        if unit is None:
            units.append(Unit([], None))
            continue
        events_bank = next(
            (path for path in string_list(unit, PROP_BANK_PATH) if path.lower().endswith("_events.bnk")), None)
        units.append(Unit(string_list(unit, PROP_EVENTS), events_bank))
    return units


def _audio_of(entry: Optional[Entry]) -> Optional[Embed]:
    field = entry.find_field(PROP_SKIN_AUDIO) if entry is not None else None
    return field.value.as_embed() if field is not None else None


def shared_units_of(entry: Optional[Entry], owner: int) -> List[SharedUnit]:
    """The bank units a bin lists that have an events bank, for the merges of
    the skin's other bins. Read it before the bank unit rename, which can fold
    a skin unit into a base unit."""
    audio = _audio_of(entry)
    if audio is None:
        return []
    return [SharedUnit(owner, unit) for unit in read_units(audio) if unit.events_bank]


def _event_list(unit_values: List[Value], index: int) -> Optional[List[Value]]:
    if not 0 <= index < len(unit_values):
        return None
    unit = unit_values[index].as_embed()
    field = unit.find_field(PROP_EVENTS) if unit is not None else None
    return field.value.as_list() if field is not None else None


def apply_unit_edits(unit_values: List[Value], edits: Sequence[Tuple[int, Optional[str], UnitEdit]]) -> None:
    """Apply (unit index, its events bank, edit) triples: every removal first,
    then the additions, so a name moved between two units that the rename
    folded into one stays listed."""
    for index, _bank, edit in edits:
        events = _event_list(unit_values, index)
        if events is not None:
            events[:] = [
                value for value in events
                if not (value.ty == STRING and any(same(name, value.v) for name in edit.unlist))
            ]
    for index, _bank, edit in edits:
        events = _event_list(unit_values, index)
        if events is None:
            continue
        for name in edit.list:
            if not any(value.ty == STRING and same(value.v, name) for value in events):
                events.append(Value.string(name))
    # The language-neutral bank goes right after the unit's own events bank, so
    # it loads after the bank whose sounds its Actions play
    for index, events_bank, edit in edits:
        unit = unit_values[index].as_embed() if 0 <= index < len(unit_values) else None
        field = unit.find_field(PROP_BANK_PATH) if unit is not None else None
        paths = field.value.as_list() if field is not None else None
        if paths is None:
            continue
        for path in edit.bank_paths:
            if any(value.ty == STRING and same(value.v, path) for value in paths):
                continue
            after = None
            if events_bank is not None:
                after = next(
                    (i for i, value in enumerate(paths) if value.ty == STRING and same(value.v, events_bank)), None)
            if after is None:
                paths.append(Value.string(path))
            else:
                paths.insert(after + 1, Value.string(path))


def apply_shared_unit_edits(bin_data: bytes, character: str, edits: Sequence[SharedUnitEdit]) -> bytes:
    """Apply the bank unit changes other bins' merges made for this bin's
    units. Run it after the bank unit rename: a unit is found by its events
    bank. On failure the bin is returned unchanged with a warning."""
    try:
        bin_file = Bin(bin_data)
        entry = bin_file.find_entry(SKIN_DATA_CLASS)
    except ValueError as e:
        log.warning(f"[BASESKIN] shared bank unit changes skipped for {character}: {e}")
        return bin_data
    audio = _audio_of(entry)
    field = audio.find_field(PROP_BANK_UNITS) if audio is not None else None
    unit_values = field.value.as_list() if field is not None else None
    if unit_values is None:
        log.warning(f"[BASESKIN] shared bank unit changes skipped for {character}: it lists no bank units")
        return bin_data
    targets: List[Tuple[int, Optional[str], UnitEdit]] = []
    for edit in edits:
        index = next(
            (i for i, value in enumerate(unit_values)
             if value.as_embed() is not None
             and any(same(path, edit.events_bank) for path in string_list(value.as_embed(), PROP_BANK_PATH))),
            None,
        )
        if index is None:
            log.warning(f"[BASESKIN] {character}: no bank unit loads {edit.events_bank}; "
                        f"{len(edit.edit.list)} alias names not listed")
        else:
            targets.append((index, edit.events_bank, edit.edit))
    apply_unit_edits(unit_values, targets)
    return bin_file.write()


def base_unit_name(name: str) -> Optional[str]:
    """Aatrox_Skin01_SFX -> Aatrox_Base_SFX; None if no Skin<n> segment."""
    def is_skin_segment(segment: str) -> bool:
        return len(segment) > 4 and lower(segment[:4]) == "skin" and segment[4:].isascii() and segment[4:].isdigit()

    segments = name.split("_")
    if not any(is_skin_segment(segment) for segment in segments):
        return None
    return "_".join("Base" if is_skin_segment(segment) else segment for segment in segments)


def _unit_name(unit: Embed) -> Optional[str]:
    field = unit.find_field(PROP_NAME)
    return field.value.as_string() if field is not None else None


def _append_strings(unit: Embed, field: int, items: Sequence[str]) -> None:
    current = unit.find_field(field)
    if current is None or current.value.as_list() is None:
        unit.set_field(field, Value(LIST, [], STRING))
    values = unit.find_field(field).value.as_list()
    for item in items:
        if not any(value.ty == STRING and same(value.v, item) for value in values):
            values.append(Value.string(item))


class UnitReport:
    def __init__(self) -> None:
        self.renamed: List[Tuple[str, str]] = []  # (old, new) units renamed and kept
        self.merged: List[Tuple[str, str]] = []   # (old, into) renamed units folded into an existing one

    def summary(self) -> str:
        return ", ".join([f"{old} -> {new}" for old, new in self.renamed]
                         + [f"{old} merged into {into}" for old, into in self.merged])


def rebase_bank_units(entry: Entry) -> Optional[UnitReport]:
    """Rename bank units from <Champ>_Skin<n>_<Kind> to <Champ>_Base_<Kind>
    (every Skin<n> segment becomes Base). A renamed unit whose new name is
    already taken is folded into that unit: its bank paths and events are
    appended, skipping duplicates. Units that were not renamed never merge with
    each other. None when nothing changed."""
    audio = _audio_of(entry)
    field = audio.find_field(PROP_BANK_UNITS) if audio is not None else None
    units = field.value.as_list() if field is not None else None
    if units is None:
        return None
    report = UnitReport()
    kept: List[Value] = []
    for value in units:
        unit = value.as_embed()
        old_name = _unit_name(unit) if unit is not None else None
        new_name = base_unit_name(old_name) if old_name is not None else None
        if unit is None or old_name is None or new_name is None:
            kept.append(value)
            continue
        unit.set_field(PROP_NAME, Value.string(new_name))
        target = next(
            (existing.as_embed() for existing in kept
             if existing.as_embed() is not None
             and (_unit_name(existing.as_embed()) is not None)
             and same(_unit_name(existing.as_embed()), new_name)),
            None,
        )
        if target is not None:
            into = _unit_name(target) or new_name
            _append_strings(target, PROP_BANK_PATH, string_list(unit, PROP_BANK_PATH))
            _append_strings(target, PROP_EVENTS, string_list(unit, PROP_EVENTS))
            report.merged.append((old_name, into))
        else:
            report.renamed.append((old_name, new_name))
            kept.append(value)
    units[:] = kept
    return report if report.renamed or report.merged else None


# --------------------------------------------------------------------------------------
# the merge
# --------------------------------------------------------------------------------------

class _Candidate:
    """An event reachable as <prefix><tag>_<suffix>."""

    __slots__ = ("priority", "is_base", "unit", "name", "prefix_end", "suffix_start", "listed")

    def __init__(self, priority: int, is_base: bool, unit: int, name: str, prefix_end: int,
                 suffix_start: int, listed: bool) -> None:
        self.priority = priority
        self.is_base = is_base
        self.unit = unit
        self.name = name
        self.prefix_end = prefix_end
        self.suffix_start = suffix_start
        self.listed = listed  # a bank unit lists the name (else it was found in a bank)


def base_tags_for(tags: Sequence[str], character: str, game_base: Optional[Sequence[str]]) -> List[str]:
    """The tags the merged list keeps: the game skin0's list when it holds a
    tag, else the one tag base_tag_for picks."""
    if game_base is not None and any(game_base):
        return list(game_base)
    return [base_tag_for(tags, character)]


def base_tag_for(tags: Sequence[str], character: str) -> str:
    """The list entry matching the character name (Classic jade_ prefix
    ignored), else the character name itself."""
    plain = strip_prefix(character, "jade_")
    if plain is None:
        plain = character
    for tag in tags:
        if same(tag, character) or same(tag, plain):
            return tag
    return plain


def merge_skin_audio_tags(
    entry: Entry, character: str, banks: AudioBanks, context: MergeContext,
) -> Optional[MergeReport]:
    """Merge every non-base tag of the character's SkinCharacterDataProperties
    into the base tags. None when there is nothing to merge. Nothing is
    modified unless the whole plan succeeds."""
    audio = _audio_of(entry)
    if audio is None:
        return None

    tags = string_list(audio, PROP_TAG_EVENT_LIST)
    base_tags = base_tags_for(tags, character, context.base_tags)

    def is_base(tag: str) -> bool:
        return any(same(base, tag) for base in base_tags)

    # Aliases are named under the last base tag, which outranks the others
    base_tag = next((tag for tag in reversed(base_tags) if tag), None)
    if base_tag is None:
        return None
    removed_tags = [tag for tag in tags if tag and not is_base(tag)]
    if not removed_tags:
        return None

    own_units = read_units(audio)
    shared = not own_units and bool(context.shared_units)
    units: List[Unit] = [item.unit for item in context.shared_units] if shared else own_units
    for unit in units:
        if unit.events_bank:
            banks.load(unit.events_bank)

    # Every event a tag lookup can reach, keyed by (prefix, suffix) without the tag
    priorities: List[Tuple[str, int]] = [(tag, index) for index, tag in enumerate(tags) if tag]
    # Base names the list never consulted still collide by ID
    unconsulted = [base for base in base_tags if base and not any(same(tag, base) for tag in tags)]
    for index, tag in enumerate(unconsulted):
        priorities.append((tag, index - len(unconsulted)))
    candidates: Dict[Tuple[str, str], List[_Candidate]] = {}
    for unit_index, unit in enumerate(units):
        for name in unit.events:
            prefix_end = tag_start(name)
            if prefix_end is None:
                continue
            rest = name[prefix_end:]
            for tag, priority in priorities:
                if len(rest) <= len(tag) or not same(rest[:len(tag)], tag) or rest[len(tag)] != "_":
                    continue
                suffix_start = prefix_end + len(tag) + 1
                key = (lower(name[:prefix_end]), lower(name[suffix_start:]))
                candidates.setdefault(key, []).append(
                    _Candidate(priority, is_base(tag), unit_index, name, prefix_end, suffix_start, True))

    bank_paths = dedup_ignore_case(
        [unit.events_bank for unit in units if unit.events_bank and banks.copies(unit.events_bank)])

    # The events the loaded banks really hold, and the units that load them
    bank_events: Dict[int, List[int]] = {}
    for unit_index, unit in enumerate(units):
        if not unit.events_bank:
            continue
        for copy in banks.copies(unit.events_bank):
            for event_id in list(copy.bank.event_ids()):
                found = bank_events.setdefault(event_id, [])
                if unit_index not in found:
                    found.append(unit_index)

    # The units' lists do not always name what their banks hold: every suffix
    # the character's names carry is tried under each tag, and kept when a bank defines it
    known = context.known
    known_names: List[str] = known.names if known is not None else []
    split_tags: List[str] = []
    for tag in list(known.tags if known is not None else []) + list(tags) + list(base_tags):
        if tag and not any(same(existing, tag) for existing in split_tags):
            split_tags.append(tag)
    suffixes: Dict[Tuple[str, str], Tuple[str, str]] = {}
    unit_events = [name for unit in units for name in unit.events]
    for name in known_names + unit_events:
        prefix_end = tag_start(name)
        if prefix_end is None:
            continue
        rest = name[prefix_end:]
        for tag in split_tags:
            after = strip_prefix(rest, tag)
            if after is None or not after.startswith("_"):
                continue
            suffix = after[1:]
            if not suffix:
                continue
            prefix = name[:prefix_end]
            suffixes.setdefault((lower(prefix), lower(suffix)), (prefix, suffix))
    for key in sorted(suffixes):
        prefix, suffix = suffixes[key]
        for tag, priority in priorities:
            name = f"{prefix}{tag}_{suffix}"
            found = bank_events.get(wwise_hash(name))
            if found is None:
                continue
            group = candidates.setdefault(key, [])
            for unit_index in found:
                if any(c.unit == unit_index and same(c.name, name) for c in group):
                    continue
                group.append(_Candidate(priority, is_base(tag), unit_index, name, len(prefix),
                                        len(prefix) + len(tag) + 1, False))
    # Names a bin posts explicitly: a base event gets an alias under a dropped tag only for those
    posted: Set[int] = {wwise_hash(name) for name in known_names + unit_events}

    dropped_tags = list(removed_tags)
    report = MergeReport()
    report.base_tag = base_tag
    report.kept_tags = list(base_tags)
    report.removed_tags = list(removed_tags)
    report.uses_shared_units = shared
    ops: List[tuple] = []
    edits: Dict[int, UnitEdit] = {}

    def edit_of(index: int) -> UnitEdit:
        found = edits.get(index)
        if found is None:
            found = edits[index] = UnitEdit()
        return found

    for key in sorted(candidates):
        group = candidates[key]
        # The client takes the most specific tag that has the event; among
        # equals a unit that lists the name, then the later bank unit wins. A
        # listed name no bank defines never answers. (max_by_key keeps the last of equals)
        winner: Optional[_Candidate] = None
        for candidate in group:
            if wwise_hash(candidate.name) not in bank_events:
                continue
            if winner is None or (candidate.priority, candidate.listed, candidate.unit) >= \
                    (winner.priority, winner.listed, winner.unit):
                winner = candidate
        if winner is None:
            if any(not candidate.is_base for candidate in group):
                report.events_missing += 1
            continue
        prefix = winner.name[:winner.prefix_end]
        suffix = winner.name[winner.suffix_start:]

        # The names that must reach the winner once the list is the base tags:
        # the base tag's (a base-tag winner still resolves by itself), and each
        # dropped tag's, which bins post explicitly. A dropped tag's name is
        # only given when no loaded bank defines it: the banks can be another
        # character's too, whose own event of that name must stay.
        aliases: List[Tuple[str, bool]] = []
        if not winner.is_base:
            aliases.append((f"{prefix}{base_tag}_{suffix}", False))
        for tag in dropped_tags:
            alias = f"{prefix}{tag}_{suffix}"
            alias_id = wwise_hash(alias)
            if same(alias, winner.name) or any(same(known_alias, alias) for known_alias, _ in aliases) \
                    or alias_id in bank_events:
                continue
            if winner.is_base and alias_id not in posted:
                continue
            aliases.append((alias, True))
        if not aliases:
            continue
        source_id = wwise_hash(winner.name)

        # Prefer the winner's own bank, then any other bank of this skin
        own_bank = units[winner.unit].events_bank
        source_bank = next(
            (path for path in ([own_bank] if own_bank else []) + bank_paths
             if any(copy.bank.has_event(source_id) for copy in banks.copies(path))),
            None,
        )
        if source_bank is None:
            report.events_missing += 1
            continue
        if not winner.listed:
            report.events_from_banks += 1

        for alias, dropped_tag in aliases:
            alias_id = wwise_hash(alias)
            if dropped_tag:
                report.events_dropped_tags += 1

            # The alias lives only in the source bank, next to its actions. Any
            # other bank defining it loses that Event (and its unit the name).
            defining = [path for path in bank_paths
                        if any(copy.bank.has_event(alias_id) for copy in banks.copies(path))]
            source_localized = banks.is_localized(source_bank)
            replaced = False
            shadowed = False
            for bank in defining:
                other = not same(bank, source_bank)
                if banks.is_localized(bank):
                    # A localized bank is never edited (it must work for every
                    # language), so its copy of the id stays
                    if source_localized or other:
                        shadowed = True
                    continue
                if not other:
                    continue
                ops.append(("remove", bank, alias_id))
                for unit_index, unit in enumerate(units):
                    if unit.events_bank and same(unit.events_bank, bank) and unit_index != winner.unit:
                        edit_of(unit_index).unlist.append(alias)
                replaced = True
            if source_localized:
                ops.append(("sidecar", source_bank, alias_id, source_id))
                report.events_language_neutral += 1
                if shadowed:
                    report.events_shadowed += 1
                sidecar = sidecar_path(source_bank)
                edit = edit_of(winner.unit)
                if not any(same(path, sidecar) for path in edit.bank_paths):
                    edit.bank_paths.append(sidecar)
            else:
                in_source = any(same(bank, source_bank) for bank in defining)
                ops.append(("put", source_bank, alias_id, source_id))
                if replaced or in_source:
                    report.events_replaced += 1
                else:
                    report.events_added += 1

            if not any(same(name, alias) for name in units[winner.unit].events):
                edit_of(winner.unit).list.append(alias)

    # Apply: banks first, then the bin
    for op in ops:
        if op[0] == "put":
            _, bank, alias_id, source_id = op

            def put(copy: _BankCopy, actions: List[int], alias_id: int = alias_id) -> None:
                if copy.bank.has_event(alias_id):
                    if copy.bank.set_event_actions(alias_id, actions) > 0:
                        copy.modified = True
                else:
                    copy.bank.add_event(alias_id, actions)
                    copy.modified = True

            _apply_to_bank(banks, bank, bank, source_id, put)
        elif op[0] == "remove":
            _, bank, alias_id = op
            for copy in banks.copies(bank):
                if copy.bank.remove_event(alias_id) > 0:
                    copy.modified = True
        else:
            _, source_bank, alias_id, source_id = op
            sidecar = banks.sidecars.get(lower(source_bank))
            if sidecar is None:
                sidecar = banks.sidecars[lower(source_bank)] = _Sidecar(source_bank, sidecar_path(source_bank))
            if not any(alias == alias_id for alias, _ in sidecar.events):
                sidecar.events.append((alias_id, source_id))

    tag_field = audio.find_field(PROP_TAG_EVENT_LIST)
    tag_values = tag_field.value.as_list() if tag_field is not None else None
    if tag_values is not None:
        tag_values[:] = [Value.string(tag) for tag in base_tags]
    if shared:
        # The units belong to other bins; the caller applies these there
        for index in sorted(edits):
            unit = context.shared_units[index]
            if unit.unit.events_bank:
                report.shared_edits.append(SharedUnitEdit(unit.owner, unit.unit.events_bank, edits[index]))
    else:
        bank_units = audio.find_field(PROP_BANK_UNITS)
        unit_values = bank_units.value.as_list() if bank_units is not None else None
        if unit_values is not None:
            apply_unit_edits(unit_values, [(index, units[index].events_bank, edits[index]) for index in sorted(edits)])
    return report


def _apply_to_bank(banks: AudioBanks, bank: str, source_bank: str, source_id: int,
                   apply: Callable[[_BankCopy, List[int]], None]) -> None:
    """Run *apply* on every copy of *bank*, handing it the source event's
    actions from the source copy with the same locale, or from the champion WAD
    copy. A locale copy never borrows another locale's actions."""
    sources: List[Tuple[Optional[str], List[int]]] = []
    for copy in banks.copies(source_bank):
        actions = copy.bank.event_actions(source_id)
        if actions is not None:
            sources.append((copy.locale, actions))
    for copy in banks.copies(bank):
        found = next((item for item in sources if item[0] == copy.locale), None) \
            or next((item for item in sources if item[0] is None), None)
        if found is not None:
            apply(copy, found[1])
