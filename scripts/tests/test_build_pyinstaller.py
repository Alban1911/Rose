import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_pyinstaller


class CleanPreviousBuildsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        root_patch = patch.object(build_pyinstaller, "ROOT", self.workspace)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        stdout = contextlib.redirect_stdout(io.StringIO())
        stdout.__enter__()
        self.addCleanup(stdout.__exit__, None, None, None)

    def write(self, relative, contents=b"keep me"):
        path = self.workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def directory_link(self, link, target):
        link.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            # Junction creation does not require Windows symlink privileges.
            subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                    "New-Item -ItemType Junction -Path $env:ROSE_TEST_LINK "
                    "-Target $env:ROSE_TEST_TARGET -ErrorAction Stop | Out-Null",
                ],
                env={**os.environ, "ROSE_TEST_LINK": str(link),
                     "ROSE_TEST_TARGET": str(target)},
                check=True, capture_output=True, text=True,
            )
            self.addCleanup(link.rmdir)
        else:
            link.symlink_to(target, target_is_directory=True)
            self.addCleanup(link.unlink)

    def test_preserves_archived_releases_artifacts_and_build_cache(self):
        self.write("dist/Rose/Rose.exe", b"old executable")
        self.write("dist/Rose/_internal/stale.dll", b"stale dependency")
        preserved = [
            self.write("dist/Rose-1.3.1-stable-local/Rose.exe"),
            self.write("dist/Rose-1.3.1-stable-local/language_cache/ko_KR.wad"),
            self.write("dist/Rose-1.3.1-stable-local.zip"),
            self.write("dist/Rose-1.3.1-stable-local.sha256"),
            self.write("build/Rose/Analysis-00.toc"),
        ]

        self.assertTrue(build_pyinstaller.clean_previous_builds())

        self.assertFalse((self.workspace / "dist/Rose").exists())
        for path in preserved:
            self.assertEqual(path.read_bytes(), b"keep me")

    def test_missing_dist_is_successful_without_creating_output(self):
        self.assertTrue(build_pyinstaller.clean_previous_builds())
        self.assertFalse((self.workspace / "dist").exists())

    def test_missing_active_output_preserves_archived_release(self):
        archived = self.write("dist/Rose-1.3.1-stable-local/Rose.exe")
        self.assertTrue(build_pyinstaller.clean_previous_builds())
        self.assertEqual(archived.read_bytes(), b"keep me")

    def test_cleanup_error_returns_false(self):
        self.write("dist/Rose/Rose.exe")
        with patch.object(build_pyinstaller.shutil, "rmtree", side_effect=PermissionError("locked")):
            self.assertFalse(build_pyinstaller.clean_previous_builds())

    def test_main_aborts_before_building_when_cleanup_fails(self):
        self.write("dist/Rose/Rose.exe")
        with (
            patch.object(build_pyinstaller, "check_relay_config", return_value=True),
            patch.object(build_pyinstaller.shutil, "rmtree", side_effect=PermissionError("locked")),
            patch.object(build_pyinstaller, "build_pengu_loader") as pengu,
            patch.object(build_pyinstaller, "build_cslol_stub") as cslol,
            patch.object(build_pyinstaller, "build_with_pyinstaller") as pyinstaller,
            self.assertRaises(SystemExit) as exited,
        ):
            build_pyinstaller.main()
        self.assertEqual(exited.exception.code, 1)
        pengu.assert_not_called()
        cslol.assert_not_called()
        pyinstaller.assert_not_called()

    def test_rejects_redirected_dist_even_without_active_output(self):
        outside = self.root / "outside"
        outside.mkdir()
        marker = outside / "archive.zip"
        marker.write_bytes(b"outside")
        self.directory_link(self.workspace / "dist", outside)

        self.assertFalse(build_pyinstaller.clean_previous_builds())
        self.assertEqual(marker.read_bytes(), b"outside")
        self.assertFalse((outside / "Rose").exists())

    def test_rejects_dist_link_within_workspace(self):
        archived = self.write("archived/Rose/Rose.exe")
        self.directory_link(self.workspace / "dist", self.workspace / "archived")

        self.assertFalse(build_pyinstaller.clean_previous_builds())
        self.assertEqual(archived.read_bytes(), b"keep me")

    def test_rejects_linked_active_output(self):
        outside = self.root / "outside"
        outside.mkdir()
        marker = outside / "Rose.exe"
        marker.write_bytes(b"outside")
        self.directory_link(self.workspace / "dist/Rose", outside)

        self.assertFalse(build_pyinstaller.clean_previous_builds())
        self.assertEqual(marker.read_bytes(), b"outside")

    def test_rejects_file_in_place_of_output_directory(self):
        for relative in ("dist", "dist/Rose"):
            with self.subTest(relative=relative):
                unexpected = self.write(relative)
                self.assertFalse(build_pyinstaller.clean_previous_builds())
                self.assertEqual(unexpected.read_bytes(), b"keep me")
                unexpected.unlink()


if __name__ == "__main__":
    unittest.main()
