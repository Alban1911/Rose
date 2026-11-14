import unittest
from unittest.mock import Mock

import ui.chroma.panel as panel_module
from state import SharedState
from ui.chroma.selector import ChromaSelector


def make_selector(champion_id, chroma_id_map=None):
    panel_module.clear_global_panel_manager()
    state = SharedState()
    state.locked_champ_id = champion_id
    cache = Mock(chroma_id_map=chroma_id_map or {})
    cache.is_loaded_for_champion.return_value = False
    scraper = Mock(lcu=None, cache=cache)
    scraper.get_chromas_for_skin.return_value = []
    return ChromaSelector(scraper, state), state


def pick(selector, chroma_id):
    """Same calls as the chroma-selection message from the wheel"""
    selector._on_chroma_selected(chroma_id, str(chroma_id))
    selector.panel._on_chroma_selected_wrapper(chroma_id, str(chroma_id))


def show(selector, skin_id, champion_id):
    """What the main loop does when last_hovered_skin_id changes"""
    selector.show_button_for_skin(skin_id, f"Skin {skin_id}", None, champion_id)


class FormSwitchTests(unittest.TestCase):
    """Once a form was picked the panel is shown for that form, and picking
    another form used to be ignored: the wheel showed the new form but the
    old one was injected"""

    CASES = [
        ("Elementalist Lux", 99, 99007, 99991, 99992),
        ("Sahn Uzal Mordekaiser", 82, 82054, 82998, 82999),
        ("Radiant Sett", 875, 875066, 875998, 875999),
        ("KDA Seraphine", 147, 147001, 147002, 147003),
        ("Viego", 234, 234043, 234994, 234995),
        ("Gun Goddess Miss Fortune", 21, 21016, 21997, 21998),
    ]

    def tearDown(self):
        panel_module.clear_global_panel_manager()

    def test_picking_a_second_form_selects_it(self):
        for name, champion_id, base_skin_id, form_a, form_b in self.CASES:
            with self.subTest(name):
                selector, state = make_selector(champion_id)
                state.last_hovered_skin_id = base_skin_id
                show(selector, base_skin_id, champion_id)
                pick(selector, form_a)
                show(selector, state.last_hovered_skin_id, champion_id)
                pick(selector, form_b)

                self.assertEqual(state.selected_chroma_id, form_b)
                self.assertEqual(state.last_hovered_skin_id, form_b)


class FormPanelStateTests(unittest.TestCase):
    """Viego forms and HOL tiers are not in the LCU chroma map, so showing
    the panel for the picked one used to reset it and tell the wheel that
    nothing was selected"""

    CASES = [
        ("Viego", 234, 234043, 234994),
        ("Risen Legend Kai'Sa", 145, 145070, 145071),
        ("Risen Legend Ahri", 103, 103085, 103086),
        ("Elementalist Lux", 99, 99007, 99991),
    ]

    def tearDown(self):
        panel_module.clear_global_panel_manager()

    def test_the_picked_form_stays_selected(self):
        for name, champion_id, base_skin_id, form_id in self.CASES:
            with self.subTest(name):
                selector, state = make_selector(champion_id)
                state.last_hovered_skin_id = base_skin_id
                show(selector, base_skin_id, champion_id)
                pick(selector, form_id)
                show(selector, state.last_hovered_skin_id, champion_id)

                self.assertEqual(selector.panel.current_selected_chroma_id, form_id)
                self.assertFalse(selector.panel.pending_hide)

    def test_a_regular_chroma_still_uses_the_chroma_map(self):
        selector, state = make_selector(1, {1002: {'id': 1002, 'skinId': 1001}})
        show(selector, 1001, 1)
        pick(selector, 1002)
        show(selector, 1002, 1)

        self.assertEqual(selector.panel.current_selected_chroma_id, 1002)
        self.assertFalse(selector.panel.pending_hide)

        show(selector, 1003, 1)

        self.assertIsNone(selector.panel.current_selected_chroma_id)
        self.assertTrue(selector.panel.pending_hide)


if __name__ == '__main__':
    unittest.main()
