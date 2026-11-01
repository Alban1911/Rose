import struct
import tempfile
import unittest
from pathlib import Path

from injection.tools.patcher import LtkPatcherStatus, read_dll_eol, read_game_build

EOL = 1_791_097_200  # 2026-10-04


def write_game(game_dir: Path, build: int, name: str = "League of Legends.exe") -> None:
    """A minimal PE header carrying build as its TimeDateStamp."""
    header = bytearray(0x200)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, 0x80)
    header[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<I", header, 0x88, build)
    (game_dir / name).write_bytes(bytes(header))


def patcher_pe(payload: bytes, legacy_eol=None) -> bytes:
    data = bytearray(0x400 + len(payload))
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", data, 0x86, 2)
    for index, (name, rva, size, offset) in enumerate((
        (b".text", 0x1000, 0x200, 0x200),
        (b".rdata", 0x2000, len(payload), 0x400),
    )):
        entry = 0x98 + index * 40
        data[entry:entry + len(name)] = name
        struct.pack_into("<III", data, entry + 12, rva, size, offset)
    data[0x400:] = payload
    if legacy_eol is not None:
        data[0x220:0x22B] = b"\x3D" + struct.pack("<I", legacy_eol) + b"\x0F\x86\0\0\0\0"
        data[0x240:0x247] = b"\x48\x8D\x15" + struct.pack("<i", 0x2000 - 0x1047)
    return bytes(data)


class PatcherMetadataTests(unittest.TestCase):
    def read(self, data):
        with tempfile.TemporaryDirectory() as temp:
            dll = Path(temp) / "ltk_patcher_dll.dll"
            dll.write_bytes(data)
            return read_dll_eol(dll)

    def test_explicit_timestamp_does_not_need_the_old_comparison(self):
        self.assertEqual(self.read(patcher_pe(b"CSLOL_EOL_TIMESTAMP=1794988800\0")), 1794988800)

    def test_timestamp_keeps_the_pe_build_range(self):
        for value in (0, 0xFFFFFFFF):
            with self.subTest(value=value):
                payload = f"CSLOL_EOL_TIMESTAMP={value}\0".encode("ascii")
                self.assertEqual(self.read(patcher_pe(payload)), value)

    def test_explicit_timestamp_takes_precedence_over_code_matching(self):
        payload = b"end of life reached, please update: \0CSLOL_EOL_TIMESTAMP=1794988800\0"
        self.assertEqual(self.read(patcher_pe(payload, EOL)), 1794988800)

    def test_old_binaries_without_metadata_still_use_the_comparison(self):
        self.assertEqual(self.read(patcher_pe(b"end of life reached, please update: \0", EOL)), EOL)

    def test_malformed_or_ambiguous_metadata_is_refused(self):
        for value in (b"", b"-1", b"123x", b"4294967296", b"12345678901"):
            with self.subTest(value=value):
                self.assertIsNone(self.read(patcher_pe(b"CSLOL_EOL_TIMESTAMP=" + value + b"\0")))
        self.assertIsNone(self.read(patcher_pe(b"CSLOL_EOL_TIMESTAMP=1794988800")))
        self.assertIsNone(self.read(patcher_pe(b"CSLOL_EOL_TIMESTAMP=1\0CSLOL_EOL_TIMESTAMP=2\0")))

    def test_invalid_metadata_does_not_fall_back_to_an_unrelated_comparison(self):
        payload = b"end of life reached, please update: \0CSLOL_EOL_TIMESTAMP=invalid\0"
        self.assertIsNone(self.read(patcher_pe(payload, EOL)))

    def test_metadata_still_requires_a_pe_section(self):
        self.assertIsNone(self.read(b"CSLOL_EOL_TIMESTAMP=1794988800\0"))
        self.assertIsNone(self.read(b"MZ"))
        data = bytearray(patcher_pe(b""))
        marker = b"CSLOL_EOL_TIMESTAMP=1794988800\0"
        data[0x50:0x50 + len(marker)] = marker
        self.assertIsNone(self.read(bytes(data)))

    def test_metadata_must_be_inside_a_complete_section(self):
        payload = b"CSLOL_EOL_TIMESTAMP=1794988800\0"
        for size in (len(payload) - 1, len(payload) + 1):
            with self.subTest(size=size):
                data = bytearray(patcher_pe(payload))
                struct.pack_into("<I", data, 0x98 + 40 + 16, size)
                self.assertIsNone(self.read(bytes(data)))


class PatcherEndOfLifeTests(unittest.TestCase):
    """The DLL compares its end of life against the game build, not today's date"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.game_dir = Path(temp_dir.name)
        self.status = LtkPatcherStatus(host=Path(), dll=Path(), missing=[], eol=EOL)

    def test_a_game_built_before_the_end_of_life_is_supported(self):
        write_game(self.game_dir, EOL - 86400)
        self.assertFalse(self.status.expired_for(self.game_dir))

    def test_a_game_built_after_the_end_of_life_is_refused(self):
        write_game(self.game_dir, EOL + 1)
        self.assertTrue(self.status.expired_for(self.game_dir))

    def test_the_other_game_executable_name_is_read(self):
        write_game(self.game_dir, EOL + 1, "League of Legends (TM) Client.exe")
        self.assertEqual(read_game_build(self.game_dir), EOL + 1)

    def test_an_unknown_game_is_not_refused(self):
        self.assertFalse(self.status.expired_for(None))
        self.assertFalse(self.status.expired_for(self.game_dir))
        (self.game_dir / "League of Legends.exe").write_bytes(b"not a PE file")
        self.assertFalse(self.status.expired_for(self.game_dir))


if __name__ == '__main__':
    unittest.main()
