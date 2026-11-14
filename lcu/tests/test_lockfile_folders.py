import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lcu.core import lockfile


class LockfileFoldersTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.saved = self.root / "Saved League"
        self.standard = self.root / "Riot Games" / "League of Legends"
        self.seen = self.root / "Seen League"
        for folder in (self.saved, self.standard, self.seen):
            folder.mkdir(parents=True)
        for target, value in (
            ("get_config_option", lambda section, key: str(self.saved)),
            ("_common_lockfiles", lambda: [self.standard / "lockfile", self.root / "Missing" / "lockfile"]),
        ):
            patcher = patch.object(lockfile, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_folders_the_lockfile_is_looked_for_in_that_exist(self):
        folders = lockfile.lockfile_folders(seen=[str(self.seen), None])

        self.assertEqual(folders, [self.saved, self.standard, self.seen])

    def test_a_folder_is_listed_once(self):
        folders = lockfile.lockfile_folders(str(self.saved / "lockfile"), [str(self.standard)])

        self.assertEqual(folders, [self.saved, self.standard])


if __name__ == "__main__":
    unittest.main()
