"""A skin's SKN/SKL rebuilt byte-distinct from the game's (injection.baseskin.mesh).

The cases are those of RoseBin's mesh.rs, which builds the packages Rose ships.
"""

import struct
import unittest

from injection.baseskin import mesh
from injection.baseskin.mesh import (
    JOINT_RADIUS, LEGACY_VERTEX_SIZE, NULL_JOINT_NAME, MeshError, elf_hash_lower, is_rebuilt, rebuild, strip_padding,
)
from injection.tests.mesh_fixtures import skl, skn

JOINTS = [("root", -1), ("pelvis", 0), ("L_Hand", 1)]


def text(data, at):
    return data[at:data.index(b"\x00", at)].decode("ascii")


def read_skeleton(data):
    assert struct.unpack_from("<I", data, 0)[0] == len(data)
    assert len(data) % 4 == 0
    count = struct.unpack_from("<H", data, 14)[0]
    influence_count = struct.unpack_from("<I", data, 16)[0]
    offset = lambda i: struct.unpack_from("<i", data, 20 + 4 * i)[0]  # noqa: E731
    joints = []
    for i in range(count):
        at = offset(0) + i * 100
        field = at + 96
        joints.append((
            text(data, field + struct.unpack_from("<i", data, field)[0]),
            struct.unpack_from("<h", data, at + 2)[0],
            struct.unpack_from("<h", data, at + 4)[0],
            struct.unpack_from("<I", data, at + 8)[0],
            struct.unpack_from("<21f", data, at + 12),
        ))
    table = [struct.unpack_from("<hhI", data, offset(1) + 8 * i)[::2] for i in range(count)]
    influences = [struct.unpack_from("<h", data, offset(2) + 2 * i)[0] for i in range(influence_count)]
    return joints, table, influences, text(data, offset(3)), text(data, offset(4))


class SkeletonTests(unittest.TestCase):
    def assert_null_joint_added(self, before, after):
        (joints, table, influences, name, asset), (new_joints, new_table, new_influences, new_name, new_asset) = (
            read_skeleton(before), read_skeleton(after))
        count = len(joints)
        self.assertEqual(new_joints[:count], joints)
        null = new_joints[count]
        self.assertEqual(null[:4], (NULL_JOINT_NAME, count, -1, elf_hash_lower(NULL_JOINT_NAME)))
        identity = (0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0)
        self.assertEqual(null[4], struct.unpack("<21f", struct.pack("<f", JOINT_RADIUS) + struct.pack("<20f", *identity * 2)))
        self.assertEqual(new_table, sorted(table + [(count, null[3])], key=lambda entry: entry[1]))
        self.assertEqual((new_influences, new_name, new_asset), (influences, name, asset))

    def test_the_elf_hash_matches_the_game_skeletons(self):
        self.assertEqual(elf_hash_lower("root"), 0x00079664)
        self.assertEqual(elf_hash_lower("BUFFBONE_GLB_GROUND_LOC"), 0x0102A113)

    def test_a_skeleton_gets_a_null_root_joint(self):
        before = skl(JOINTS)
        null = elf_hash_lower(NULL_JOINT_NAME)
        hashes = [elf_hash_lower(name) for name, _ in JOINTS]
        self.assertTrue(any(h < null for h in hashes) and any(h > null for h in hashes))  # sorts between
        after, added = rebuild(before)
        self.assertEqual(added, "null joint")
        self.assert_null_joint_added(before, after)
        self.assertEqual(after[44:64], before[44:64])  # the header's reserved fields are kept

    def test_a_skeleton_with_joint_names_before_its_name_is_rebuilt(self):
        before = skl(JOINTS, names_first=True)
        self.assert_null_joint_added(before, rebuild(before)[0])

    def test_the_padding_is_redone_for_every_name_length(self):
        for name in ("a", "ab", "abc", "abcd"):
            before = skl([("root", -1), (name, 0)])
            self.assert_null_joint_added(before, rebuild(before)[0])

    def test_a_skeleton_already_holding_the_null_joint_is_refused(self):
        once = rebuild(skl(JOINTS))[0]
        with self.assertRaisesRegex(MeshError, NULL_JOINT_NAME):
            rebuild(once)


class MeshTests(unittest.TestCase):
    def test_a_mesh_gets_a_copy_of_its_last_vertex(self):
        before = skn(4, [(0, 4), (4, 5)])
        after, added = rebuild(before)
        self.assertEqual(added, "null vertex")
        size, vertices_end = 56, len(before) - 12
        last_vertex = before[vertices_end - size:vertices_end]
        counts_at = 8 + 4 + 2 * 80 + 4
        expected = bytearray(before[:vertices_end] + last_vertex + before[vertices_end:])
        struct.pack_into("<I", expected, counts_at + 4, 10)       # vertex count
        struct.pack_into("<I", expected, 8 + 4 + 80 + 68, 6)      # the last range's vertex count
        self.assertEqual(after, bytes(expected))

    def test_old_mesh_versions_get_a_null_vertex(self):
        for major in (0, 1, 2):
            before = skn(major, [(0, 3), (3, 4)])
            after, _ = rebuild(before)
            self.assertEqual(len(after), len(before) + LEGACY_VERTEX_SIZE)
            self.assertTrue(is_rebuilt(after))

    def test_other_files_are_refused(self):
        with self.assertRaises(MeshError):
            rebuild(b"skl-data")
        with self.assertRaises(MeshError):
            rebuild(skl(JOINTS)[:40])
        with self.assertRaises(MeshError):
            rebuild(skn(4, [(0, 3)])[:-40])
        future = bytearray(skn(4, [(0, 3)]))
        future[4] = 5
        with self.assertRaises(MeshError):
            rebuild(bytes(future))


class StoredSkinTests(unittest.TestCase):
    """Rose checks a stored skin again: a rebuilt file is told apart, and one an older Rose padded is undone."""

    def test_a_rebuilt_file_is_told_apart(self):
        for original in (skl(JOINTS), skn(4, [(0, 3), (3, 4)]), skn(2, [(0, 3)])):
            self.assertFalse(is_rebuilt(original))
            self.assertTrue(is_rebuilt(rebuild(original)[0]))
        self.assertFalse(is_rebuilt(b"anything"))

    def test_a_mesh_whose_last_vertex_a_triangle_uses_is_not_taken_for_rebuilt(self):
        # Two equal last vertices, the last drawn: an original mesh
        data = bytearray(skn(4, [(0, 3)]))
        size, end = 56, len(data) - 12
        data[end - size:end] = data[end - 2 * size:end - size]
        self.assertFalse(is_rebuilt(bytes(data)))

    def test_the_padding_of_an_older_rose_is_taken_off(self):
        for original in (skl(JOINTS), skn(4, [(0, 3), (3, 4)])):
            self.assertEqual(strip_padding(original + bytes(16)), original)
            self.assertEqual(strip_padding(original), original)
        self.assertEqual(strip_padding(b"x" + bytes(16)), b"x" + bytes(16))  # not a mesh: as it is

    def test_module_constants_match_rosebin(self):
        self.assertEqual((mesh.SKL_JOINT_SIZE, mesh.SKN_RANGE_SIZE, mesh.LEGACY_VERTEX_SIZE), (100, 80, 52))
