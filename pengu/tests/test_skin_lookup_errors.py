import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from pengu.processing.skin_processor import SkinProcessor


class SkinLookupErrorTests(unittest.TestCase):
    """A failure while loading or matching the champion's skins returned None
    silently: the hovered skin was never recognised and nothing got injected"""

    def setUp(self):
        self.scraper = MagicMock()
        self.processor = SkinProcessor(SimpleNamespace(locked_champ_id=21), skin_scraper=self.scraper, skin_mapping=MagicMock())

    def test_a_failed_skin_load_is_logged(self):
        self.scraper.scrape_champion_skins.side_effect = ConnectionError('LCU unavailable')
        with self.assertLogs(level='ERROR') as logs:
            self.assertIsNone(self.processor._find_skin_id('Miss Fortune T1'))
        self.assertIn('champion 21', logs.output[0])
        self.assertIn('Traceback', logs.output[0])

    def test_a_failed_name_match_is_logged(self):
        self.scraper.scrape_champion_skins.return_value = True
        self.scraper.find_skin_by_text.side_effect = TypeError('bad cache')
        with self.assertLogs(level='ERROR') as logs:
            self.assertIsNone(self.processor._find_skin_id('Miss Fortune T1'))
        self.assertIn('Miss Fortune T1', logs.output[0])


if __name__ == '__main__':
    unittest.main()
