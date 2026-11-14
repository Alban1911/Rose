import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from utils.system import folder_watch
from utils.system.folder_watch import FolderWatch


@unittest.skipUnless(os.name == "nt", "Windows change notifications")
class FolderWatchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.watch = FolderWatch()

    def wait_in_thread(self, *args):
        result = {}

        def run():
            started = time.monotonic()
            result["woke"] = self.watch.wait(*args)
            result["after"] = time.monotonic() - started

        thread = threading.Thread(target=run)
        thread.start()
        return thread, result

    def test_a_file_created_in_the_folder_ends_the_wait(self):
        thread, result = self.wait_in_thread([self.folder], 10.0)
        time.sleep(0.2)
        (self.folder / "lockfile").write_text("LeagueClient:1:2:pw:https")
        thread.join(5)

        self.assertEqual(result["woke"], folder_watch.CHANGED)
        self.assertLess(result["after"], 5)

    def test_a_file_in_a_subfolder_does_not(self):
        (self.folder / "Game").mkdir()
        thread, result = self.wait_in_thread([self.folder], 0.5)
        time.sleep(0.1)
        (self.folder / "Game" / "patch.bin").write_bytes(b"x")
        thread.join(5)

        self.assertEqual(result["woke"], folder_watch.TIMEOUT)

    def test_wake_ends_this_wait_and_every_later_one(self):
        thread, result = self.wait_in_thread([self.folder], 10.0)
        time.sleep(0.2)
        self.watch.wake()
        thread.join(5)

        self.assertEqual(result["woke"], folder_watch.WOKEN)
        self.assertEqual(self.watch.wait([self.folder], 10.0), folder_watch.WOKEN)

    def test_a_ready_check_ends_it_before_waiting(self):
        checked = []

        def ready():
            checked.append(True)
            return True

        self.assertEqual(self.watch.wait([self.folder], 10.0, ready), folder_watch.READY)
        self.assertEqual(checked, [True])

    def test_nothing_to_watch_is_none(self):
        self.assertIsNone(self.watch.wait([], 10.0))
        self.assertIsNone(self.watch.wait([self.folder / "missing"], 10.0))


if __name__ == "__main__":
    unittest.main()
