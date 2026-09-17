"""Crash-safe file replacement.

Writing directly with ``open(path, "w")`` truncates the target first, so a crash, a full
disk or a locked file mid-write leaves an empty or partial file behind. These helpers write
to a sibling temporary file and swap it in with ``os.replace``, which is atomic on NTFS:
readers see either the old content or the new one, never a mix.

Kept free of project imports so ``config`` can use it without an import cycle.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
from collections.abc import Generator
from pathlib import Path
from typing import IO

# Antivirus scanners and concurrent readers briefly hold new files open on Windows,
# which makes os.replace fail with PermissionError for a few milliseconds.
_REPLACE_ATTEMPTS = 5
_REPLACE_RETRY_DELAY_S = 0.05


def _replace_with_retry(source: str, target: Path) -> None:
    for attempt in range(1, _REPLACE_ATTEMPTS + 1):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_RETRY_DELAY_S)


@contextlib.contextmanager
def atomic_write(
    path: Path,
    mode: str = "w",
    encoding: str | None = "utf-8",
    *,
    durable: bool = True,
) -> Generator[IO, None, None]:
    """Open a temporary file next to *path* and move it over *path* when the block succeeds.

    ``durable`` flushes to disk before the swap (~10 ms per file on Windows). Use it for small
    state files; bulk downloads can skip it because an interrupted sync is redone anyway.
    """
    if mode not in ("w", "wb"):
        raise ValueError(f"unsupported mode {mode!r}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, mode, encoding=None if mode == "wb" else encoding) as handle:
            yield handle
            if durable:
                handle.flush()
                os.fsync(handle.fileno())
        _replace_with_retry(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def write_text_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    with atomic_write(path, "w", encoding) as handle:
        handle.write(text)
