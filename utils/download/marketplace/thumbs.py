#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Marketplace thumbnails, served to the plugin through /market-thumb

Images come only from the providers' image CDNs and are kept on disk, so
scrolling back through results never downloads a card twice.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from utils.core.atomic_file import atomic_write
from utils.core.paths import get_user_data_dir

from .divine import DivineProvider
from .http import PoliteSession
from .runeforge import RuneForgeProvider

log = logging.getLogger(__name__)

ALLOWED_HOSTS = frozenset(RuneForgeProvider.image_hosts + DivineProvider.image_hosts)
# Image resizers that live on a site's own host, allowed for these paths only
ALLOWED_PATH_PREFIXES = {"runeforge.dev": "/cdn-cgi/image/"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
CACHE_LIMIT_BYTES = 200 * 1024 * 1024
TRIM_EVERY_WRITES = 50
CONTENT_TYPES = {
    b"\x89PNG": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF8": "image/gif",
}

_session: Optional[PoliteSession] = None
_session_lock = threading.Lock()
_writes = 0


def is_allowed_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if host in ALLOWED_HOSTS:
        return True
    prefix = ALLOWED_PATH_PREFIXES.get(host)
    return bool(prefix) and parsed.path.startswith(prefix) and ".." not in parsed.path


def cache_dir() -> Path:
    return get_user_data_dir() / "cache" / "marketplace" / "thumbs"


def _content_type(data: bytes) -> str:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    for magic, content_type in CONTENT_TYPES.items():
        if data.startswith(magic):
            return content_type
    return "application/octet-stream"


def _get_session() -> PoliteSession:
    global _session
    with _session_lock:
        if _session is None:
            _session = PoliteSession()  # CDN images: no API rate limit
        return _session


def _trim_cache(directory: Path) -> None:
    try:
        files = [(p.stat().st_mtime, p.stat().st_size, p) for p in directory.glob("*.img")]
    except OSError:
        return
    total = sum(size for _, size, _ in files)
    for _, size, path in sorted(files):
        if total <= CACHE_LIMIT_BYTES:
            break
        try:
            path.unlink()
            total -= size
        except OSError:
            pass


def fetch_thumbnail(url: str, directory: Optional[Path] = None) -> Optional[tuple]:
    """Return (content_type, bytes) for an allowed image URL, from disk when cached."""
    global _writes
    if not is_allowed_url(url):
        return None

    directory = directory or cache_dir()
    cached = directory / f"{hashlib.sha1(url.encode('utf-8')).hexdigest()}.img"
    try:
        data = cached.read_bytes()
        cached.touch()
        return _content_type(data), data
    except OSError:
        pass

    try:
        response = _get_session().get(url, stream=True, timeout=(5, 15))
        if response.status_code != 200 or not is_allowed_url(response.url):
            return None
        chunks, size = [], 0
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size > MAX_IMAGE_BYTES:
                return None
            chunks.append(chunk)
        data = b"".join(chunks)
    except Exception as exc:  # noqa: BLE001
        log.debug("[Marketplace] Thumbnail %s failed: %s", url, exc)
        return None

    content_type = _content_type(data)
    if not content_type.startswith("image/"):
        return None
    try:
        with atomic_write(cached, "wb", durable=False) as handle:
            handle.write(data)
        _writes += 1
        if _writes % TRIM_EVERY_WRITES == 0:
            threading.Thread(target=_trim_cache, args=(directory,), daemon=True).start()
    except OSError as exc:
        log.debug("[Marketplace] Could not cache thumbnail: %s", exc)
    return content_type, data
