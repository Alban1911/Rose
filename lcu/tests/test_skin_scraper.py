import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

from lcu.data.skin_scraper import LCUSkinScraper


class SkinScraperTests(unittest.TestCase):
    def test_a_late_response_cannot_replace_or_mix_with_the_new_champion(self):
        first_requested = Event()
        release_first = Event()

        def get(endpoint, timeout):
            champion = int(endpoint.rsplit("/", 1)[1].removesuffix(".json"))
            if champion == 34:
                first_requested.set()
                if not release_first.wait(5):
                    raise TimeoutError("test did not release the first request")
            return {"skins": [{
                "id": champion * 1000 + 1,
                "name": f"Skin {champion}",
                "chromas": [{"id": champion * 1000 + 2}],
            }]}

        scraper = LCUSkinScraper(Mock(get=get))
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(scraper.scrape_champion_skins, 34)
            try:
                self.assertTrue(first_requested.wait(5))
                self.assertTrue(pool.submit(scraper.scrape_champion_skins, 51).result(timeout=5))
            finally:
                release_first.set()
            self.assertFalse(first.result(timeout=5))

        self.assertTrue(scraper.cache.is_loaded_for_champion(51))
        self.assertEqual([skin["championId"] for skin in scraper.cache.skins], [51])
        self.assertEqual(list(scraper.cache.chroma_id_map), [51002])
