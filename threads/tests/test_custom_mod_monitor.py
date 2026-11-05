import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from threads.handlers.injection_trigger import InjectionTrigger


class CustomModInjectionCase(unittest.TestCase):
    """A custom mod injection with its game monitor and injector mocked"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)

        self.monitor_active = False
        self.manager = MagicMock()
        type(self.manager)._monitor_active = property(lambda _: self.monitor_active)
        self.manager._start_monitor.side_effect = lambda: setattr(self, "monitor_active", True)
        self.manager._stop_monitor.side_effect = lambda: setattr(self, "monitor_active", False)
        self.injector = self.manager.injector
        self.injector.mods_dir = self.root / "mods"
        self.injector.overlay_manager.mk_run_overlay.return_value = 0

        state = SimpleNamespace(
            locked_champ_id=103,
            hovered_champ_id=None,
            selected_map_mod=None,
            selected_font_mod=None,
            selected_announcer_mod=None,
            selected_other_mods=None,
            selected_other_mod=None,
            selected_custom_mod=None,
            party_manager=None,
        )
        self.trigger = InjectionTrigger(lcu=MagicMock(), state=state, injection_manager=self.manager)
        self.trigger._force_base_skin = MagicMock()

    def custom_mod(self, mod_path):
        return {
            "mod_name": "Mod",
            "mod_folder_name": "Mod",
            "mod_path": str(mod_path),
            "skin_id": 103001,
            "champion_id": 103,
        }

    def inject(self, custom_mod, **kwargs):
        self.trigger._inject_custom_mod(custom_mod, **kwargs)
        self.manager._start_monitor.assert_called_once()
        self.assertFalse(self.monitor_active, "the game monitor is still running")


class CustomModInjectionMonitorTests(CustomModInjectionCase):
    """The game monitor suspends the game while mods are prepared, so every
    way out of a custom mod injection stops it and lets the game run"""

    def test_a_missing_carrier_archive_stops_the_monitor(self):
        self.injector._resolve_zip.return_value = None
        self.inject(self.custom_mod(self.root / "Mod"), base_skin_name="skin_103001")
        self.injector.overlay_manager.mk_run_overlay.assert_not_called()

    def test_a_missing_mod_source_stops_the_monitor(self):
        self.inject(self.custom_mod(self.root / "deleted"))
        self.injector.overlay_manager.mk_run_overlay.assert_not_called()

    def test_nothing_to_inject_stops_the_monitor(self):
        self.inject({"mod_folder_name": None, "mod_path": None, "skin_id": 103001})
        self.injector.overlay_manager.mk_run_overlay.assert_not_called()

    def test_an_error_stops_the_monitor(self):
        mod_source = self.root / "Mod"
        mod_source.mkdir()
        with patch("threads.handlers.injection_trigger.link_or_extract", side_effect=OSError("locked")):
            self.inject(self.custom_mod(mod_source))
        self.injector.overlay_manager.mk_run_overlay.assert_not_called()

    def test_a_completed_injection_stops_the_monitor(self):
        mod_source = self.root / "Mod"
        mod_source.mkdir()

        def link(source, dest, cache_dir=None):
            dest.mkdir(parents=True)

        with patch("threads.handlers.injection_trigger.link_or_extract", side_effect=link), \
                patch("utils.core.mod_historic.write_historic_mod"), \
                patch("utils.core.historic.write_historic_entry"), \
                patch("utils.core.historic.write_historic_target"):
            self.inject(self.custom_mod(mod_source))
        self.injector.overlay_manager.mk_run_overlay.assert_called_once()


class CustomModBaseSkinTests(CustomModInjectionCase):
    """The default skin a carrier replaces is forced before the mods are
    extracted, while the champ select still accepts it (issue #422)"""

    def setUp(self):
        super().setUp()
        self.events = []
        archive = self.root / "103001.fantome"
        archive.write_bytes(b"skin")
        self.injector._resolve_zip.return_value = archive

        def extract(zp):
            self.events.append("extract carrier")
            folder = self.root / "mods" / "103001"
            folder.mkdir(parents=True, exist_ok=True)
            return folder

        self.injector._extract_zip_to_mod.side_effect = extract
        self.trigger._force_base_skin.side_effect = lambda skin_id: self.events.append(f"force {skin_id}")
        self.trigger.state.selected_font_mod = {
            "mod_name": "Font", "mod_folder_name": "Font", "mod_path": str(self.root / "Font"),
        }
        (self.root / "Font").mkdir()

    def link(self, source, dest, cache_dir=None):
        self.events.append(f"link {Path(source).name}")
        dest.mkdir(parents=True, exist_ok=True)

    def test_the_default_skin_is_forced_before_any_mod_is_extracted(self):
        with patch("threads.handlers.injection_trigger.link_or_extract", side_effect=self.link), \
                patch("utils.core.mod_historic.write_historic_mod"), \
                patch("utils.core.historic.write_historic_entry"):
            self.inject({"mod_folder_name": None, "skin_id": 103001, "champion_id": 103},
                        base_skin_name="skin_103001")

        self.assertEqual(self.events, ["force 103000", "extract carrier", "link Font"])
        self.injector.overlay_manager.mk_run_overlay.assert_called_once()

    def test_a_missing_carrier_forces_nothing(self):
        self.injector._resolve_zip.return_value = None
        self.inject({"mod_folder_name": None, "skin_id": 103001, "champion_id": 103},
                    base_skin_name="skin_103001")

        self.trigger._force_base_skin.assert_not_called()

    def test_an_owned_skin_is_not_forced(self):
        with patch("threads.handlers.injection_trigger.link_or_extract", side_effect=self.link), \
                patch("utils.core.mod_historic.write_historic_mod"):
            self.inject({"mod_folder_name": None, "skin_id": 103001, "champion_id": 103})

        self.trigger._force_base_skin.assert_not_called()


if __name__ == "__main__":
    unittest.main()
