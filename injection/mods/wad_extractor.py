"""Resolve packed WAD entries to custom-skin targets without unpacking payloads.

WAD files store xxHash64 values for their original asset paths in the table of
contents.  The bundled CommunityDragon hash table resolves those values back
to paths.  Rose only needs matching character/skin paths to identify targets,
so this module streams the hash table and keeps no full-database index in
memory.  Unknown paths remain unresolved and are handled by the storage-folder
fallback.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

from .wad_parser import read_wad_path_hashes


_SKIN_COMPONENT_RE = re.compile(
    r"skin[_-]?0*(\d+)(?:\.[^.]+)?$",
    re.IGNORECASE,
)


def _default_hash_file() -> Path:
    """Return the runtime hash table location used by Rose."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            candidates.append(
                Path(sys._MEIPASS) / "injection" / "tools" / "hashes.game.txt"
            )
        executable_root = Path(sys.executable).parent
        candidates.extend(
            (
                executable_root / "injection" / "tools" / "hashes.game.txt",
                executable_root / "_internal" / "injection" / "tools" / "hashes.game.txt",
            )
        )
    else:
        candidates.append(
            Path(__file__).resolve().parents[2]
            / "injection"
            / "tools"
            / "hashes.game.txt"
        )

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def get_hash_file_signature(
    hash_file: Optional[Path] = None,
) -> Optional[dict[str, int]]:
    """Return the signature used to invalidate WAD target metadata."""
    path = Path(hash_file) if hash_file is not None else _default_hash_file()
    try:
        stat = path.stat()
    except OSError:
        return None
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _parse_hash_line(line: str) -> Optional[tuple[int, str]]:
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    fields = line.split(maxsplit=1)
    if len(fields) != 2:
        return None

    raw_hash, raw_path = fields
    try:
        raw_hash = raw_hash.lower()
        if raw_hash.startswith("0x"):
            raw_hash = raw_hash[2:]
        path_hash = int(raw_hash, 16)
    except ValueError:
        return None

    resolved_path = raw_path.replace(chr(92), "/").strip("/")
    if not resolved_path:
        return None
    return path_hash, resolved_path


def _normalized_champion_path_names(champion_name: str) -> set[str]:
    compact_name = re.sub(r"[^a-z0-9]", "", str(champion_name).casefold())
    if not compact_name:
        return set()

    names = {compact_name}
    aliases = {
        "wukong": "monkeyking",
        "nunuandwillump": "nunu",
        "renataglasc": "renata",
    }
    for source, alias in aliases.items():
        if compact_name == source:
            names.add(alias)
        elif compact_name == alias:
            names.add(source)
    return names


def _skin_id_from_resolved_path(
    resolved_path: str,
    champion_id: int,
    champion_path_names: set[str],
) -> Optional[int]:
    parts = tuple(part for part in resolved_path.split("/") if part)
    normalized_parts = tuple(part.casefold() for part in parts)
    for index in range(len(parts) - 4):
        if normalized_parts[index] not in {"data", "assets"}:
            continue
        if normalized_parts[index + 1] != "characters":
            continue
        if normalized_parts[index + 2] not in champion_path_names:
            continue
        if normalized_parts[index + 3] != "skins":
            continue

        match = _SKIN_COMPONENT_RE.fullmatch(parts[index + 4])
        if not match:
            continue
        suffix = int(match.group(1))
        return suffix if suffix >= 1000 else int(champion_id) * 1000 + suffix
    return None


def resolve_wad_skin_targets(
    wad_path: Path,
    champion_id: int,
    champion_name: str,
    hash_file: Optional[Path] = None,
) -> set[int]:
    """Resolve known WAD paths to skin IDs using bounded memory.

    The WAD TOC is read into a set of hashes, then the CommunityDragon hash
    file is streamed line by line.  Only rows whose hash occurs in the WAD
    are parsed for a matching data/assets champion skin path.  This does not
    decompress WAD payloads; if all relevant hashes are unknown, the caller
    must use the storage-folder fallback or explicit metadata.
    """
    wanted_hashes = read_wad_path_hashes(Path(wad_path))
    champion_path_names = _normalized_champion_path_names(champion_name)
    if not wanted_hashes or not champion_path_names:
        return set()

    path = Path(hash_file) if hash_file is not None else _default_hash_file()
    targets: set[int] = set()
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            parsed = _parse_hash_line(line)
            if parsed is None:
                continue
            path_hash, resolved_path = parsed
            if path_hash not in wanted_hashes:
                continue
            skin_id = _skin_id_from_resolved_path(
                resolved_path,
                champion_id,
                champion_path_names,
            )
            if skin_id is not None:
                targets.add(skin_id)
    return targets
