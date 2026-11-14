#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Skin library sync from LeagueSkins' manifest.

LeagueSkins publishes manifest.json on its "manifest" branch (a workflow
rebuilds it on every push): the git blob SHA and size of every file under
skins/, classic/ and resources/. The sync reads it from
raw.githubusercontent.com, compares it with the files on disk, and downloads
only the ones that differ, pinned to the manifest's commit, each checked
against its blob SHA. None of this is a GitHub API call, so the 60 calls an
hour GitHub allows without a login are not spent, and it does not use the
repository ZIP, which GitHub refuses (429) for a library this size.

Each file that lands is recorded right away (.skin_sync_state.json), so an
interrupted sync resumes where it stopped instead of starting over. A file
already on disk is trusted when it matches what was recorded for it (size and
modification time); otherwise its blob SHA is computed once.
Only a complete sync can retire files from the last completed library.

Without a manifest, the repository tree is listed with one API call instead
(files then come from main), unless GitHub's rate limit refuses it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

import requests

from config import APP_USER_AGENT, SKIN_DOWNLOAD_STREAM_TIMEOUT_S
from utils.core.atomic_file import atomic_write, write_text_atomic
from utils.core.junction import is_junction
from utils.core.logging import get_logger

from . import github_rate_limit

log = get_logger()

REPO = "Alban1911/LeagueSkins"
MANIFEST_URL = f"https://raw.githubusercontent.com/{REPO}/manifest/manifest.json"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}"
TREE_API_URL = f"https://api.github.com/repos/{REPO}/git/trees/main?recursive=1"
SYNCED_FOLDERS = ("skins", "classic", "resources")
MANIFEST_VERSION = 1

STATE_FILE = ".skin_sync_state.json"
MANIFEST_COPY = ".skin_manifest.json"

DOWNLOAD_WORKERS = 4
# Checking files on disk is bound by opening them, not by hashing: more threads
VERIFY_WORKERS = 8
DOWNLOAD_ATTEMPTS = 3
STATE_FLUSH_S = 2.0
PROGRESS_INTERVAL_S = 0.25
CHUNK = 1024 * 1024

ProgressCallback = Callable[[float, Optional[str]], None]


class _ContentMismatch(Exception):
    """A download whose blob SHA is not the manifest's."""


def blob_sha(path: Path) -> str:
    """The git blob SHA-1 of a file: what the manifest lists for it."""
    digest = hashlib.sha1(b"blob %d\0" % path.stat().st_size)
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _format_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} GB"


@dataclass
class Manifest:
    """The library as LeagueSkins lists it: repo path -> (blob SHA, size).

    *commit* pins the downloads; None when the listing came from main (the
    tree API fallback), whose files are then fetched from main.
    """
    commit: Optional[str]
    files: Dict[str, Tuple[str, int]]
    etag: Optional[str] = None
    source: str = "manifest"


@dataclass
class SyncResult:
    complete: bool
    commit: Optional[str] = None
    downloaded: int = 0
    failed: int = 0
    removed: int = 0
    throttled: bool = False
    pending: List[str] = field(default_factory=list)


class SkinSync:
    """Brings the local library to the manifest's content."""

    def __init__(
        self,
        resolve: Callable[[str], Optional[Path]],
        roots: Iterable[Path],
        state_dir: Path,
        progress: Optional[ProgressCallback] = None,
        workers: int = DOWNLOAD_WORKERS,
    ):
        self.resolve = resolve
        self.roots = [Path(root) for root in roots]
        self.state_path = Path(state_dir) / STATE_FILE
        self.manifest_copy = Path(state_dir) / MANIFEST_COPY
        self.progress = progress
        self.workers = max(1, workers)
        self._local = threading.local()
        self._stop = threading.Event()
        self._last_progress = 0.0

    # -- state ------------------------------------------------------------------
    def _load_state(self) -> dict:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(state, dict) and isinstance(state.get("files"), dict):
                return state
        except (OSError, ValueError):
            pass
        return {"files": {}}

    def _save_state(self, state: dict) -> None:
        try:
            write_text_atomic(self.state_path, json.dumps(state, separators=(",", ":")))
        except OSError as e:
            log.warning(f"[SKINS] Could not save the sync state: {e}")

    # -- the manifest -----------------------------------------------------------
    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"User-Agent": APP_USER_AGENT})
            self._local.session = session
        return session

    @staticmethod
    def _parse_manifest(data: dict, etag: Optional[str] = None) -> Optional[Manifest]:
        if not isinstance(data, dict) or data.get("version") != MANIFEST_VERSION:
            return None
        files: Dict[str, Tuple[str, int]] = {}
        entries = data.get("files")
        if not isinstance(entries, list):
            return None
        seen = set()
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or len(entry) != 3:
                return None
            path, sha, size = entry
            if not isinstance(path, str) or "\\" in path or ":" in path:
                return None
            parts = path.split("/")
            if parts[0] not in SYNCED_FOLDERS:
                continue  # a folder Rose does not sync
            if len(parts) < 2 or any(not part or part.endswith((".", " ")) for part in parts):
                return None
            key = os.path.normcase(path)
            if (key in seen or not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha)
                    or type(size) is not int or size < 0):
                return None
            seen.add(key)
            files[path] = (sha, size)
        if not any(path.startswith("skins/") for path in files):
            return None  # an empty or broken listing must never empty the library
        commit = data.get("commit")
        return Manifest(commit=str(commit) if commit else None, files=files, etag=etag)

    def _read_manifest_copy(self, etag: Optional[str]) -> Optional[Manifest]:
        try:
            cached = json.loads(self.manifest_copy.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and etag and cached.get("etag") == etag:
                return self._parse_manifest(cached.get("manifest"), etag)
        except (OSError, ValueError):
            pass
        return None

    def fetch_manifest(self, state: dict) -> Optional[Manifest]:
        """The manifest from raw.githubusercontent.com (an unchanged one is read
        from the local copy), else the tree API's listing, else None."""
        headers = {}
        if state.get("manifest_etag") and self.manifest_copy.exists():
            headers["If-None-Match"] = state["manifest_etag"]
        try:
            response = self._session().get(MANIFEST_URL, headers=headers, timeout=30)
            if response.status_code == 304:
                manifest = self._read_manifest_copy(state.get("manifest_etag"))
                if manifest is not None:
                    log.info("[SKINS] The skin manifest is unchanged")
                    return manifest
                response = self._session().get(MANIFEST_URL, timeout=30)
            if response.status_code == 200:
                data = response.json()
                manifest = self._parse_manifest(data, response.headers.get("ETag"))
                if manifest is not None:
                    try:
                        cache = {"etag": manifest.etag, "manifest": data}
                        write_text_atomic(self.manifest_copy, json.dumps(cache, separators=(",", ":")))
                    except OSError as e:
                        log.debug(f"[SKINS] Could not keep a copy of the manifest: {e}")
                    log.info(
                        f"[SKINS] Skin manifest: {len(manifest.files)} files "
                        f"(commit {(manifest.commit or '?')[:8]})"
                    )
                    return manifest
                log.warning("[SKINS] The skin manifest could not be read")
            else:
                log.warning(f"[SKINS] Skin manifest unavailable (HTTP {response.status_code})")
        except (requests.RequestException, ValueError) as e:
            log.warning(f"[SKINS] Skin manifest unavailable: {e}")
        return self._manifest_from_tree()

    def _manifest_from_tree(self) -> Optional[Manifest]:
        """The repository listing from the tree API (one call), the manifest's fallback."""
        try:
            response = github_rate_limit.api_get(TREE_API_URL, self._session(), timeout=60)
        except requests.RequestException as e:
            log.warning(f"[SKINS] Repository listing unavailable: {e}")
            return None
        if response is None:
            return None
        if response.status_code != 200:
            log.warning(f"[SKINS] Repository listing unavailable (HTTP {response.status_code})")
            return None
        try:
            tree = response.json()
        except ValueError:
            return None
        if tree.get("truncated"):
            log.warning("[SKINS] The repository listing is truncated")
            return None
        files = [
            [entry["path"], entry["sha"], entry["size"]]
            for entry in tree.get("tree") or []
            if entry.get("type") == "blob" and entry.get("path", "").split("/", 1)[0] in SYNCED_FOLDERS
        ]
        manifest = self._parse_manifest({"version": MANIFEST_VERSION, "commit": None, "files": files})
        if manifest is not None:
            manifest.source = "tree"
            log.info(f"[SKINS] Repository listing (API): {len(manifest.files)} files")
        return manifest

    # -- progress ---------------------------------------------------------------
    def _emit(self, percent: float, message: Optional[str], force: bool = False) -> None:
        if not self.progress:
            return
        now = time.monotonic()
        if not force and now - self._last_progress < PROGRESS_INTERVAL_S:
            return
        self._last_progress = now
        self.progress(max(0.0, min(percent, 100.0)), message)

    # -- what to download -------------------------------------------------------
    def plan(self, manifest: Manifest, state: dict) -> Tuple[List[Tuple[str, Path, str, int]], List[str]]:
        """The files to download: missing, of another size, or whose content
        differs, plus entries that cannot be placed in the library."""
        known: Dict[str, list] = state["files"]
        todo: List[Tuple[str, Path, str, int]] = []
        unresolved: List[str] = []
        to_hash: List[Tuple[str, Path, str, int, os.stat_result]] = []
        for path, (sha, size) in manifest.files.items():
            local = self.resolve(path)
            if local is None:
                unresolved.append(path)
                continue
            try:
                stat = local.stat()
            except OSError:
                todo.append((path, local, sha, size))
                continue
            record = known.get(path)
            if record and record[0] == sha and record[1] == stat.st_size and record[2] == stat.st_mtime_ns:
                continue
            if stat.st_size != size:
                todo.append((path, local, sha, size))
            else:
                to_hash.append((path, local, sha, size, stat))

        total = len(to_hash)
        if not total:
            return todo, unresolved

        def matches(local: Path, sha: str) -> bool:
            try:
                return blob_sha(local) == sha
            except OSError:
                return False

        # Hashed in parallel: reading many files is slowed per file (an
        # antivirus scans each one it opens), not by the hashing itself
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=max(self.workers, VERIFY_WORKERS), thread_name_prefix="SkinVerify") as pool:
            futures = {pool.submit(matches, entry[1], entry[2]): entry for entry in to_hash}
            for index, future in enumerate(as_completed(futures), 1):
                path, local, sha, size, stat = futures[future]
                if future.result():
                    known[path] = [sha, stat.st_size, stat.st_mtime_ns]
                else:
                    todo.append((path, local, sha, size))
                self._emit(5 + 10 * index / total, f"Verifying skin library... {index}/{total}")
        log.info(f"[SKINS] Verified {total} files already on disk in {time.monotonic() - started:.1f}s")
        return todo, unresolved

    # -- downloads --------------------------------------------------------------
    def _urls(self, manifest: Manifest, path: str) -> List[str]:
        quoted = quote(path)
        urls = [f"{RAW_BASE}/{manifest.commit}/{quoted}"] if manifest.commit else []
        # A commit rewritten away from the history is gone: main still has the file
        urls.append(f"{RAW_BASE}/main/{quoted}")
        return urls

    def _download(self, manifest: Manifest, path: str, local: Path, sha: str, size: int) -> Tuple[str, Optional[str]]:
        """("ok"|"failed"|"throttled"|"skipped", detail) for one file.

        The file is hashed as it streams (the blob SHA covers a header with
        the size, which the manifest gives) and only replaces the one on disk
        when it matches.
        """
        detail = None
        for url in self._urls(manifest, path):
            for attempt in range(DOWNLOAD_ATTEMPTS):
                if self._stop.is_set():
                    return "skipped", None
                try:
                    with self._session().get(url, stream=True, timeout=SKIN_DOWNLOAD_STREAM_TIMEOUT_S) as response:
                        if response.status_code in (403, 429):
                            self._stop.set()
                            return "throttled", f"HTTP {response.status_code}"
                        if response.status_code == 404:
                            detail = "HTTP 404"
                            break  # the next url
                        response.raise_for_status()
                        digest = hashlib.sha1(b"blob %d\0" % size)
                        with atomic_write(local, "wb", durable=False) as handle:
                            for chunk in response.iter_content(chunk_size=CHUNK):
                                if chunk:
                                    handle.write(chunk)
                                    digest.update(chunk)
                            if digest.hexdigest() != sha:
                                # raised inside the block: the file on disk is left as it was
                                raise _ContentMismatch()
                        return "ok", None
                except _ContentMismatch:
                    detail = "content differs from the manifest"
                    break  # the next url (main may hold it after a history rewrite)
                except (requests.RequestException, OSError) as e:
                    detail = str(e)
                    if attempt + 1 < DOWNLOAD_ATTEMPTS:
                        time.sleep(min(2 ** attempt, 4))
        return "failed", detail

    def download(self, manifest: Manifest, state: dict, todo: List[Tuple[str, Path, str, int]]) -> SyncResult:
        result = SyncResult(complete=False, commit=manifest.commit)
        if not todo:
            result.complete = True
            return result
        total_bytes = sum(size for _, _, _, size in todo) or 1
        done_bytes = 0
        log.info(f"[SKINS] Downloading {len(todo)} files ({_format_size(total_bytes)})")
        # A kill from here on can leave partial downloads: the next start sweeps them
        state["downloading"] = True
        self._save_state(state)
        self._emit(15, f"Downloading {len(todo)} skin files...", force=True)
        last_flush = time.monotonic()
        with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="SkinSync") as pool:
            futures = {
                pool.submit(self._download, manifest, path, local, sha, size): (path, local, sha, size)
                for path, local, sha, size in todo
            }
            for future in as_completed(futures):
                path, local, sha, size = futures[future]
                try:
                    outcome, detail = future.result()
                except Exception as e:  # a worker must never take the sync down
                    outcome, detail = "failed", str(e)
                done_bytes += size
                if outcome == "ok":
                    result.downloaded += 1
                    try:
                        stat = local.stat()
                        state["files"][path] = [sha, stat.st_size, stat.st_mtime_ns]
                    except OSError:
                        pass
                else:
                    result.pending.append(path)
                    if outcome == "failed":
                        result.failed += 1
                        log.warning(f"[SKINS] Could not download {path}: {detail}")
                    elif outcome == "throttled" and not result.throttled:
                        result.throttled = True
                        log.warning(f"[SKINS] GitHub is throttling the downloads ({detail}) - "
                                    "the rest is downloaded next start")
                if time.monotonic() - last_flush >= STATE_FLUSH_S:
                    self._save_state(state)
                    last_flush = time.monotonic()
                self._emit(
                    15 + 80 * done_bytes / total_bytes,
                    f"Downloading skins... {_format_size(done_bytes)} / {_format_size(total_bytes)}",
                )
        result.complete = not result.pending
        return result

    # -- files no longer in the library -----------------------------------------
    def _completed_files(self, state: dict) -> Dict[str, str]:
        completed = state.get("completed_files")
        if isinstance(completed, dict):
            return completed
        # Older releases only recorded whether the last sync was complete.
        # Their download cache is a usable baseline only in that case.
        if state.get("complete") is not True:
            return {}
        return {
            path: record[0] for path, record in state["files"].items()
            if isinstance(record, list) and record and isinstance(record[0], str)
        }

    def _finish_sync(self, manifest: Manifest, state: dict) -> int:
        """Retire previously synced, unmodified files after a complete sync."""
        expected = {os.path.normcase(path) for path in manifest.files}
        completed = {path: sha for path, (sha, _) in manifest.files.items()}
        removed = 0
        # Files an incomplete sync downloaded are not in completed_files yet.
        # Still only an unmodified file (same blob) is removed
        candidates = {
            path: record[0] for path, record in state["files"].items()
            if isinstance(record, list) and record and isinstance(record[0], str)
        }
        candidates.update(self._completed_files(state))
        for path, sha in candidates.items():
            if os.path.normcase(os.path.normpath(path)) in expected:
                continue
            local = self.resolve(path)
            if local is None or is_junction(local) or local.is_symlink():
                continue
            root = next((root for root in self.roots if root in local.parents), None)
            if root is None:
                continue
            if any(is_junction(folder) or folder.is_symlink() for folder in local.parents if root in folder.parents):
                continue
            try:
                if not local.is_file() or blob_sha(local) != sha:
                    continue
                local.unlink()
            except FileNotFoundError:
                continue
            except OSError as e:
                # A locked file can be retired on the next complete sync.
                completed[path] = sha
                log.debug(f"[SKINS] Could not remove {local}: {e}")
                continue
            removed += 1
            for folder in local.parents:
                if folder == root:
                    break
                try:
                    folder.rmdir()
                except OSError:
                    break
        known = state["files"]
        for path in [p for p in known if p not in manifest.files]:
            del known[path]
        state["completed_files"] = completed
        if removed:
            log.info(f"[SKINS] Removed {removed} files no longer in the library")
        return removed

    # -- temp files a killed sync left behind -----------------------------------
    def _remove_stale_temps(self, state: dict) -> None:
        """Delete atomic_write temp files (.<name>.<random>.tmp) from an interrupted sync.

        A hard kill skips atomic_write's cleanup, and _finish_sync only retires
        files a sync recorded, so a partial download would stay on disk forever.
        The library is only walked after a sync that was downloading did not
        finish (or once, for a state from before this was recorded).
        """
        folders = [(self.state_path.parent, False)]
        if state.get("downloading", True):
            folders += [(root, True) for root in self.roots]
        for folder, recursive in folders:
            if not folder.is_dir():
                continue
            for local in list(folder.rglob(".*.tmp") if recursive else folder.glob(".*.tmp")):
                try:
                    if local.is_file():
                        local.unlink()
                except OSError as e:
                    log.debug(f"[SKINS] Could not remove stale temp file {local}: {e}")

    # -- all of it --------------------------------------------------------------
    def run(self) -> Optional[SyncResult]:
        """Sync the library; None when no listing could be read (nothing changed)."""
        self._emit(0, "Checking for skin updates...", force=True)
        state = self._load_state()
        self._remove_stale_temps(state)
        manifest = self.fetch_manifest(state)
        if manifest is None:
            return None
        state["completed_files"] = self._completed_files(state)
        self._emit(5, "Checking skin library...", force=True)
        todo, unresolved = self.plan(manifest, state)
        result = self.download(manifest, state, todo)
        if unresolved:
            result.pending.extend(unresolved)
            result.failed += len(unresolved)
            result.complete = False
        if result.complete:
            self._emit(95, "Cleaning up removed skins...", force=True)
            result.removed = self._finish_sync(manifest, state)
        state["manifest_etag"] = manifest.etag if manifest.source == "manifest" else None
        state["commit"] = manifest.commit
        state["complete"] = result.complete
        state["downloading"] = False
        self._save_state(state)
        if result.complete:
            self._emit(100, "Skins ready" if result.downloaded else "Skins already up to date", force=True)
        elif result.throttled:
            self._emit(100, f"Skins partly updated ({len(result.pending)} left for next start)", force=True)
        else:
            self._emit(100, f"{len(result.pending)} skin files could not be downloaded", force=True)
        log.info(
            f"[SKINS] Sync {'complete' if result.complete else 'incomplete'}: {result.downloaded} downloaded, "
            f"{len(result.pending)} pending, {result.removed} removed"
        )
        return result
