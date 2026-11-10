import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from launcher.update import update_sequence
from launcher.update.update_sequence import UpdateSequence

HASHES = Path("_internal/injection/tools/hashes.game.txt")


class ReleaseHashesTests(unittest.TestCase):
    """The installed hashes.game.txt is carried into the update, so the
    release's copy is only downloaded when there is none to carry."""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.install_dir = Path(temp_dir.name) / "Rose"
        self.install_dir.mkdir()
        self.extracted = Path(temp_dir.name) / "staging"
        self.sequence = UpdateSequence.__new__(UpdateSequence)
        self.sequence.github_client = Mock()
        self.sequence.github_client.get_hash_asset.return_value = {"browser_download_url": "https://example.invalid/h"}
        self.sequence.downloader = Mock()
        self.sequence.downloader.download_update.return_value = True
        self.sequence.installer = Mock()
        self.sequence.installer.workspace.return_value = Path(temp_dir.name) / "Rose.update"
        self.sequence.installer.extract_update.return_value = self.extracted
        self.sequence.installer.install.return_value = True

    def prepare(self):
        with patch.object(update_sequence.sys, "executable", str(self.install_dir / "Rose.exe")):
            return self.sequence._prepare_update(
                {}, "9.9.9", {"browser_download_url": "https://example.invalid/u"}, Mock(), Mock(), None,
            )

    def test_an_installed_copy_is_kept_without_downloading_the_release_one(self):
        (self.install_dir / HASHES).parent.mkdir(parents=True)
        (self.install_dir / HASHES).write_text("installed hashes")

        self.assertTrue(self.prepare())

        self.sequence.downloader.download_hash_file.assert_not_called()

    def test_the_release_copy_fills_in_a_missing_one(self):
        self.assertTrue(self.prepare())

        self.sequence.downloader.download_hash_file.assert_called_once()
        self.assertEqual(self.sequence.downloader.download_hash_file.call_args.args[1], self.extracted / HASHES)


if __name__ == "__main__":
    unittest.main()
