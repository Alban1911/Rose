import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from lcu.features.lcu_swiftplay import LCUSwiftplay

CASSIOPEIA = 69
SPIRIT_BLOSSOM = 69009
SPIRIT_BLOSSOM_RUBY = 69010


class OwnedChromaWithoutSkinTests(unittest.TestCase):
    """A chroma bought without its skin is in the inventory, but the client
    refuses it, so Swiftplay must still put the base skin in the slot (#73)"""

    def setUp(self):
        self.slots = [{"championId": CASSIOPEIA, "skinId": SPIRIT_BLOSSOM_RUBY}]
        responses = {
            "/lol-lobby/v2/lobby": {"localMember": {"playerSlots": self.slots}},
            f"/lol-game-data/assets/v1/champions/{CASSIOPEIA}.json": {
                "skins": [{"id": SPIRIT_BLOSSOM, "chromas": [{"id": SPIRIT_BLOSSOM_RUBY}]}],
            },
        }
        self.api = MagicMock()
        self.api.get.side_effect = lambda path, *args, **kwargs: responses.get(path)
        self.api.put.return_value = SimpleNamespace(status_code=204)
        self.swiftplay = LCUSwiftplay(self.api, MagicMock())

    def force(self, owned):
        return self.swiftplay.force_base_skin_slots({CASSIOPEIA: SPIRIT_BLOSSOM_RUBY}, owned)

    def test_the_base_skin_is_forced_for_a_chroma_owned_without_its_skin(self):
        self.assertTrue(self.force({SPIRIT_BLOSSOM_RUBY}))
        self.api.put.assert_called_once()
        slots = self.api.put.call_args.args[1]
        self.assertEqual(slots[0]["skinId"], CASSIOPEIA * 1000)

    def test_a_chroma_owned_with_its_skin_is_left_alone(self):
        self.assertTrue(self.force({SPIRIT_BLOSSOM, SPIRIT_BLOSSOM_RUBY}))
        self.api.put.assert_not_called()
        self.assertEqual(self.slots[0]["skinId"], SPIRIT_BLOSSOM_RUBY)


if __name__ == '__main__':
    unittest.main()
