#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin sound banks
Fixes a skin package whose skin0.bin plays another skin's sounds, or no sound for events the game's bins name.

A skin package runs the skin as the champion's default one, and the game then plays the default skin's events
("Play_sfx_Yasuo_..."). So the package names its banks after the default skin (LTK Manager turns the overlay off for a
skin0 that names another skin), keeps only the default tag in skinAudioProperties.tagEventList, and ships the skin's
events bank with a copy of each skin event under the default event's name, those events being taken out of the
default skin's events bank.

Nightbringer Yasuo's package did that with Skin87's banks instead of its own (Skin09's): its spells played another
skin's sounds, and the events Skin87 has no copy of (its E's EQ hit...) played nothing (#462).

When a bank of the package names another skin that the game's own bin for the skin does not list, the bank unit that
holds it gets the game's banks of that kind (sfx or vo) for the skin, and its events, and the skin's events bank is
built the way the packages build theirs: from the game's copy, with the default skin's names added, and the default
skin's events bank without them. Banks the package ships itself for the skin (a *_basetag_events.bnk) stay. Risen
Legend Ahri and Kai'Sa's packages had the same fault.

The game plays an event named after one of the skin's tags (tagEventList) as the most specific tag's event it has:
Genesis Nightbringer Yasuo's E dash effect names "Play_sfx_YasuoSkin09_YasuoDashWrapper_cast", and the game plays
Skin87's dash for it. A package keeps only the default tag, so such a name is played as it is and nothing answers it:
the E made no sound. Each name of the game's bins (the skin's, its animations' and the bins they link) that is after a
tag the package dropped gets a copy of the event the game would take, in the bank that holds that event. A package
whose banks and events already answer every name is not touched.

A bin (PROP v3) is: links, the entries' class hashes, then the entries, each "u32 size, u32 key, u16 field count,
fields". A field is "u32 name hash, u8 type, value". Only the fields on the way to the bank units are read; any other
value is stepped over by its size. A Wwise bank is sections ("tag, u32 size, data"); its HIRC section is "u32 count",
then objects "u8 type, u32 size, u32 id, ...", an event being type 4.
"""

import re
import struct
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

import xxhash
import zstandard

from utils.core.logging import get_logger
from ..loadingname.loading_name import FORM_RECORDS, _read_entry, _wad_holds, _xxh64, champion_aliases

log = get_logger()


def _fnv1a(name: str) -> int:
    """How a bin names its classes and fields."""
    h = 0x811C9DC5
    for c in name.lower().encode("utf-8"):
        h = ((h ^ c) * 0x01000193) & 0xFFFFFFFF
    return h


def event_id(name: str) -> int:
    """How Wwise names an event (FNV-1 of the lowercase name)."""
    h = 0x811C9DC5
    for c in name.lower().encode("utf-8"):
        h = ((h * 0x01000193) & 0xFFFFFFFF) ^ c
    return h


SKIN_DATA_CLASS = _fnv1a("SkinCharacterDataProperties")
AUDIO_FIELD = _fnv1a("skinAudioProperties")
TAGS_FIELD = _fnv1a("tagEventList")
BANK_UNITS_FIELD = _fnv1a("bankUnits")
NAME_FIELD = _fnv1a("name")
BANK_PATH_FIELD = _fnv1a("bankPath")
EVENTS_FIELD = _fnv1a("events")

# A bank of a skin: .../Skins/Skin09/Yasuo_Skin09_SFX_events.bnk, of a kind (sfx or vo)
SKIN_OF_PATH = re.compile(r"/skins/skin(\d+)/", re.IGNORECASE)
KIND_OF_PATH = re.compile(r"/(sfx|vo)/", re.IGNORECASE)
# An event name the way bins write it ("Play_sfx_YasuoSkin09_YasuoDashWrapper_cast")
EVENT_NAME = re.compile(rb"[A-Za-z]+_(?:sfx|vo)_[A-Za-z0-9_]+", re.IGNORECASE)
# A word of a bin, that may name one of the champion's other characters ("NidaleeCougar")
WORD = re.compile(rb"[A-Za-z][A-Za-z0-9_]{2,47}")

# Bin value types: fixed sizes, then the ones that carry their own size
_FIXED = {0: 0, 1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 4, 7: 4, 8: 8, 9: 8, 10: 4, 11: 8, 12: 12, 13: 16, 14: 64, 15: 4,
          17: 4, 18: 8, 0x84: 4, 0x87: 1}
_STRING, _LIST, _LIST2, _POINTER, _EMBED, _OPTION, _MAP = 0x10, 0x80, 0x81, 0x82, 0x83, 0x85, 0x86

_WAD_HEADER = 272
_WAD_TOC_ENTRY = struct.Struct("<QIIIBBHQ")  # hash, offset, stored size, size, type | subchunks << 4, dup, first, xxh3

_HIRC_EVENT = 4


class BankUnit(NamedTuple):
    name: str
    paths: List[str]
    events: List[str]
    raw: bytes  # the whole embed: class, size, fields


class _Field(NamedTuple):
    name: int
    kind: int
    start: int  # where the value starts
    end: int


# --------------------------------------------------------------------------------------
# bins
# --------------------------------------------------------------------------------------

def _value_end(data: bytes, at: int, kind: int) -> int:
    if kind in _FIXED:
        return at + _FIXED[kind]
    if kind == _STRING:
        return at + 2 + struct.unpack_from("<H", data, at)[0]
    if kind in (_LIST, _LIST2):
        return at + 5 + struct.unpack_from("<I", data, at + 1)[0]
    if kind in (_POINTER, _EMBED):
        cls = struct.unpack_from("<I", data, at)[0]
        return at + 4 if cls == 0 else at + 8 + struct.unpack_from("<I", data, at + 4)[0]
    if kind == _MAP:
        return at + 6 + struct.unpack_from("<I", data, at + 2)[0]
    if kind == _OPTION:
        inner, count = data[at], data[at + 1]
        at += 2
        for _ in range(count):
            at = _value_end(data, at, inner)
        return at
    raise ValueError(f"unknown bin value type {kind:#x}")


def _fields(data: bytes, at: int, count: int, end: int) -> List[_Field]:
    out = []
    for _ in range(count):
        name, kind = struct.unpack_from("<IB", data, at)
        value_end = _value_end(data, at + 5, kind)
        out.append(_Field(name, kind, at + 5, value_end))
        at = value_end
    if at != end:
        raise ValueError("bin fields overrun their entry")
    return out


def _find(fields: Iterable[_Field], name: int, kind: int) -> Optional[_Field]:
    return next((f for f in fields if f.name == name and f.kind == kind), None)


def _embed_fields(data: bytes, value: _Field) -> List[_Field]:
    """The fields of an embedded object (class, size, u16 count, fields)."""
    return _fields(data, value.start + 10, struct.unpack_from("<H", data, value.start + 8)[0], value.end)


def _audio_field(data: bytes) -> Optional[Tuple[int, _Field]]:
    """(the entry's offset, its skinAudioProperties) in a skin bin, or None when it has none."""
    if data[:4] != b"PROP" or struct.unpack_from("<I", data, 4)[0] != 3:
        raise ValueError("not a PROP v3 bin")
    at = 8
    links = struct.unpack_from("<I", data, at)[0]
    at += 4
    for _ in range(links):
        at += 2 + struct.unpack_from("<H", data, at)[0]
    count = struct.unpack_from("<I", data, at)[0]
    classes = struct.unpack_from(f"<{count}I", data, at + 4)
    at += 4 + 4 * count
    for cls in classes:
        entry, size = at, struct.unpack_from("<I", data, at)[0]
        at = entry + 4 + size
        if cls != SKIN_DATA_CLASS:
            continue
        fields = _fields(data, entry + 10, struct.unpack_from("<H", data, entry + 8)[0], at)
        audio = _find(fields, AUDIO_FIELD, _EMBED)
        if not audio or struct.unpack_from("<I", data, audio.start)[0] == 0:
            return None
        return entry, audio
    return None


def _links(data: bytes) -> List[str]:
    """The bins a bin links (loaded with it)."""
    if data[:4] != b"PROP" or struct.unpack_from("<I", data, 4)[0] < 2:
        return []
    out, at = [], 12
    for _ in range(struct.unpack_from("<I", data, 8)[0]):
        out.append(_string_at(data, at))
        at += 2 + struct.unpack_from("<H", data, at)[0]
    return out


def _string_at(data: bytes, at: int) -> str:
    size = struct.unpack_from("<H", data, at)[0]
    return data[at + 2:at + 2 + size].decode("utf-8")


def _strings(data: bytes, value: Optional[_Field]) -> List[str]:
    """The strings of a list of strings."""
    if not value or data[value.start] != _STRING:
        return []
    out, at = [], value.start + 9
    for _ in range(struct.unpack_from("<I", data, value.start + 5)[0]):
        out.append(_string_at(data, at))
        at += 2 + struct.unpack_from("<H", data, at)[0]
    return out


def _string_list(items: Sequence[str]) -> bytes:
    body = b"".join(struct.pack("<H", len(e)) + e for e in (i.encode("utf-8") for i in items))
    return struct.pack("<BII", _STRING, 4 + len(body), len(items)) + body


def tag_events(data: bytes) -> List[str]:
    """A skin bin's skinAudioProperties.tagEventList."""
    found = _audio_field(data)
    return _strings(data, _find(_embed_fields(data, found[1]), TAGS_FIELD, _LIST)) if found else []


def _units_field(data: bytes) -> Optional[Tuple[int, _Field, _Field]]:
    found = _audio_field(data)
    if not found:
        return None
    entry, audio = found
    units = _find(_embed_fields(data, audio), BANK_UNITS_FIELD, _LIST2)
    return (entry, audio, units) if units and data[units.start] == _EMBED else None


def bank_units(data: bytes) -> List[BankUnit]:
    """The sound banks of a skin bin, in its order."""
    found = _units_field(data)
    if not found:
        return []
    units = found[2]
    at, out = units.start + 9, []
    for _ in range(struct.unpack_from("<I", data, units.start + 5)[0]):
        unit = _Field(0, _EMBED, at, _value_end(data, at, _EMBED))
        fields = _embed_fields(data, unit) if struct.unpack_from("<I", data, at)[0] else []
        name = _find(fields, NAME_FIELD, _STRING)
        out.append(BankUnit(
            _string_at(data, name.start) if name else "",
            _strings(data, _find(fields, BANK_PATH_FIELD, _LIST)),
            _strings(data, _find(fields, EVENTS_FIELD, _LIST)),
            data[unit.start:unit.end],
        ))
        at = unit.end
    return out


def _unit_with(unit: BankUnit, paths: Sequence[str], events: Sequence[str]) -> bytes:
    """The unit with these bank files and events (the fields it has; the others kept as they are)."""
    raw = unit.raw
    fields = _embed_fields(raw, _Field(0, _EMBED, 0, len(raw)))
    parts = []
    for f in fields:
        value = raw[f.start:f.end]
        if f.kind == _LIST and raw[f.start] == _STRING and f.name in (BANK_PATH_FIELD, EVENTS_FIELD):
            value = _string_list(paths if f.name == BANK_PATH_FIELD else events)
        parts.append(raw[f.start - 5:f.start] + value)
    body = struct.pack("<H", len(fields)) + b"".join(parts)
    return raw[:4] + struct.pack("<I", len(body)) + body


def _with_units(data: bytes, units: Sequence[bytes]) -> bytes:
    """*data* with its bank units replaced by *units* (whole embeds), and the sizes around them updated."""
    entry, audio, old = _units_field(data)
    items = b"".join(units)
    value = struct.pack("<BII", _EMBED, 4 + len(items), len(units)) + items
    grown = len(value) - (old.end - old.start)
    out = bytearray(data[:old.start] + value + data[old.end:])
    # the skinAudioProperties embed and the entry both hold the bank units
    struct.pack_into("<I", out, audio.start + 4, struct.unpack_from("<I", data, audio.start + 4)[0] + grown)
    struct.pack_into("<I", out, entry, struct.unpack_from("<I", data, entry)[0] + grown)
    return bytes(out)


def event_names(data: bytes) -> List[str]:
    """The event names a bin writes (each a string: its u16 length right before it)."""
    out = []
    for match in EVENT_NAME.finditer(data):
        if match.start() < 2:
            continue
        size = struct.unpack_from("<H", data, match.start() - 2)[0]
        if 0 < size <= len(match.group()):
            out.append(match.group()[:size].decode("ascii"))
    return out


# --------------------------------------------------------------------------------------
# Wwise banks
# --------------------------------------------------------------------------------------

def _bank_sections(bank: bytes) -> List[Tuple[bytes, bytes]]:
    out, at = [], 0
    while at < len(bank):
        tag, size = bank[at:at + 4], struct.unpack_from("<I", bank, at + 4)[0]
        out.append((tag, bank[at + 8:at + 8 + size]))
        at += 8 + size
    if at != len(bank):
        raise ValueError("bank sections overrun the file")
    return out


def _hirc_objects(section: bytes) -> List[Tuple[int, int, bytes]]:
    """(type, id, body after the id) of each object."""
    out, at = [], 4
    for _ in range(struct.unpack_from("<I", section, 0)[0]):
        kind, size = struct.unpack_from("<BI", section, at)
        out.append((kind, struct.unpack_from("<I", section, at + 5)[0], section[at + 9:at + 5 + size]))
        at += 5 + size
    if at != len(section):
        raise ValueError("bank objects overrun their section")
    return out


def _with_objects(bank: bytes, objects: Sequence[Tuple[int, int, bytes]]) -> bytes:
    body = struct.pack("<I", len(objects)) + b"".join(
        struct.pack("<BII", kind, 4 + len(rest), oid) + rest for kind, oid, rest in objects)
    sections = _bank_sections(bank)
    if not any(tag == b"HIRC" for tag, _ in sections):
        sections.append((b"HIRC", body))  # a bank without objects (an empty events bank)
    out = b""
    for tag, data in sections:
        data = body if tag == b"HIRC" else data
        out += tag + struct.pack("<I", len(data)) + data
    return out


def _objects(bank: bytes) -> List[Tuple[int, int, bytes]]:
    """The bank's objects (none for a bank without a HIRC section)."""
    hirc = next((data for tag, data in _bank_sections(bank) if tag == b"HIRC"), None)
    return _hirc_objects(hirc) if hirc is not None else []


def with_aliases(bank: bytes, aliases: Dict[int, int]) -> Tuple[bytes, List[int]]:
    """The events bank with a copy of each event of *aliases*' values under its key, when it does not have one yet.
    Returns the bank and the ids added."""
    objects = _objects(bank)
    events = {oid: rest for kind, oid, rest in objects if kind == _HIRC_EVENT}
    added = [alias for alias, source in aliases.items() if source in events and alias not in events]
    objects += [(_HIRC_EVENT, alias, events[aliases[alias]]) for alias in added]
    return _with_objects(bank, objects), added


def without_events(bank: bytes, ids: Iterable[int]) -> bytes:
    ids = set(ids)
    return _with_objects(bank, [o for o in _objects(bank) if not (o[0] == _HIRC_EVENT and o[1] in ids)])


# --------------------------------------------------------------------------------------
# wads
# --------------------------------------------------------------------------------------

def _wad_hashes(wad: Path) -> set:
    """The path hashes of a packed wad v3's entries (its table only is read)."""
    with open(wad, "rb") as handle:
        header = handle.read(_WAD_HEADER)
        if len(header) < _WAD_HEADER or header[:2] != b"RW" or header[2] != 3:
            return set()
        toc = handle.read(struct.unpack_from("<I", header, 268)[0] * _WAD_TOC_ENTRY.size)
    return {struct.unpack_from("<Q", toc, i)[0] for i in range(0, len(toc) - 31, _WAD_TOC_ENTRY.size)}


def write_wad_entries(wad: Path, contents: Dict[int, bytes]) -> None:
    """Rewrites a packed wad v3 with these entries replaced or added (zstd, with their xxh3 checksums), or writes
    a new one."""
    data = wad.read_bytes() if wad.is_file() else b"RW\x03\x04" + bytes(_WAD_HEADER - 4)  # a new wad
    if len(data) < _WAD_HEADER or data[:2] != b"RW" or data[2] != 3:
        raise ValueError(f"{wad.name}: not a wad v3")
    count = struct.unpack_from("<I", data, 268)[0]
    entries = {}
    for i in range(count):
        entry = _WAD_TOC_ENTRY.unpack_from(data, _WAD_HEADER + i * _WAD_TOC_ENTRY.size)
        entries[entry[0]] = ("old", entry)
    for path_hash, content in contents.items():
        entries[path_hash] = ("new", content)
    first_blob = _WAD_HEADER + len(entries) * _WAD_TOC_ENTRY.size
    toc, blobs, placed = bytearray(), bytearray(), {}
    for path_hash in sorted(entries):
        state, value = entries[path_hash]
        if state == "new":
            stored = zstandard.ZstdCompressor().compress(value)
            entry = (path_hash, first_blob + len(blobs), len(stored), len(value), 3, 0, 0,
                     xxhash.xxh3_64_intdigest(stored))
            blobs += stored
        else:
            # entries sharing their data (duplicates) keep sharing it
            key = (value[1], value[2])
            if key not in placed:
                placed[key] = first_blob + len(blobs)
                blobs += data[value[1]:value[1] + value[2]]
            entry = (value[0], placed[key]) + tuple(value[2:])
        toc += _WAD_TOC_ENTRY.pack(*entry)
    header = bytearray(data[:_WAD_HEADER])
    struct.pack_into("<I", header, 268, len(entries))
    temp = wad.with_name(wad.name + ".tmp")
    temp.write_bytes(bytes(header) + toc + blobs)
    temp.replace(wad)


# --------------------------------------------------------------------------------------
# what the injector calls
# --------------------------------------------------------------------------------------

def _skin_of(path: str) -> Optional[int]:
    match = SKIN_OF_PATH.search(path)
    return int(match.group(1)) if match else None


def _kind_of(path: str) -> Optional[str]:
    match = KIND_OF_PATH.search(path)
    return match.group(1).lower() if match else None


def _game_skin(game_wad: Path, alias: str, skin_ids: Iterable[int]) -> Optional[Tuple[int, bytes]]:
    """(skin number, the game's bin) of the first of *skin_ids* the game has a bin of."""
    for skin_id in skin_ids:
        if not skin_id or skin_id % 1000 == 0:
            continue
        number = skin_id % 1000
        found = _read_entry(game_wad, _xxh64(f"data/characters/{alias}/skins/skin{number}.bin".encode()))
        if found:
            return number, found
    return None


def _read_bank_from(path: str, mod_wad: Path, game_wads: Sequence[Path]) -> Tuple[Optional[bytes], str]:
    """A bank file and the name of the wad it is in: the package's copy when it ships one, the game's otherwise (a
    voice bank is in the language's wad, Yasuo.ko_KR.wad.client)."""
    path_hash = _xxh64(path.lower().encode("utf-8"))
    for wad in (mod_wad, *game_wads):
        found = _read_entry(wad, path_hash) if wad.is_file() else None
        if found:
            return found, wad.name
    return None, mod_wad.name


def _read_bank(path: str, mod_wad: Path, game_wads: Sequence[Path]) -> Optional[bytes]:
    """A bank file: the package's copy when it ships one, the game's otherwise."""
    return _read_bank_from(path, mod_wad, game_wads)[0]


def _repair_champion(game_dir: Path, mod_wad: Path, alias: str, skin_ids: Sequence[int]) -> bool:
    lower = alias.lower()
    champions = Path(game_dir) / "DATA" / "FINAL" / "Champions"
    game_wads = [champions / f"{alias}.wad.client", *sorted(champions.glob(f"{alias}.*.wad.client"))]
    skin0_hash = _xxh64(f"data/characters/{lower}/skins/skin0.bin".encode())
    skin0 = _read_entry(mod_wad, skin0_hash)
    if not skin0:
        return False
    units = bank_units(skin0)
    default_tags = tag_events(skin0)

    def ships(path: str) -> bool:
        return bool(_wad_holds(mod_wad, {_xxh64(path.lower().encode("utf-8"))}))

    def is_default(path: str) -> bool:
        return "/skins/base/" in path.lower()

    game = _game_skin(game_wads[0], lower, skin_ids)
    if not game:
        return False
    number, game_bin = game
    game_units = bank_units(game_bin)
    game_paths = {p.lower() for u in game_units for p in u.paths}

    paths = [list(u.paths) for u in units]
    events = [list(u.events) for u in units]
    written: Dict[int, bytes] = {}
    # the package's wad each written file goes to: the one named like the wad it was read from, as the game reads a
    # file from the wad it has it in (a voice bank from the language's wad)
    wad_of: Dict[int, str] = {}
    fixes = []

    def read(path: str) -> Optional[bytes]:
        h = _xxh64(path.lower().encode("utf-8"))
        if h in written:
            return written[h]
        bank, wad_name = _read_bank_from(path, mod_wad, game_wads)
        wad_of.setdefault(h, wad_name)
        return bank

    def write(path: str, bank: bytes) -> None:
        h = _xxh64(path.lower().encode("utf-8"))
        if h not in wad_of:
            read(path)
        written[h] = bank

    def answered() -> Dict[int, str]:
        """The events the package's banks answer, with the bank answering each."""
        holders: Dict[int, str] = {}
        for path in dict.fromkeys(p for unit_paths in paths for p in unit_paths):
            if path.lower().endswith("_events.bnk"):
                bank = read(path)
                for t, oid, _ in _objects(bank) if bank else []:
                    if t == _HIRC_EVENT:
                        holders.setdefault(oid, path)
        return holders

    # A. The banks of another skin the game does not load for this one, by the kind of sound they hold (a file the
    # package ships itself, as a *_basetag_events.bnk, is its own): the unit gets the game's banks of that kind,
    # and the skin's events bank its events under the default skin's names
    wrong_kinds = set()
    for unit in units:
        for path in unit.paths:
            skin = _skin_of(path)
            if (skin is not None and skin != number and path.lower() not in game_paths and _kind_of(path)
                    and not ships(path)):
                wrong_kinds.add(_kind_of(path))
    if wrong_kinds:
        skin_tags = [t for t in tag_events(game_bin) if t not in default_tags]
        names = event_names(game_bin)
        animations = _read_entry(game_wads[0], _xxh64(f"data/characters/{lower}/animations/skin{number}.bin".encode()))
        if animations:
            names += event_names(animations)
        done_kinds = set()
        for i, unit in enumerate(units):
            unit_kinds = {_kind_of(p) for p in unit.paths} & wrong_kinds
            if not unit_kinds:
                continue
            kind = sorted(unit_kinds)[0]
            # the game's banks of that kind for the skin, then what the package ships for it itself
            game_kind = [u for u in game_units if any(_kind_of(p) == kind for p in u.paths)]
            new_paths = list(dict.fromkeys(p for u in game_kind for p in u.paths))
            new_paths += [p for p in unit.paths if p.lower() not in {q.lower() for q in new_paths}
                          and (_skin_of(p) in (None, number) or p.lower() in game_paths) and ships(p)]
            new_events = list(dict.fromkeys(e for u in game_kind for e in u.events))
            if default_tags and kind not in done_kinds:
                aliases, alias_names = {}, {}
                for name in dict.fromkeys(names + new_events):
                    for tag in skin_tags:
                        if f"_{tag}_" in name:
                            alias_name = name.replace(f"_{tag}_", f"_{default_tags[0]}_")
                            aliases[event_id(alias_name)] = event_id(name)
                            alias_names[event_id(alias_name)] = alias_name
                added = []
                for path in new_paths:
                    if path.lower().endswith("_events.bnk") and not is_default(path):
                        bank = read(path)
                        if bank:
                            bank, new_ids = with_aliases(bank, aliases)
                            write(path, bank)
                            added += new_ids
                # the default skin's events of those names would come first and be the ones played
                for path in new_paths:
                    if path.lower().endswith("_events.bnk") and is_default(path) and added:
                        bank = read(path)
                        if bank:
                            write(path, without_events(bank, added))
                new_events = list(dict.fromkeys(new_events + [alias_names[i] for i in added]))
                done_kinds.add(kind)
            fixes.append(f"its {kind} banks were another skin's, now skin {number}'s: "
                         + ", ".join(Path(p).name for p in new_paths if p not in unit.paths))
            paths[i], events[i] = new_paths, new_events

    # B. Banks the game loads for the skin that the package leaves out, of a kind of sound it has: Nightbringer
    # Yasuo's default voice lines (the default skin's voice bank), DJ Sona's dance, death and laugh (Skin06's sound
    # effects). They join the package's unit of that kind, without the events the package's banks already answer,
    # which are the ones it plays.
    kinds = {_kind_of(p) for unit_paths in paths for p in unit_paths} - {None}
    for kind in sorted(kinds):
        have = {p.lower() for unit_paths in paths for p in unit_paths}
        missing_units = [u for u in game_units
                         if any(_kind_of(p) == kind and p.lower() not in have for p in u.paths)]
        missing = list(dict.fromkeys(p for u in missing_units for p in u.paths if p.lower() not in have))
        holders = [i for i, unit_paths in enumerate(paths) if any(_kind_of(p) == kind for p in unit_paths)]
        if not missing or not holders:
            continue
        played = set(answered())
        for path in missing:
            if path.lower().endswith("_events.bnk"):
                bank = read(path)
                if bank:
                    write(path, without_events(bank, played))
        i = holders[-1]
        paths[i] = [p for p in missing if is_default(p)] + paths[i] + [p for p in missing if not is_default(p)]
        events[i] = list(dict.fromkeys(events[i] + [e for u in missing_units for e in u.events]))
        fixes.append(f"the {kind} banks the game loads for skin {number} were left out: "
                     + ", ".join(Path(p).name for p in missing))

    # C. The game's bins name some events after a tag the package dropped: Genesis Nightbringer Yasuo's E dash
    # effect plays "Play_sfx_YasuoSkin09_YasuoDashWrapper_cast", which the game plays as the skin's own
    # ("YasuoSkin09" is in its tagEventList). With the default tag only, the name is played as it is and nothing
    # answers it. Each such name gets the event the game would take, the most specific of its tags first. The
    # champion's other characters the package carries (Nidalee's cougar, Elise's spider...) have tags of their own
    # (NidaleeCougarSkin48) and play the champion's banks: they get the same.
    def bins_of(character: str, character_bin: bytes) -> List[bytes]:
        """A character's skin bin, its animations' and the bins they link (but the character's root record)."""
        out, todo, seen_bins = [], [character_bin], set()
        animations = _read_entry(
            game_wads[0], _xxh64(f"data/characters/{character}/animations/skin{number}.bin".encode()))
        if animations:
            todo.append(animations)
        while todo:
            data = todo.pop()
            out.append(data)
            for link in _links(data):
                if link.lower() not in seen_bins and link.lower() != f"data/characters/{character}/{character}.bin":
                    seen_bins.add(link.lower())
                    linked = _read_entry(game_wads[0], _xxh64(link.lower().encode("utf-8")))
                    if linked:
                        todo.append(linked)
        return out

    characters = [(lower, game_bin, default_tags)]
    # the champion's other characters: the words of its bins and its record (they name them, "NidaleeCougar",
    # "AnnieTibbers") and the forms the loading screen name knows, the ones the package has a skin0.bin for
    record = _read_entry(game_wads[0], _xxh64(f"data/characters/{lower}/{lower}.bin".encode())) or b""
    words = {w.decode("ascii").lower() for data in [record, *bins_of(lower, game_bin)] for w in WORD.findall(data)}
    words |= set(FORM_RECORDS.get(lower, ()))
    carried_hashes = _wad_hashes(mod_wad)
    others = sorted(w for w in words - {lower}
                    if _xxh64(f"data/characters/{w}/skins/skin0.bin".encode()) in carried_hashes)
    for other in others:
        carried = _read_entry(mod_wad, _xxh64(f"data/characters/{other}/skins/skin0.bin".encode()))
        its_game_bin = _read_entry(game_wads[0], _xxh64(f"data/characters/{other}/skins/skin{number}.bin".encode()))
        if carried and its_game_bin:
            characters.append((other, its_game_bin, tag_events(carried)))

    added_names = []
    for character, character_bin, package_tags in characters:
        game_tags = tag_events(character_bin)
        if not package_tags or not [t for t in game_tags if t not in package_tags]:
            continue
        names = [n for data in bins_of(character, character_bin) for n in event_names(data)]
        holders = answered()
        aliases_by_bank: Dict[str, Dict[int, int]] = {}
        alias_names: Dict[int, str] = {}
        for name in dict.fromkeys(names):
            if event_id(name) in holders:
                continue
            # a name after any of the skin's tags: a dropped one, or the default one the package's copies of the
            # skin's events missed (Arcane Councilor Mel's "Play_sfx_Mel_Dance3D_leadin" is MelSkin01's in the game)
            tag = max((t for t in game_tags if f"_{t}_" in name), key=len, default=None)
            if not tag:
                continue
            for candidate_tag in reversed(game_tags):
                candidate = name.replace(f"_{tag}_", f"_{candidate_tag}_", 1)
                if event_id(candidate) in holders:
                    aliases_by_bank.setdefault(holders[event_id(candidate)], {})[event_id(name)] = event_id(candidate)
                    alias_names[event_id(name)] = name
                    break
        for path, aliases in aliases_by_bank.items():
            bank, added = with_aliases(read(path), aliases)
            if added:
                write(path, bank)
                added_names += [alias_names[i] for i in added]
                i = next(i for i, unit_paths in enumerate(paths) if path in unit_paths)
                events[i] = list(dict.fromkeys(events[i] + [alias_names[a] for a in added]))
    if added_names:
        fixes.append(f"{len(added_names)} event(s) named after a dropped tag now play the skin's sound "
                     f"({', '.join(sorted(added_names)[:3])}...)")

    if not fixes:
        return False
    new_units = [_unit_with(unit, paths[i], events[i]) if (paths[i], events[i]) != (unit.paths, unit.events)
                 else unit.raw for i, unit in enumerate(units)]
    written[skin0_hash] = _with_units(skin0, new_units)
    wad_of[skin0_hash] = mod_wad.name
    for wad_name in dict.fromkeys(wad_of[h] for h in written):
        write_wad_entries(mod_wad.with_name(wad_name), {h: b for h, b in written.items() if wad_of[h] == wad_name})
    log.info(f"[SKINAUDIO] {alias} skin {number}: " + "; ".join(fixes))
    return True


def repair(game_dir: Optional[Path], mod_folder: Path, skin_ids: Iterable[int]) -> List[str]:
    """Repairs the sound banks of the skin's skin0.bin from the game's own bin for the skin (see the module's note).
    Returns the champions repaired.

    *skin_ids* are the client's ids of the skin or chroma. A skin the game has no bin of (a form Rose builds, as DJ
    Sona's genres, numbered 998 and 999) is left as it is: its skin's bin does not describe it. It never fails
    the injection: a skin it cannot read is injected as it is.
    """
    repaired = []
    if not game_dir:
        return repaired
    skin_ids = list(skin_ids)
    for alias in champion_aliases(mod_folder):
        mod_wad = Path(mod_folder) / "WAD" / f"{alias}.wad.client"
        if not mod_wad.is_file():
            continue
        try:
            if _repair_champion(Path(game_dir), mod_wad, alias, skin_ids):
                repaired.append(alias)
        except Exception as e:
            # sounds are fixed when they can be: an injection must never fail because of it
            log.warning(f"[SKINAUDIO] {alias}: skipped: {e}")
    return repaired
