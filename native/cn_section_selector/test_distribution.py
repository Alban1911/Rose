"""Synthetic PE tests only; no publisher DLL or game needed."""
import struct
import unittest

import pefile

from build_candidate import build, unsigned_distribution


def synthetic_pe():
    data = bytearray(0x420)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3C, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', data, 0x84, 0x8664, 1, 0, 0, 0, 0xF0, 0x2022)
    opt = 0x98
    struct.pack_into('<H', data, opt, 0x20B)
    struct.pack_into('<Q', data, opt + 24, 0x180000000)
    struct.pack_into('<II', data, opt + 32, 0x1000, 0x200)
    struct.pack_into('<II', data, opt + 56, 0x2000, 0x200)
    struct.pack_into('<I', data, opt + 108, 16)
    struct.pack_into('<II', data, opt + 112 + 32, 0x400, 0x20)
    data[0x188:0x190] = b'.text\0\0\0'
    struct.pack_into('<IIII', data, 0x190, 0x200, 0x1000, 0x200, 0x200)
    struct.pack_into('<I', data, 0x188 + 36, 0x60000020)
    data[0x200:0x400] = b'\x90' * 0x200
    data[0x400:] = b'C' * 0x20
    return bytes(data)


class DistributionTests(unittest.TestCase):
    def test_certificate_is_removed_without_changing_section_bytes(self):
        original = synthetic_pe()
        result = unsigned_distribution(original)
        self.assertEqual(len(result), 0x400)
        self.assertEqual(result[0x200:0x400], original[0x200:0x400])
        pe = pefile.PE(data=result)
        self.assertEqual(pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].VirtualAddress, 0)
        self.assertEqual(pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size, 0)
        self.assertEqual(pe.OPTIONAL_HEADER.CheckSum, pe.generate_checksum())

    def test_unexpected_trailing_data_is_not_silently_deleted(self):
        with self.assertRaises(ValueError):
            unsigned_distribution(synthetic_pe() + b'other-data')

    def test_unknown_dll_is_not_patched(self):
        with self.assertRaises(ValueError):
            build(synthetic_pe(), b'not-the-game')
