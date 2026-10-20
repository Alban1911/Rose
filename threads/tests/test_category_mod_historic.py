import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from state import SharedState
from threads.handlers.injection_trigger import InjectionTrigger
from injection.mods.storage import ModStorageService
from utils.core import mod_historic


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
        self.storage = MagicMock()
        self.storage.mods_root = self.root / 'library'
        self.source = self.storage.mods_root / 'vfx' / 'Saved VFX'
        self.source.mkdir(parents=True)
        self.storage.CATEGORY_VFX = 'vfx'
        self.storage.list_mods_for_category.side_effect = lambda category: [
            {'id': 'vfx/Saved VFX', 'path': 'vfx/Saved VFX', 'name': 'Saved VFX'},
        ] if category == 'vfx' else []
        for target, kwargs in (
            ('injection.mods.storage.ModStorageService', {'return_value': self.storage}),
            ('utils.core.historic.get_historic_skin_for_champion', {'return_value': None}),
            ('utils.core.mod_historic.load_mod_historic', {'return_value': {'vfx': ['vfx/Saved VFX']}}),
            ('utils.core.mod_historic.write_historic_mod', {}),
            ('utils.core.historic.write_historic_entry', {}),
            ('utils.core.historic.write_historic_target', {}),
            ('threads.handlers.injection_trigger.get_injection_dir', {'return_value': self.root / 'injection'}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def link(self, source, dest, cache_dir=None):
        dest.mkdir(parents=True, exist_ok=True)

    def test_saved_category_mod_reaches_overlay_without_opening_selector(self):
        with patch('threads.handlers.injection_trigger.link_or_extract', side_effect=self.link):
            self.trigger.trigger_injection('skin_1000', ticker_id=1)
        self.assertTrue(self.state.selected_other_mods, 'saved category selection was not restored')
        self.assertEqual(self.state.selected_other_mods[0]['relative_path'], 'vfx/Saved VFX')
        overlay = self.manager.injector.overlay_manager.mk_run_overlay
        overlay.assert_called_once()
        self.assertIn('Saved VFX', overlay.call_args.args[0])

    def test_current_selection_wins_over_saved_category_mod(self):
        current = self.storage.mods_root / 'vfx' / 'Current VFX'
        current.mkdir()
        self.state.selected_other_mods = [{
            'mod_name': 'Current VFX', 'mod_folder_name': 'Current VFX',
            'mod_path': str(current), 'relative_path': 'vfx/Current VFX',
        }]
        with patch('threads.handlers.injection_trigger.link_or_extract', side_effect=self.link):
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
            ('threads.handlers.injection_trigger.get_injection_dir', {'return_value': self.root / 'injection'}),
            ('threads.handlers.injection_trigger.link_or_extract', {'side_effect': self.link}),
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

    def test_successful_save_does_not_duplicate_an_existing_category(self):
        valid = self.register('vfx', 'Saved VFX')
        mod_historic.write_historic_mod('vfx', [valid])
        self.assertEqual(self.restore(), [valid])
        self.assertEqual(json.loads(self.history.read_text()), {'vfx': [valid]})
        self.assertEqual(self.restore(), [valid])


if __name__ == '__main__':
    unittest.main()
