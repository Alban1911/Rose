import tempfile
import unittest
from pathlib import Path

import configparser

from config import read_config_file
from subclient import frontend
from subclient.__main__ import disable_analytics
from subclient.tests.test_wad import build_wad

PLUGINS = [
    {"fullName": "rcp-fe-plugin-runner", "shortName": "plugin-runner", "supertype": "frontend",
     "dependencies": [], "mountedAssetBundles": {"assets.wad": "Plugins\\rcp-fe-plugin-runner\\assets.wad"}},
    {"fullName": "rcp-be-lol-game-data", "shortName": "lol-game-data", "supertype": "backend"},
    {"fullName": "rcp-fe-common-libs", "shortName": "common-libs", "supertype": "frontend", "dependencies": [],
     "mountedAssetBundles": {"assets.wad": "Plugins\\rcp-fe-common-libs\\assets.wad"}},
    {"fullName": "rcp-fe-lol-champ-select", "shortName": "lol-champ-select", "supertype": "frontend",
     "dependencies": [{"fullName": "rcp-fe-common-libs"}],
     "implementedContracts": [{"fullName": "rcp-fe-lol-champ-select"}],
     "mountedAssetBundles": {"assets.wad": "Plugins\\rcp-fe-lol-champ-select\\assets.wad"}},
]
MANIFEST = {"plugins": [{"name": "rcp-fe-lol-champ-select", "lazy": True},
                        {"name": "rcp-be-lol-game-data", "lazy": True}]}


class FrontendTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.league = Path(tmp.name)
        for name, files in {
            "rcp-fe-plugin-runner": {"rcp-fe-plugin-runner.js": b"runner"},
            "rcp-fe-common-libs": {"rcp-fe-common-libs.js": b"libs", "rcp-fe-common-libs.css": b"css"},
            "rcp-fe-lol-champ-select": {"rcp-fe-lol-champ-select.js": b"cs", "sounds/click.ogg": b"ogg"},
        }.items():
            folder = self.league / "Plugins" / name
            folder.mkdir(parents=True)
            build_wad(folder / "assets.wad", {f"plugins/{name}/global/default/{k}": (0, v) for k, v in files.items()})
        self.frontend = frontend.frontend_plugins(PLUGINS)
        self.assets = frontend.FrontendAssets(self.league, self.frontend)

    def test_graph_initializes_frontend_plugins_in_mount_order(self):
        graph = frontend.build_graph(self.frontend, MANIFEST)
        self.assertEqual(graph["sequence"], ["rcp-fe-common-libs", "rcp-fe-lol-champ-select"])
        self.assertEqual(graph["dependencies"]["rcp-fe-lol-champ-select"], ["rcp-fe-common-libs"])
        self.assertEqual(graph["lazy"], ["rcp-fe-lol-champ-select"])

    def test_assets_come_from_the_plugin_wad(self):
        self.assertEqual(self.assets.read("lol-champ-select", "sounds/click.ogg"), b"ogg")
        self.assertIsNone(self.assets.read("lol-champ-select", "../rcp-fe-common-libs/x"))
        self.assertIsNone(self.assets.read("unknown", "x.js"))

    def test_bootstrap_loads_the_client_then_this_worktrees_plugins(self):
        html = frontend.build_bootstrap(self.frontend, self.assets, title="Rose sub-client - wt",
                                        websocket_url="ws://127.0.0.1:1/", rose_plugins=["ROSE-UI"],
                                        config={"bridgePort": 50001, "worktree": "</script>"})
        self.assertIn("<link rel='riot:plugins:websocket' href='ws://127.0.0.1:1/' />", html)
        self.assertIn("href='/fe/common-libs/rcp-fe-common-libs.css'", html)
        self.assertNotIn("rcp-fe-lol-champ-select.css", html)
        self.assertLess(html.index("window.__roseSubclient"), html.index("/fe/common-libs/rcp-fe-common-libs.js"))
        self.assertIn("<script type='module' src='/rose-plugins/ROSE-UI/index.js'></script>", html)
        self.assertRegex(html, r"<script src='/fe/plugin-runner/rcp-fe-plugin-runner\.js\?t=\d+'></script></body></html>$")
        self.assertNotIn('"</script>"', html)

    def test_disabled_plugins_are_not_loaded(self):
        plugins = self.league / "plugins"
        for name, entry in (("ROSE-UI", "index.js"), ("ROSE-Jade", "index.js_")):
            (plugins / name).mkdir(parents=True)
            (plugins / name / entry).write_text("", encoding="utf-8")
        self.assertEqual(frontend.rose_plugin_names(plugins), ["ROSE-UI"])


class ProfileTests(unittest.TestCase):
    def test_analytics_are_off_and_other_settings_stay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.ini"
            path.write_text("[General]\nclientPath = C:\\League\n", encoding="ascii")
            disable_analytics(Path(tmp))
            config = configparser.ConfigParser(interpolation=None)
            read_config_file(config, path)
            self.assertEqual(config.get("General", "analytics_enabled"), "false")
            self.assertEqual(config.get("General", "clientPath"), "C:\\League")


if __name__ == "__main__":
    unittest.main()
