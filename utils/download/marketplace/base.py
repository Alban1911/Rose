#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
What every marketplace provider offers, and the filter vocabulary they share
"""

from __future__ import annotations

import re
from typing import Optional

from .models import DownloadSpec, MarketQuery, SearchPage

# Features shown in the filter panel, keyed by the slug the plugin sends
FEATURE_LABELS = {
    "chroma": "Chroma",
    "textures": "Textures",
    "model": "Model",
    "animations": "Animations",
    "vfx": "Visual Effects",
    "sfx": "Sound Effects",
    "voiceover": "Voiceover",
    "tft": "TFT",
}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")


def champion_key(name: str) -> str:
    """Compare champion names across sites ("Kai'Sa", "Kaisa", "Nunu & Willump")."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


class MarketProvider:
    """A mod site Rose can browse. Subclasses raise models.Unsupported for filters
    they cannot apply and models.MarketError when the site fails."""

    name = ""
    label = ""
    # Hosts whose API asks to be called sparingly
    api_hosts: tuple = ()
    # Hosts Rose may proxy images from and open in the browser
    image_hosts: tuple = ()
    page_hosts: tuple = ()

    def facets(self) -> dict:
        """Filter values this site understands:
        {"champions": [{"id", "name"}], "maps": [{"id", "name"}], "categories": [rose category],
         "themes": [{"value", "label"}], "features": [slug], "gilded": bool, "aiOnly": bool}"""
        raise NotImplementedError

    def search(self, query: MarketQuery) -> SearchPage:
        raise NotImplementedError

    def resolve_download(self, item_id: str) -> DownloadSpec:
        raise NotImplementedError

    def page_url(self, item: dict) -> Optional[str]:
        return item.get("page_url") or None
