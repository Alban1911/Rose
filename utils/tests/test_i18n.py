import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from utils.core import i18n
from utils.core.i18n import (
    LANGUAGES,
    Text,
    i18n_payload,
    language_for_locale,
    load_strings,
    resolve_language,
    text_fields,
)

SHIPPED_LOCALES = Path(__file__).resolve().parents[2] / "Pengu Loader" / "plugins" / "ROSE-I18n" / "locales"


class LanguageTests(unittest.TestCase):
    def test_client_locales_map_to_their_language(self):
        self.assertEqual(language_for_locale("fr_FR"), "fr")
        self.assertEqual(language_for_locale("de_DE"), "de")
        self.assertEqual(language_for_locale("ko-KR"), "ko")
        self.assertEqual(language_for_locale("en_GB"), "en")

    def test_language_variants(self):
        self.assertEqual(language_for_locale("es_ES"), "es_ES")
        self.assertEqual(language_for_locale("es_AR"), "es_MX")
        self.assertEqual(language_for_locale("es_MX"), "es_MX")
        self.assertEqual(language_for_locale("pt_BR"), "pt_BR")
        self.assertEqual(language_for_locale("zh_CN"), "zh_CN")
        self.assertEqual(language_for_locale("zh_MY"), "zh_CN")
        self.assertEqual(language_for_locale("zh_TW"), "zh_TW")
        self.assertEqual(language_for_locale("zh_HK"), "zh_TW")

    def test_unknown_or_missing_locale_is_english(self):
        self.assertEqual(language_for_locale(None), "en")
        self.assertEqual(language_for_locale(""), "en")
        self.assertEqual(language_for_locale("xx_YY"), "en")

    def test_settings_choice_wins_over_the_client(self):
        self.assertEqual(resolve_language("de", "fr_FR"), "de")

    def test_auto_or_unknown_choice_follows_the_client(self):
        self.assertEqual(resolve_language("auto", "fr_FR"), "fr")
        self.assertEqual(resolve_language(None, "ja_JP"), "ja")
        self.assertEqual(resolve_language("klingon", "ja_JP"), "ja")
        self.assertEqual(resolve_language("auto", None), "en")


class TextTests(unittest.TestCase):
    def test_reads_as_the_english_text(self):
        text = Text("Connected to {name}", name="Alban")
        self.assertEqual(text, "Connected to Alban")
        self.assertEqual(text.template, "Connected to {name}")
        self.assertEqual(text.values, {"name": "Alban"})

    def test_values_become_strings(self):
        self.assertEqual(Text("{count} games", count=3).values, {"count": "3"})

    def test_text_fields(self):
        self.assertEqual(
            text_fields("error", Text("Couldn't reach the party server: {error}", error="timeout")),
            {"errorTemplate": "Couldn't reach the party server: {error}", "errorValues": {"error": "timeout"}},
        )
        self.assertEqual(text_fields("message", "Party mode is not enabled"), {})


class LoadStringsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_reads_the_language_file(self):
        (self.directory / "fr.json").write_text(
            json.dumps({"Save": "Enregistrer", "Empty": "", "Number": 3}), encoding="utf-8"
        )
        self.assertEqual(load_strings("fr", self.directory), {"Save": "Enregistrer"})

    def test_missing_or_broken_file_falls_back_to_english(self):
        self.assertEqual(load_strings("de", self.directory), {})
        (self.directory / "de.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(load_strings("de", self.directory), {})

    def test_english_needs_no_file(self):
        self.assertEqual(load_strings("en", self.directory), {})

    def test_payload_follows_the_client(self):
        (self.directory / "ar.json").write_text(json.dumps({"Save": "حفظ"}), encoding="utf-8")
        state = SimpleNamespace(current_locale="ar_AE")
        with patch("config.get_config_option", return_value=None), \
                patch.object(i18n, "locales_dir", return_value=self.directory):
            payload = i18n_payload(state)
        self.assertEqual(payload["language"], "ar")
        self.assertEqual(payload["setting"], "auto")
        self.assertEqual(payload["direction"], "rtl")
        self.assertEqual(payload["strings"], {"Save": "حفظ"})
        self.assertEqual(payload["languages"], LANGUAGES)

    def test_payload_uses_the_settings_choice(self):
        (self.directory / "fr.json").write_text(json.dumps({"Save": "Enregistrer"}), encoding="utf-8")
        state = SimpleNamespace(current_locale="ko_KR")
        with patch("config.get_config_option", return_value="fr"), \
                patch.object(i18n, "locales_dir", return_value=self.directory):
            payload = i18n_payload(state)
        self.assertEqual(payload["language"], "fr")
        self.assertEqual(payload["setting"], "fr")
        self.assertEqual(payload["direction"], "ltr")


class ShippedLocalesTests(unittest.TestCase):
    def test_every_language_has_every_text(self):
        files = {path.stem: path for path in SHIPPED_LOCALES.glob("*.json")}
        self.assertEqual(set(files), set(LANGUAGES) - {"en"})

        catalogs = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in files.items()}
        keys = set(catalogs["fr"])
        self.assertTrue(keys)
        for name, strings in catalogs.items():
            with self.subTest(language=name):
                self.assertEqual(set(strings), keys)
                for key, value in strings.items():
                    self.assertTrue(value.strip(), key)
                    self.assertEqual(
                        sorted(re.findall(r"\{\w+\}", key)), sorted(re.findall(r"\{\w+\}", value)), key
                    )


if __name__ == "__main__":
    unittest.main()
