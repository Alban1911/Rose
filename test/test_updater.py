"""Tests for the startup update decision flow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher.update.update_sequence import UpdateSequence


class _ReleaseClient:
    def get_latest_release(self) -> dict:
        return {
            "tag_name": "1.2.13",
            "assets": [
                {
                    "name": "Rose.zip",
                    "browser_download_url": "https://example.invalid/Rose.zip",
                    "size": 123,
                }
            ],
        }

    def get_release_version(self, release: dict) -> str:
        return release["tag_name"]

    def get_zip_asset(self, release: dict) -> dict:
        return release["assets"][0]


class _RecordingDownloader:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def download_update(self, *args, **kwargs) -> bool:
        self.calls.append((args, kwargs))
        return True


class UpdatePromptTests(unittest.TestCase):
    def test_declining_available_update_does_not_download_or_change_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.ini"
            sequence = UpdateSequence()
            downloader = _RecordingDownloader()
            sequence.github_client = _ReleaseClient()
            sequence.downloader = downloader

            statuses: list[str] = []
            confirmations: list[tuple[str, str]] = []

            def decline(remote_version: str, local_version: str) -> bool:
                confirmations.append((remote_version, local_version))
                return False

            with patch(
                "launcher.update.update_sequence.get_config_file_path",
                return_value=config_path,
            ):
                updated = sequence.perform_update(
                    statuses.append,
                    lambda _: None,
                    confirm_callback=decline,
                )

            self.assertFalse(updated)
            self.assertEqual(confirmations, [("1.2.13", "1.2.12")])
            self.assertEqual(downloader.calls, [])
            self.assertIn("Update skipped by user", statuses[-1])
            self.assertFalse(config_path.exists())


if __name__ == "__main__":
    unittest.main()
