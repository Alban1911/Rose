import json
import struct
import tempfile
import unittest
from pathlib import Path
from typing import NamedTuple, Optional
from unittest.mock import patch

import xxhash
import zstandard

from injection.mods.storage import ModStorageService
from party.discovery import custom_mods
from utils.core.junction import link_or_extract
from utils.core.modpkg import ModPackage, ModpkgError, _unpack_msgpack, extract_modpkg

NONE = 0xFFFFFFFF
SKIN0 = "DATA/Characters/Aatrox/Skins/Skin0/Skin0.bin"
SKIN0_HASH = 0x35FA033498B5C335
METADATA = {
    "schema_version": 5,
    "name": "old-aatrox",
    "display_name": "Old Aatrox",
    "description": "Brings him back",
    "version": "1.2.0",
    "distributor": None,
    "authors": [{"name": "Crauzer", "role": None}, {"name": "Alban", "role": "Artist"}],
    "license": {"type": "spdx", "spdx_id": "MIT"},
}

# Appendix A of docs/design/modpkg.md in LeagueToolkit/league-mod: a package
# written by the reference writer (ltk_modpkg 0.9.2)
REFERENCE_PACKAGE = bytes.fromhex(
    "5f6d6f64706b675f010000000000000002000000010000000400000062617365"
    "00000000020000005f6d6574615f2f696e666f2e6d73677061636b0044415441"
    "2f436861726163746572732f416174726f782f536b696e732f536b696e302f53"
    "6b696e302e62696e0001000000616174726f782e7761642e636c69656e740000"
    "de5a054051196f73fa0000000000000000a100000000000000a1000000000000"
    "003a0b5d1b818f8ac03a0b5d1b818f8ac000000000ffffffffffffffff35c3b5"
    "983403fa359b010000000000000005000000000000000500000000000000fddc"
    "625c55e85595fddc625c55e8559501000000000000000000000088ae73636865"
    "6d615f76657273696f6e03a46e616d65a76578616d706c65ac646973706c6179"
    "5f6e616d65a74578616d706c65ab6465736372697074696f6eaa416e20657861"
    "6d706c65a776657273696f6ea5312e302e30ab6469737472696275746f72c0a7"
    "617574686f72739182a46e616d65a7437261757a6572a4726f6c65c0a76c6963"
    "656e736582a474797065a473706478a7737064785f6964a34d495468656c6c6f"
)

# Packed by league-mod 0.2.1 (November 2025): no WAD table, each path starts
# with its WAD and the path hash covers the whole path
LEGACY_PACKAGE = bytes.fromhex(
    "5f6d6f64706b675f010000000000000003000000010000000400000062617365"
    "0000000003000000616174726f782e7761642e636c69656e745c646174615c63"
    "6861726163746572735c616174726f785c736b696e735c736b696e302e62696e"
    "006d617031312e7761642e636c69656e745c3031323334353637383961626364"
    "65662e746578005f6d6574615f2f696e666f2e6d73677061636b000000000000"
    "de5a054051196f73570100000000000000c100000000000000c1000000000000"
    "007a7a0c0c638cac9c7a7a0c0c638cac9c02000000ffffffffffffffff6e5b5f"
    "94e39fed131802000000000000010e00000000000000050000000000000041bf"
    "ef8271bd46fcfddc625c55e855950000000000000000ffffffff62b3d498f298"
    "c1682602000000000000010c000000000000000300000000000000bf97184754"
    "b7a75f5273f223c232cc240100000000000000ffffffff89ae736368656d615f"
    "76657273696f6e01a46e616d65a66c6567616379ac646973706c61795f6e616d"
    "65a64c6567616379ab6465736372697074696f6eaa4f6c64206c61796f7574a7"
    "76657273696f6ea5302e312e30ab6469737472696275746f72c0a7617574686f"
    "72739182a46e616d65a7437261757a6572a4726f6c65c0a76c6963656e736581"
    "a474797065a46e6f6e65a66c61796572739183a46e616d65a462617365a87072"
    "696f7269747900ab6465736372697074696f6ea44261736528b52ffd00582900"
    "0068656c6c6f28b52ffd0058190000686578"
)

# Packed by league-mod 0.2.0 (September 2025): metadata inline in the header
EARLY_PACKAGE = bytes.fromhex(
    "5f6d6f64706b675f010000000000000002000000010000000400000062617365"
    "0000000002000000616174726f782e7761642e636c69656e745c646174615c63"
    "6861726163746572735c616174726f785c736b696e735c736b696e302e62696e"
    "006d617031312e7761642e636c69656e745c3031323334353637383961626364"
    "65662e7465780000000000050000006561726c79050000004561726c790a0000"
    "004f6c64206c61796f757405000000302e312e30000000000100000007000000"
    "437261757a65720000000000000000006e5b5f94e39fed134a01000000000000"
    "010e00000000000000050000000000000041bfef8271bd46fcfddc625c55e855"
    "950000000000000000ffffffff62b3d498f298c1685801000000000000010c00"
    "0000000000000300000000000000bf97184754b7a75f5273f223c232cc240100"
    "000000000000ffffffff28b52ffd005829000068656c6c6f28b52ffd00581900"
    "00686578"
)


class Chunk(NamedTuple):
    path: str
    content: bytes
    layer: Optional[str] = "base"
    wad: Optional[str] = "aatrox.wad.client"
    zstd: bool = False
    path_hash: Optional[int] = None


def msgpack(value) -> bytes:
    """Just enough of a MessagePack writer for metadata documents"""
    if value is None:
        return b"\xc0"
    if isinstance(value, bool):
        return b"\xc3" if value else b"\xc2"
    if isinstance(value, int):
        return bytes([value]) if 0 <= value < 0x80 else b"\xd3" + struct.pack(">q", value)
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return b"\xd9" + bytes([len(raw)]) + raw
    if isinstance(value, list):
        return b"\xdc" + struct.pack(">H", len(value)) + b"".join(map(msgpack, value))
    return b"\xde" + struct.pack(">H", len(value)) + b"".join(msgpack(k) + msgpack(v) for k, v in value.items())


def build_package(chunks, layers=(("base", 0),), metadata=METADATA, tweak=None) -> bytes:
    """Write a format version 1 package; *tweak* may edit each record's fields"""
    chunks = list(chunks)
    if metadata is not None:
        chunks.insert(0, Chunk("_meta_/info.msgpack", msgpack(metadata), layer=None, wad=None))
    paths = list(dict.fromkeys(chunk.path for chunk in chunks))
    wads = list(dict.fromkeys(chunk.wad for chunk in chunks if chunk.wad is not None))
    layer_names = [name for name, _ in layers]

    head = bytearray(b"_modpkg_" + struct.pack("<III", 1, 0, len(chunks)))
    head += struct.pack("<I", len(layers))
    for name, priority in layers:
        head += struct.pack("<I", len(name.encode())) + name.encode() + struct.pack("<i", priority)
    for table in (paths, wads):
        head += struct.pack("<I", len(table)) + b"".join(name.encode() + b"\0" for name in table)
    head += b"\0" * (-len(head) % 8)

    toc = bytearray()
    data = bytearray()
    data_start = len(head) + 61 * len(chunks)
    for index, chunk in enumerate(chunks):
        stored = zstandard.ZstdCompressor().compress(chunk.content) if chunk.zstd else chunk.content
        fields = [
            chunk.path_hash if chunk.path_hash is not None else xxhash.xxh64_intdigest(chunk.path.encode().lower()),
            data_start + len(data),
            1 if chunk.zstd else 0,
            len(stored),
            len(chunk.content),
            xxhash.xxh3_64_intdigest(stored),
            xxhash.xxh3_64_intdigest(chunk.content),
            paths.index(chunk.path),
            NONE if chunk.layer is None else layer_names.index(chunk.layer),
            NONE if chunk.wad is None else wads.index(chunk.wad),
        ]
        if tweak:
            tweak(index, fields)
        toc += struct.pack("<QQBQQQQIII", *fields)
        data += stored
    return bytes(head + toc + data)


class ModpkgFormatTests(unittest.TestCase):
    def test_reads_the_reference_package(self):
        package = ModPackage(REFERENCE_PACKAGE)
        self.assertEqual(package.metadata(), {
            "schema_version": 3,
            "name": "example",
            "display_name": "Example",
            "description": "An example",
            "version": "1.0.0",
            "distributor": None,
            "authors": [{"name": "Crauzer", "role": None}],
            "license": {"type": "spdx", "spdx_id": "MIT"},
        })
        files = dict(package.iter_files())
        self.assertEqual(list(files), ["META/info.json", "WAD/aatrox.wad.client/35fa033498b5c335.bin"])
        self.assertEqual(files["WAD/aatrox.wad.client/35fa033498b5c335.bin"], b"hello")
        self.assertEqual(json.loads(files["META/info.json"]), {
            "Name": "Example",
            "Author": "Crauzer",
            "Version": "1.0.0",
            "Description": "An example",
        })

    def test_reads_packages_from_league_mod_0_2_1(self):
        files = dict(ModPackage(LEGACY_PACKAGE).iter_files())
        skin0_hash = xxhash.xxh64_intdigest(b"data/characters/aatrox/skins/skin0.bin")
        self.assertEqual(sorted(files), [
            "META/info.json",
            f"WAD/aatrox.wad.client/{skin0_hash:016x}.bin",
            "WAD/map11.wad.client/0123456789abcdef.tex",
        ])
        self.assertEqual(files[f"WAD/aatrox.wad.client/{skin0_hash:016x}.bin"], b"hello")
        self.assertEqual(files["WAD/map11.wad.client/0123456789abcdef.tex"], b"hex")
        self.assertEqual(json.loads(files["META/info.json"])["Name"], "Legacy")

    def test_refuses_packages_from_earlier_league_mod_versions(self):
        with self.assertRaisesRegex(ModpkgError, "early LeagueToolkit version"):
            ModPackage(EARLY_PACKAGE)

    def test_unpacks_the_base_layer_into_wad_folders(self):
        package = ModPackage(build_package([
            Chunk(SKIN0, b"skin" * 1000, zstd=True),
            Chunk("ASSETS/Characters/Aatrox/Skins/Base/Aatrox.TEX", b"texture", wad="Aatrox.wad.client"),
            # Hex-named: the path hash is the value the name spells
            Chunk("0123456789abcdef.dds", b"unknown", path_hash=0x0123456789ABCDEF),
            # One file shared by two WADs lands in both
            Chunk("data/shared.bin", b"shared", wad="map11.wad.client"),
            Chunk("data/shared.bin", b"shared", wad="map12.wad.client"),
            Chunk("assets/hd.tex", b"hd", layer="high-res"),
            Chunk("data/override.bin", b"no wad", wad=None),
            Chunk("_meta_/thumbnail.webp", b"RIFF-webp", layer=None, wad=None),
        ], layers=(("base", 0), ("high-res", 10))))

        files = dict(package.iter_files())
        self.assertEqual(sorted(files), [
            "META/image.webp",
            "META/info.json",
            "WAD/aatrox.wad.client/0123456789abcdef.dds",
            f"WAD/aatrox.wad.client/{SKIN0_HASH:016x}.bin",
            f"WAD/aatrox.wad.client/{xxhash.xxh64_intdigest(b'assets/characters/aatrox/skins/base/aatrox.tex'):016x}.tex",
            f"WAD/map11.wad.client/{xxhash.xxh64_intdigest(b'data/shared.bin'):016x}.bin",
            f"WAD/map12.wad.client/{xxhash.xxh64_intdigest(b'data/shared.bin'):016x}.bin",
        ])
        self.assertEqual(package.file_paths(), sorted(files))
        self.assertEqual(files[f"WAD/aatrox.wad.client/{SKIN0_HASH:016x}.bin"], b"skin" * 1000)
        self.assertEqual(files["META/image.webp"], b"RIFF-webp")
        self.assertEqual(json.loads(files["META/info.json"]), {
            "Name": "Old Aatrox",
            "Author": "Crauzer, Alban",
            "Version": "1.2.0",
            "Description": "Brings him back",
        })
        self.assertEqual(package.optional_layers, ["high-res"])
        self.assertEqual(package.unplaced_file_count, 1)

    def test_metadata_is_optional(self):
        package = ModPackage(build_package([Chunk(SKIN0, b"skin")], metadata=None))
        self.assertEqual(package.metadata(), {})
        info = json.loads(dict(package.iter_files())["META/info.json"])
        self.assertEqual(info, {"Name": "", "Author": "", "Version": "", "Description": ""})

        # Early packages named the chunk _meta_/metadata.msgpack
        legacy = ModPackage(build_package([
            Chunk(SKIN0, b"skin"),
            Chunk("_meta_/metadata.msgpack", msgpack({"name": "legacy"}), layer=None, wad=None),
        ], metadata=None))
        self.assertEqual(legacy.metadata(), {"name": "legacy"})

    def test_refuses_names_that_escape_the_mod_folder(self):
        for name in ("../x.bin", "a/../../x.bin", "a\\..\\..\\x.bin", "/x.bin", "\\x.bin", "C:x.bin"):
            with self.subTest(path=name), self.assertRaises(ModpkgError):
                ModPackage(build_package([Chunk(name, b"x")]))
        with self.assertRaises(ModpkgError):
            ModPackage(build_package([Chunk(SKIN0, b"x", wad="../../pwned.wad.client")]))
        with self.assertRaises(ModpkgError):
            ModPackage(build_package([Chunk(SKIN0, b"x")], layers=(("base", 0), ("..", 1))))
        # Only real escapes are refused
        ModPackage(build_package([Chunk("..bin", b"x"), Chunk("./a/b..c", b"y")]))

    def test_refuses_damaged_packages(self):
        valid = build_package([Chunk(SKIN0, b"skin")])
        damaged = {
            "not a package": b"PK\x03\x04" + valid[4:],
            "unknown format version": valid[:8] + struct.pack("<I", 2) + valid[12:],
            "truncated tables": valid[:40],
            "truncated table of contents": valid[:130],
            "truncated data": valid[:-1],
            "empty": b"",
        }
        for label, data in damaged.items():
            with self.subTest(label), self.assertRaises(ModpkgError):
                ModPackage(data)

        def compression(index, fields):
            fields[2] = 2

        def past_the_end(index, fields):
            fields[3] = 1 << 40

        def bad_path_index(index, fields):
            fields[7] = 99

        for tweak in (compression, past_the_end, bad_path_index):
            with self.subTest(tweak.__name__), self.assertRaises(ModpkgError):
                ModPackage(build_package([Chunk(SKIN0, b"skin")], tweak=tweak))

        with self.assertRaises(ModpkgError):
            ModPackage(build_package([Chunk(SKIN0, b"skin", layer="extra")], layers=(("extra", 1),)))

    def test_refuses_two_contents_for_one_path(self):
        with self.assertRaises(ModpkgError):
            ModPackage(build_package([
                Chunk(SKIN0, b"one", wad="aatrox.wad.client"),
                Chunk(SKIN0, b"two", wad="aatrox.en_us.wad.client"),
            ]))

    def test_checks_file_contents(self):
        data = bytearray(build_package([Chunk(SKIN0, b"skin")]))
        data[-1] ^= 0xFF
        with self.assertRaises(ModpkgError):
            list(ModPackage(bytes(data)).iter_files())

        def wrong_size(index, fields):
            if fields[2] == 1:
                fields[4] += 1

        package = ModPackage(build_package([Chunk(SKIN0, b"skin" * 100, zstd=True)], tweak=wrong_size))
        with self.assertRaises(ModpkgError):
            list(package.iter_files())

        def not_a_frame(index, fields):
            if fields[2] == 0 and index == 1:
                fields[2] = 1

        package = ModPackage(build_package([Chunk(SKIN0, b"skin")], tweak=not_a_frame))
        with self.assertRaises(ModpkgError):
            list(package.iter_files())


class MsgpackTests(unittest.TestCase):
    def test_decodes_the_formats_a_document_can_use(self):
        data = (
            b"\x8a"
            b"\xa1a\x7f"                                  # positive fixint
            b"\xa1b\xff"                                  # negative fixint
            b"\xa1c\xd1\xfc\x18"                          # int16
            b"\xa1d\xcd\x01\x00"                          # uint16
            b"\xa1e\xcb" + struct.pack(">d", 1.5) +       # float64
            b"\xa1f\xc4\x02\x00\x01"                      # bin8
            b"\xa1g\xd6\x01\x00\x00\x00\x00"              # fixext4, skipped
            b"\xa1h\xdc\x00\x02\xc3\xc2"                  # array16
            b"\xa1i\xda\x00\x03\xc3\xa9t"                 # str16
            b"\xa1j\xde\x00\x01\xa1k\xc0"                 # map16
        )
        self.assertEqual(_unpack_msgpack(data), {
            "a": 127, "b": -1, "c": -1000, "d": 256, "e": 1.5, "f": b"\x00\x01",
            "g": None, "h": [True, False], "i": "ét", "j": {"k": None},
        })

    def test_refuses_unreadable_documents(self):
        for data in (b"", b"\x82\xa1a", b"\xdb\xff\xff\xff\xff", b"\xc1", b"\x81\x90\x01", b"\x91" * 100 + b"\xc0"):
            with self.subTest(data=data), self.assertRaises(ModpkgError):
                _unpack_msgpack(data)


class ModpkgModTests(unittest.TestCase):
    """.modpkg files are custom mods like .zip and .fantome archives"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.package = self.root / "old-aatrox_1.2.0.modpkg"
        self.package.write_bytes(build_package([
            Chunk(SKIN0, b"skin" * 1000, zstd=True),
            Chunk("_meta_/thumbnail.webp", b"RIFF-webp", layer=None, wad=None),
        ]))

    def test_extracts_a_folder_mod_tools_reads(self):
        target = self.root / "mod"
        extract_modpkg(self.package, target)
        self.assertTrue((target / "META" / "info.json").is_file())
        self.assertEqual((target / "META" / "image.webp").read_bytes(), b"RIFF-webp")
        self.assertEqual(
            (target / "WAD" / "aatrox.wad.client" / f"{SKIN0_HASH:016x}.bin").read_bytes(),
            b"skin" * 1000,
        )

    def test_a_package_without_game_files_is_refused(self):
        empty = self.root / "empty.modpkg"
        empty.write_bytes(build_package([Chunk("assets/hd.tex", b"hd", layer="high-res")],
                                        layers=(("base", 0), ("high-res", 1))))
        with self.assertRaises(ModpkgError):
            extract_modpkg(empty, self.root / "empty")

    def test_imports_into_mod_storage(self):
        storage = ModStorageService(mods_root=self.root / "mods")
        mod_folder, _manifest, mod_name = storage.import_mod_file(266, self.package, [266001])
        self.assertEqual(mod_name, "old-aatrox_1.2.0")
        self.assertTrue((mod_folder / "WAD" / "aatrox.wad.client" / f"{SKIN0_HASH:016x}.bin").is_file())
        listed = storage.list_mods_for_skin(266001)
        self.assertEqual([entry.mod_name for entry in listed], ["old-aatrox_1.2.0"])

        category_folder, _ = storage.import_category_mod_file("others", self.package)
        self.assertTrue((category_folder / "META" / "info.json").is_file())

    def test_a_package_dropped_in_storage_is_listed(self):
        storage = ModStorageService(mods_root=self.root / "mods")
        skin_dir = storage.get_skin_dir(266001)
        skin_dir.mkdir(parents=True)
        (skin_dir / self.package.name).write_bytes(self.package.read_bytes())
        self.assertEqual(
            [entry.mod_name for entry in storage.list_mods_for_skin(266001)],
            ["old-aatrox_1.2.0"],
        )

    def test_links_into_the_injection_folder(self):
        dest = self.root / "injection" / "mods" / self.package.stem
        dest.parent.mkdir(parents=True)
        link_or_extract(self.package, dest, cache_dir=self.root / "cache")
        self.assertTrue((dest / "META" / "info.json").is_file())
        self.assertTrue((dest / "WAD" / "aatrox.wad.client" / f"{SKIN0_HASH:016x}.bin").is_file())

    def test_party_hash_matches_the_imported_folder(self):
        folder = self.root / "imported"
        extract_modpkg(self.package, folder)
        with patch.object(custom_mods, "get_user_data_dir", return_value=self.root):
            package_hash, _ = custom_mods.mod_hashes(self.package)
            folder_hash, _ = custom_mods.mod_hashes(folder)
        self.assertIsNotNone(package_hash)
        self.assertEqual(package_hash, folder_hash)


if __name__ == "__main__":
    unittest.main()
