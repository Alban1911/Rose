#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LTK patcher binaries (ltk_patcher_host.exe + ltk_patcher_dll.dll).

Users provide their own copy (e.g. from an LTK Manager install); Rose does
not ship or pin them. The DLL refuses game builds newer than its built-in
end-of-life date, so we read that date and the game's build date to fail
early instead of silently injecting nothing. A DLL past that date still works
until League itself updates.

A download manager that renames the file to "ltk_patcher_dll(1).dll" leaves the
bytes alone and used to make the pair undetectable, so both are also recognised
by content and renamed back: the host loads its hook by the literal name
"ltk_patcher_dll.dll" and cannot work with a copy called anything else.
"""

import hashlib
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import GAME_EXECUTABLE_NAMES
from utils.core.logging import get_logger

log = get_logger()

LTK_PATCHER_HOST = "ltk_patcher_host.exe"
LTK_PATCHER_DLL = "ltk_patcher_dll.dll"

# SHA-256 of one specific LeagueToolkit build (ltk-manager's
# src-tauri/resources). An exact match, so it stays the fast path -- but these
# binaries are replaced often (11 host updates between July and October 2026,
# and the DLL grew from 764160 to 1013152 bytes), so a hash alone would stop
# matching whatever build the user's LTK Manager ships. The signatures below are
# what carries recognition across builds.
KNOWN_HOST_SHA256 = frozenset({
    "23fa1aaeda1a0c743da44227f179084e1fb81c7cd262144a3c8604ffc49d3bc1",
})
KNOWN_DLL_SHA256 = frozenset({
    "6d419057e6667994ba752ad0fb089b363db98267618644d7f7b6632441a21d74",
})

# Strings baked into the patcher host in every release checked since July 2026:
# the hook DLL it loads and the named pipe it talks over. All of them together
# are specific enough that an unrelated .exe will not match.
_HOST_SIGNATURES = (b"ltk_patcher_dll.dll", b"ltk-patcher-pipe")

# Log line the DLL prints when the game build is newer than its EOL date
_EOL_MESSAGE = b"end of life reached, please update: "
# How far before the message reference to look for the EOL comparison
_EOL_SEARCH_WINDOW = 0x100


@dataclass
class LtkPatcherStatus:
    host: Path
    dll: Path
    missing: list
    eol: Optional[int]  # Unix timestamp, None if it could not be read

    def expired_for(self, game_dir: Optional[Path]) -> bool:
        """True when the DLL refuses the game installed in game_dir.

        Unknown game builds count as supported: the DLL still reports a
        refused build itself when the game starts.
        """
        if self.eol is None or game_dir is None:
            return False
        build = read_game_build(game_dir)
        return build is not None and build > self.eol


def _file_sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _carries_eol_signature(path: Path) -> bool:
    """True when the file is an LTK patcher DLL, whatever its name or build.

    The EOL message is compiled into the DLL and present in every release since
    at least July 2026, so it recognises builds the pinned hash has moved past.
    """
    try:
        return _EOL_MESSAGE in path.read_bytes()
    except OSError:
        return False


def _looks_like_patcher_host(path: Path) -> bool:
    """True when the file is an LTK patcher host, whatever its name or build.

    The host has no EOL message of its own, so it is recognised by the strings
    it cannot work without: the hook DLL it loads and its named pipe. Without
    this a renamed host would only be found for the one build pinned above.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return False
    return all(marker in data for marker in _HOST_SIGNATURES)


def _restore_name(found: Path, canonical: Path) -> Path:
    """Put the canonical name back; returns the path the caller should use.

    ltk_patcher_host.exe carries the literal string "ltk_patcher_dll.dll" and
    loads it with LoadLibraryExW, so a copy that merely kept a mangled name
    would be found by Rose and still fail to attach in the host.
    """
    try:
        found.replace(canonical)
    except OSError as e:
        log.warning(f"[LTK] Could not rename {found.name} to {canonical.name}: {e}")
        return found
    log.info(f"[LTK] Renamed {found.name} back to {canonical.name}")
    return canonical


def _files_with_suffix(tools_dir: Path, suffix: str):
    """Sorted files of one kind; an unreadable folder yields nothing to match."""
    try:
        entries = sorted(tools_dir.iterdir())
    except OSError:
        return []
    return [e for e in entries if e.is_file() and e.suffix.lower() == suffix]


def resolve_ltk_host(tools_dir: Path) -> Optional[Path]:
    """The patcher host, restored to its real name when a download renamed it."""
    direct = tools_dir / LTK_PATCHER_HOST
    if direct.is_file():
        return direct
    for entry in _files_with_suffix(tools_dir, ".exe"):
        if _file_sha256(entry) in KNOWN_HOST_SHA256 or _looks_like_patcher_host(entry):
            return _restore_name(entry, direct)
    return None


def resolve_ltk_dll(tools_dir: Path) -> Optional[Path]:
    """The hook DLL, restored to its real name when a download renamed it."""
    direct = tools_dir / LTK_PATCHER_DLL
    if direct.is_file():
        return direct
    for entry in _files_with_suffix(tools_dir, ".dll"):
        if _file_sha256(entry) in KNOWN_DLL_SHA256 or _carries_eol_signature(entry):
            return _restore_name(entry, direct)
    return None


def check_ltk_patcher(tools_dir: Path) -> LtkPatcherStatus:
    """Report which LTK patcher files are missing and the DLL's EOL date."""
    host = resolve_ltk_host(tools_dir) or tools_dir / LTK_PATCHER_HOST
    dll = resolve_ltk_dll(tools_dir) or tools_dir / LTK_PATCHER_DLL
    missing = [name for name, path in ((LTK_PATCHER_HOST, host), (LTK_PATCHER_DLL, dll))
               if not path.is_file()]
    eol = read_dll_eol(dll) if dll.is_file() else None
    return LtkPatcherStatus(host=host, dll=dll, missing=missing, eol=eol)


def describe_ltk_patcher_files(tools_dir: Path) -> str:
    """Size, date and SHA-256 of each patcher file, to tell copies apart in logs.

    Users bring their own copy from different LTK Manager releases, so a
    failure report is only comparable when it says which files were used.
    """
    parts = []
    for name, path in ((LTK_PATCHER_HOST, resolve_ltk_host(tools_dir)),
                       (LTK_PATCHER_DLL, resolve_ltk_dll(tools_dir))):
        if path is None:
            parts.append(f"{name}: missing")
            continue
        try:
            data = path.read_bytes()
            modified = time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))
        except OSError as e:
            parts.append(f"{name}: unreadable ({e})")
            continue
        parts.append(f"{path.name}: {len(data)} bytes, modified {modified}, sha256 {hashlib.sha256(data).hexdigest()}")
    return "; ".join(parts)


def read_dll_eol(dll_path: Path) -> Optional[int]:
    """Return the EOL timestamp compiled into the LTK patcher DLL.

    The DLL compares the game executable's PE build timestamp against a
    constant (``cmp eax, imm32; jbe``) right before referencing the
    "end of life reached" message. We locate that message, find the code that
    loads it, and read the nearest preceding comparison constant.
    """
    try:
        data = dll_path.read_bytes()
        sections = _parse_sections(data)
    except (OSError, ValueError, struct.error):
        return None

    msg_offset = data.find(_EOL_MESSAGE)
    if msg_offset < 0:
        return None
    msg_rva = _offset_to_rva(sections, msg_offset)
    text = next((s for s in sections if s[0] == b".text"), None)
    if msg_rva is None or text is None:
        return None

    _, text_rva, text_size, text_raw = text
    code = data[text_raw:text_raw + text_size]
    for i in range(len(code) - 7):
        # lea r64, [rip + disp32]
        if code[i] not in (0x48, 0x4C) or code[i + 1] != 0x8D or (code[i + 2] & 0xC7) != 0x05:
            continue
        disp = struct.unpack_from("<i", code, i + 3)[0]
        # Newer Rust format templates prefix the text with its length
        if not 0 <= msg_rva - (text_rva + i + 7 + disp) <= 16:
            continue
        eol = _find_eol_compare(code, i)
        if eol is not None:
            return eol
    return None


def read_game_build(game_dir: Path) -> Optional[int]:
    """Return the build timestamp of the game executable in game_dir.

    This is the PE header's TimeDateStamp, which the DLL reads from the game's
    memory and compares against its end-of-life date.
    """
    for name in GAME_EXECUTABLE_NAMES:
        try:
            with open(Path(game_dir) / name, "rb") as f:
                header = f.read(0x1000)
        except OSError:
            continue
        try:
            pe = struct.unpack_from("<I", header, 0x3C)[0]
            if header[:2] == b"MZ" and header[pe:pe + 4] == b"PE\0\0":
                return struct.unpack_from("<I", header, pe + 8)[0]
        except struct.error:
            pass
    return None


def _find_eol_compare(code: bytes, lea_index: int) -> Optional[int]:
    """Find the closest ``cmp eax, imm32; jbe rel32`` before the message load."""
    start = max(0, lea_index - _EOL_SEARCH_WINDOW)
    for j in range(lea_index - 11, start - 1, -1):
        if code[j] == 0x3D and code[j + 5] == 0x0F and code[j + 6] == 0x86:
            return struct.unpack_from("<I", code, j + 1)[0]
    return None


def _parse_sections(data: bytes):
    """Return (name, rva, raw_size, raw_offset) for each PE section."""
    if data[:2] != b"MZ":
        raise ValueError("not a PE file")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("not a PE file")
    count = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    table = pe + 24 + opt_size
    sections = []
    for k in range(count):
        entry = table + k * 40
        name = data[entry:entry + 8].rstrip(b"\0")
        rva, raw_size, raw_offset = struct.unpack_from("<III", data, entry + 12)
        sections.append((name, rva, raw_size, raw_offset))
    return sections


def _offset_to_rva(sections, offset: int) -> Optional[int]:
    for _, rva, raw_size, raw_offset in sections:
        if raw_offset <= offset < raw_offset + raw_size:
            return offset - raw_offset + rva
    return None
