import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from injection.retarget import carriers
from injection.tests.test_retarget import SKIN0, builtin_stub, make_bin, raw_wad
from state import SharedState
from threads.handlers.injection_trigger import InjectionTrigger

AHRI = 103
DYNASTY = 103001  # owned
STAR_GUARDIAN = 103014  # unowned, injected


class _RunNow:
    """threading.Thread that runs its target at start()"""

    def __init__(self, target=None, **_):
        self.target = target

    def start(self):
        self.target()


class UnownedSkinCarrierTests(unittest.TestCase):
    """An unowned skin runs as the owned skin picked for it: that one is forced, and the skin retargeted onto it"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        for target, kwargs in (
            ("injection.retarget.carriers.get_user_data_dir", {"return_value": self.root}),
            ("threads.handlers.injection_trigger.threading.Thread", {"new": _RunNow}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

        # The game's own skin 14, and Rose's Star Guardian Ahri built on it
        game = self.root / "game"
        (game / "DATA" / "FINAL" / "Champions").mkdir(parents=True)
        (game / "DATA" / "FINAL" / "Champions" / "Ahri.wad.client").write_bytes(raw_wad({
            "data/characters/ahri/skins/skin14.bin": make_bin([], [("Characters/Ahri/Skins/Skin14", [])]),
        }))
        archive = self.root / "103014.fantome"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("WAD/Ahri.wad.client", raw_wad({SKIN0: builtin_stub()}))
            zf.writestr("META/info.json", json.dumps({"Name": "Star Guardian Ahri"}))

        self.state = SharedState()
        self.state.locked_champ_id = AHRI
        self.state.owned_skin_ids = {DYNASTY, 103007}
        self.manager = MagicMock()
        self.manager.injector._resolve_zip.return_value = archive
        self.manager.injector.game_dir = game
        self.manager.inject_skin_immediately.return_value = False
        lcu = MagicMock(session={}, ok=True)
        scraper = SimpleNamespace(cache=SimpleNamespace(chroma_id_map={103007: {"skinId": DYNASTY}}))
        self.trigger = InjectionTrigger(lcu, self.state, self.manager, scraper)
        self.trigger._force_base_skin = MagicMock()

    def inject(self):
        with patch("ui.core.user_interface.get_user_interface", create=True):
            self.trigger._inject_unowned_skin(f"skin_{STAR_GUARDIAN}", "Ahri")
        return self.manager.inject_skin_immediately.call_args.kwargs.get("retarget")

    def test_the_owned_skin_is_forced_and_the_skin_moved_onto_it(self):
        carriers.set_carrier(STAR_GUARDIAN, DYNASTY)
        retarget = self.inject()
        self.trigger._force_base_skin.assert_called_once_with(DYNASTY)
        self.assertEqual((retarget.source_number, retarget.target_number), (0, 1))

    def test_an_owned_chroma_can_carry_the_skin(self):
        carriers.set_carrier(STAR_GUARDIAN, 103007)
        retarget = self.inject()
        self.trigger._force_base_skin.assert_called_once_with(103007)
        self.assertEqual(retarget.target_number, 7)

    def test_without_a_carrier_the_default_skin_is_forced(self):
        self.assertIsNone(self.inject())
        self.trigger._force_base_skin.assert_called_once_with(AHRI * 1000)

    def test_a_carrier_no_longer_owned_leaves_the_default_skin(self):
        carriers.set_carrier(STAR_GUARDIAN, 103002)
        self.assertIsNone(self.inject())
        self.trigger._force_base_skin.assert_called_once_with(AHRI * 1000)

    def test_a_carrier_the_skin_is_built_on_leaves_the_default_skin(self):
        self.state.owned_skin_ids.add(STAR_GUARDIAN)
        carriers.set_carrier(103020, STAR_GUARDIAN)
        self.trigger._inject_unowned_skin("skin_103020", "Ahri")
        self.trigger._force_base_skin.assert_called_once_with(AHRI * 1000)
        self.assertIsNone(self.manager.inject_skin_immediately.call_args.kwargs.get("retarget"))

    def test_rift_classic_keeps_the_default_skin(self):
        carriers.set_carrier(STAR_GUARDIAN, DYNASTY)
        self.state.current_game_mode = "JADE"
        self.assertIsNone(self.inject())
        self.trigger._force_base_skin.assert_called_once_with(AHRI * 1000)


if __name__ == "__main__":
    unittest.main()
