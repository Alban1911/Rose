import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from utils.download.marketplace import turbo_stream
from utils.download.marketplace.divine import DivineProvider
from utils.download.marketplace.models import (
    CaptchaRequired,
    DownloadSpec,
    MarketError,
    MarketItem,
    MarketQuery,
    SearchPage,
    Unsupported,
)
from utils.download.marketplace.runeforge import RuneForgeProvider
from utils.download.marketplace.service import MarketplaceService, archive_suffix, safe_file_stem
from utils.download.marketplace.thumbs import is_allowed_url

MOD_ID = "cbea5861-63a9-4b1b-b15e-1670f9e3a8e8"
RELEASE_ID = "09e87b4b-07bd-4794-a8a9-21989a9dc4f1"

# Shape of runeforge.dev/mods/<id>.data: a flat value table plus a deferred chunk
PAGE_DATA = "\n".join([
    json.dumps([
        {"_1": 2, "_3": 4},
        "root", {"_5": -5},
        "routes/mods/$modId/layout", {"_5": 6},
        "data", {"_7": 8, "_9": 10, "_11": 12},
        "details", {"_13": 14, "_15": 16},
        "contributorsPromise", ["P", 11],
        "mod", {"_17": 18},
        "latestRelease", {"_17": 19, "_20": 21, "_22": -7},
        "champions", [23],
        "id", MOD_ID, RELEASE_ID,
        "tag", "1.0.0",
        "assetPath",
        {"_17": 24, "_25": 26},
        157, "name", "Yasuo",
    ]),
    'P11:[[28],{"_25":29},"Kurayami_Shadow"]',
    "P99:-7",
])


class TurboStreamTests(unittest.TestCase):
    def test_decodes_references_constants_and_promises(self):
        data = turbo_stream.decode(PAGE_DATA)
        layout = data["routes/mods/$modId/layout"]["data"]
        self.assertIsNone(data["root"]["data"])
        self.assertEqual(layout["details"]["latestRelease"], {"id": RELEASE_ID, "tag": "1.0.0", "assetPath": None})
        self.assertEqual(layout["details"]["champions"], [{"id": 157, "name": "Yasuo"}])
        self.assertEqual(layout["contributorsPromise"], [{"name": "Kurayami_Shadow"}])
        self.assertEqual(layout["mod"], {"id": MOD_ID})

    def test_finds_the_latest_release(self):
        self.assertEqual(RuneForgeProvider.release_from_page_data(PAGE_DATA), (RELEASE_ID, "1.0.0"))

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            turbo_stream.decode("")


class FakeHttp:
    """Answers by URL prefix; records every call"""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []

    def _answer(self, url):
        for prefix, answer in self.routes.items():
            if url.startswith(prefix):
                return answer
        raise AssertionError(f"unexpected request {url}")

    def get_json(self, url, params=None):
        self.calls.append((url, params))
        return self._answer(url)

    def get(self, url, params=None, **kwargs):
        self.calls.append((url, params))
        return self._answer(url)


RF_FACETS = {
    "https://runeforge.dev/api/champions": {"champions": [{"id": 145, "name": "Kai'Sa"}, {"id": 157, "name": "Yasuo"}]},
    "https://runeforge.dev/api/maps": {"maps": [{"id": 11, "name": "Summoner's Rift"}]},
}


class RuneForgeTests(unittest.TestCase):
    def setUp(self):
        self.provider = RuneForgeProvider(FakeHttp(dict(RF_FACETS)))

    def test_query_becomes_indexed_params(self):
        query = MarketQuery(search="demon", sort="new", page=2, page_size=24, champions=["kaisa", "Yasuo"],
                            categories=["skins", "maps"], themes=["anime"], features=["model", "chroma"],
                            gilded_only=True, ai="exclude")
        params = self.provider.build_params(query)
        self.assertEqual(params, [
            ("page", 2), ("pageSize", 24), ("sortBy", "recently_published"), ("search", "demon"),
            ("categories[0]", "champion_skin"), ("categories[1]", "map_skin"),
            ("champions[0]", 145), ("champions[1]", 157),
            ("themes[0]", "anime"),
            ("features[0]", "custom_model"), ("features[1]", "chroma"),
            ("onlyGilded", "true"), ("ai", "exclude"),
        ])

    def test_filters_it_does_not_know(self):
        with self.assertRaises(Unsupported):
            self.provider.build_params(MarketQuery(themes=["chibi"]))
        with self.assertRaises(Unsupported):
            self.provider.build_params(MarketQuery(champions=["Nobody"]))

    def test_parses_a_mod(self):
        item = RuneForgeProvider.parse_mod({
            "id": MOD_ID, "name": "Demon Yasuo", "publisher": {"username": "Kurayami"},
            "thumbnailKey": "abc.png", "category": "champion_skin", "champions": [{"id": 157, "name": "Yasuo"}],
            "features": ["custom_model"], "themes": ["anime"], "isGilded": True, "downloadCount": 5,
            "likeCount": 2, "updatedAt": "2026-09-11", "hasAiGeneratedPostContent": False,
        })
        self.assertEqual(item.key, f"runeforge:{MOD_ID}")
        self.assertEqual(item.category, "skins")
        self.assertTrue(item.thumb_url.startswith("https://runeforge.dev/cdn-cgi/image/"))
        self.assertTrue(item.thumb_url.endswith("/https://r2-images-prod.runeforge.dev/abc.png"))
        self.assertTrue(is_allowed_url(item.thumb_url))
        self.assertEqual(item.page_url, f"https://runeforge.dev/mods/{MOD_ID}")
        self.assertEqual(item.features, ["model"])
        self.assertIsNone(RuneForgeProvider.parse_mod({"name": "no id"}))

    def test_download_points_at_the_latest_release(self):
        page = MagicMock(text=PAGE_DATA)
        self.provider.http.routes[f"https://runeforge.dev/mods/{MOD_ID}.data"] = page
        spec = self.provider.resolve_download(MOD_ID)
        self.assertEqual(spec.url, f"https://runeforge.dev/mods/{MOD_ID}/releases/{RELEASE_ID}/download")
        self.assertEqual(spec.version, "1.0.0")
        with self.assertRaises(MarketError):
            self.provider.resolve_download("../../etc")


DV_META = {
    "https://api.divineskins.gg/api/catalog/metadata": {
        "categories": [],
        "themes": [{"id": 1, "name": "Anime", "active": True}, {"id": 4, "name": "NSFW", "active": True},
                   {"id": 10, "name": "Chroma", "active": True}],
        "features": [{"id": 2, "name": "Model"}, {"id": 5, "name": "Voice Over"}],
    },
    "https://api.divineskins.gg/api/catalog/champions": [{"name": "Kai'Sa", "slug": "kaisa"}, {"name": "Yasuo"}],
}


class DivineTests(unittest.TestCase):
    def setUp(self):
        self.provider = DivineProvider(FakeHttp(dict(DV_META)))

    def test_query_becomes_params(self):
        params = self.provider.build_params(MarketQuery(
            champions=["KAISA"], categories=["skins", "others"], themes=["anime"],
            features=["model", "chroma"], ai="exclude", sort="likes",
        ))
        self.assertEqual(params["championName"], "Kai'Sa")
        self.assertEqual(params["categoryIds"], "1,8,9")
        self.assertEqual(params["featureIds"], "2")
        self.assertEqual(params["themeIds"], "1,10")
        self.assertEqual(params["sortBy"], "likeCount")
        self.assertEqual(params["excludeNsfw"], "true")
        self.assertEqual(params["excludeDisclosures"], "ai_media,ai_assisted")

    def test_filters_it_cannot_apply(self):
        for query in (MarketQuery(maps=["11"]), MarketQuery(gilded_only=True), MarketQuery(ai="only"),
                      MarketQuery(champions=["Yasuo", "Kai'Sa"]), MarketQuery(categories=["vfx"]),
                      MarketQuery(features=["textures"])):
            with self.subTest(query=query), self.assertRaises(Unsupported):
                self.provider.build_params(query)

    def test_nsfw_is_never_offered(self):
        self.assertNotIn("nsfw", [t["value"] for t in self.provider.facets()["themes"]])
        self.assertIsNone(DivineProvider.parse_skin({"id": 1, "name": "x", "nsfw": True}))

    def test_parses_a_skin(self):
        item = DivineProvider.parse_skin({
            "id": 200, "name": "Mahoraga Malphite", "imagePath": "thumbnails/a.webp", "champion": "Malphite",
            "slug": "mahoraga-malphite", "artistUsername": "disco", "categoryId": 1, "downloadCount": 9,
            "disclosures": ["ai_media"], "contentUpdatedDate": "2026-08-07T07:13:58Z",
        })
        self.assertEqual(item.key, "divine:200")
        self.assertEqual(item.page_url, "https://divineskins.gg/disco/mahoraga-malphite")
        self.assertEqual(item.thumb_url, "https://lol-assets.divine-cdn.com/thumbnails/a.webp")
        self.assertEqual(item.champions, [{"id": None, "name": "Malphite"}])
        self.assertTrue(item.ai)

    def test_picks_the_newest_version(self):
        latest = DivineProvider.latest_version([
            {"id": 1, "uploadDate": "2025-01-01"}, {"id": 7, "uploadDate": "2026-02-01"}, {"id": 3, "uploadDate": "2025-06-01"},
        ])
        self.assertEqual(latest["id"], 7)

    def _skin(self, status):
        self.provider.http.routes.update({
            "https://api.divineskins.gg/api/skins/200": {
                "artistUsername": "disco", "slug": "mahoraga-malphite",
                "versions": [{"id": 165, "title": "v1.0.0", "contentHash": "ABC", "fileSize": 10}],
            },
            "https://api.divineskins.gg/api/celestial/manual/200/versions/165/download-url": MagicMock(
                status_code=status, json=lambda: {"url": "https://x.r2.cloudflarestorage.com/a.fantome"},
                raise_for_status=lambda: None,
            ),
        })

    def test_download_link(self):
        self._skin(200)
        spec = self.provider.resolve_download("200")
        self.assertEqual(spec.url, "https://x.r2.cloudflarestorage.com/a.fantome")
        self.assertEqual((spec.version, spec.sha256, spec.size), ("v1.0.0", "abc", 10))

    def test_captcha_is_left_to_the_site(self):
        self._skin(429)
        with self.assertRaises(CaptchaRequired) as caught:
            self.provider.resolve_download("200")
        self.assertEqual(caught.exception.page_url, "https://divineskins.gg/download/disco/mahoraga-malphite")


class QueryTests(unittest.TestCase):
    def test_payload_is_sanitised(self):
        query = MarketQuery.from_payload({
            "providers": ["runeforge", "runeforge", {"x": 1}], "search": "  a" * 80, "sort": "evil",
            "page": "-3", "pageSize": 1000, "maps": ["11", "SR"], "categories": ["skins", "nope"],
            "gildedOnly": "yes", "ai": "only",
        })
        self.assertEqual(query.providers, ["runeforge"])
        self.assertEqual(len(query.search), 100)
        self.assertEqual((query.sort, query.page, query.page_size), ("trending", 0, 48))
        self.assertEqual(query.maps, ["11"])
        self.assertEqual(query.categories, ["skins"])
        self.assertFalse(query.gilded_only)
        self.assertEqual(query.ai, "only")


class StubProvider:
    def __init__(self, name, items=(), total=0, error=None, spec=None, chunks=(b"",), headers=None):
        self.name = name
        self.label = name
        self.page_hosts = ("example.com",)
        self._items = list(items)
        self._total = total
        self._error = error
        self._spec = spec
        self.queries = []
        self.http = MagicMock()
        self.http.get.return_value = MagicMock(
            status_code=200, url="https://cdn.example.com/f", headers=headers or {},
            iter_content=lambda size: iter(chunks), raise_for_status=lambda: None,
        )

    def facets(self):
        return {"champions": [{"id": 157 if self.name == "a" else None, "name": "Yasuo"}], "maps": [],
                "categories": ["skins"], "themes": [], "features": ["model"], "gilded": self.name == "a", "aiOnly": False}

    def search(self, query):
        self.queries.append(query)
        if self._error:
            raise self._error
        return SearchPage(items=self._items, total=self._total, has_more=False)

    def resolve_download(self, item_id):
        return self._spec


def item(provider, number, updated="2026-01-01"):
    return MarketItem(provider=provider, id=str(number), name=f"{provider}{number}", updated_at=updated)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.sent = []
        self.storage = MagicMock()

    def tearDown(self):
        self._tmp.cleanup()

    def service(self, *providers):
        service = MarketplaceService(self.sent.append, self.storage, providers=list(providers), data_dir=self.data_dir)
        self.addCleanup(service.shutdown)
        return service

    def test_merges_two_sites_and_reports_skipped_ones(self):
        a = StubProvider("a", [item("a", 1), item("a", 2), item("a", 3)], total=30)
        b = StubProvider("b", [item("b", 1)], total=5)
        c = StubProvider("c", error=Unsupported("map"))
        with patch("utils.download.marketplace.service.enabled_provider_names", side_effect=lambda names: names):
            result = self.service(a, b, c).search(MarketQuery(page_size=24))
        self.assertEqual([i["name"] for i in result["items"]], ["a1", "b1", "a2", "a3"])
        self.assertEqual(result["total"], 35)
        self.assertEqual(result["skipped"], {"c": "map"})
        self.assertEqual(a.queries[0].page_size, 8)

    def test_facets_list_who_supports_what(self):
        with patch("utils.download.marketplace.service.enabled_provider_names", side_effect=lambda names: names):
            facets = self.service(StubProvider("a"), StubProvider("b")).facets()
        self.assertEqual(facets["champions"], [{"name": "Yasuo", "id": 157, "providers": ["a", "b"]}])
        self.assertEqual(facets["features"], [{"value": "model", "label": "Model", "providers": ["a", "b"]}])
        self.assertEqual(facets["gilded"], ["a"])

    def _download(self, provider, **payload):
        with patch("utils.download.marketplace.service.enabled_provider_names", side_effect=lambda names: names):
            self.service(provider).download({"provider": provider.name, "id": "7", "name": "Demon: Yasuo?", **payload})
        return self.sent[-1]

    def test_downloads_and_imports_a_skin_mod(self):
        data = b"PK\x03\x04" + b"x" * 100
        spec = DownloadSpec(url="https://cdn.example.com/f", filename="", version="1.0",
                            sha256=hashlib.sha256(data).hexdigest())
        provider = StubProvider("a", spec=spec, chunks=[data[:50], data[50:]],
                                headers={"Content-Disposition": 'attachment; filename="Iron Golem.fantome"'})
        imported = {}

        def import_mod_file(champion_id, path, skin_ids):
            imported.update(path=path, exists=path.is_file(), champion=champion_id, skins=skin_ids)
            folder = self.data_dir / "mods" / "Demon Yasuo"
            folder.mkdir(parents=True)
            return folder, None, "Demon Yasuo"

        self.storage.import_mod_file.side_effect = import_mod_file
        result = self._download(provider, category="skins", championId=157, skinIds=[157001, "157002"],
                                updatedAt="2026-09-11")
        self.assertTrue(result["success"], result)
        self.assertEqual(imported["path"].name, "Demon Yasuo.fantome")
        self.assertTrue(imported["exists"])
        self.assertEqual((imported["champion"], imported["skins"]), (157, [157001, 157002]))
        self.assertFalse(imported["path"].exists(), "temporary download should be removed")
        self.assertTrue(any(m["type"] == "marketplace-download-progress" for m in self.sent))

        installed = json.loads((self.data_dir / "marketplace_installed.json").read_text(encoding="utf-8"))
        self.assertEqual(installed["a:7"]["modName"], "Demon Yasuo")

        # The card now shows installed, and an update once the mod changes
        service = self.service(provider)
        with patch("utils.download.marketplace.service.enabled_provider_names", side_effect=lambda names: names):
            self.assertTrue(service._card(item("a", 7, updated="2026-09-11"))["installed"])
            self.assertTrue(service._card(item("a", 7, updated="2026-10-01"))["updateAvailable"])

    def test_category_mod(self):
        spec = DownloadSpec(url="https://cdn.example.com/f", filename="")
        provider = StubProvider("a", spec=spec, chunks=[b"_modpkg_" + b"\0" * 20])
        self.storage.import_category_mod_file.return_value = (self.data_dir / "x", "Font")
        result = self._download(provider, category="fonts")
        self.assertTrue(result["success"], result)
        self.assertEqual(self.storage.import_category_mod_file.call_args.args[1].suffix, ".modpkg")

    def test_damaged_download_is_not_imported(self):
        spec = DownloadSpec(url="https://cdn.example.com/f", filename="", sha256="0" * 64)
        result = self._download(StubProvider("a", spec=spec, chunks=[b"PK\x03\x04data"]), category="maps")
        self.assertFalse(result["success"])
        self.assertIn("checksum", result["error"])
        self.storage.import_category_mod_file.assert_not_called()

    def test_skin_mods_need_targets(self):
        result = self._download(StubProvider("a"), category="skins", championId=157, skinIds=[])
        self.assertFalse(result["success"])
        self.assertIn("Skin ID", result["error"])

    def test_captcha_result(self):
        provider = StubProvider("a")
        provider.resolve_download = MagicMock(side_effect=CaptchaRequired("captcha", "https://example.com/d"))
        result = self._download(provider, category="maps")
        self.assertEqual((result["captcha"], result["pageUrl"]), (True, "https://example.com/d"))

    def test_only_provider_pages_open(self):
        service = self.service(StubProvider("a"))
        with patch("webbrowser.open", return_value=True) as browser:
            self.assertTrue(service.open_page("https://example.com/mod"))
            self.assertFalse(service.open_page("https://evil.com/mod"))
            self.assertFalse(service.open_page("http://example.com/mod"))
            self.assertFalse(service.open_page("file:///C:/Windows"))
        browser.assert_called_once_with("https://example.com/mod")


class HelperTests(unittest.TestCase):
    def test_archive_type(self):
        self.assertEqual(archive_suffix("", "https://r2/a%2Fb.fantome?filename=b.fantome", "", b""), ".fantome")
        self.assertEqual(archive_suffix("", "https://r2/download", 'attachment; filename="A B.zip"', b""), ".zip")
        self.assertEqual(archive_suffix("", "https://r2/x", "", b"_modpkg_\0"), ".modpkg")
        self.assertEqual(archive_suffix("", "https://r2/x", "", b"PK\x03\x04"), ".fantome")
        self.assertIsNone(archive_suffix("", "https://r2/x.exe", "", b"MZ"))

    def test_file_stem(self):
        self.assertEqual(safe_file_stem('Demon: Yasuo? <v2>'), "Demon Yasuo v2")
        self.assertEqual(safe_file_stem("..."), "Marketplace mod")

    def test_thumbnail_allowlist(self):
        self.assertTrue(is_allowed_url("https://r2-images-prod.runeforge.dev/a.png"))
        self.assertTrue(is_allowed_url("https://lol-assets.divine-cdn.com/thumbnails/a.webp"))
        self.assertFalse(is_allowed_url("http://r2-images-prod.runeforge.dev/a.png"))
        self.assertFalse(is_allowed_url("https://127.0.0.1/a.png"))
        self.assertFalse(is_allowed_url("https://r2-images-prod.runeforge.dev.evil.com/a.png"))
        self.assertFalse(is_allowed_url("https://runeforge.dev/api/mods"))


if __name__ == "__main__":
    unittest.main()
