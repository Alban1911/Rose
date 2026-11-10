import os
import sys
import unittest
from pathlib import Path

from utils.system.process_list import running_processes


class RunningProcessesTests(unittest.TestCase):
    def test_this_process_is_listed_by_its_executable_name(self):
        names = dict(running_processes())

        self.assertEqual(names[os.getpid()].lower(), Path(sys.executable).name.lower())

    def test_every_process_has_a_name(self):
        processes = running_processes()

        self.assertGreater(len(processes), 1)
        self.assertTrue(all(name for _, name in processes))


if __name__ == '__main__':
    unittest.main()
