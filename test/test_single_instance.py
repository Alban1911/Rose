
import ctypes
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from main.core import lockfile
from main.core.state import get_app_state


@unittest.skipUnless(sys.platform == "win32", "Windows mutexes")
class SingleInstanceTests(unittest.TestCase):
    def isolate_from_this_pc(self, tag: str, state_dir: Path) -> None:
        """Never this PC's running Rose, nor its state folder."""
        for patcher in (
            patch.object(lockfile, "SINGLE_INSTANCE_MUTEX_NAME", rf"Local\RoseTest-{tag}"),
            patch.object(lockfile, "MOD_MIGRATION_MUTEX_NAME", self.migration_mutex),
            patch.object(lockfile, "get_state_dir", return_value=state_dir),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        tag = uuid.uuid4().hex
        self.migration_mutex = rf"Local\RoseTestMigration-{tag}"
        self.isolate_from_this_pc(tag, Path(temp_dir.name))
        patcher = patch.object(lockfile.atexit, "register")
        patcher.start()
        self.addCleanup(patcher.stop)
        app_state = get_app_state()
        previous = app_state.mutex_handle

        def restore():
            if app_state.mutex_handle and app_state.mutex_handle != previous:
                ctypes.windll.kernel32.CloseHandle(app_state.mutex_handle)
            app_state.mutex_handle = previous

        self.addCleanup(restore)

    def test_a_rose_moving_the_mods_is_another_instance(self):
        migrating = ctypes.windll.kernel32.CreateMutexW(None, False, self.migration_mutex)
        self.assertTrue(migrating)
        try:
            self.assertFalse(lockfile.create_single_instance_mutex())
        finally:
            ctypes.windll.kernel32.CloseHandle(migrating)

        self.assertTrue(lockfile.create_single_instance_mutex(), "once it is done")


if __name__ == "__main__":
    unittest.main()
