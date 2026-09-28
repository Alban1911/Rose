#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Interface language
Picks the language of Rose's menus: the one chosen in Settings, else the
League client's, else English. The texts live in the ROSE-I18n plugin
(locales/<language>.json, keyed by their English text); Rose serves the
chosen language's texts to the plugins at /i18n.
"""

import json
from pathlib import Path
from typing import Dict, Optional

from utils.core.logging import get_logger

log = get_logger()

AUTO = "auto"
ENGLISH = "en"

# Every language the League client ships, by the name it gives itself
LANGUAGES: Dict[str, str] = {
    "en": "English",
    "fr": "Français",
    "de": "Deutsch",
    "es_ES": "Español (España)",
    "es_MX": "Español (Latinoamérica)",
    "pt_BR": "Português (Brasil)",
    "it": "Italiano",
    "pl": "Polski",
    "ro": "Română",
    "hu": "Magyar",
    "cs": "Čeština",
    "el": "Ελληνικά",
    "ru": "Русский",
    "tr": "Türkçe",
    "ar": "العربية",
    "ja": "日本語",
    "ko": "한국어",
    "zh_CN": "简体中文",
    "zh_TW": "繁體中文",
    "th": "ไทย",
    "vi": "Tiếng Việt",
    "id": "Bahasa Indonesia",
}

RIGHT_TO_LEFT = {"ar"}

# Client locales whose language comes in more than one variant
_LOCALE_LANGUAGES = {
    "es_AR": "es_MX",
    "es_MX": "es_MX",
    "es_ES": "es_ES",
    "pt_BR": "pt_BR",
    "zh_CN": "zh_CN",
    "zh_MY": "zh_CN",
    "zh_TW": "zh_TW",
    "zh_HK": "zh_TW",
}


class Text(str):
    """An English text shown in Rose's menus that has values in it: it reads as the
    final English string, and carries its template and values so the plugins can
    translate the template ("Connected to {name}") and fill it in again."""

    def __new__(cls, template: str, **values):
        text = super().__new__(cls, template.format(**values))
        text.template = template
        text.values = {key: str(value) for key, value in values.items()}
        return text


def text_fields(prefix: str, text) -> Dict[str, object]:
    """messageTemplate/messageValues (for prefix "message") when the text has values."""
    if isinstance(text, Text):
        return {f"{prefix}Template": text.template, f"{prefix}Values": text.values}
    return {}


def language_for_locale(locale: Optional[str]) -> str:
    """The language Rose uses for a client locale (fr_FR -> fr), English if none fits."""
    if not locale:
        return ENGLISH
    locale = locale.replace("-", "_")
    if locale in _LOCALE_LANGUAGES:
        return _LOCALE_LANGUAGES[locale]
    language = locale.split("_")[0].lower()
    return language if language in LANGUAGES else ENGLISH


def resolve_language(setting: Optional[str], client_locale: Optional[str]) -> str:
    """The Settings choice when it is a known language, else the client's."""
    if setting and setting != AUTO and setting in LANGUAGES:
        return setting
    return language_for_locale(client_locale)


def locales_dir() -> Path:
    from utils.integration.pengu_loader import PENGU_DIR
    return Path(PENGU_DIR) / "plugins" / "ROSE-I18n" / "locales"


def load_strings(language: str, directory: Optional[Path] = None) -> Dict[str, str]:
    """English text -> translation for a language ({} for English or a missing file)."""
    if language == ENGLISH:
        return {}
    path = (directory or locales_dir()) / f"{language}.json"
    try:
        strings = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.warning(f"[I18N] No texts for {language} ({path})")
        return {}
    except (OSError, ValueError) as e:
        log.warning(f"[I18N] Could not read {path}: {e}")
        return {}
    return {k: v for k, v in strings.items() if isinstance(k, str) and isinstance(v, str) and v}


def current_language(shared_state=None) -> str:
    """The language Rose's menus use right now."""
    from config import get_config_option
    setting = get_config_option("General", "language")
    client_locale = getattr(shared_state, "current_locale", None) if shared_state else None
    return resolve_language(setting, client_locale)


def i18n_payload(shared_state=None) -> dict:
    """What the plugins load: the language, its direction and its texts."""
    language = current_language(shared_state)
    from config import get_config_option
    return {
        "language": language,
        "setting": get_config_option("General", "language") or AUTO,
        "direction": "rtl" if language in RIGHT_TO_LEFT else "ltr",
        "languages": LANGUAGES,
        "strings": load_strings(language),
    }
