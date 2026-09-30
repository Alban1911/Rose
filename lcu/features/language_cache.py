"""Persistent copies of locale assets; Riot remains responsible for patch validation."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile

from utils.core.paths import get_user_data_dir


_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_ASSETS = 10000


def _digest(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Language cache assets must be regular files")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_link(path):
    info = path.lstat()
    # Windows junctions and other reparse points need not be symlinks.
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


class LanguageCache:
    """Cache language-specific assets, isolated by installation, patchline and build.

    An entry is a reusable copy, not a replacement for Riot's patch validation.
    Writes are atomic per file; an interrupted restore may leave a partial set
    for Riot to validate/download normally.
    """

    def __init__(self, installation, patchline, root=None):
        self.installation = Path(installation).resolve(strict=True)
        if patchline not in ("live", "pbe"):
            raise ValueError("Invalid patchline")
        # Include exact content/code builds and the client binary so hotfixes
        # also invalidate entries, independently of the selected language.
        self.version = self._version()
        identity = f"{os.path.normcase(str(self.installation))}\n{patchline}\n{self.version}"
        key = hashlib.sha256(identity.encode()).hexdigest()
        cache_root = Path(root) if root is not None else get_user_data_dir() / "language-cache"
        self.directory = cache_root.absolute() / key

    def _version(self):
        digest = hashlib.sha256()
        for name in ("Game/content-metadata.json", "Game/code-metadata.json", "LeagueClient.exe"):
            digest.update(_digest(self._inside(self.installation, name)).encode())
        return digest.hexdigest()

    @staticmethod
    def _locale(locale):
        if not isinstance(locale, str) or not re.fullmatch(r"[a-z]{2}_[A-Z]{2}", locale):
            raise ValueError("Invalid locale")
        return locale

    @staticmethod
    def _asset(relative, locale):
        # Restrict manifest paths too: never restore settings, executables,
        # arbitrary files, or another language's assets from a modified cache.
        if not isinstance(relative, str) or not relative:
            return False
        path = PurePosixPath(relative)
        if path.is_absolute() or path.as_posix() != relative:
            return False
        if any(p in ("..", ".") or p.endswith((" ", "."))
               or re.search(r'[\x00-\x1f<>:"\\|?*]', p)
               or re.fullmatch(r"(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p)
               for p in path.parts):
            return False
        if len(path.parts) < 2 or path.parts[0].lower() not in ("plugins", "game", "data", "locales"):
            return False
        if not path.name.lower().endswith((".wad", ".wad.client", ".pak")):
            return False
        pattern = re.escape(locale.lower()).replace("_", "[-_]")
        return re.search(r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])", relative.lower()) is not None

    @staticmethod
    def _inside(root, relative):
        root = root.absolute()
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Asset path escapes its root")
        # Do not follow even an in-root link: a cache/junction replacement must
        # not turn a locale restore into a write through an unrelated path.
        for component in (path, *path.parents):
            try:
                if _is_link(component):
                    raise ValueError("Language cache paths must not contain links or reparse points")
            except FileNotFoundError:
                continue
        return path

    @classmethod
    def _copy(cls, source_root, relative_source, target_root, relative_target, checksum):
        source = cls._inside(source_root, relative_source)
        destination = cls._inside(target_root, relative_target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        cls._inside(target_root, relative_target)
        descriptor, temporary = tempfile.mkstemp(prefix=".rose-language-", dir=destination.parent)
        os.close(descriptor)
        try:
            shutil.copy2(source, temporary)
            # The source may have changed since manifest validation or hashing.
            # Only publish bytes that match the expected content-addressed blob.
            if _digest(Path(temporary)) != checksum:
                raise OSError("Language assets changed while copying")
            cls._inside(source_root, relative_source)
            cls._inside(target_root, relative_target)
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def save(self, locale):
        """Publish a manifest only after every discovered asset has been copied."""
        locale = self._locale(locale)
        if self._version() != self.version:
            return 0
        assets = []

        def scan_error(error):
            # Do not publish an incomplete inventory after an unreadable folder.
            raise error

        for directory_name in ("Plugins", "Game", "DATA", "locales"):
            directory = self._inside(self.installation, directory_name)
            if not directory.is_dir():
                continue
            for parent, directories, files in os.walk(directory, followlinks=False, onerror=scan_error):
                directories[:] = sorted(d for d in directories if not _is_link(Path(parent) / d))
                for name in sorted(files):
                    source = Path(parent) / name
                    relative = source.relative_to(self.installation).as_posix()
                    if not self._asset(relative, locale):
                        continue
                    if len(assets) >= _MAX_ASSETS:
                        raise ValueError("Too many language cache assets")
                    source = self._inside(self.installation, relative)
                    before = source.stat()
                    checksum = _digest(source)
                    blob_relative = "blobs/" + checksum
                    blob = self._inside(self.directory, blob_relative)
                    if not blob.is_file() or _digest(blob) != checksum:
                        self._copy(self.installation, relative, self.directory, blob_relative, checksum)
                    after = source.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or _digest(blob) != checksum:
                        raise OSError("Language assets changed while caching")
                    assets.append({"path": relative, "sha256": checksum, "size": after.st_size})
        if not assets or self._version() != self.version:
            return 0
        content = json.dumps({"schema": 1, "locale": locale, "version": self.version, "files": assets}).encode("utf-8")
        if len(content) > _MAX_MANIFEST_BYTES:
            raise ValueError("Language cache manifest is too large")
        manifest = self._inside(self.directory, locale + ".json")
        descriptor, temporary = tempfile.mkstemp(prefix=".manifest-", dir=self.directory)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
            self._inside(self.directory, locale + ".json")
            os.replace(temporary, manifest)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return len(assets)

    def restore(self, locale):
        """Validate the entire entry before writing; corrupt/missing entries miss."""
        locale = self._locale(locale)
        try:
            with self._inside(self.directory, locale + ".json").open("rb") as source:
                content = source.read(_MAX_MANIFEST_BYTES + 1)
            if len(content) > _MAX_MANIFEST_BYTES:
                return 0
            manifest = json.loads(content)
            if (not isinstance(manifest, dict) or type(manifest.get("schema")) is not int
                    or manifest["schema"] != 1 or manifest.get("locale") != locale
                    or manifest.get("version") != self.version or self._version() != self.version):
                return 0
            assets = manifest["files"]
            if not isinstance(assets, list) or not 0 < len(assets) <= _MAX_ASSETS:
                return 0
            validated, seen = [], set()
            for item in assets:
                if not isinstance(item, dict):
                    return 0
                relative, checksum, size = item["path"], item["sha256"], item["size"]
                if (not self._asset(relative, locale) or not isinstance(checksum, str)
                        or not re.fullmatch(r"[0-9a-f]{64}", checksum)
                        or type(size) is not int or size < 0 or relative.casefold() in seen):
                    return 0
                seen.add(relative.casefold())
                blob = self._inside(self.directory, "blobs/" + checksum)
                self._inside(self.installation, relative)
                if blob.stat().st_size != size or _digest(blob) != checksum:
                    return 0
                validated.append((relative, checksum))
            # Hashing all blobs can take time: check the build again before writes.
            if self._version() != self.version:
                return 0
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            return 0
        for relative, checksum in validated:
            target = self._inside(self.installation, relative)
            if not target.is_file() or _digest(target) != checksum:
                self._copy(self.directory, "blobs/" + checksum, self.installation, relative, checksum)
        return len(validated)
