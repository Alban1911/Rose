#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PROP (.bin) files: read and edit one entry, keep every other byte.

A skin's bin is hundreds of KB (particles, animations...), but the base-skin
steps only touch its SkinCharacterDataProperties entry. A Bin finds the entries
by their sizes without reading them, parses the one asked for, and writes the
file back with the other entries copied as they were, so an entry nobody
changed is byte for byte the mod's own.

Naming follows the file: an entry's *type hash* is listed in the header
(SkinCharacterDataProperties...), its *path hash* opens the entry
(Characters/Ezreal/Skins/Skin0).

Fixed-size values stay raw bytes (floats keep their exact bits); strings are
text; lists, structs, options and maps are read down to their values.
"""

from __future__ import annotations

import struct
from typing import Dict, List, Optional, Tuple

# Value types
NONE, BOOL, I8, U8, I16, U16, I32, U32, I64, U64, F32, VEC2, VEC3, VEC4, MTX44, RGBA = range(16)
STRING, HASH, FILE = 0x10, 0x11, 0x12
LIST, LIST2, POINTER, EMBED, LINK, OPTION, MAP, FLAG = range(0x80, 0x88)

_FIXED_SIZES: Dict[int, int] = {
    BOOL: 1, I8: 1, U8: 1, I16: 2, U16: 2, I32: 4, U32: 4, I64: 8, U64: 8, F32: 4,
    VEC2: 8, VEC3: 12, VEC4: 16, MTX44: 64, RGBA: 4, HASH: 4, FILE: 8, LINK: 4, FLAG: 1,
}
_KNOWN_TYPES = set(_FIXED_SIZES) | {NONE, STRING, LIST, LIST2, POINTER, EMBED, OPTION, MAP}

# StaticMaterialDef.name is tagged HASH but holds 8 bytes: without this the
# reader loses its place in the rest of the entry
STATIC_MATERIAL_DEF = 0xFF9D3409
STATIC_MATERIAL_DEF_NAME = 0x8D39BDE6


class PropError(ValueError):
    """The bytes are not a PROP file this module can read."""


def fnv1a_lower(text: str) -> int:
    """The 32-bit FNV-1a hash of the lowercased text (bin type, field and path names)."""
    value = 0x811C9DC5
    for byte in text.encode("utf-8").lower():
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return value


class Value:
    """A typed value. *v* is raw bytes for a fixed-size type, text for a
    STRING, a list for LIST/LIST2, an Embed (or None) for POINTER/EMBED, a
    Value (or None) for OPTION and (key, value) pairs for MAP. *elem* is the
    element (or key) type and *aux* the map's value type."""

    __slots__ = ("ty", "v", "elem", "aux")

    def __init__(self, ty: int, v=None, elem: int = 0, aux: int = 0) -> None:
        self.ty = ty
        self.v = v
        self.elem = elem
        self.aux = aux

    @staticmethod
    def string(text: str) -> "Value":
        return Value(STRING, text)

    def as_string(self) -> Optional[str]:
        return self.v if self.ty == STRING else None

    def as_embed(self) -> Optional["Embed"]:
        return self.v if self.ty in (POINTER, EMBED) else None

    def as_list(self) -> Optional[list]:
        return self.v if self.ty in (LIST, LIST2) else None


class Field:
    __slots__ = ("name_hash", "value")

    def __init__(self, name_hash: int, value: Value) -> None:
        self.name_hash = name_hash
        self.value = value


class Struct:
    """Fields by name hash: what an entry and an embedded struct share."""

    __slots__ = ("fields",)

    def __init__(self, fields: List[Field]) -> None:
        self.fields = fields

    def find_field(self, name_hash: int) -> Optional[Field]:
        for field in self.fields:
            if field.name_hash == name_hash:
                return field
        return None

    def set_field(self, name_hash: int, value: Value) -> None:
        field = self.find_field(name_hash)
        if field is not None:
            field.value = value
        else:
            self.fields.append(Field(name_hash, value))


class Embed(Struct):
    __slots__ = ("name_hash",)

    def __init__(self, name_hash: int, fields: List[Field]) -> None:
        super().__init__(fields)
        self.name_hash = name_hash


class Entry(Struct):
    __slots__ = ("type_hash", "path_hash")

    def __init__(self, type_hash: int, path_hash: int, fields: List[Field]) -> None:
        super().__init__(fields)
        self.type_hash = type_hash
        self.path_hash = path_hash


# --------------------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------------------

class _Reader:
    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos

    def take(self, count: int) -> bytes:
        end = self.pos + count
        if end > len(self.data):
            raise PropError(f"unexpected end of data at {self.pos} (need {count})")
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def string(self) -> str:
        return self.take(self.u16()).decode("utf-8", "surrogateescape")

    def type_tag(self) -> int:
        tag = self.u8()
        if tag not in _KNOWN_TYPES:
            raise PropError(f"unknown value type 0x{tag:02x}")
        return tag

    def field(self, owner: int) -> Field:
        name_hash = self.u32()
        ty = self.type_tag()
        if ty == HASH and owner == STATIC_MATERIAL_DEF and name_hash == STATIC_MATERIAL_DEF_NAME:
            return Field(name_hash, Value(HASH, self.take(8)))
        return Field(name_hash, self.value(ty))

    def fields(self, owner: int) -> List[Field]:
        return [self.field(owner) for _ in range(self.u16())]

    def value(self, ty: int) -> Value:
        size = _FIXED_SIZES.get(ty)
        if size is not None:
            return Value(ty, self.take(size))
        if ty == STRING:
            return Value(STRING, self.string())
        if ty == NONE:
            return Value(NONE)
        if ty in (LIST, LIST2):
            elem = self.type_tag()
            self.u32()  # size
            count = self.u32()
            return Value(ty, [self.value(elem) for _ in range(count)], elem)
        if ty in (POINTER, EMBED):
            name_hash = self.u32()
            if name_hash == 0:
                return Value(ty, None)
            self.u32()  # size
            return Value(ty, Embed(name_hash, self.fields(name_hash)))
        if ty == OPTION:
            elem = self.type_tag()
            present = self.u8() != 0
            return Value(OPTION, self.value(elem) if present else None, elem)
        if ty == MAP:
            key_ty = self.type_tag()
            value_ty = self.type_tag()
            self.u32()  # size
            count = self.u32()
            pairs = [(self.value(key_ty), self.value(value_ty)) for _ in range(count)]
            return Value(MAP, pairs, key_ty, value_ty)
        raise PropError(f"unreadable value type 0x{ty:02x}")  # pragma: no cover - type_tag filters these


# --------------------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------------------

def _write_string(out: bytearray, text: str) -> None:
    raw = text.encode("utf-8", "surrogateescape")
    out += struct.pack("<H", len(raw))
    out += raw


def _write_fields(out: bytearray, fields: List[Field]) -> None:
    out += struct.pack("<H", len(fields))
    for field in fields:
        out += struct.pack("<IB", field.name_hash, field.value.ty)
        _write_value(out, field.value)


def _write_value(out: bytearray, value: Value) -> None:
    ty = value.ty
    if ty in _FIXED_SIZES:
        out += value.v
    elif ty == STRING:
        _write_string(out, value.v)
    elif ty in (LIST, LIST2):
        body = bytearray(struct.pack("<I", len(value.v)))
        for item in value.v:
            _write_value(body, item)
        out += struct.pack("<BI", value.elem, len(body))
        out += body
    elif ty in (POINTER, EMBED):
        embed = value.v
        if embed is None:
            out += struct.pack("<I", 0)
            return
        body = bytearray()
        _write_fields(body, embed.fields)
        out += struct.pack("<II", embed.name_hash, len(body))
        out += body
    elif ty == OPTION:
        out += struct.pack("<BB", value.elem, 0 if value.v is None else 1)
        if value.v is not None:
            _write_value(out, value.v)
    elif ty == MAP:
        body = bytearray(struct.pack("<I", len(value.v)))
        for key, item in value.v:
            _write_value(body, key)
            _write_value(body, item)
        out += struct.pack("<BBI", value.elem, value.aux, len(body))
        out += body


def _entry_bytes(entry: Entry) -> bytes:
    """The entry as the file stores it: size, path hash, fields."""
    body = bytearray(struct.pack("<I", entry.path_hash))
    _write_fields(body, entry.fields)
    return struct.pack("<I", len(body)) + bytes(body)


# --------------------------------------------------------------------------------------
# the file
# --------------------------------------------------------------------------------------

class Bin:
    """A PROP file whose entries are read when asked for."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        reader = _Reader(data)
        magic = reader.take(4)
        if magic == b"PTCH":  # a patch header: 8 bytes, then the real file
            reader.take(8)
            magic = reader.take(4)
        if magic != b"PROP":
            raise PropError("not a PROP file")
        self.version = reader.u32()
        if self.version >= 2:
            for _ in range(reader.u32()):  # linked files
                reader.take(reader.u16())
        count = reader.u32()
        self._types: List[int] = list(struct.unpack_from(f"<{count}I", reader.take(4 * count)))
        self._head_end = reader.pos
        self._bounds: Optional[List[Tuple[int, int]]] = None
        self._parsed: Dict[int, Entry] = {}

    @property
    def types(self) -> List[int]:
        """The type hash of each entry, in file order."""
        return self._types

    def _locate(self) -> List[Tuple[int, int]]:
        """The (start, end) of each entry, its size field included."""
        if self._bounds is None:
            bounds = []
            pos = self._head_end
            data = self._data
            for _ in self._types:
                if pos + 4 > len(data):
                    raise PropError("an entry runs past the end of the file")
                end = pos + 4 + struct.unpack_from("<I", data, pos)[0]
                if end > len(data):
                    raise PropError("an entry runs past the end of the file")
                bounds.append((pos, end))
                pos = end
            self._bounds = bounds
        return self._bounds

    def find_entry(self, type_hash: int) -> Optional[Entry]:
        """The first entry of this type, parsed (edit it, then write())."""
        try:
            index = self._types.index(type_hash)
        except ValueError:
            return None
        entry = self._parsed.get(index)
        if entry is None:
            start, end = self._locate()[index]
            reader = _Reader(self._data[start + 4:end])
            path_hash = reader.u32()
            entry = Entry(type_hash, path_hash, reader.fields(type_hash))
            self._parsed[index] = entry
        return entry

    def write(self) -> bytes:
        """The file with the entries that were read written from their
        values and every other byte as it was. The bytes it came from when
        nothing changed."""
        if not self._parsed:
            return self._data
        bounds = self._locate()
        parts: List[bytes] = [self._data[:self._head_end]]
        pos = self._head_end
        changed = False
        for index, (start, end) in enumerate(bounds):
            entry = self._parsed.get(index)
            raw = self._data[start:end]
            if entry is not None:
                fresh = _entry_bytes(entry)
                if fresh != raw:
                    raw = fresh
                    changed = True
            parts.append(raw)
            pos = end
        if not changed:
            return self._data
        parts.append(self._data[pos:])
        return b"".join(parts)


def entry_types(data: bytes) -> List[int]:
    """The type hashes a file lists, without reading its entries ([] if it is not a PROP file)."""
    try:
        return Bin(data).types
    except (PropError, struct.error):
        return []


def build(entries: List[Entry], version: int = 3, linked_files=()) -> bytes:
    """A PROP file holding *entries* (tests and tools build bins with it)."""
    out = bytearray(b"PROP" + struct.pack("<I", version))
    if version >= 2:
        out += struct.pack("<I", len(linked_files))
        for name in linked_files:
            _write_string(out, name)
    out += struct.pack("<I", len(entries))
    for entry in entries:
        out += struct.pack("<I", entry.type_hash)
    for entry in entries:
        out += _entry_bytes(entry)
    return bytes(out)
