import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils.download.marketplace import repair


class RepairArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.archive = Path(self.tmp.name) / "Feixiao Samira.fantome"
        self.archive.write_bytes(b"PK")

    def tearDown(self):
        self.tmp.cleanup()

    def run_with(self, report: dict, write_output: bool = True):
        def fake_run(command, **_kwargs):
            if write_output:
                Path(command[2]).write_bytes(b"fixed")
            return subprocess.CompletedProcess(command, 0, json.dumps(report) + "\n", "")

        with mock.patch.object(repair, "find_repair_tool", return_value=Path("rose-repair.exe")), \
                mock.patch.object(repair, "league_root", return_value=None), \
                mock.patch.object(repair.subprocess, "run", side_effect=fake_run):
            return repair.repair_archive(self.archive)

    def test_missing_tool_keeps_original(self):
        with mock.patch.object(repair, "find_repair_tool", return_value=None):
            result = repair.repair_archive(self.archive)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.path, self.archive)

    def test_repaired_file_keeps_mod_name(self):
        result = self.run_with({"status": "repaired", "applied": 12, "extension": "fantome"})
        self.assertEqual(result.status, "repaired")
        self.assertEqual(result.applied, 12)
        self.assertEqual(result.path.name, self.archive.name)
        self.assertEqual(result.path.read_bytes(), b"fixed")

    def test_unchanged_and_failed_keep_original(self):
        self.assertEqual(self.run_with({"status": "unchanged"}, False).path, self.archive)
        failed = self.run_with({"status": "failed", "error": "boom"}, False)
        self.assertEqual((failed.status, failed.error, failed.path), ("failed", "boom", self.archive))


if __name__ == "__main__":
    unittest.main()
