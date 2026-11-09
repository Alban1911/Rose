"""Run the Windows update helper against temporary installation trees."""
import ctypes
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import zipfile
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

import psutil

from launcher.update import update_installer
from utils.core import safe_extract


@unittest.skipUnless(sys.platform == "win32", "Windows update helper")
class UpdateInstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.install_dir = root / "Rose update é"
        self.install_dir.mkdir()
        self.installer = update_installer.UpdateInstaller()
        self.workspace = self.installer.workspace(self.install_dir)
        self.candidate = self.workspace / "staging"
        self.candidate.mkdir()
        system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        self.shell = system32 / "WindowsPowerShell/v1.0/powershell.exe"
        self.system_exe = system32 / "rundll32.exe"
        self.executable = "Rose.exe"
        self.mutex_name = rf"Local\Rose-update-test-{uuid.uuid4()}"
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.log = self.workspace / "update.log"

    @staticmethod
    def write(root, relative, text):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def start_process(self, args, **kwargs):
        process = subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW, **kwargs)
        self.addCleanup(self.stop_process, process)
        return process

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=5)

    def launch_parent(self):
        return self.start_process([sys.executable, "-c", "import sys; sys.stdin.read()"],
                                  stdin=subprocess.PIPE, cwd=self.install_dir)

    def new_mutex(self):
        handle = self.kernel.CreateMutexW(None, False, self.mutex_name)
        error = ctypes.get_last_error()
        self.assertTrue(handle)
        return handle, error

    def script_args(self, *arguments):
        return [str(self.shell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", str(self.workspace / "apply.ps1"), *arguments]

    def write_plan(self, owner_pid, candidate):
        self.write(self.workspace, "apply.ps1", update_installer.APPLY_UPDATE_SCRIPT)
        self.write(self.workspace, "plan.json", json.dumps({
            "destination": str(self.install_dir),
            "executable": self.executable,
            "candidate": str(candidate),
            "parent_pid": owner_pid,
            "mutex": self.mutex_name,
        }))

    def wait_for_helper(self, process):
        deadline = time.monotonic() + 10
        while not (self.workspace / "ready").exists():
            if process.poll() is not None or time.monotonic() > deadline:
                self.fail(f"Helper did not acknowledge the mutex handoff (exit code {process.poll()})")
            time.sleep(0.05)

    def test_handoff_replaces_complete_tree_and_preserves_user_files(self):
        plugins = "_internal/Pengu Loader/plugins/"
        self.write(self.install_dir, plugins + "ROSE-Test/stale.js", "obsolete")
        self.write(self.install_dir, plugins + "ROSE-Test/index.js_", "disabled old code")
        self.write(self.install_dir, plugins + "ROSE-Enabled/index.js", "enabled old code")
        self.write(self.install_dir, plugins + "Other-Plugin/index.js", "user")
        self.write(self.install_dir, "_internal/Pengu Loader/datastore", "plugin settings")
        self.write(self.install_dir, "unins001.exe", "uninstaller")
        self.write(self.install_dir, "unins001.dat", "uninstall data")
        self.write(self.install_dir, "_internal/injection/tools/hashes.game.txt", "old hashes")
        self.write(self.install_dir, "config.ini", "local config")
        self.write(self.install_dir, "Rose.cfg", "legacy config")
        self.write(self.install_dir, "_internal/old.dll", "old")
        self.write(self.install_dir, "user-note.txt", "user data")
        self.write(self.install_dir, "unrelated-app/settings.txt", "its settings")
        self.write(self.install_dir, self.executable, "old exe")
        self.write(self.candidate, plugins + "ROSE-Test/index.js", "new")
        self.write(self.candidate, plugins + "ROSE-Enabled/index.js_", "new enabled")
        self.write(self.candidate, "_internal/injection/tools/hashes.game.txt", "new hashes")
        shutil.copyfile(self.system_exe, self.candidate / self.executable)
        owner = self.launch_parent()
        old_handle, error = self.new_mutex()
        self.assertEqual(error, 0)
        processes = []
        popen = subprocess.Popen

        def launch_helper(args, **kwargs):
            helper = popen(args[:-1], **kwargs)  # omit the interactive error message
            processes.append(helper)
            self.addCleanup(self.stop_process, helper)
            return helper

        try:
            statuses = []
            with patch.object(update_installer, "SINGLE_INSTANCE_MUTEX_NAME", self.mutex_name), \
                    patch.object(update_installer.os, "getpid", return_value=owner.pid), \
                    patch.object(update_installer.sys, "executable", str(self.install_dir / self.executable)), \
                    patch.object(update_installer.subprocess, "Popen", side_effect=launch_helper):
                self.assertTrue(self.installer.install(
                    self.candidate, self.install_dir, self.workspace, statuses.append,
                ), statuses)
            self.assertTrue((self.install_dir / "_internal/old.dll").is_file())
        finally:
            self.kernel.CloseHandle(old_handle)

        # The helper owns the only remaining handle. Another launch still
        # receives ERROR_ALREADY_EXISTS before the parent has exited.
        contender, error = self.new_mutex()
        self.kernel.CloseHandle(contender)
        self.assertEqual(error, 183)

        owner.communicate(timeout=5)
        helper = processes[0]
        self.assertEqual(helper.wait(timeout=15), 0)
        launched = re.search(r"Rose relaunched \(PID (\d+)\)", self.log.read_text(encoding="utf-8-sig"))
        self.assertIsNotNone(launched)
        try:
            psutil.Process(int(launched[1])).wait(timeout=5)
        except psutil.NoSuchProcess:
            pass
        self.assertFalse((self.install_dir / "_internal/old.dll").exists())
        self.assertFalse((self.install_dir / (plugins + "ROSE-Test/stale.js")).exists())
        self.assertFalse((self.install_dir / (plugins + "ROSE-Test/index.js")).exists())
        self.assertEqual((self.install_dir / (plugins + "ROSE-Test/index.js_")).read_text(), "new")
        self.assertEqual((self.install_dir / (plugins + "ROSE-Enabled/index.js")).read_text(), "new enabled")
        self.assertEqual((self.install_dir / (plugins + "Other-Plugin/index.js")).read_text(), "user")
        self.assertEqual((self.install_dir / "_internal/Pengu Loader/datastore").read_text(), "plugin settings")
        self.assertEqual((self.install_dir / "unins001.exe").read_text(), "uninstaller")
        self.assertEqual((self.install_dir / "unins001.dat").read_text(), "uninstall data")
        self.assertEqual((self.install_dir / "config.ini").read_text(), "local config")
        self.assertEqual((self.install_dir / "Rose.cfg").read_text(), "legacy config")
        self.assertEqual((self.install_dir / "_internal/injection/tools/hashes.game.txt").read_text(), "old hashes")
        self.assertEqual((self.install_dir / "user-note.txt").read_text(), "user data")
        self.assertEqual((self.install_dir / "unrelated-app/settings.txt").read_text(), "its settings")
        self.assertTrue((self.workspace / "previous/_internal/old.dll").is_file())
        contender, error = self.new_mutex()
        self.kernel.CloseHandle(contender)
        self.assertEqual(error, 0)

    def test_second_rename_failure_restores_old_tree(self):
        self.write(self.install_dir, self.executable, "old exe")
        self.write(self.install_dir, "old.dll", "old")
        # The candidate passes validation. Moving the live tree to previous
        # then makes the candidate's original path unavailable.
        candidate = self.install_dir / "misplaced"
        self.write(candidate, self.executable, "candidate exe")
        owner = self.launch_parent()
        self.write_plan(owner.pid, candidate)
        handle, error = self.new_mutex()
        self.assertEqual(error, 0)
        try:
            helper = self.start_process(self.script_args(), cwd=self.workspace)
            self.wait_for_helper(helper)
            owner.communicate(timeout=5)
        finally:
            self.kernel.CloseHandle(handle)

        self.assertEqual(helper.wait(timeout=15), 1)
        self.assertEqual((self.install_dir / self.executable).read_text(), "old exe")
        self.assertEqual((self.install_dir / "old.dll").read_text(), "old")
        self.assertFalse((self.workspace / "previous").exists())
        self.assertNotIn("Update applied", self.log.read_text(encoding="utf-8-sig"))

    def test_recovery_can_run_again_after_interrupted_swap(self):
        self.write(self.install_dir, self.executable, "old exe")
        self.write(self.candidate, self.executable, "candidate exe")
        self.write_plan(0, self.candidate)
        self.install_dir.rename(self.workspace / "previous")

        # This is the persisted state after a kill or power loss between renames.
        for _ in range(2):
            recovery = self.start_process(self.script_args("-Recover"), cwd=self.workspace)
            self.assertEqual(recovery.wait(timeout=10), 0)
            self.assertEqual((self.install_dir / self.executable).read_text(), "old exe")

    def test_launch_failure_restores_previous_installation_and_keeps_failed_tree(self):
        self.write(self.install_dir, self.executable, "old exe")
        self.write(self.candidate, self.executable, "MZ invalid executable")
        owner = self.launch_parent()
        self.write_plan(owner.pid, self.candidate)
        handle, error = self.new_mutex()
        self.assertEqual(error, 0)
        try:
            helper = self.start_process(self.script_args(), cwd=self.workspace)
            self.wait_for_helper(helper)
        finally:
            # The running Rose drops its handle when it exits. Here the test
            # process holds that handle on behalf of the temporary parent.
            self.kernel.CloseHandle(handle)
        owner.communicate(timeout=5)

        self.assertEqual(helper.wait(timeout=15), 1)
        self.assertEqual((self.install_dir / self.executable).read_text(), "old exe")
        self.assertEqual((self.workspace / "failed" / self.executable).read_text(), "MZ invalid executable")
        log = self.log.read_text(encoding="utf-8-sig")
        self.assertIn("Could not launch the installed Rose", log)
        self.assertIn("Previous installation restored", log)
        self.assertNotIn("Update applied", log)

    def test_extraction_rejects_incomplete_or_oversized_archive(self):
        package = self.workspace / "package.zip"
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr(self.executable, b"MZ exe")
            archive.writestr("_internal/file.dll", "library")
        statuses = []
        with patch.object(safe_extract, "MAX_ARCHIVE_ENTRIES", 1):
            self.assertIsNone(self.installer.extract_update(package, self.candidate, lambda _: None, statuses.append))
        self.assertIn("2 entries", statuses[-1])
        with patch.object(update_installer.sys, "executable", str(self.install_dir / self.executable)):
            self.assertIsNone(self.installer.extract_update(package, self.candidate, lambda _: None, statuses.append))
        self.assertIn("Python runtime", statuses[-1])

    def test_rejects_truncated_archive_and_runtime_without_python_dll(self):
        package = self.workspace / "package.zip"
        statuses = []
        with patch.object(update_installer.sys, "executable", str(self.install_dir / self.executable)):
            library = io.BytesIO()
            with zipfile.ZipFile(library, "w") as archive:
                archive.writestr("encodings/__init__.pyc", "test")
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr(self.executable, b"MZ exe")
                archive.writestr("_internal/base_library.zip", library.getvalue())
            self.assertIsNone(self.installer.extract_update(package, self.candidate, lambda _: None, statuses.append))
            self.assertIn("Python runtime", statuses[-1])

            with zipfile.ZipFile(package, "a") as archive:
                archive.writestr("_internal/python312.dll", b"MZ library")
            self.assertEqual(
                self.installer.extract_update(package, self.candidate, lambda _: None, statuses.append),
                self.candidate,
            )

            package.write_bytes(package.read_bytes()[:-12])
            self.assertIsNone(self.installer.extract_update(package, self.candidate, lambda _: None, statuses.append))
            self.assertIn("File is not a zip file", statuses[-1])

    def test_leaves_an_unrelated_sibling_folder_alone(self):
        other_install = self.install_dir.with_name("Unrelated")
        unrelated = other_install.with_name("Unrelated.update")
        self.write(unrelated, "file.txt", "unrelated user data")

        with self.assertRaisesRegex(OSError, "was not created by Rose"):
            self.installer.workspace(other_install)
        self.assertEqual((unrelated / "file.txt").read_text(), "unrelated user data")

    def test_preserves_root_files_through_successive_upgrades(self):
        self.write(self.install_dir, "user-note.txt", "user data")
        self.write(self.install_dir, "unrelated-app/settings.txt", "its settings")
        self.write(self.install_dir, "_internal/obsolete.dll", "obsolete")
        self.write(self.candidate, "_internal/new.dll", "candidate")
        third = self.workspace / "third"
        self.write(third, "_internal/newer.dll", "third")

        update_installer._preserve_install_files(self.install_dir, self.candidate)
        update_installer._preserve_install_files(self.candidate, third)

        self.assertEqual((third / "user-note.txt").read_text(), "user data")
        self.assertEqual((third / "unrelated-app/settings.txt").read_text(), "its settings")
        self.assertFalse((third / "_internal/obsolete.dll").exists())
        self.assertFalse((third / "_internal/new.dll").exists())

    def test_refuses_to_overwrite_unrelated_root_files(self):
        self.write(self.install_dir, "user-note.txt", "user data")
        self.write(self.install_dir, "_internal/old.dll", "old")
        self.write(self.candidate, "user-note.txt", "candidate")

        with self.assertRaisesRegex(OSError, "conflicts with an existing"):
            update_installer._preserve_install_files(self.install_dir, self.candidate)
        self.assertEqual((self.install_dir / "user-note.txt").read_text(), "user data")
