import unittest
from unittest.mock import MagicMock, patch

from state import SharedState
from ui.core.user_interface import UserInterface
from ui.handlers.randomization_handler import RandomizationHandler

DARIUS = 122
BASE_DARIUS = 122000
GOD_KING_DARIUS = 122015
DIVINE_GOD_KING_DARIUS = 122064


class RandomModeTests(unittest.TestCase):
    """Verify that forced base skin transition does not cancel active random mode,
    while manual carousel selection of a different skin does."""

    def setUp(self):
        self.state = SharedState()
        self.state.locked_champ_id = DARIUS
        self.skin_scraper = MagicMock()
        self.skin_scraper.cache.champion_id = DARIUS
        self.skin_scraper.cache.skins = [
            {'skinId': BASE_DARIUS, 'skinName': 'Darius'},
            {'skinId': GOD_KING_DARIUS, 'skinName': 'God-King Darius'},
            {'skinId': DIVINE_GOD_KING_DARIUS, 'skinName': 'Divine God-King Darius'},
        ]
        self.skin_scraper.cache.chroma_id_map = {}
        self.skin_scraper.get_chromas_for_skin.return_value = []

        self.ui = UserInterface(self.state, self.skin_scraper)
        self.ui.is_ui_initialized = MagicMock(return_value=True)
        self.ui.skin_display_handler = MagicMock()
        self.ui.skin_display_handler.show_skin.return_value = (None, None)
        self.ui.historic_handler = MagicMock()

    def test_forced_base_skin_does_not_cancel_random_mode(self):
        # User entered ChampSelect with God-King Darius selected
        self.ui.current_skin_id = GOD_KING_DARIUS

        lcu_mock = MagicMock()
        lcu_mock.set_my_selection_skin.return_value = True

        # User clicks random favorites dice
        success = self.ui.randomization_handler.force_base_skin_and_randomize(lcu_mock, mode="all")
        self.assertTrue(success)
        self.assertTrue(self.state.random_mode_active)
        self.assertEqual(self.ui.randomization_handler._forced_base_skin_id, BASE_DARIUS)

        # Asynchronous LCU skin change event arrives for the forced base skin
        self.ui.show_skin(BASE_DARIUS, "Darius", "Darius", DARIUS)

        # Random mode MUST remain active and not cancelled
        self.assertTrue(self.state.random_mode_active)
        self.assertIsNone(self.ui.randomization_handler._forced_base_skin_id)

    def test_manual_carousel_selection_cancels_random_mode(self):
        # Random mode is active on base skin
        self.state.random_mode_active = True
        self.state.random_skin_id = DIVINE_GOD_KING_DARIUS
        self.ui.current_skin_id = BASE_DARIUS

        # User manually clicks God-King Darius on the carousel
        self.ui.show_skin(GOD_KING_DARIUS, "God-King Darius", "Darius", DARIUS)

        # Random mode MUST be cancelled
        self.assertFalse(self.state.random_mode_active)
        self.assertIsNone(self.state.random_skin_id)

    def test_handle_dice_click_disabled_when_on_non_base_skin(self):
        self.ui.current_skin_id = GOD_KING_DARIUS
        lcu_mock = MagicMock()
        lcu_mock.set_my_selection_skin.return_value = True
        self.skin_scraper.lcu = lcu_mock

        # User clicks dice
        self.ui._handle_dice_click_disabled(mode="all")

        # LCU was asked to set base skin and random mode is active
        lcu_mock.set_my_selection_skin.assert_called_once_with(BASE_DARIUS)
        self.assertTrue(self.state.random_mode_active)

        # LCU notifies of skin change to base skin
        self.ui.show_skin(BASE_DARIUS, "Darius", "Darius", DARIUS)
        self.assertTrue(self.state.random_mode_active)

    def test_handle_dice_click_enabled_cancels_random_mode(self):
        self.state.random_mode_active = True
        self.state.random_skin_id = DIVINE_GOD_KING_DARIUS
        self.ui.current_skin_id = BASE_DARIUS

        self.ui._handle_dice_click_enabled()

        self.assertFalse(self.state.random_mode_active)
        self.assertIsNone(self.state.random_skin_id)

    def test_reset_skin_state_clears_forced_base_skin_id(self):
        self.ui.randomization_handler._forced_base_skin_id = BASE_DARIUS
        self.ui.reset_skin_state()
        self.assertIsNone(self.ui.randomization_handler._forced_base_skin_id)


if __name__ == "__main__":
    unittest.main()

