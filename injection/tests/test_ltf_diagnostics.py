import unittest
from unittest.mock import patch

from injection.overlay.overlay_manager import LTF_LOGS_HINT
from pengu.communication import message_handler


def summarize(*reports):
    """Troubleshooting's summaries of (message, fix) reports, as the file holds them."""
    lines = []
    for message, fix in reports:
        lines.append(f"Nov 02 00:52 | {message}")
        lines.append(f"Fix: {fix}")
    handler = object.__new__(message_handler.MessageHandler)
    with patch.object(message_handler, "read_issues_tail", return_value=lines):
        return message_handler.MessageHandler._compute_diagnostics_errors(handler)


class LtfDiagnosticsTests(unittest.TestCase):
    def test_an_import_failure_without_ltf_in_its_text_is_still_one(self):
        # The mod name and the error text name neither LTF nor LTK Manager
        (summary,) = summarize((
            "Injection failed: could not install Beezcrank (Rose Quartz) (LTKBridge request failed: timed out).",
            f"Free some disk space, then retry. {LTF_LOGS_HINT}",
        ))

        self.assertEqual(summary["code"], "LTF_IMPORT_FAILED")
        self.assertEqual(summary["cause"], "import")

    def test_a_session_failure_is_recognized_by_its_hint(self):
        (summary,) = summarize((
            "Injection failed: the game started before the patcher was scanning (joined too late)",
            f"The game started before the patcher was ready. Retry the next game. {LTF_LOGS_HINT}",
        ))

        self.assertEqual(summary["code"], "LTF_FAILED")
        self.assertEqual(summary["cause"], "late")

    def test_an_open_ltk_manager_gets_its_own_cause(self):
        (summary,) = summarize((
            "Injection failed: LTK Manager is already open without Rose's bridge",
            f"Close LTK Manager, then retry. {LTF_LOGS_HINT}",
        ))

        self.assertEqual(summary["code"], "LTF_FAILED")
        self.assertEqual(summary["cause"], "running")


if __name__ == "__main__":
    unittest.main()
