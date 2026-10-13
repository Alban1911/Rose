"""Build an isolated CN section-selector candidate; never load or install it.

The original LTK pattern search and initialization remain untouched. This is
not proof of runtime compatibility: CN restores some code only at runtime.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parent
import pefile

DLL_SHA256 = "6d419057e6667994ba752ad0fb089b363db98267618644d7f7b6632441a21d74"
GAME_SHA256 = "ee3c887b4579aeab12ca77b2a43cc1cc3411a8aa30bc43d2dfea856f6ce497c8"
BLOCK_SHA256 = "a8c24b5289eb9285a646553865460f41721d82b5287cd069086d078a544adf40"
START, FOUND, NEXT = 0x14BB1, 0x14C55, 0x14BA3
TIMESTAMP, SECTION_COUNT, IMAGE_SIZE = 0x6AC0019A, 9, 0x219C000
CN_RVA, CN_SIZE, CN_FLAGS = 0x1A07000, 0x44A782, 0x40000040


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def selector_bytes():
    """A bounded replacement for the original name-only selection block.

    No calls, memory writes, injected code, or changes to verification flags.
    Existing .rdata behavior is retained; the extra .ace case is build-bound.
    The original instruction immediately after FOUND initializes downstream
    working registers, independently of the removed UTF-8/name comparison.
    """
    code = bytearray()
    fixups, labels = [], {}

    def emit(raw):
        code.extend(bytes.fromhex(raw))

    def imm(value):
        code.extend(struct.pack("<I", value))

    def branch(opcode, target):
        emit(opcode)
        fixups.append((len(code), target))
        code.extend(b"\0" * 4)

    # Exact original name: .rdata\0\0.
    emit("81 3b"); imm(int.from_bytes(b".rda", "little"))
    branch("0f 85", "cn")
    emit("81 7b 04"); imm(int.from_bytes(b"ta\0\0", "little"))
    branch("0f 84", FOUND)
    branch("e9", NEXT)

    labels["cn"] = START + len(code)
    emit("81 3b"); imm(int.from_bytes(b".ace", "little"))
    branch("0f 85", NEXT)
    emit("81 7b 04"); imm(0)
    branch("0f 85", NEXT)
    for offset, value in [(0x24, CN_FLAGS), (0x0C, CN_RVA), (0x08, CN_SIZE)]:
        emit(f"81 7b {offset:02x}"); imm(value)
        branch("0f 85", NEXT)

    # rbx is the current section; [rsp+0x80] is the original main-module base.
    # Independently refuse a changed build at runtime, not just during build.
    emit("48 8b 84 24 80 00 00 00")  # mov rax, [rsp+0x80]
    emit("8b 48 3c")                 # mov ecx, [rax+e_lfanew]
    emit("81 7c 08 08"); imm(TIMESTAMP)
    branch("0f 85", NEXT)
    emit("66 83 7c 08 06 09")       # cmp word [NT+6], 9
    branch("0f 85", NEXT)
    emit("81 7c 08 50"); imm(IMAGE_SIZE)
    branch("0f 85", NEXT)
    branch("e9", FOUND)

    if len(code) > FOUND - START:
        raise ValueError("Selector does not fit the original bounded block")
    for offset, target in fixups:
        target = labels[target] if isinstance(target, str) else target
        struct.pack_into("<i", code, offset, target - (START + offset + 4))
    return bytes(code).ljust(FOUND - START, b"\x90")


def inspect_game(data):
    """Check disk identity and pattern evidence without mapping/executing code."""
    if sha256(data) != GAME_SHA256:
        raise ValueError("Unexpected game executable: candidate is for the exact observed build only")
    pe = pefile.PE(data=data, fast_load=True)
    assert pe.FILE_HEADER.Machine == 0x8664
    assert pe.FILE_HEADER.TimeDateStamp == TIMESTAMP
    assert pe.FILE_HEADER.NumberOfSections == SECTION_COUNT
    assert pe.OPTIONAL_HEADER.SizeOfImage == IMAGE_SIZE
    matches = []
    pattern = re.compile(bytes.fromhex("01 00 00 00 00 00 00 00") + b".{8}"
                         + bytes.fromhex("7f 00 00 00 00 00 00 00 20 00 00 00 00 00 00 00"), re.S)
    for section in pe.sections:
        raw = section.get_data()
        for match in pattern.finditer(raw):
            pos = match.start()
            pointer = struct.unpack_from("<Q", raw, pos + 8)[0]
            rva = pointer - pe.OPTIONAL_HEADER.ImageBase
            if not 0 <= rva < IMAGE_SIZE or pe.get_data(rva, 8) != b"openssl\0":
                continue
            functions = [struct.unpack_from("<Q", raw, pos + offset)[0]
                         - pe.OPTIONAL_HEADER.ImageBase for offset in (0xA0, 0xA8)]
            matches.append((section, section.VirtualAddress + pos, functions))
    if len(matches) != 1:
        raise ValueError("Expected exactly one OpenSSL table, not an ambiguous guessed section")
    section, table_rva, functions = matches[0]
    assert section.Name == b".ace\0\0\0\0"
    assert (section.VirtualAddress, section.Misc_VirtualSize, section.Characteristics) == (CN_RVA, CN_SIZE, CN_FLAGS)
    function_evidence = []
    for rva in functions:
        target = pe.get_section_by_rva(rva)
        assert target is not None and target.Characteristics & 0x20000000
        function_evidence.append({"rva": hex(rva), "executable_section": True,
                                  "file_backed": rva - target.VirtualAddress < target.SizeOfRawData})
    return {"sha256": GAME_SHA256, "table_rva": hex(table_rva), "functions": function_evidence,
                     "runtime_unknown": "Disk inspection cannot establish readiness of virtual-only function targets; see README for limited user-confirmed runtime evidence."}


def build(original, game):
    if sha256(original) != DLL_SHA256:
        raise ValueError("Unexpected original LTK DLL; refusing to patch a different or already modified file")
    game_evidence = inspect_game(game)
    pe = pefile.PE(data=original, fast_load=True)
    offset = pe.get_offset_from_rva(START)
    assert pe.get_offset_from_rva(FOUND) == offset + FOUND - START
    old = original[offset:offset + FOUND - START]
    assert sha256(old) == BLOCK_SHA256
    replacement = selector_bytes()
    patched = original[:offset] + replacement + original[offset + len(replacement):]
    assert len(patched) == len(original)
    assert patched[:offset] == original[:offset]
    assert patched[offset + len(replacement):] == original[offset + len(replacement):]
    return patched, {"original_sha256": DLL_SHA256, "candidate_sha256": sha256(patched),
                     "changed_block_rva": hex(START), "block_size": len(replacement),
                     "game": game_evidence, "live_validation": "NOT_RUN_DO_NOT_AUTO_DEPLOY",
                     "digital_signature": "Invalidated by modification (HashMismatch). This is not an official signed build. Do not disable signature enforcement to load it.",
                     "verification_flags": "unchanged", "original_pattern_and_hook": "unchanged"}


def unsigned_distribution(patched):
    """Remove the publisher certificate as required by LTK-PATCHER-LICENSE.

    This changes no mapped section contents. Never sign on the publisher's
    behalf or disable signature enforcement to load the output.
    """
    pe = pefile.PE(data=patched, fast_load=True)
    security = pe.OPTIONAL_HEADER.DATA_DIRECTORY[4]
    start, size = security.VirtualAddress, security.Size
    if not size or start + size != len(patched):
        raise ValueError('Unexpected certificate layout; refusing to strip it')
    end_of_sections = max(s.PointerToRawData + s.SizeOfRawData for s in pe.sections)
    if start < end_of_sections:
        raise ValueError('Certificate overlaps mapped section data')
    result = bytearray(patched[:start])
    struct.pack_into('<II', result, security.get_file_offset(), 0, 0)
    checksum_offset = pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum')
    struct.pack_into('<I', result, checksum_offset, 0)
    checksum = pefile.PE(data=bytes(result), fast_load=True).generate_checksum()
    struct.pack_into('<I', result, checksum_offset, checksum)
    for section in pe.sections:
        at, length = section.PointerToRawData, section.SizeOfRawData
        if result[at:at + length] != patched[at:at + length]:
            raise ValueError('Signature removal changed section contents')
    return bytes(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dll', required=True, type=Path, help='Exact original LTK 1.27.2 DLL')
    parser.add_argument('--game', required=True, type=Path, help='Exact CN 16.20.824.8524 game image')
    parser.add_argument('--output', required=True, type=Path, help='New standalone output, never installed automatically')
    args = parser.parse_args()
    if not __debug__:
        parser.error('Do not run this experimental builder with Python optimization enabled')
    if args.output.resolve() in (args.dll.resolve(), args.game.resolve()):
        parser.error('Output must not overwrite either input')
    patched, report = build(args.dll.read_bytes(), args.game.read_bytes())
    unsigned = unsigned_distribution(patched)
    report['candidate_sha256_before_signature_removal'] = report.pop('candidate_sha256')
    report['candidate_sha256'] = sha256(unsigned)
    report['digital_signature'] = 'Publisher certificate removed; unsigned, unofficial output'
    report['live_validation'] = 'Same selector privately user-tested; unsigned distribution output NOT live-tested'
    # Exclusive creation prevents accidental overwrite of installed/previous DLLs.
    with args.output.open('xb') as output:
        output.write(unsigned)
    print(json.dumps(report, indent=2))
