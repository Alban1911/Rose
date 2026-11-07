import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from injection.mods import skin_audio
from party.discovery.skin_collector import PartySkinData
from party.integration import injection_hook


class PeerSkinSoundTests(unittest.TestCase):
    """A friend's skin gets its sound banks repaired like ours, in a copy of the cached extraction."""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.archive = self.root / "skins" / "157" / "157009" / "157009.fantome"
        self.archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("WAD/Yasuo.wad.client", b"wad")
            archive.writestr("META/info.json", "{}")
        self.injector = SimpleNamespace(game_dir=self.root / "Game", mods_dir=self.root / "mods")
        self.injector.mods_dir.mkdir()
        self.calls = []

        def repair(game_dir, mod_folder, skin_ids):
            self.calls.append((game_dir, Path(mod_folder).name, list(skin_ids)))
            (Path(mod_folder) / "WAD" / "Yasuo.wad.client").write_bytes(b"repaired")
            return ["Yasuo"]

        patches = [
            patch.object(skin_audio, "repair", repair),
            patch.object(injection_hook, "get_injection_dir", lambda: self.root / "injection"),
            patch.object(injection_hook, "_resolve_skin_zip", lambda skin_data, injector, classic=False: self.archive),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_friends_skin_is_repaired_in_a_copy(self):
        folder = injection_hook.prepare_peer_skin(
            PartySkinData(summoner_id=7, summoner_name="Friend", champion_id=157, skin_id=157009, chroma_id=157034),
            self.injector)

        self.assertEqual(self.calls, [(self.injector.game_dir, "party_7", [157034])])
        self.assertEqual((self.injector.mods_dir / folder / "WAD" / "Yasuo.wad.client").read_bytes(), b"repaired")
        # the cached extraction later games reuse keeps the package as it is
        cached = self.root / "injection" / ".extract_cache" / "157009" / "WAD" / "Yasuo.wad.client"
        self.assertEqual(cached.read_bytes(), b"wad")

    def test_a_rift_classic_skin_is_left_as_it_is(self):
        injection_hook.prepare_peer_skin(
            PartySkinData(summoner_id=7, summoner_name="Friend", champion_id=60157, skin_id=60157009),
            self.injector, classic=True)

        self.assertEqual(self.calls, [])

    def test_a_friends_custom_mod_is_left_as_it_is(self):
        mods_root = self.root / "custom"
        (mods_root / "skins" / "Mine" / "WAD").mkdir(parents=True)
        with patch.object(injection_hook, "get_mods_root", lambda: mods_root):
            injection_hook.prepare_peer_skin(
                PartySkinData(summoner_id=7, summoner_name="Friend", champion_id=157, skin_id=157009,
                              custom_mod_path="skins/Mine"),
                self.injector)

        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
