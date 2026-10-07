#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Loading screen name
Builds a mod that makes the loading screen print the injected skin's name instead of the champion's.

The loading screen is drawn by the game, which asks its text table for
"game_character_skin_displayname_<Champion>_<n>" when the server says the player is on skin n, and for the champion's
own name when it says 0. An injected skin always runs as skin 0, so the screen prints the champion's name.

The skin's name is already in the player's game, translated, for every skin: this copies the table the game has
installed, writes the skin's text over the champion's, and leaves the copy in the mods directory as one more mod. The
language and the patch are therefore always the player's own, and nothing has to be downloaded or shipped.

The mod is a loose file, RAW/DATA/Menu/en_US/lol.stringtable (the folder is en_US in every language: the language is
in the name of the game's wad, not in the path inside it). mod-tools resolves that path by its hash and packs it into
whichever Global.<locale>.wad.client the player has.

The champion's text is also what the chat ("Player (Champion): ...") and the name over the champion's head print, and
those should keep the champion's name. They read the key the champion's own record names
("Characters/<Champion>/CharacterRecords/Root", field name), while the loading screen builds its key from the champion's
internal name. So the mod also carries the champion's record pointing at a key of its own, of the same length, that
holds the champion's name: RAW/data/characters/<champion>/<champion>.bin.
"""

import json
import re
import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from utils.core.logging import get_logger

log = get_logger()

MOD_FOLDER = "ROSE-LoadingName"
TABLE_PATH = Path("RAW") / "DATA" / "Menu" / "en_US" / "lol.stringtable"
TABLE_HASH = 0x062D6ED714BFF7DF  # xxh64("data/menu/en_us/lol.stringtable"), fixed for every language
RST_MASK = (1 << 38) - 1
# The champion's record points here instead, for the chat and the name over its head. "rose" is as long as "game",
# so the record's text keeps its length and the file keeps its layout.
RECORD_KEY = "game_character_displayname_"
RECORD_KEY_OWN = "rose_character_displayname_"


# --------------------------------------------------------------------------------------
# the game's files
# --------------------------------------------------------------------------------------

def _language_wads(game_dir: Path) -> List[Path]:
    localized = Path(game_dir) / "DATA" / "FINAL" / "Localized"
    return sorted(localized.glob("Global.*.wad.client")) if localized.is_dir() else []


def _read_entry(wad: Path, path_hash: int) -> Optional[bytes]:
    """One entry of a wad, decompressed."""
    data = wad.read_bytes()
    if len(data) < 272 or data[:2] != b"RW" or data[2] != 3:
        log.warning(f"[LOADNAME] {wad.name}: not a wad v3")
        return None
    count = struct.unpack_from("<I", data, 268)[0]
    for i in range(count):
        at = 272 + i * 32
        entry_hash, offset, packed, size = struct.unpack_from("<QIII", data, at)
        if entry_hash != path_hash:
            continue
        kind = data[at + 20] & 0xF
        if kind == 0:
            return data[offset:offset + size]
        if kind in (3, 4):
            return _unzstd(data[offset:offset + packed], size, single_frame=kind == 3)
        log.warning(f"[LOADNAME] {wad.name}: entry {path_hash:016x} is stored as type {kind}")
        return None
    return None


def _read_table(wad: Path) -> Optional[bytes]:
    """The lol.stringtable entry of a wad, decompressed."""
    return _read_entry(wad, TABLE_HASH)


def _record_path(alias: str) -> str:
    return f"data/characters/{alias}/{alias}.bin".lower()


def _champion_record(game_dir: Path, mod_folder: Path, alias: str) -> Optional[bytes]:
    """The champion's own bin: the skin's copy when it carries one, the game's otherwise."""
    game_path = _record_path(alias)
    path_hash = _xxh64(game_path.encode("utf-8"))
    carried = Path(mod_folder) / "WAD" / f"{alias}.wad.client"
    if carried.is_file():
        found = _read_entry(carried, path_hash)
        if found:
            return found
    elif carried.is_dir():
        for loose in (carried / game_path, carried / f"{path_hash:016x}.bin"):
            if loose.is_file():
                return loose.read_bytes()
    installed = Path(game_dir) / "DATA" / "FINAL" / "Champions" / f"{alias}.wad.client"
    return _read_entry(installed, path_hash) if installed.is_file() else None


def _with_own_record_key(record: bytes, alias: str) -> Optional[bytes]:
    """The champion's bin with its name key renamed to ours, or None when it has none."""
    key = (RECORD_KEY + alias).encode("utf-8")
    # a bin string is its u16 length and its bytes
    pattern = re.compile(b"(?-i:" + re.escape(struct.pack("<H", len(key))) + b")" + re.escape(key), re.IGNORECASE)
    own = RECORD_KEY_OWN.encode("utf-8")
    patched, found = pattern.subn(lambda m: m.group(0)[:2] + own + m.group(0)[2 + len(own):], record)
    return patched if found else None


def _unzstd(chunk: bytes, size: int, single_frame: bool) -> Optional[bytes]:
    """Decompresses a wad entry: the standard library from Python 3.14 on, zstandard before that."""
    try:
        from compression.zstd import decompress   # Python 3.14+, reads frames one after the other
        return decompress(chunk)
    except ImportError:
        pass
    try:
        import zstandard
    except ImportError:
        log.warning("[LOADNAME] zstandard is not installed, the loading screen name is skipped")
        return None
    if single_frame:
        return zstandard.ZstdDecompressor().decompress(chunk, max_output_size=size)
    import io
    # type 4 is the same stream cut into frames, so they are read one after the other
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(chunk), read_across_frames=True) as reader:
        return reader.read(size)


# --------------------------------------------------------------------------------------
# RST v5: "RST", 5, u32 count, count x u64 (38-bit key hash | offset << 38), then the texts
# --------------------------------------------------------------------------------------

def _entries(table: bytes) -> Tuple[int, int]:
    count = struct.unpack_from("<I", table, 4)[0]
    return count, 8 + count * 8


def _text_of(table: bytes, key_hash: int) -> Optional[str]:
    count, text_start = _entries(table)
    for i in range(count):
        entry = struct.unpack_from("<Q", table, 8 + i * 8)[0]
        if entry & RST_MASK != key_hash:
            continue
        at = text_start + (entry >> 38)
        end = table.index(b"\0", at)
        return table[at:end].decode("utf-8", "replace")
    return None


def _with_text(table: bytes, key_hash: int, text: str) -> bytes:
    """The table again, with this key's text replaced.

    The offsets are counted from the start of the text block, which is copied whole, so appending one text leaves
    every other offset where it was.
    """
    count, text_start = _entries(table)
    entries = [struct.unpack_from("<Q", table, 8 + i * 8)[0] for i in range(count)]
    added = text.encode("utf-8") + b"\0"
    entry = key_hash | ((len(table) - text_start) << 38)

    for i, existing in enumerate(entries):
        if existing & RST_MASK == key_hash:
            entries[i] = entry
            break
    else:
        entries.append(entry)
        entries.sort(key=lambda e: e & RST_MASK)

    out = bytearray(table[:4])
    out += struct.pack("<I", len(entries))
    for e in entries:
        out += struct.pack("<Q", e)
    out += table[text_start:]
    out += added
    return bytes(out)


# --------------------------------------------------------------------------------------
# XXH3-64 (seed 0, default secret), for inputs of 17 to 128 bytes: every key this module hashes
# --------------------------------------------------------------------------------------

_SECRET = bytes.fromhex(
    "b8fe6c3923a44bbe7c01812cf721ad1cded46de9839097db7240a4a4b7b3671f"
    "cb79e64eccc0e578825ad07dccff7221b8084674f743248ee03590e6813a264c"
    "3c2852bb91c300cb88d0658b1b532ea371644897a20df94e3819ef46a9deacd8"
    "a8fa763fe39c343ff9dcbbc7c70b4f1d8a51e04bcdb45931c89f7ec9d9787364"
)
_U64 = (1 << 64) - 1


def _u64(v: int) -> int:
    return v & _U64


def _read64(data: bytes, at: int) -> int:
    return struct.unpack_from("<Q", data, at)[0]


def _mul_fold(a: int, b: int) -> int:
    product = a * b
    return _u64(product) ^ (product >> 64)


def _mix16(data: bytes, at: int, secret_at: int) -> int:
    return _mul_fold(_read64(data, at) ^ _read64(_SECRET, secret_at),
                     _read64(data, at + 8) ^ _read64(_SECRET, secret_at + 8))


def _xxh3_64(data: bytes) -> int:
    size = len(data)
    if not 17 <= size <= 128:
        raise ValueError("xxh3: only 17 to 128 bytes are supported here")
    acc = _u64(size * 0x9E3779B185EBCA87)
    if size > 32:
        if size > 64:
            if size > 96:
                acc += _mix16(data, 48, 96) + _mix16(data, size - 64, 112)
            acc += _mix16(data, 32, 64) + _mix16(data, size - 48, 80)
        acc += _mix16(data, 16, 32) + _mix16(data, size - 32, 48)
    acc = _u64(acc + _mix16(data, 0, 0) + _mix16(data, size - 16, 16))
    acc ^= acc >> 37
    acc = _u64(acc * 0x165667919E3779F9)
    return acc ^ (acc >> 32)


def _key_hash(key: str) -> int:
    return _xxh3_64(key.lower().encode("utf-8")) & RST_MASK


# --------------------------------------------------------------------------------------
# XXH64 (seed 0): how a wad names its entries by path
# --------------------------------------------------------------------------------------

_P1, _P2, _P3 = 0x9E3779B185EBCA87, 0xC2B2AE3D27D4EB4F, 0x165667B19E3779F9
_P4, _P5 = 0x85EBCA77C2B2AE63, 0x27D4EB2F165667C5


def _rotl(v: int, r: int) -> int:
    return _u64((v << r) | (v >> (64 - r)))


def _round(acc: int, lane: int) -> int:
    return _u64(_rotl(_u64(acc + lane * _P2), 31) * _P1)


def _xxh64(data: bytes) -> int:
    size, at = len(data), 0
    if size >= 32:
        v = [_u64(_P1 + _P2), _P2, 0, _u64(-_P1)]
        while at + 32 <= size:
            v = [_round(v[k], _read64(data, at + 8 * k)) for k in range(4)]
            at += 32
        acc = _u64(_rotl(v[0], 1) + _rotl(v[1], 7) + _rotl(v[2], 12) + _rotl(v[3], 18))
        for lane in v:
            acc = _u64((acc ^ _round(0, lane)) * _P1 + _P4)
    else:
        acc = _P5
    acc = _u64(acc + size)
    while at + 8 <= size:
        acc = _u64(_rotl(acc ^ _round(0, _read64(data, at)), 27) * _P1 + _P4)
        at += 8
    if at + 4 <= size:
        acc = _u64(_rotl(acc ^ _u64(struct.unpack_from("<I", data, at)[0] * _P1), 23) * _P2 + _P3)
        at += 4
    while at < size:
        acc = _u64(_rotl(acc ^ _u64(data[at] * _P5), 11) * _P1)
        at += 1
    acc = _u64((acc ^ (acc >> 33)) * _P2)
    acc = _u64((acc ^ (acc >> 29)) * _P3)
    return acc ^ (acc >> 32)


# --------------------------------------------------------------------------------------
# what the injector calls
# --------------------------------------------------------------------------------------

def champion_aliases(mod_folder: Path) -> List[str]:
    """The champions a mod carries files for, from the names of its wads (Zed.wad.client -> Zed)."""
    wad_dir = Path(mod_folder) / "WAD"
    if not wad_dir.is_dir():
        return []
    aliases = []
    for wad in wad_dir.iterdir():
        name = wad.name
        if not name.lower().endswith(".wad.client"):
            continue
        alias = name[: -len(".wad.client")].split(".")[0]
        if alias.lower() != "global" and alias not in aliases:
            aliases.append(alias)
    return aliases


def parse_skin_id(skin_name: str, champion_id: Optional[int] = None) -> int:
    """The client's skin id out of the name the injector was given ("Shockblade Zed 238001" -> 238001).

    Skin names end in a number of their own ("Worlds 2016"), so with a champion known the id has to belong to it.
    """
    for token in reversed(str(skin_name or "").replace("_", " ").split()):
        if not token.isdigit():
            continue
        value = int(token)
        if value < 1000:
            continue
        if champion_id and value // 1000 != int(champion_id):
            continue
        return value
    return 0


def build(game_dir: Path, mods_dir: Path, mod_folder: Path, skin_id: int) -> Optional[str]:
    """Writes the mod and returns its folder name, or None when there is nothing to show.

    skin_id is the client's id (champion id * 1000 + skin number); chromas pass their base skin's id.
    """
    try:
        if not skin_id or skin_id % 1000 == 0:
            return None
        aliases = champion_aliases(mod_folder)
        if not aliases:
            log.debug("[LOADNAME] the skin carries no champion wad, skipped")
            return None

        wads = _language_wads(Path(game_dir))
        if not wads:
            log.debug("[LOADNAME] no language wad in the game folder, skipped")
            return None

        for wad in wads:
            table = _read_table(wad)
            if not table or table[:3] != b"RST" or table[3] != 5:
                continue
            for alias in aliases:
                name = _text_of(table, _key_hash(f"game_character_skin_displayname_{alias}_{skin_id % 1000}"))
                if not name:
                    continue
                champion_key = _key_hash(f"{RECORD_KEY}{alias}")
                champion_name = _text_of(table, champion_key)
                if champion_name is None:
                    continue
                target = Path(mods_dir) / MOD_FOLDER
                (target / TABLE_PATH.parent).mkdir(parents=True, exist_ok=True)
                (target / "META").mkdir(parents=True, exist_ok=True)
                (target / "META" / "info.json").write_text(json.dumps({
                    "Author": "Rose",
                    "Description": name,
                    "Name": "Loading screen name",
                    "Version": "1.0.0",
                }), encoding="utf-8")
                table = _with_text(table, champion_key, name)

                # the chat and the name over the head keep the champion's name (see the module's note)
                record = _champion_record(game_dir, mod_folder, alias)
                own_record = _with_own_record_key(record, alias) if record else None
                if own_record:
                    table = _with_text(table, _key_hash(f"{RECORD_KEY_OWN}{alias}"), champion_name)
                    record_file = target / "RAW" / _record_path(alias)
                    record_file.parent.mkdir(parents=True, exist_ok=True)
                    record_file.write_bytes(own_record)
                else:
                    log.debug(f"[LOADNAME] {alias}'s record not found, the chat shows the skin's name too")

                (target / TABLE_PATH).write_bytes(table)
                log.info(f"[LOADNAME] the loading screen will show '{name}'")
                return MOD_FOLDER
        log.debug(f"[LOADNAME] the game has no name for skin {skin_id}, skipped")
        return None
    except Exception as e:
        # a name is a nicety: an injection must never fail because of it
        log.warning(f"[LOADNAME] skipped: {e}")
        return None
