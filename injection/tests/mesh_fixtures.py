"""Small skeletons and meshes laid out like the game's (RoseBin's mesh.rs fixtures)."""

import struct
import zlib

from injection.baseskin.mesh import (
    JOINT_NAME_OFFSET, JOINT_RADIUS, LEGACY_VERTEX_SIZE, SKL_FORMAT_TOKEN, SKL_HEADER_SIZE, SKL_JOINT_SIZE,
    SKN_MAGIC, elf_hash_lower, rebuild,
)


def skl(joints, names_first=False):
    """A skeleton: header, joints, lookup table, influences, skeleton name,
    asset name, joint names, zero padding. Each joint is (name, parent); every
    joint is an influence. *names_first*: joint names before the skeleton and
    asset names (LeagueToolkit's layout)."""
    count = len(joints)
    joints_at = SKL_HEADER_SIZE
    table_at = joints_at + count * SKL_JOINT_SIZE
    influences_at = table_at + count * 8
    strings_at = influences_at + count * 2
    strings = bytearray()

    def put(text):
        at = strings_at + len(strings)
        strings.extend(text.encode("ascii") + b"\x00")
        return at

    if names_first:
        joint_names = [put(name) for name, _ in joints]
        name_at, asset_at = put("skeleton"), put("asset")
    else:
        name_at, asset_at = put("skeleton"), put("asset")
        joint_names = [put(name) for name, _ in joints]

    out = bytearray(SKL_HEADER_SIZE)
    struct.pack_into("<I", out, 4, SKL_FORMAT_TOKEN)
    struct.pack_into("<H", out, 14, count)
    struct.pack_into("<I", out, 16, count)
    for i, offset in enumerate([joints_at, table_at, influences_at, name_at, asset_at, joint_names[0]]):
        struct.pack_into("<i", out, 20 + 4 * i, offset)
    for i in range(5):
        struct.pack_into("<i", out, 44 + 4 * i, -1)
    for i, (name, parent) in enumerate(joints):
        at = len(out)
        out += struct.pack("<HhhhIf", 0, i, parent, 0, elf_hash_lower(name), JOINT_RADIUS)
        out += b"".join(struct.pack("<f", i + value / 8.0) for value in range(20))
        out += struct.pack("<i", joint_names[i] - (at + JOINT_NAME_OFFSET))
    for name_hash, joint_id in sorted((elf_hash_lower(name), i) for i, (name, _) in enumerate(joints)):
        out += struct.pack("<hhI", joint_id, 0, name_hash)
    for i in range(count):
        out += struct.pack("<h", i)
    out += strings
    out += bytes(-len(out) % 4)
    struct.pack_into("<I", out, 0, len(out))
    return bytes(out)


def skn(major, ranges, seed=0):
    """A mesh of version *major* with one range per (start, count) vertex
    range, each drawing one triangle from its own vertices. Version 4 meshes
    use the 56-byte color vertex. Every vertex differs; *seed* changes them."""
    vertex_count = ranges[-1][0] + ranges[-1][1] if ranges else 0
    vertex_size = 56 if major == 4 else LEGACY_VERTEX_SIZE
    indices = [start + i for start, _ in ranges for i in range(3)]
    out = bytearray(struct.pack("<IHH", SKN_MAGIC, major, 1))
    if major != 0:
        out += struct.pack("<I", len(ranges))
        for i, (start, count) in enumerate(ranges):
            out += f"mat{i:02}".encode("ascii").ljust(64, b"\x00")
            out += struct.pack("<4I", start, count, i * 3, 3)
    if major == 4:
        out += struct.pack("<I", 0)
    out += struct.pack("<II", len(indices), vertex_count)
    if major == 4:
        out += struct.pack("<II", vertex_size, 1)
        out += b"".join(struct.pack("<f", value - 3.0) for value in range(10))
    out += b"".join(struct.pack("<H", index) for index in indices)
    for vertex in range(vertex_count):
        out += bytes((vertex * 7 + byte + seed) & 0xFF for byte in range(vertex_size))
    if major != 0:
        out += bytes(12)
    return bytes(out)


def fake(name):
    """A skeleton (a name holding "skl") or mesh of its own for each *name*."""
    seed = zlib.crc32(name.encode("utf-8")) & 0xFF
    if "skl" in name:
        return skl([("root", -1), (f"joint_{seed}", 0)])
    return skn(4, [(0, 3), (3, 4)], seed)


def rebuilt(data):
    return rebuild(data)[0]
