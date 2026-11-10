"""Check for a release and hand a prepared update to the Windows helper."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

from config import APP_VERSION
from utils.core.logging import get_named_logger

from .github_client import GitHubClient
from .update_downloader import UpdateDownloader
from .update_installer import UpdateInstaller

updater_log = get_named_logger("updater", prefix="log_updater")


def _parse_semver_like(version: str) -> Optional[tuple[int, ...]]:
    """Parse version numbers, allowing v prefixes and suffixes."""
    v = version.strip()
    if v.lower().startswith("v"):
        v = v[1:].strip()
    for sep in (" ", "-", "+"):
        v = v.split(sep, 1)[0]

    parts: list[int] = []
    for raw in v.split("."):
        digits = ""
        for ch in raw:
            if not ch.isascii() or not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) if parts else None


def _cmp_version(a: Optional[tuple[int, ...]], b: Optional[tuple[int, ...]]) -> Optional[int]:
    """Return -1/0/1 if comparable."""
    if a is None or b is None:
        return None
    max_len = max(len(a), len(b))
    aa = a + (0,) * (max_len - len(a))
    bb = b + (0,) * (max_len - len(b))
    return (aa > bb) - (aa < bb)


class UpdateSequence:
    """Check for, download, and prepare an update."""

    def __init__(self):
        self.github_client = GitHubClient()
        self.downloader = UpdateDownloader()
        self.installer = UpdateInstaller()

    def perform_update(
        self,
        status_callback: Callable[[str], None],
        progress_callback: Callable[[int], None],
        bytes_callback: Optional[Callable[[int, Optional[int]], None]] = None,
        dev_mode: bool = False,
        confirm_callback: Optional[Callable[[str, str], bool]] = None,
    ) -> bool:
        """Return True when the update helper has acknowledged handoff."""
        if dev_mode or not getattr(sys, "frozen", False) or APP_VERSION == "999":
            status_callback("Update skipped (development build)")
            return False

        status_callback("Checking for updates...")
        release = self.github_client.get_latest_release()
        if not release:
            status_callback("Update check failed")
            return False

        remote_version = self.github_client.get_release_version(release)
        # Only the running build proves which version was installed. Older
        # updaters wrote installed_version before they had applied the update.
        comparison = _cmp_version(_parse_semver_like(APP_VERSION), _parse_semver_like(remote_version))
        if comparison is None:
            status_callback("Could not compare update versions")
            return False
        if comparison >= 0:
            status_callback("Launcher is already up to date")
            return False

        asset = self.github_client.get_zip_asset(release)
        if not asset or not asset.get("browser_download_url"):
            status_callback("No release asset found")
            return False

        if confirm_callback is not None:
            try:
                accepted = confirm_callback(remote_version, APP_VERSION)
            except Exception:
                updater_log.exception("Could not prompt for update confirmation")
                accepted = False
            if not accepted:
                status_callback(f"Update skipped by user ({remote_version} available)")
                return False

        from main.core.lockfile import update_instance_lock

        with update_instance_lock() as acquired:
            if not acquired:
                status_callback("Close the running Rose before installing an update")
                return False
            return self._prepare_update(
                release, remote_version, asset, status_callback, progress_callback, bytes_callback
            )

    def _prepare_update(self, release, remote_version, asset, status_callback, progress_callback, bytes_callback):
        install_dir = Path(sys.executable).resolve().parent
        try:
            updates_root = self.installer.workspace(install_dir)
        except OSError as exc:
            status_callback(f"Could not create update workspace: {exc}")
            return False
        zip_path = updates_root / "package.zip"
        status_callback(f"Downloading update {remote_version}")
        if not self.downloader.download_update(
            asset["browser_download_url"], zip_path, status_callback, bytes_callback, asset.get("size") or None,
        ):
            return False

        status_callback("Extracting update")
        extracted_root = self.installer.extract_update(
            zip_path, updates_root / "staging", progress_callback, status_callback,
        )
        if extracted_root is None:
            return False
        try:
            zip_path.unlink()
        except OSError as exc:
            updater_log.debug("Could not remove downloaded update package: %s", exc)

        # The installed hashes are carried into the update (see
        # _preserve_install_files): the release's copy only fills in a missing one
        hashes = Path("_internal") / "injection" / "tools" / "hashes.game.txt"
        hash_asset = None if (install_dir / hashes).is_file() else self.github_client.get_hash_asset(release)
        if hash_asset:
            status_callback("Downloading hash file...")
            self.downloader.download_hash_file(
                hash_asset.get("browser_download_url"), extracted_root / hashes, status_callback,
            )

        status_callback("Preparing to install update")
        if not self.installer.install(extracted_root, install_dir, updates_root, status_callback):
            return False
        progress_callback(100)
        status_callback("Update ready to apply after Rose exits")
        return True
