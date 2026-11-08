import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from injection.core.mod_source import saved_selection
from injection.mods.ltk_ref import ltk_ref
from injection.mods.mod_facts import ModFacts
from injection.mods.storage import ModStorageService
from threads.handlers.injection_trigger import InjectionTrigger

# LTK Manager library ids of saved mods
SKIN_ID = "5e9b2219-f49f-4cf1-bc7e-774fb43e1349"
FONT_ID = "d6f841c7-140b-4ac2-a11c-b37e18eb8006"


class CustomModInjectionCase(unittest.TestCase):
    """A custom mod injection with its manager and injector mocked"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)

        self.manager = MagicMock()
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
        cache = patch("injection.core.mod_source.get_injection_dir", return_value=self.root / "injection")
        cache.start()
        self.addCleanup(cache.stop)

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
        self.manager.start_patcher_in_background.assert_called_once()
        self.manager.discard_early_patcher.assert_called_once()


class CustomModInjectionStagingTests(CustomModInjectionCase):
    """LTK Manager is brought up while the mods are prepared, and every way
    out of a custom mod injection ends the countdown's staging"""

    def test_a_missing_carrier_archive_ends_the_staging(self):
        self.injector._resolve_zip.return_value = None
        self.inject(self.custom_mod(self.root / "Mod"), base_skin_name="skin_103001")
        self.injector.overlay_manager.mk_run_overlay.assert_not_called()

    def test_a_missing_mod_source_ends_the_staging(self):
        self.inject(self.custom_mod(self.root / "deleted"))
        self.injector.overlay_manager.mk_run_overlay.assert_not_called()

    def test_nothing_to_inject_ends_the_staging(self):
        self.inject({"mod_folder_name": None, "mod_path": None, "skin_id": 103001})
        self.injector.overlay_manager.mk_run_overlay.assert_not_called()

    def test_an_error_ends_the_staging(self):
        mod_source = self.root / "Mod"
        mod_source.mkdir()
        with patch("injection.core.mod_source.link_or_extract", side_effect=OSError("locked")):
            self.inject(self.custom_mod(mod_source))
        self.injector.overlay_manager.mk_run_overlay.assert_not_called()

    def test_a_completed_injection_ends_the_staging(self):
        mod_source = self.root / "Mod"
        mod_source.mkdir()

        def link(source, dest, cache_dir=None):
            dest.mkdir(parents=True)

        with patch("injection.core.mod_source.link_or_extract", side_effect=link), \
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

        def link_archive(zp):
            self.events.append("link carrier")
            linked = self.root / "mods" / "103001"
            linked.parent.mkdir(parents=True, exist_ok=True)
            linked.write_bytes(Path(zp).read_bytes())
            return linked

        self.injector._link_archive.side_effect = link_archive
        self.trigger._force_base_skin.side_effect = lambda skin_id: self.events.append(f"force {skin_id}")
        self.trigger.state.selected_font_mod = {
            "mod_name": "Font", "mod_folder_name": "Font", "mod_path": str(self.root / "Font"),
        }
        (self.root / "Font").mkdir()

    def link(self, source, dest, cache_dir=None):
        self.events.append(f"link {Path(source).name}")
        dest.mkdir(parents=True, exist_ok=True)

    def test_the_default_skin_is_forced_before_any_mod_is_extracted(self):
        with patch("injection.core.mod_source.link_or_extract", side_effect=self.link), \
                patch("utils.core.mod_historic.write_historic_mod"), \
                patch("utils.core.historic.write_historic_entry"):
            self.inject({"mod_folder_name": None, "skin_id": 103001, "champion_id": 103},
                        base_skin_name="skin_103001")

        self.assertEqual(self.events, ["force 103000", "link carrier", "link Font"])
        self.injector.overlay_manager.mk_run_overlay.assert_called_once()

    def test_a_missing_carrier_forces_nothing(self):
        self.injector._resolve_zip.return_value = None
        self.inject({"mod_folder_name": None, "skin_id": 103001, "champion_id": 103},
                    base_skin_name="skin_103001")

        self.trigger._force_base_skin.assert_not_called()

    def test_an_owned_skin_is_not_forced(self):
        with patch("injection.core.mod_source.link_or_extract", side_effect=self.link), \
                patch("utils.core.mod_historic.write_historic_mod"):
            self.inject({"mod_folder_name": None, "skin_id": 103001, "champion_id": 103})

        self.trigger._force_base_skin.assert_not_called()


class SavedLtkModInjectionTests(CustomModInjectionCase):
    """A saved mod LTK Manager holds goes into the injection as its LTK
    reference, with nothing linked into the mods folder"""

    def selection(self, name, ltk_id, missing=False, facts=None):
        path = self.root / "library" / f"{name}.fantome"  # Rose's copy is gone
        return {"mod_name": name, **saved_selection(path, ltk_id, missing, facts)}

    def test_the_custom_mod_and_a_font_go_as_their_references(self):
        custom = dict(self.selection("Mod", SKIN_ID, facts=ModFacts(None, ("Annie",), False)),
                      skin_id=103001, champion_id=103)
        font_facts = ModFacts(None, (), True)
        self.trigger.state.selected_font_mod = self.selection("Font", FONT_ID, facts=font_facts)

        with patch("injection.core.mod_source.link_or_extract", side_effect=AssertionError("linked")), \
                patch("threads.handlers.injection_trigger.build_loading_name", return_value=None) as loading_name, \
                patch("utils.core.mod_historic.write_historic_mod"), \
                patch("utils.core.historic.write_historic_entry"), \
                patch("utils.core.historic.write_historic_target"):
            self.inject(custom)

        names = self.injector.overlay_manager.mk_run_overlay.call_args.args[0]
        self.assertEqual(names, [ltk_ref(SKIN_ID), ltk_ref(FONT_ID)])
        self.assertEqual(loading_name.call_args.args[2].aliases, ("Annie",))
        self.assertEqual(loading_name.call_args.kwargs["other_mods"], [font_facts])

    def test_a_custom_mod_missing_from_ltk_manager_is_not_injected(self):
        custom = dict(self.selection("Mod", SKIN_ID, missing=True), skin_id=103001, champion_id=103)

        self.inject(custom)

        self.injector.overlay_manager.mk_run_overlay.assert_not_called()

    def saved_custom_mod(self, historic="skins/103000/Mod.fantome", copy=None, **entry):
        """The custom mod the last game saved for Ahri (*historic*), as the
        trigger restores it; *copy* is a file Rose still holds of it"""
        storage = ModStorageService(self.root / "library")
        manifest = storage.get_champion_dir(103) / ModStorageService.TARGET_METADATA
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"version": 1, "mods": {
            "Mod": {"name": "Mod", "targets": [103001], "ltkId": SKIN_ID, **entry},
        }}), encoding="utf-8")
        if copy:
            (manifest.parent / copy).write_bytes(b"PK\x05\x06" + bytes(18))
        with patch("injection.mods.storage.ModStorageService", return_value=storage), \
                patch("utils.core.historic.get_historic_skin_for_champion", return_value=f"path:{historic}"), \
                patch("utils.core.historic.get_historic_target_for_champion", return_value=None):
            return self.trigger._saved_custom_mod(103001, 103001)

    def test_a_saved_custom_mod_ltk_manager_holds_is_restored_as_its_reference(self):
        facts = ModFacts(None, ("Ahri",), False)

        selection = self.saved_custom_mod(**facts.to_manifest())

        self.assertEqual(selection["mod_folder_name"], ltk_ref(SKIN_ID))
        self.assertEqual((selection["ltk_id"], selection["facts"]), (SKIN_ID, facts.to_manifest()))
        self.assertEqual(selection["relative_path"], "skins/103000/Mod.fantome")

    def test_a_saved_custom_mod_still_named_by_the_zip_rose_kept_is_restored(self):
        """A selection the migration could not rename names the .zip Rose kept of the mod"""
        selection = self.saved_custom_mod(historic="skins/103000/Mod.zip", copy="Mod.zip")

        self.assertEqual((selection["ltk_id"], selection["mod_folder_name"]), (SKIN_ID, ltk_ref(SKIN_ID)))
        self.assertEqual(selection["relative_path"], "skins/103000/Mod.fantome")

    def test_a_saved_custom_mod_ltk_manager_lost_is_not_restored(self):
        with self.assertLogs(level="WARNING"):
            self.assertIsNone(self.saved_custom_mod(missing=True))


if __name__ == "__main__":
    unittest.main()
