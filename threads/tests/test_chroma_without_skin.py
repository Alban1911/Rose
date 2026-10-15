import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from state import SharedState
from threads.handlers.injection_trigger import InjectionTrigger
from utils.core.utilities import is_selectable_owned

CASSIOPEIA = 69
SPIRIT_BLOSSOM = 69009
SPIRIT_BLOSSOM_RUBY = 69010
DEFAULT_SKIN_CHROMA = 69005
CHROMA_ID_MAP = {
    DEFAULT_SKIN_CHROMA: {"skinId": 69000},
    SPIRIT_BLOSSOM_RUBY: {"skinId": SPIRIT_BLOSSOM},
}


class ChromaWithoutSkinTests(unittest.TestCase):
    """A chroma bought without its skin (Mythic Shop) is in the inventory, so
    Rose forced it through the client, which refused it, and nothing was
    injected (#73)"""

    def setUp(self):
        self.state = SharedState()
        self.state.locked_champ_id = CASSIOPEIA
        self.state.last_hovered_skin_id = SPIRIT_BLOSSOM
        self.state.selected_chroma_id = SPIRIT_BLOSSOM_RUBY
        scraper = SimpleNamespace(cache=SimpleNamespace(chroma_id_map=CHROMA_ID_MAP))
        self.trigger = InjectionTrigger(MagicMock(), self.state, MagicMock(), scraper)
        self.trigger._force_owned_skin = MagicMock()
        self.trigger._inject_unowned_skin = MagicMock()
        # Keep this machine's saved skins and mods out of the injection path
        for target, kwargs in (
            ("utils.core.historic.get_historic_skin_for_champion", {"return_value": None}),
            ("utils.core.mod_historic.load_mod_historic", {"return_value": {}}),
            ("injection.mods.storage.ModStorageService", {}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_chroma_owned_without_its_skin_is_injected(self):
        self.state.owned_skin_ids = {SPIRIT_BLOSSOM_RUBY}
        self.trigger.trigger_injection(f"chroma_{SPIRIT_BLOSSOM_RUBY}", ticker_id=1)
        self.trigger._force_owned_skin.assert_not_called()
        self.trigger._inject_unowned_skin.assert_called_once_with(f"chroma_{SPIRIT_BLOSSOM_RUBY}", "")

    def test_a_chroma_owned_with_its_skin_is_still_forced(self):
        self.state.owned_skin_ids = {SPIRIT_BLOSSOM, SPIRIT_BLOSSOM_RUBY}
        self.trigger.trigger_injection(f"chroma_{SPIRIT_BLOSSOM_RUBY}", ticker_id=1)
        self.trigger._force_owned_skin.assert_called_once_with(SPIRIT_BLOSSOM_RUBY)
        self.trigger._inject_unowned_skin.assert_not_called()

    def test_a_chroma_of_the_default_skin_needs_only_itself(self):
        self.assertTrue(is_selectable_owned(DEFAULT_SKIN_CHROMA, {DEFAULT_SKIN_CHROMA}, CHROMA_ID_MAP))


if __name__ == '__main__':
    unittest.main()
