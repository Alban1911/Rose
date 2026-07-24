"""Resolve packed WAD entries into a temporary path tree.

Rose only needs the resolved asset paths to identify custom-skin targets.  The
WAD table of contents stores hashes rather than paths, so this module uses the
bundled CommunityDragon hash table and materializes the known paths in the
requested directory.  It deliberately does not copy or decompress payloads.
Unknown hashes are ignored because they cannot be used to infer a target.
"""

from __future__ import annotations

from functools import lru_cache
import sys
from pathlib import Path, PurePosixPath
from typing import Optional

from .wad_parser import read_wad_path_hashes


def _default_hash_file() -> Path:
    """Return the runtime hash table location used by Rose."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "injection" / "tools" / "hashes.game.txt")
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


@lru_cache(maxsize=2)
def _load_hash_paths(
    path_string: str,
    mtime_ns: int,
    size: int,
) -> dict[int, tuple[str, ...]]:
    """Load hash-to-path mappings, keyed by the file signature."""
    del mtime_ns, size
    mappings: dict[int, list[str]] = {}
    with Path(path_string).open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split(maxsplit=1)
            if len(fields) != 2:
                continue
            raw_hash, raw_path = fields
            try:
                raw_hash = raw_hash.lower()
                if raw_hash.startswith("0x"):
                    raw_hash = raw_hash[2:]
                path_hash = int(raw_hash, 16)
            except ValueError:
                continue
            resolved_path = raw_path.replace(chr(92), "/").strip("/")
            if not resolved_path:
                continue
            mappings.setdefault(path_hash, []).append(resolved_path)
    return {path_hash: tuple(paths) for path_hash, paths in mappings.items()}


def _read_hash_paths(hash_file: Optional[Path]) -> dict[int, tuple[str, ...]]:
    path = Path(hash_file) if hash_file is not None else _default_hash_file()
    stat = path.stat()
    return _load_hash_paths(str(path), stat.st_mtime_ns, stat.st_size)


def _safe_resolved_path(output_directory: Path, resolved_path: str) -> Optional[Path]:
    """Return a safe output path for a trusted hash-table entry."""
    relative = PurePosixPath(resolved_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        return None

    target = output_directory.joinpath(*relative.parts)
    try:
        target.resolve().relative_to(output_directory.resolve())
    except ValueError:
        return None
    return target


def extract_wad_to_directory(
    wad_path: Path,
    output_directory: Path,
    hash_file: Optional[Path] = None,
) -> None:
    """Materialize resolved WAD paths below *output_directory*.

    This is intentionally a path-only extraction.  Target detection does not
    need asset bytes, and avoiding payload decompression keeps the fallback
    cheap and independent from optional compression libraries.
    """
    wad_path = Path(wad_path)
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)

    path_hashes = read_wad_path_hashes(wad_path)
    hash_paths = _read_hash_paths(hash_file)
    for path_hash in path_hashes:
        for resolved_path in hash_paths.get(path_hash, ()):
            target = _safe_resolved_path(output_directory, resolved_path)
            if target is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch(exist_ok=True)
