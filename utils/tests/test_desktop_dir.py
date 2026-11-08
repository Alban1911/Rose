
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from utils.core import paths
from utils.core.paths import (
    FOLDERID_DESKTOP,
    TOKEN_DUPLICATE,
    TOKEN_IMPERSONATE,
    TOKEN_QUERY,
    get_desktop_user_desktop_dir,
)

ONEDRIVE_DESKTOP = Path(r"C:\Users\daish\OneDrive\Desktop")
DAISH_TOKEN = object()


class DesktopDirTests(unittest.TestCase):
    def setUp(self):
        self.opened = []
        self.asked = []
        self.known = ONEDRIVE_DESKTOP
        self.desktop_user = ("daish", r"C:\Users\daish")

        @contextmanager
        def explorer_token(access):
            self.opened.append(access)
            yield DAISH_TOKEN

        def known_folder(folder_id, token):
            self.asked.append((folder_id, token))
            return self.known

        for patcher in (
            patch.object(paths, "_explorer_token", explorer_token),
            patch.object(paths, "_known_folder", known_folder),
            patch.object(paths, "_get_desktop_user_info", lambda: self.desktop_user),
            patch.dict(os.environ, {"USERNAME": "daish", "USERPROFILE": r"C:\Users\daish"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_windows_says_where_the_desktop_is(self):
        self.assertEqual(get_desktop_user_desktop_dir(), ONEDRIVE_DESKTOP)
        self.assertEqual(self.asked, [(FOLDERID_DESKTOP, None)], "this account's")
        self.assertEqual(self.opened, [])

    def test_an_elevated_rose_running_as_another_account_asks_for_the_desktop_users(self):
        with patch.dict(os.environ, {"USERNAME": "Admin", "USERPROFILE": r"C:\Users\Admin"}):
            self.assertEqual(get_desktop_user_desktop_dir(), ONEDRIVE_DESKTOP)

        self.assertEqual(self.opened, [TOKEN_QUERY | TOKEN_IMPERSONATE | TOKEN_DUPLICATE])
        self.assertEqual(self.asked, [(FOLDERID_DESKTOP, DAISH_TOKEN)])

    def test_without_an_answer_the_desktop_is_in_the_profile(self):
        self.known = None

        self.assertEqual(get_desktop_user_desktop_dir(), Path(r"C:\Users\daish") / "Desktop")
        with patch.dict(os.environ, {"USERNAME": "Admin", "USERPROFILE": r"C:\Users\Admin"}):
            self.assertEqual(get_desktop_user_desktop_dir(), Path(r"C:\Users\daish") / "Desktop")

    def test_without_the_desktop_user_it_is_this_accounts(self):
        self.desktop_user = (None, None)
        self.known = None

        with patch.dict(os.environ, {"USERNAME": "Admin", "USERPROFILE": r"C:\Users\Admin"}):
            self.assertEqual(get_desktop_user_desktop_dir(), Path(r"C:\Users\Admin") / "Desktop")
        self.assertEqual(self.opened, [])


@unittest.skipUnless(sys.platform == "win32", "Windows known folders")
class KnownFolderTests(unittest.TestCase):
    """Reads where Windows keeps this account's folders; touches none of them"""

    def test_windows_answers_with_this_accounts_desktop(self):
        desktop = paths._known_folder(FOLDERID_DESKTOP, None)

        self.assertIsNotNone(desktop)
        self.assertTrue(desktop.is_absolute())

    def test_an_unknown_folder_is_none(self):
        self.assertIsNone(paths._known_folder("{00000000-0000-0000-0000-000000000000}", None))


if __name__ == "__main__":
    unittest.main()
