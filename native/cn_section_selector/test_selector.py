"""Emulate ONLY the replacement selector on synthetic memory; never load a DLL."""
import struct
import unittest

from build_candidate import selector_bytes, START, FOUND, NEXT, TIMESTAMP, IMAGE_SIZE, CN_RVA, CN_SIZE, CN_FLAGS
import capstone
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE
from unicorn.x86_const import *

BASE, PE, SECTION, STACK = 0x180000000, 0x400000, 0x500000, 0x600000
NONVOLATILE = [UC_X86_REG_RBX, UC_X86_REG_RBP, UC_X86_REG_RSI, UC_X86_REG_RDI,
               UC_X86_REG_R12, UC_X86_REG_R13, UC_X86_REG_R14, UC_X86_REG_R15, UC_X86_REG_RSP]


def emulate(name=b".ace\0\0\0\0", flags=CN_FLAGS, rva=CN_RVA, size=CN_SIZE,
            timestamp=TIMESTAMP, count=9, image_size=IMAGE_SIZE):
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    uc.mem_map(BASE, 0x20000)
    uc.mem_map(PE, 0x1000)
    uc.mem_map(SECTION, 0x1000)
    uc.mem_map(STACK, 0x2000)
    uc.mem_write(BASE + START, selector_bytes())
    header = bytearray(0x1000)
    struct.pack_into("<I", header, 0x3C, 0x80)
    struct.pack_into("<H", header, 0x80 + 6, count)
    struct.pack_into("<I", header, 0x80 + 8, timestamp)
    struct.pack_into("<I", header, 0x80 + 0x50, image_size)
    uc.mem_write(PE, bytes(header))
    section = bytearray(0x1000)
    section[:8] = name[:8].ljust(8, b"\0")
    struct.pack_into("<II", section, 8, size, rva)
    struct.pack_into("<I", section, 0x24, flags)
    uc.mem_write(SECTION, bytes(section))
    for index, register in enumerate(NONVOLATILE):
        uc.reg_write(register, 0x76543000 + index)
    uc.reg_write(UC_X86_REG_RBX, SECTION)
    uc.reg_write(UC_X86_REG_RSP, STACK + 0x800)
    uc.mem_write(STACK + 0x880, struct.pack("<Q", PE))
    before_regs = [uc.reg_read(register) for register in NONVOLATILE]
    before_memory = [bytes(uc.mem_read(address, size)) for address, size in [(PE, 0x1000), (SECTION, 0x1000), (STACK, 0x2000)]]
    exits = []

    def stop_at_exit(engine, address, size, unused):
        if address in (BASE + FOUND, BASE + NEXT):
            exits.append(address - BASE)
            engine.emu_stop()
        elif not BASE + START <= address < BASE + FOUND:
            raise AssertionError(f"Unexpected code target {address:#x}")

    uc.hook_add(UC_HOOK_CODE, stop_at_exit)
    uc.emu_start(BASE + START, BASE + FOUND + 1, count=100)
    assert len(exits) == 1, "Must reach one original exit without extra calls"
    assert before_regs == [uc.reg_read(register) for register in NONVOLATILE], "Nonvolatile register changed"
    assert before_memory == [bytes(uc.mem_read(address, size)) for address, size in [(PE, 0x1000), (SECTION, 0x1000), (STACK, 0x2000)]], "Selector wrote memory"
    return exits[0]


class SelectorTests(unittest.TestCase):
    def test_current_cn_section_is_accepted(self):
        self.assertEqual(emulate(), FOUND)

    def test_original_rdata_path_does_not_depend_on_cn_build(self):
        self.assertEqual(emulate(name=b".rdata", timestamp=1, count=5, image_size=0x5000,
                                 flags=0xC0000040, rva=0x9000, size=123), FOUND)

    def test_other_section_names_are_not_accepted(self):
        for name in (b".text", b".data", b".pdata", b".RDATA", b".ACE", b".ace!", b".ace\0\0\0x", b".rdataxx", b".rd\0ata", b"", b"\xff\xff"):
            with self.subTest(name=name):
                self.assertEqual(emulate(name=name), NEXT)

    def test_changed_cn_metadata_is_rejected(self):
        for field, values in {
            "flags": [0x60000020, 0xC0000040, 0xE0000040, 0, CN_FLAGS | 0x2000000],
            "rva": [CN_RVA - 1, CN_RVA + 1, 0],
            "size": [CN_SIZE - 1, CN_SIZE + 1, 0],
            "timestamp": [TIMESTAMP - 1, TIMESTAMP + 1, 0],
            "count": [0, 5, 8, 10],
            "image_size": [IMAGE_SIZE - 1, IMAGE_SIZE + 1, 0],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assertEqual(emulate(**{field: value}), NEXT)

    def test_no_calls_stores_or_stack_changes_in_candidate(self):
        code = selector_bytes()
        self.assertEqual(len(code), FOUND - START)
        dis = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        instructions = list(dis.disasm(code, START))
        self.assertEqual(sum(i.size for i in instructions), len(code))
        self.assertTrue(all(i.mnemonic in ("cmp", "jne", "je", "jmp", "mov", "nop") for i in instructions))
        for i in instructions:
            if i.mnemonic == "mov":
                self.assertIn(i.op_str.split(",")[0], ("rax", "ecx"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
