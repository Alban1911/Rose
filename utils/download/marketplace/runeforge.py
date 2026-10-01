#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RuneForge (runeforge.dev) provider

Endpoints (undocumented, read without an account):
  GET /api/mods?page&pageSize&search&sortBy&categories[i]&champions[i]&maps[i]&themes[i]&features[i]&onlyGilded&ai
  GET /api/champions, /api/maps
  GET /mods/{id}.data                         page data (turbo-stream) with details.latestRelease
  GET /mods/{id}/releases/{release}/download  302 to the .fantome file
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Optional

from . import turbo_stream
from .base import MarketProvider, champion_key
from .http import PoliteSession
from .models import DownloadSpec, MarketError, MarketItem, MarketQuery, SearchPage, Unsupported

log = logging.getLogger(__name__)

BASE_URL = "https://runeforge.dev"
IMAGES_URL = "https://r2-images-prod.runeforge.dev"
# The site's own resizer: originals are multi-MB PNGs, a card needs ~50 KB
THUMBNAIL_URL = "https://runeforge.dev/cdn-cgi/image/width=480,height=300,quality=80,format=webp,fit=cover/" + IMAGES_URL
FACETS_TTL_S = 6 * 3600

CATEGORY_TO_ROSE = {
    "champion_skin": "skins",
    "map_skin": "maps",
    "font": "fonts",
    "announcer": "announcers",
    "ui": "ui",
    "voiceover": "voiceover",
    "loading_screen": "loading_screen",
    "vfx": "vfx",
    "sfx": "sfx",
    "miscellaneous": "others",
}
ROSE_TO_CATEGORY = {rose: site for site, rose in CATEGORY_TO_ROSE.items()}

SORTS = {
    "trending": "trending",
    "new": "recently_published",
    "updated": "recently_updated",
    "downloads": "download_count",
    "likes": "like_count",
}

THEMES = {"anime": "Anime", "meme": "Meme", "scifi": "Sci-Fi", "fantasy": "Fantasy", "events": "Events"}

FEATURE_TO_SITE = {
    "chroma": "chroma",
    "textures": "custom_textures",
    "model": "custom_model",
    "animations": "custom_animations",
    "vfx": "custom_visual_effects",
    "sfx": "custom_sound_effects",
    "voiceover": "custom_voiceover",
    "tft": "tft",
}
SITE_TO_FEATURE = {site: slug for slug, site in FEATURE_TO_SITE.items()}

_RELEASE_LINK = re.compile(r"/mods/([0-9a-f-]{36})/releases/([0-9a-f-]{36})/download")
_UUID = re.compile(r"^[0-9a-f-]{36}$")


class RuneForgeProvider(MarketProvider):
    name = "runeforge"
    label = "RuneForge"
    api_hosts = ("runeforge.dev",)
    image_hosts = ("r2-images-prod.runeforge.dev",)
    page_hosts = ("runeforge.dev",)

    def __init__(self, http: PoliteSession):
        self.http = http
        self._facets: Optional[dict] = None
        self._facets_at = 0.0
        self._facets_lock = threading.Lock()

    # ------------------------------------------------------------------ facets
    def facets(self) -> dict:
        with self._facets_lock:
            if self._facets and time.monotonic() - self._facets_at < FACETS_TTL_S:
                return self._facets
            try:
                champions_raw = self.http.get_json(f"{BASE_URL}/api/champions").get("champions") or []
                maps_raw = self.http.get_json(f"{BASE_URL}/api/maps").get("maps") or []
            except Exception as exc:  # noqa: BLE001
                raise MarketError(f"RuneForge is not reachable: {exc}") from exc

            champions = []
            for champ in champions_raw:
                try:
                    champions.append({"id": int(champ["id"]), "name": str(champ["name"])})
                except (KeyError, TypeError, ValueError):
                    continue
            maps = []
            for game_map in maps_raw:
                try:
                    maps.append({"id": int(game_map["id"]), "name": str(game_map["name"])})
                except (KeyError, TypeError, ValueError):
                    continue

            self._facets = {
                "champions": sorted(champions, key=lambda c: c["name"]),
                "maps": sorted(maps, key=lambda m: m["name"]),
                "categories": list(ROSE_TO_CATEGORY),
                "themes": [{"value": slug, "label": label} for slug, label in THEMES.items()],
                "features": list(FEATURE_TO_SITE),
                "gilded": True,
                "aiOnly": True,
            }
            self._facets_at = time.monotonic()
            return self._facets

    def _champion_ids(self, names: list) -> list:
        by_key = {champion_key(c["name"]): c["id"] for c in self.facets()["champions"]}
        ids = [by_key[champion_key(n)] for n in names if champion_key(n) in by_key]
        if names and not ids:
            raise Unsupported("champion")
        return ids

    # ------------------------------------------------------------------ search
    def build_params(self, query: MarketQuery) -> list:
        params: list = [
            ("page", query.page),
            ("pageSize", query.page_size),
            ("sortBy", SORTS.get(query.sort, "trending")),
        ]
        if query.search:
            params.append(("search", query.search))

        def add_list(name: str, values: list) -> None:
            for index, value in enumerate(values):
                params.append((f"{name}[{index}]", value))

        if query.categories:
            add_list("categories", [ROSE_TO_CATEGORY[c] for c in query.categories if c in ROSE_TO_CATEGORY])
        if query.champions:
            add_list("champions", self._champion_ids(query.champions))
        if query.maps:
            add_list("maps", query.maps)
        if query.themes:
            themes = [t for t in query.themes if t in THEMES]
            if not themes:
                raise Unsupported("theme")
            add_list("themes", themes)
        if query.features:
            features = [FEATURE_TO_SITE[f] for f in query.features if f in FEATURE_TO_SITE]
            if not features:
                raise Unsupported("feature")
            add_list("features", features)
        if query.gilded_only:
            params.append(("onlyGilded", "true"))
        if query.ai != "all":
            params.append(("ai", query.ai))
        return params

    def search(self, query: MarketQuery) -> SearchPage:
        params = self.build_params(query)
        try:
            data = self.http.get_json(f"{BASE_URL}/api/mods", params=params)
        except Exception as exc:  # noqa: BLE001
            raise MarketError(f"RuneForge search failed: {exc}") from exc
        items = [item for item in (self.parse_mod(m) for m in data.get("mods") or []) if item]
        total = int(data.get("total") or 0)
        return SearchPage(items=items, total=total, has_more=(query.page + 1) * query.page_size < total)

    @staticmethod
    def parse_mod(mod: dict) -> Optional[MarketItem]:
        if not isinstance(mod, dict) or not mod.get("id") or not mod.get("name"):
            return None
        mod_id = str(mod["id"])
        thumbnail_key = mod.get("thumbnailKey")
        publisher = mod.get("publisher") if isinstance(mod.get("publisher"), dict) else {}
        champions = []
        for champ in mod.get("champions") or []:
            if isinstance(champ, dict) and champ.get("name"):
                champions.append({"id": champ.get("id"), "name": str(champ["name"])})
        site_category = str(mod.get("category") or "")
        return MarketItem(
            provider=RuneForgeProvider.name,
            id=mod_id,
            name=str(mod["name"]),
            author=str(publisher.get("username") or ""),
            thumb_url=f"{THUMBNAIL_URL}/{thumbnail_key}" if thumbnail_key else "",
            page_url=f"{BASE_URL}/mods/{mod_id}",
            category=CATEGORY_TO_ROSE.get(site_category),
            source_category=site_category,
            champions=champions,
            maps=[str(m.get("name")) for m in mod.get("maps") or [] if isinstance(m, dict) and m.get("name")],
            themes=[str(t) for t in mod.get("themes") or [] if isinstance(t, str)],
            features=[SITE_TO_FEATURE.get(f, f) for f in mod.get("features") or [] if isinstance(f, str)],
            gilded=bool(mod.get("isGilded")),
            ai=bool(mod.get("hasAiGeneratedPostContent")),
            downloads=int(mod.get("downloadCount") or 0),
            likes=int(mod.get("likeCount") or 0),
            updated_at=str(mod.get("updatedAt") or mod.get("publishedAt") or ""),
        )

    # ---------------------------------------------------------------- download
    def resolve_download(self, item_id: str) -> DownloadSpec:
        if not _UUID.match(str(item_id)):
            raise MarketError("Invalid RuneForge mod id")
        release_id, version = self._latest_release(item_id)
        return DownloadSpec(
            url=f"{BASE_URL}/mods/{item_id}/releases/{release_id}/download",
            filename="",
            version=version or release_id,
        )

    def _latest_release(self, mod_id: str) -> tuple:
        try:
            response = self.http.get(f"{BASE_URL}/mods/{mod_id}.data")
            response.raise_for_status()
            release = self.release_from_page_data(response.text)
            if release:
                return release
        except MarketError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("[Marketplace] RuneForge page data unreadable for %s: %s", mod_id, exc)

        # The page data layout can change; the mod page links its download too
        try:
            response = self.http.get(f"{BASE_URL}/mods/{mod_id}", headers={"Accept": "text/html"})
            response.raise_for_status()
            for found_mod, release_id in _RELEASE_LINK.findall(response.text):
                if found_mod == mod_id:
                    return release_id, ""
        except Exception as exc:  # noqa: BLE001
            raise MarketError(f"RuneForge mod page unavailable: {exc}") from exc
        raise MarketError("This RuneForge mod has no downloadable release")

    @staticmethod
    def release_from_page_data(text: str) -> Optional[tuple]:
        release = turbo_stream.find_key(turbo_stream.decode(text), "latestRelease")
        if isinstance(release, dict) and _UUID.match(str(release.get("id") or "")):
            return str(release["id"]), str(release.get("tag") or "")
        return None
