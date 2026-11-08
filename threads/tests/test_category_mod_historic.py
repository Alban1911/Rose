import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from state import SharedState
from threads.handlers.injection_trigger import InjectionTrigger
from injection.mods.mod_source import LtkEntry, RoseFile
from injection.mods.storage import ModStorageService
from utils.core import mod_historic

# The LTK Manager library id of a saved mod
LTK_ID = "5e9b2219-f49f-4cf1-bc7e-774fb43e1349"


class SynchronousThread:
    """threading.Thread running its target at start(): the test sees what it did."""

    def __init__(self, target, **_):
        self.target = target

    def start(self):
        self.target()


class CategoryModHistoricTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = SharedState(locked_champ_id=1, last_hovered_skin_id=1000)
        self.state.selected_other_mods = []
        self.manager = MagicMock()
        self.manager.injector.mods_dir = self.root / 'injection' / 'mods'
        self.manager.injector.overlay_manager.mk_run_overlay.return_value = 0
        self.trigger = InjectionTrigger(MagicMock(), self.state, self.manager)
        self.trigger._force_base_skin = MagicMock()
        self.storage = ModStorageService(self.root / 'library')
        self.source = self.storage.mods_root / 'vfx' / 'Saved VFX'
        self.source.mkdir(parents=True)
        (self.source.parent / self.storage.CATEGORY_METADATA).write_text(json.dumps({
            'mods': {'Saved VFX': {'name': 'Saved VFX', 'path': 'Saved VFX'}},
        }), encoding='utf-8')
        for target, kwargs in (
            ('injection.mods.storage.ModStorageService', {'return_value': self.storage}),
            ('utils.core.historic.get_historic_skin_for_champion', {'return_value': None}),
            ('utils.core.mod_historic.load_mod_historic', {'return_value': {'vfx': ['vfx/Saved VFX']}}),
            ('utils.core.mod_historic.write_historic_mod', {}),
            ('utils.core.historic.write_historic_entry', {}),
            ('utils.core.historic.write_historic_target', {}),
            ('injection.mods.mod_source.get_injection_dir', {'return_value': self.root / 'injection'}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def link(self, source, dest, cache_dir=None):
        dest.mkdir(parents=True, exist_ok=True)

    def test_saved_category_mod_reaches_overlay_without_opening_selector(self):
        with patch('injection.mods.mod_source.link_or_extract', side_effect=self.link):
            self.trigger.trigger_injection('skin_1000', ticker_id=1)
        self.assertTrue(self.state.selected_other_mods, 'saved category selection was not restored')
        self.assertEqual(self.state.selected_other_mods[0]['relative_path'], 'vfx/Saved VFX')
        overlay = self.manager.injector.overlay_manager.mk_run_overlay
        overlay.assert_called_once()
        self.assertIn('Saved VFX', overlay.call_args.args[0])

    def test_a_history_listing_a_mod_under_two_categories_selects_it_once(self):
        """Before #379 each category write also listed its paths under "others"."""
        legacy = {'vfx': ['vfx/Saved VFX'], 'others': ['vfx/Saved VFX']}
        with patch('utils.core.mod_historic.load_mod_historic', return_value=legacy), \
                patch('injection.mods.mod_source.link_or_extract', side_effect=self.link):
            self.trigger.trigger_injection('skin_1000', ticker_id=1)
        self.assertEqual([m['relative_path'] for m in self.state.selected_other_mods], ['vfx/Saved VFX'])
        names = self.manager.injector.overlay_manager.mk_run_overlay.call_args.args[0]
        self.assertEqual(names.count('Saved VFX'), 1)

    def test_the_countdown_plan_includes_saved_category_mods(self):
        """The staging plan read a key load_mod_historic never returns ("other")."""
        planned = self.trigger._planned_other_mods()
        self.assertEqual([m['relative_path'] for m in planned], ['vfx/Saved VFX'])

    def test_current_selection_wins_over_saved_category_mod(self):
        current = self.storage.mods_root / 'vfx' / 'Current VFX'
        current.mkdir()
        self.state.selected_other_mods = [{
            'mod_name': 'Current VFX', 'relative_path': 'vfx/Current VFX', 'source': RoseFile.at(current),
        }]
        with patch('injection.mods.mod_source.link_or_extract', side_effect=self.link):
            self.trigger.trigger_injection('skin_1000', ticker_id=1)
        names = self.manager.injector.overlay_manager.mk_run_overlay.call_args.args[0]
        self.assertIn('Current VFX', names)
        self.assertNotIn('Saved VFX', names)


class CategoryHistoricRoundtripTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.history = self.root / 'mod_historic.json'
        self.storage = ModStorageService(self.root / 'library')
        self.state = SharedState(locked_champ_id=1, last_hovered_skin_id=1000)
        self.state.selected_other_mods = []
        self.manager = MagicMock()
        self.manager.injector.mods_dir = self.root / 'injection' / 'mods'
        self.manager.injector.overlay_manager.mk_run_overlay.return_value = 0
        self.trigger = InjectionTrigger(MagicMock(), self.state, self.manager)
        for target, kwargs in (
            ('utils.core.mod_historic._mod_historic_file_path', {'return_value': self.history}),
            ('injection.mods.storage.ModStorageService', {'return_value': self.storage}),
            ('utils.core.historic.get_historic_skin_for_champion', {'return_value': None}),
            ('injection.mods.mod_source.get_injection_dir', {'return_value': self.root / 'injection'}),
            ('injection.mods.mod_source.link_or_extract', {'side_effect': self.link}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def link(source, dest, cache_dir=None):
        dest.mkdir(parents=True, exist_ok=True)

    def register(self, category, name):
        directory = self.storage.mods_root / category
        (directory / name).mkdir()
        (directory / self.storage.CATEGORY_METADATA).write_text(json.dumps({
            'mods': {name: {'name': name, 'path': name}},
        }), encoding='utf-8')
        return f'{category}/{name}'

    def restore(self):
        self.state.last_hover_written = False
        self.state.selected_other_mods = []
        self.manager.injector.overlay_manager.mk_run_overlay.reset_mock()
        self.trigger.trigger_injection('skin_1000', ticker_id=1)
        return [mod['relative_path'] for mod in self.state.selected_other_mods]

    def test_partial_missing_history_restores_once_on_second_attempt(self):
        valid = self.register('vfx', 'Saved VFX')
        mod_historic.write_historic_mod('vfx', [valid, 'vfx/Missing VFX'])
        mod_historic.write_historic_mod('ui', ['ui/Missing UI'])
        self.assertEqual(self.restore(), [valid])
        self.assertEqual(json.loads(self.history.read_text()), {'vfx': [valid]})
        self.assertEqual(self.restore(), [valid])
        self.assertEqual(self.manager.injector.overlay_manager.mk_run_overlay.call_args.args[0], ['Saved VFX'])
        self.assertEqual(json.loads(self.history.read_text()), {'vfx': [valid]})

    def test_mixed_categories_keep_their_keys_after_pruning_and_restore(self):
        vfx = self.register('vfx', 'Saved VFX')
        ui = self.register('ui', 'Saved UI')
        mod_historic.write_historic_mod('vfx', [vfx])
        mod_historic.write_historic_mod('ui', [ui])
        mod_historic.write_historic_mod('sfx', ['sfx/Missing SFX'])
        self.assertCountEqual(self.restore(), [vfx, ui])
        self.assertEqual(json.loads(self.history.read_text()), {'vfx': [vfx], 'ui': [ui]})
        self.assertCountEqual(self.restore(), [vfx, ui])
        self.assertEqual(len(self.manager.injector.overlay_manager.mk_run_overlay.call_args.args[0]), 2)

    def test_all_missing_categories_are_cleared(self):
        mod_historic.write_historic_mod('vfx', ['vfx/Missing VFX'])
        mod_historic.write_historic_mod('ui', ['ui/Missing UI'])
        self.assertEqual(self.restore(), [])
        self.assertEqual(json.loads(self.history.read_text()), {})
        self.assertEqual(self.restore(), [])
        self.manager.injector.overlay_manager.mk_run_overlay.assert_not_called()

    def test_a_saved_mod_still_named_by_the_zip_rose_kept_is_selected(self):
        """A selection the migration could not rename names the .zip Rose kept of the mod"""
        maps = self.storage.mods_root / 'maps'
        (maps / self.storage.CATEGORY_METADATA).write_text(json.dumps({
            'mods': {'Rift': {'name': 'Rift', 'path': 'Rift', 'ltkId': LTK_ID}},
        }), encoding='utf-8')
        (maps / 'Rift.zip').write_bytes(b'PK\x05\x06' + bytes(18))

        selected = self.trigger._find_saved_mod(self.storage, 'maps', 'maps/Rift.zip')

        self.assertEqual((selected['source'], selected['relative_path']), (LtkEntry(LTK_ID), 'maps/Rift.fantome'))
        self.assertIsNone(self.trigger._find_saved_mod(self.storage, 'fonts', 'maps/Rift.zip'))

    def test_the_cleanup_after_a_game_keeps_a_saved_mod_ltk_manager_holds(self):
        """Its archive is no longer in Rose: a file check took it for deleted"""
        (self.storage.mods_root / 'maps' / self.storage.CATEGORY_METADATA).write_text(json.dumps({
            'mods': {'Rift': {'name': 'Rift', 'path': 'Rift', 'ltkId': LTK_ID}},
        }), encoding='utf-8')
        mod_historic.write_historic_mod('map', 'maps/Rift.fantome')
        mod_historic.write_historic_mod('font', 'fonts/Deleted.fantome')
        self.trigger._force_base_skin = MagicMock()

        with patch('threads.handlers.injection_trigger.threading.Thread', SynchronousThread), \
                patch('utils.core.historic.write_historic_entry'), \
                patch.dict('sys.modules', {'ui.core.user_interface': SimpleNamespace(get_user_interface=MagicMock())}):
            self.trigger._inject_unowned_skin('skin_1001', 'Leona')

        self.manager.inject_skin_immediately.assert_called_once()
        self.assertEqual(json.loads(self.history.read_text()), {'map': 'maps/Rift.fantome'})

    def test_successful_save_does_not_duplicate_an_existing_category(self):
        valid = self.register('vfx', 'Saved VFX')
        mod_historic.write_historic_mod('vfx', [valid])
        self.assertEqual(self.restore(), [valid])
        self.assertEqual(json.loads(self.history.read_text()), {'vfx': [valid]})
        self.assertEqual(self.restore(), [valid])


if __name__ == '__main__':
    unittest.main()
