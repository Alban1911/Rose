"""The LTK Manager version Rose logs comes from the executable's version resource (#479)."""

import re
import sys
import tempfile
import unittest
from pathlib import Path

from injection.tools.tools_manager import _with_version, file_version


class FileVersionTests(unittest.TestCase):
    def test_an_executable_with_a_version_resource(self):
        # python.exe carries one, as ltk-manager.exe does
        version = file_version(Path(sys.executable))

        self.assertRegex(version or "", r"^\d+\.\d+\.\d+(\.\d+)?$")
        self.assertTrue(_with_version(Path(sys.executable)).endswith(f"(v{version})"))

    def test_a_file_without_one(self):
        with tempfile.TemporaryDirectory() as folder:
            plain = Path(folder) / "ltk-manager.exe"
            plain.write_bytes(b"not a program")

            self.assertIsNone(file_version(plain))
            self.assertEqual(_with_version(plain), str(plain))

    def test_a_missing_file(self):
        missing = Path(tempfile.gettempdir()) / "no-such-ltk-manager" / "ltk-manager.exe"

        self.assertIsNone(file_version(missing))
        self.assertIsNone(re.search(r"\(v", _with_version(missing)))


if __name__ == "__main__":
    unittest.main()
