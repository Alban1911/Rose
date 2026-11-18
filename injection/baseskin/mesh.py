#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebuild a skin's skeleton (.skl) or mesh (.skn) into a file that is not
byte-identical to the game's but draws and animates the same:

- a skeleton gets one more joint, null_bone: a root joint at the origin with an
  identity bind pose, no animation track and no influence on any vertex;
- a mesh gets one more vertex, a copy of its last one, added to its last
  submesh; no triangle uses it.

Every other byte is kept. Ported from RoseBin (tools/rosebin/src/mesh.rs),
which checked it on every skeleton and mesh of the game's champion WADs
(2026-11-18): every skeleton is version 0, joint lookup table sorted by the ELF
hash of the lowercased joint name, ending with zero padding to a multiple of 4;
meshes are versions 4.1, 2.1, 1.1 and 0.1, and every last submesh range ends at
the last vertex.

Rose's own additions: is_rebuilt tells a file this already rebuilt (Rose checks
a stored skin again, RoseBin builds each package once), and strip_padding takes
off the 16 zero bytes older Roses appended instead.
"""

from __future__ import annotations

import struct
from typing import List, Optional, Tuple

SKL_FORMAT_TOKEN = 0x22FD4FC3
SKN_MAGIC = 0x00112233

NULL_JOINT_NAME = "null_bone"

# Skeleton header fields
SKL_HEADER_SIZE = 64
SKL_FILE_SIZE = 0
SKL_VERSION = 8
SKL_JOINT_COUNT = 14
SKL_INFLUENCE_COUNT = 16
# Six section offsets: joints, joint lookup table, influences, skeleton name,
# asset name, joint names. Zero or negative when absent
SKL_SECTION_OFFSETS = 20
SKL_JOINTS = 0
SKL_TABLE = 1
SKL_INFLUENCES = 2
SKL_NAME = 3
SKL_ASSET_NAME = 4

SKL_JOINT_SIZE = 100
JOINT_NAME_OFFSET = 96          # the joint's name offset, relative to the field itself
SKL_TABLE_ENTRY_SIZE = 8        # joint id (i16), padding (i16), name hash (u32)
JOINT_RADIUS = 2.1

SKN_RANGE_SIZE = 80
RANGE_VERTEX_START = 64         # after the range's 64-byte material name
RANGE_VERTEX_COUNT = 68
LEGACY_VERTEX_SIZE = 52         # vertex size of meshes before version 4, which do not store it
SKN_BOUNDS_SIZE = 40            # version 4 bounding box (6 floats) and sphere (4 floats)

# What older Roses appended to every SKN/SKL instead of rebuilding it
LEGACY_PADDING = bytes(16)


class MeshError(ValueError):
    """A file that is not a skeleton or mesh this can rebuild."""


def _u16(data: bytes, at: int) -> Optional[int]:
    return struct.unpack_from("<H", data, at)[0] if 0 <= at and at + 2 <= len(data) else None


def _u32(data: bytes, at: int) -> Optional[int]:
    return struct.unpack_from("<I", data, at)[0] if 0 <= at and at + 4 <= len(data) else None


def _i32(data: bytes, at: int) -> Optional[int]:
    return struct.unpack_from("<i", data, at)[0] if 0 <= at and at + 4 <= len(data) else None


def elf_hash_lower(name: str) -> int:
    """The ELF hash of a lowercased name, as skeletons hash joint names."""
    value = 0
    for byte in name.encode("utf-8"):
        if 65 <= byte <= 90:
            byte += 32
        value = ((value << 4) + byte) & 0xFFFFFFFF
        high = value & 0xF0000000
        if high:
            value ^= high >> 24
        value &= ~high & 0xFFFFFFFF
    return value


NULL_JOINT_HASH = elf_hash_lower(NULL_JOINT_NAME)


def _section(data: bytes, offset: int, length: int) -> Optional[Tuple[int, int]]:
    if offset <= 0:
        return None
    end = offset + length
    return (offset, end) if end <= len(data) else None


def _string_at(data: bytes, offset: int) -> Optional[Tuple[int, int]]:
    """The NUL-terminated string at *offset*, terminator included."""
    if offset < 0 or offset >= len(data):
        return None
    end = data.find(b"\x00", offset)
    return (offset, end + 1) if end >= 0 else None


def is_skeleton(data: bytes) -> bool:
    return _u32(data, 4) == SKL_FORMAT_TOKEN


def is_mesh(data: bytes) -> bool:
    return _u32(data, 0) == SKN_MAGIC


def rebuild(data: bytes) -> Tuple[bytes, str]:
    """Rebuild a skeleton or a mesh, told apart by its header: (the new file,
    what was added). Raises MeshError for anything else, or a file this
    cannot rebuild."""
    if is_skeleton(data):
        return _add_null_joint(data), "null joint"
    if is_mesh(data):
        return _add_null_vertex(data), "null vertex"
    raise MeshError("neither a skeleton (SKL) nor a mesh (SKN)")


# --------------------------------------------------------------------------------------
# skeletons
# --------------------------------------------------------------------------------------

class _Skeleton:
    """The sections of a skeleton, as the rebuild needs them."""

    def __init__(self, data: bytes) -> None:
        if len(data) < SKL_HEADER_SIZE:
            raise MeshError("skeleton header truncated")
        version = _u32(data, SKL_VERSION) or 0
        if version != 0:
            raise MeshError(f"skeleton version {version} not supported")
        count = _u16(data, SKL_JOINT_COUNT) or 0
        if count == 0 or count >= 0x7FFF:
            raise MeshError(f"skeleton has {count} joints")
        offsets = [_i32(data, SKL_SECTION_OFFSETS + 4 * i) or 0 for i in range(6)]
        joints = _section(data, offsets[SKL_JOINTS], count * SKL_JOINT_SIZE)
        if joints is None:
            raise MeshError("skeleton joints out of bounds")
        table = _section(data, offsets[SKL_TABLE], count * SKL_TABLE_ENTRY_SIZE)
        if table is None:
            raise MeshError("skeleton joint table out of bounds")
        if joints[0] < table[1] and table[0] < joints[1]:
            raise MeshError("skeleton joints and joint table overlap")

        # Every string, joint names first, in joint order
        strings: List[Tuple[int, int]] = []
        for i in range(count):
            field = joints[0] + i * SKL_JOINT_SIZE + JOINT_NAME_OFFSET
            found = _string_at(data, field + (_i32(data, field) or 0))
            if found is None:
                raise MeshError(f"skeleton joint {i} name out of bounds")
            strings.append(found)
        for field in (SKL_NAME, SKL_ASSET_NAME):
            if offsets[field] > 0:
                found = _string_at(data, offsets[field])
                if found is None:
                    raise MeshError("skeleton name out of bounds")
                strings.append(found)
        influences = None
        if offsets[SKL_INFLUENCES] > 0:
            influence_count = _u32(data, SKL_INFLUENCE_COUNT) or 0
            influences = _section(data, offsets[SKL_INFLUENCES], influence_count * 2)
            if influences is None:
                raise MeshError("skeleton influences out of bounds")

        self.count = count
        self.offsets = offsets
        self.joints = joints
        self.table = table
        self.strings = strings
        self.sections = [joints, table] + ([influences] if influences else []) + strings
        self.content_end = max(end for _start, end in self.sections)

    def hashes(self, data: bytes) -> List[int]:
        start, end = self.table
        return [_u32(data, at + 4) for at in range(start, end, SKL_TABLE_ENTRY_SIZE)]


def _null_joint(joint_id: int, name_hash: int, name_offset: int) -> bytes:
    """A root joint at the origin: identity local transform and bind pose."""
    identity = (0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    return (struct.pack("<HhhhIf", 0, joint_id, -1, 0, name_hash, JOINT_RADIUS)
            + struct.pack("<10f", *identity) * 2
            + struct.pack("<i", name_offset))


def _add_null_joint(data: bytes) -> bytes:
    """Add null_bone after the last joint. The joints keep their indices, so
    the mesh's influences and every animation track still find theirs."""
    skeleton = _Skeleton(data)
    count, joints, table = skeleton.count, skeleton.joints, skeleton.table

    # The new joint goes at the end of the joints, its table entry at the end
    # of the table (then sorted in). Nothing may straddle either point
    joint_insert, table_insert = joints[1], table[1]
    for start, end in skeleton.sections:
        if any(start < at < end for at in (joint_insert, table_insert)):
            raise MeshError("skeleton sections overlap")

    entries = [data[at:at + SKL_TABLE_ENTRY_SIZE] for at in range(table[0], table[1], SKL_TABLE_ENTRY_SIZE)]
    if any(_u32(entry, 4) == NULL_JOINT_HASH for entry in entries):
        raise MeshError(f"skeleton already has a joint hashed like {NULL_JOINT_NAME}")

    # The zero padding after the last section is redone after the new name
    tail = data[skeleton.content_end:]
    body_end = skeleton.content_end if len(tail) < 4 and not any(tail) else len(data)

    def moved(at: int) -> int:
        """Where an original byte lands in the new file."""
        return (at + (SKL_JOINT_SIZE if at >= joint_insert else 0)
                + (SKL_TABLE_ENTRY_SIZE if at >= table_insert else 0))

    out = bytearray()
    copied = 0
    for at, length in sorted([(joint_insert, SKL_JOINT_SIZE), (table_insert, SKL_TABLE_ENTRY_SIZE)]):
        out += data[copied:at]
        out += bytes(length)
        copied = at
    out += data[copied:body_end]
    name_at = len(out)
    out += NULL_JOINT_NAME.encode("ascii") + b"\x00"
    out += bytes(-len(out) % 4)

    struct.pack_into("<I", out, SKL_FILE_SIZE, len(out))
    struct.pack_into("<H", out, SKL_JOINT_COUNT, count + 1)
    for i, offset in enumerate(skeleton.offsets):
        if offset > 0:
            struct.pack_into("<i", out, SKL_SECTION_OFFSETS + 4 * i, moved(offset))
    for i, (name_start, _end) in enumerate(skeleton.strings[:count]):
        field = moved(joints[0] + i * SKL_JOINT_SIZE + JOINT_NAME_OFFSET)
        struct.pack_into("<i", out, field, moved(name_start) - field)
    joint_at = moved(joint_insert) - SKL_JOINT_SIZE
    out[joint_at:joint_at + SKL_JOINT_SIZE] = _null_joint(count, NULL_JOINT_HASH,
                                                          name_at - (joint_at + JOINT_NAME_OFFSET))

    entry = struct.pack("<hhI", count, 0, NULL_JOINT_HASH)
    position = next((i for i, other in enumerate(entries) if _u32(other, 4) > NULL_JOINT_HASH), len(entries))
    entries.insert(position, entry)
    start = moved(table[0])
    out[start:start + len(entries) * SKL_TABLE_ENTRY_SIZE] = b"".join(entries)
    return bytes(out)


# --------------------------------------------------------------------------------------
# meshes
# --------------------------------------------------------------------------------------

class _Mesh:
    """Where a mesh's vertices are, as the rebuild needs it."""

    def __init__(self, data: bytes) -> None:
        def truncated() -> MeshError:
            return MeshError("mesh truncated")

        major = _u16(data, 4)
        if major is None:
            raise truncated()
        at = 8
        self.last_range: Optional[int] = None
        if major in (1, 2, 4):
            range_count = _u32(data, at)
            if range_count is None:
                raise truncated()
            at += 4
            if range_count > 0:
                self.last_range = at + (range_count - 1) * SKN_RANGE_SIZE
            at += range_count * SKN_RANGE_SIZE
            if major == 4:
                at += 4  # flags
        elif major != 0:
            raise MeshError(f"mesh version {major} not supported")
        index_count = _u32(data, at)
        vertex_count = _u32(data, at + 4)
        if index_count is None or vertex_count is None:
            raise truncated()
        self.vertex_count_at = at + 4
        at += 8
        vertex_size = LEGACY_VERTEX_SIZE
        if major == 4:
            vertex_size = _u32(data, at)
            if vertex_size is None:
                raise truncated()
            at += 8 + SKN_BOUNDS_SIZE  # vertex size, vertex type, bounds
        if vertex_count == 0 or vertex_size == 0:
            raise MeshError("mesh has no vertices")
        self.indices_at = at
        self.index_count = index_count
        self.vertex_count = vertex_count
        self.vertex_size = vertex_size
        self.vertices_end = at + index_count * 2 + vertex_count * vertex_size
        if self.vertices_end > len(data):
            raise truncated()


def _add_null_vertex(data: bytes) -> bytes:
    """Add a copy of the last vertex to the end of the vertex buffer and of the
    last submesh range. The index buffer is unchanged, so no triangle uses it,
    and the bounds stay right."""
    mesh = _Mesh(data)
    end, size = mesh.vertices_end, mesh.vertex_size
    out = bytearray(data[:end])
    out += data[end - size:end]
    out += data[end:]
    struct.pack_into("<I", out, mesh.vertex_count_at, mesh.vertex_count + 1)
    if mesh.last_range is not None:
        start = _u32(data, mesh.last_range + RANGE_VERTEX_START)
        count = _u32(data, mesh.last_range + RANGE_VERTEX_COUNT)
        if start is None or count is None:
            raise MeshError("mesh truncated")
        if start + count == mesh.vertex_count:
            struct.pack_into("<I", out, mesh.last_range + RANGE_VERTEX_COUNT, count + 1)
    return bytes(out)


# --------------------------------------------------------------------------------------
# Rose's checks of a stored skin
# --------------------------------------------------------------------------------------

def is_rebuilt(data: bytes) -> bool:
    """Whether *data* is a file rebuild made: a skeleton holding null_bone, or
    a mesh whose last vertex copies the one before it and no triangle uses."""
    try:
        if is_skeleton(data):
            return NULL_JOINT_HASH in _Skeleton(data).hashes(data)
        if is_mesh(data):
            mesh = _Mesh(data)
            if mesh.vertex_count < 2:
                return False
            end, size = mesh.vertices_end, mesh.vertex_size
            if data[end - size:end] != data[end - 2 * size:end - size]:
                return False
            last = mesh.vertex_count - 1
            indices = struct.unpack_from(f"<{mesh.index_count}H", data, mesh.indices_at)
            return all(index != last for index in indices)
    except (MeshError, struct.error):
        return False
    return False


def strip_padding(data: bytes) -> bytes:
    """*data* without the 16 zero bytes an older Rose appended, when it ends
    with them past the file's own content; else *data* as it is."""
    if not data.endswith(LEGACY_PADDING):
        return data
    stripped = data[:-len(LEGACY_PADDING)]
    try:
        if is_skeleton(data):
            fits = _Skeleton(stripped).content_end <= len(stripped)
        elif is_mesh(data):
            fits = _Mesh(stripped).vertices_end <= len(stripped)
        else:
            return data
    except MeshError:
        return data
    return stripped if fits else data
