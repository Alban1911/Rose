"""schtasks output in a non-ANSI code page must not crash a reader thread (#478)."""

import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from utils.system import admin_utils

# What a Turkish schtasks prints when the task does not exist, as console (OEM)
# bytes: 0x8d is "ı" in cp857 and undefined in the ANSI pages (cp1252, cp1254)
TURKISH_ERROR = b"HATA: Sistem belirtilen dosyay\x8d bulam\x8dyor.\r\n"


def _schtasks_stand_in(code: int):
    """subprocess.run with schtasks replaced by a child printing TURKISH_ERROR."""
    real_run = subprocess.run
    script = (
        "import sys; "
        f"sys.stdout.buffer.write({TURKISH_ERROR!r}); "
        f"sys.stderr.buffer.write({TURKISH_ERROR!r}); "
        f"sys.exit({code})"
    )

    def run(_command, *args, **kwargs):
        return real_run([sys.executable, "-c", script], *args, **kwargs)

    return run


class SchtasksOutputTests(unittest.TestCase):
    def setUp(self):
        self.thread_errors = []
        hook = patch.object(threading, "excepthook", lambda hook_args: self.thread_errors.append(hook_args.exc_value))
        hook.start()
        self.addCleanup(hook.stop)

    def test_checking_autostart_reads_only_the_exit_code(self):
        with patch.object(admin_utils.subprocess, "run", _schtasks_stand_in(1)):
            registered = admin_utils.is_registered_for_autostart()

        self.assertFalse(registered)
        self.assertEqual(self.thread_errors, [])

    def test_a_failed_registration_reports_schtasks_message(self):
        with patch.object(admin_utils, "is_admin", return_value=True), \
                patch.object(admin_utils, "is_registered_for_autostart", return_value=False), \
                patch.object(admin_utils.subprocess, "run", _schtasks_stand_in(1)):
            ok, message = admin_utils.register_autostart()

        self.assertFalse(ok)
        self.assertTrue(message.startswith("Failed to register: HATA: Sistem belirtilen dosyay"), message)
        self.assertEqual(self.thread_errors, [])

    def test_a_failed_removal_reports_schtasks_message(self):
        with patch.object(admin_utils, "is_admin", return_value=True), \
                patch.object(admin_utils, "is_registered_for_autostart", return_value=True), \
                patch.object(admin_utils.subprocess, "run", _schtasks_stand_in(1)):
            ok, message = admin_utils.unregister_autostart()

        self.assertFalse(ok)
        self.assertTrue(message.startswith("Failed to unregister: HATA: Sistem belirtilen dosyay"), message)
        self.assertEqual(self.thread_errors, [])


if __name__ == "__main__":
    unittest.main()
