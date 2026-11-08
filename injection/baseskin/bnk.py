#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wwise sound banks (.bnk): read and edit Event objects.

Only the HIRC chunk is read, and inside it only Events (type 4); every other
chunk and object is kept byte for byte, so a bank nobody edited writes back
identical.
"""

from __future__ import annotations

import struct
from functools import lru_cache
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

HIRC_ACTION = 3
HIRC_EVENT = 4
# Banks up to this version store an Event's action count as a u32; newer ones
# use Wwise's variable-length integer
LAST_U32_ACTION_COUNT_VERSION = 122


class BankError(ValueError):
    """The bytes are not a bank this module can read."""


@lru_cache(maxsize=65536)
def wwise_hash(name: str) -> int:
    """Wwise's 32-bit FNV-1 hash of the lowercased name: an Event's id."""
    value = 0x811C9DC5
    for byte in name.encode("utf-8", "surrogateescape").lower():
        value = (value * 0x01000193) & 0xFFFFFFFF
        value ^= byte
    return value


class _Object:
    __slots__ = ("kind", "id", "body")

    def __init__(self, kind: int, object_id: int, body: bytes) -> None:
        self.kind = kind
        self.id = object_id
        self.body = body


def _read_var_uint(data: bytes) -> Optional[Tuple[int, int]]:
    """Wwise's variable-length integer: (value, bytes used)."""
    value = 0
    for index, byte in enumerate(data[:5]):
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, index + 1
    return None


def _write_var_uint(value: int) -> bytes:
    groups = [value & 0x7F]
    value >>= 7
    while value:
        groups.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(groups))


def _decode_actions(body: bytes, version: int) -> Optional[List[int]]:
    if version <= LAST_U32_ACTION_COUNT_VERSION:
        if len(body) < 4:
            return None
        count, pos = struct.unpack_from("<I", body)[0], 4
    else:
        counted = _read_var_uint(body)
        if counted is None:
            return None
        count, pos = counted
    if len(body) != pos + count * 4:
        return None
    return list(struct.unpack_from(f"<{count}I", body, pos))


def _encode_actions(actions: Sequence[int], version: int) -> bytes:
    head = struct.pack("<I", len(actions)) if version <= LAST_U32_ACTION_COUNT_VERSION else _write_var_uint(len(actions))
    return head + struct.pack(f"<{len(actions)}I", *actions)


class Bank:
    """A parsed bank. Chunks are ("raw", tag, bytes) or ("hirc", [objects])."""

    def __init__(self, version: int, chunks: list) -> None:
        self.version = version
        self._chunks = chunks
        self._events: Optional[Dict[int, List[_Object]]] = None

    # -- reading and writing ------------------------------------------------
    @classmethod
    def parse(cls, data: bytes) -> "Bank":
        chunks: list = []
        version: Optional[int] = None
        pos = 0
        while pos < len(data):
            if pos + 8 > len(data):
                raise BankError(f"truncated bank chunk header at {pos}")
            tag = data[pos:pos + 4]
            length = struct.unpack_from("<I", data, pos + 4)[0]
            body = data[pos + 8:pos + 8 + length]
            if len(body) != length:
                raise BankError(f"bank chunk {tag.decode('latin-1')} overruns the file")
            if tag == b"BKHD":
                if length < 4:
                    raise BankError("BKHD chunk is too short")
                version = struct.unpack_from("<I", body)[0]
            if tag == b"HIRC":
                chunks.append(("hirc", _parse_hirc(body)))
            else:
                chunks.append(("raw", tag, body))
            pos += 8 + length
        if version is None:
            raise BankError("bank has no BKHD chunk")
        return cls(version, chunks)

    def write(self) -> bytes:
        out = bytearray()
        for chunk in self._chunks:
            if chunk[0] == "raw":
                _, tag, body = chunk
                out += tag + struct.pack("<I", len(body)) + body
            else:
                objects = chunk[1]
                body = bytearray(struct.pack("<I", len(objects)))
                for obj in objects:
                    body += struct.pack("<BII", obj.kind, 4 + len(obj.body), obj.id)
                    body += obj.body
                out += b"HIRC" + struct.pack("<I", len(body)) + body
        return bytes(out)

    # -- events -------------------------------------------------------------
    def _objects(self) -> Iterator[_Object]:
        for chunk in self._chunks:
            if chunk[0] == "hirc":
                yield from chunk[1]

    def _event_index(self) -> Dict[int, List[_Object]]:
        if self._events is None:
            index: Dict[int, List[_Object]] = {}
            for obj in self._objects():
                if obj.kind == HIRC_EVENT:
                    index.setdefault(obj.id, []).append(obj)
            self._events = index
        return self._events

    def has_event(self, event_id: int) -> bool:
        return event_id in self._event_index()

    def event_ids(self) -> Iterator[int]:
        return iter(self._event_index())

    def event_actions(self, event_id: int) -> Optional[List[int]]:
        """Action ids of the first Event with this id (None when the bank has
        none, or its payload is not in the expected layout)."""
        found = self._event_index().get(event_id)
        return _decode_actions(found[0].body, self.version) if found else None

    def set_event_actions(self, event_id: int, actions: Sequence[int]) -> int:
        """Point every Event with this id at *actions*; how many changed."""
        body = _encode_actions(actions, self.version)
        changed = 0
        for obj in self._event_index().get(event_id, ()):
            if obj.body != body:
                obj.body = body
                changed += 1
        return changed

    def add_event(self, event_id: int, actions: Sequence[int]) -> None:
        """Append an Event (the caller makes sure the id is unused)."""
        for chunk in self._chunks:
            if chunk[0] == "hirc":
                obj = _Object(HIRC_EVENT, event_id, _encode_actions(actions, self.version))
                chunk[1].append(obj)
                if self._events is not None:
                    self._events.setdefault(event_id, []).append(obj)
                return
        raise BankError("bank has no HIRC chunk")

    def remove_event(self, event_id: int) -> int:
        """Remove every Event with this id (its Actions stay, unreferenced)."""
        removed = 0
        for chunk in self._chunks:
            if chunk[0] == "hirc":
                kept = [obj for obj in chunk[1] if not (obj.kind == HIRC_EVENT and obj.id == event_id)]
                removed += len(chunk[1]) - len(kept)
                chunk[1][:] = kept
        self._events = None
        return removed

    def extract_events(self, bank_id: int, language_id: int, events: Sequence[Tuple[int, int]]) -> Tuple["Bank", int]:
        """A new events bank holding, for each (alias_id, source_id), an Event
        alias_id with the actions of this bank's Event source_id, plus copies
        of those Action objects (an Event's actions must sit in its own bank).
        The header is this bank's with *bank_id* and *language_id*. Pairs whose
        source Event or Actions are missing are skipped; returns the bank and
        how many Events it holds."""
        header: Optional[bytes] = None
        for chunk in self._chunks:
            if chunk[0] == "raw" and chunk[1] == b"BKHD":
                header = chunk[2]
                break
        if header is None:
            raise BankError("bank has no BKHD chunk")
        if len(header) < 12:
            raise BankError("BKHD chunk is too short")
        header = header[:4] + struct.pack("<II", bank_id, language_id) + header[12:]

        actions_by_id: Dict[int, _Object] = {}
        for obj in self._objects():
            if obj.kind == HIRC_ACTION:
                actions_by_id.setdefault(obj.id, obj)
        actions_out: List[_Object] = []
        events_out: List[_Object] = []
        for alias_id, source_id in events:
            if any(event.id == alias_id for event in events_out):
                continue
            actions = self.event_actions(source_id)
            if actions is None:
                continue
            objects = [actions_by_id.get(action) for action in actions]
            if any(obj is None for obj in objects):
                continue
            for obj in objects:
                if not any(existing.id == obj.id for existing in actions_out):
                    actions_out.append(_Object(obj.kind, obj.id, obj.body))
            events_out.append(_Object(HIRC_EVENT, alias_id, _encode_actions(actions, self.version)))
        count = len(events_out)
        actions_out.extend(events_out)
        return Bank(self.version, [("raw", b"BKHD", header), ("hirc", actions_out)]), count


def _parse_hirc(data: bytes) -> List[_Object]:
    if len(data) < 4:
        raise BankError("HIRC chunk is too short")
    count = struct.unpack_from("<I", data)[0]
    objects: List[_Object] = []
    pos = 4
    for index in range(count):
        if pos + 5 > len(data):
            raise BankError(f"truncated HIRC object {index}")
        kind, size = struct.unpack_from("<BI", data, pos)
        if size < 4:
            raise BankError(f"HIRC object {index} is smaller than its ID")
        payload = data[pos + 5:pos + 5 + size]
        if len(payload) != size:
            raise BankError(f"HIRC object {index} overruns the chunk")
        objects.append(_Object(kind, struct.unpack_from("<I", payload)[0], payload[4:]))
        pos += 5 + size
    if pos != len(data):
        raise BankError(f"HIRC chunk has {len(data) - pos} trailing bytes")
    return objects
