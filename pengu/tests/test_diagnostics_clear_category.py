import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pengu.communication import message_handler
from utils.core import issue_reporter

SESSION = "aaaa0001"

LINES = [
    (f"2026-11-12 10:00:00 [BASE_SKIN_VERIFY_FAILED] #{SESSION} | "
     "Base skin verification failed (selected skin may not apply)."),
    ("Fix: Base skin force time: 1.900s, injection threshold: 1.000s. "
     "Increase Injection Threshold until the warning is gone, then retry."),
    (f"2026-11-12 10:05:00 [LTF_FAILED] #{SESSION} | Injection failed: LTK Manager's patcher "
     "refused the overlay (host verification failed: parent (cmd.exe))"),
    "Fix: Reinstall LTK Manager.",
]


class DiagnosticsClearCategoryTests(unittest.TestCase):
    def setUp(self):
        self.handler = object.__new__(message_handler.MessageHandler)
        self.sent = []
        self.handler._send_response = lambda message: self.sent.append(json.loads(message))
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = self.dir / "rose_diagnostics.txt"
        self.path.write_text("\n".join(LINES) + "\n", encoding="utf-8")
        for patcher in (
            patch.object(message_handler, "get_user_data_dir", return_value=self.dir),
            patch.object(issue_reporter, "get_user_data_dir", return_value=self.dir),
            patch("injection.config.base_skin_tracker.get_stats", return_value={}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_clearing_injection_threshold_keeps_an_ltk_patcher_refusal(self):
        self.assertEqual([e["code"] for e in self.handler._compute_diagnostics_errors()],
                         ["LTF_FAILED", "BASE_SKIN_VERIFY_FAILED"])

        self.handler._handle_diagnostics_clear_category({"categories": ["injection_threshold"]})

        self.assertEqual([e["code"] for e in self.handler._compute_diagnostics_errors()], ["LTF_FAILED"])
        self.assertEqual(self.path.read_text(encoding="utf-8").splitlines(), LINES[2:])
        self.assertTrue(self.sent[-1]["success"])

    def test_clearing_another_category_keeps_every_report(self):
        self.handler._handle_diagnostics_clear_category({"categories": ["monitor_timeout"]})

        self.assertEqual(self.path.read_text(encoding="utf-8").splitlines(), LINES)


if __name__ == "__main__":
    unittest.main()
