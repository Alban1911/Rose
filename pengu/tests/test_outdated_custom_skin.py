"""A custom skin still as an older Rose prepared it: the player is told, in Troubleshooting, to add it again."""

import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from injection.baseskin import library
from pengu.communication import message_handler
from utils.core import issue_reporter

SESSION = "cccc0003"


class OutdatedCustomSkinTests(unittest.TestCase):
    def setUp(self):
        self.handler = object.__new__(message_handler.MessageHandler)
        self.handler.mod_storage = SimpleNamespace(mods_root=Path("C:/mods"))
        self.picked = SimpleNamespace(path=Path("C:/mods/skins/81000/Gojo.fantome"),
                                      display_name="Gojo Ezreal", mod_name="Gojo")

    def test_picking_an_outdated_skin_reports_it(self):
        with patch.object(library, "needs_reinstall", return_value=True) as check, \
                patch.object(library, "report_outdated") as report:
            self.handler._warn_if_outdated(self.picked)
        check.assert_called_once_with(Path("C:/mods"), self.picked.path)
        report.assert_called_once_with("Gojo Ezreal")

    def test_picking_an_up_to_date_skin_reports_nothing(self):
        with patch.object(library, "needs_reinstall", return_value=False), \
                patch.object(library, "report_outdated") as report:
            self.handler._warn_if_outdated(self.picked)
        report.assert_not_called()

    def test_a_check_that_fails_never_fails_the_pick(self):
        with patch.object(library, "needs_reinstall", side_effect=OSError("locked")):
            self.handler._warn_if_outdated(self.picked)

    def test_troubleshooting_shows_it_with_the_skins_name(self):
        line = (f"{time.strftime('%Y-%m-%d %H:%M:%S')} [CUSTOM_SKIN_OUTDATED] #{SESSION} | "
                f"Custom skin Gojo Ezreal was added with an older Rose")
        lines = [line, "Fix: Please update your custom skin by reinstalling it into Rose."]
        with patch.object(message_handler, "read_issues_tail", return_value=lines), \
                patch.object(issue_reporter, "SESSION_ID", SESSION):
            errors = self.handler._compute_diagnostics_errors()
        self.assertEqual([(e["code"], e.get("detail"), e["thisSession"]) for e in errors],
                         [("CUSTOM_SKIN_OUTDATED", "Gojo Ezreal", True)])


if __name__ == "__main__":
    unittest.main()
