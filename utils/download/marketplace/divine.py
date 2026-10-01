#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Celestial / Divine Skins (divineskins.gg) provider

Celestial is Divine Skins' launcher; the catalog lives on api.divineskins.gg
(undocumented, read without an account):
  GET /api/catalog/skins?page&size&sortBy&direction&search&categoryIds&themeIds&featureIds&championName&excludeNsfw&excludeDisclosures
  GET /api/catalog/metadata, /api/catalog/champions
  GET /api/skins/{id}                                           versions[] with contentHash
  GET /api/celestial/manual/{id}/versions/{vid}/download-url    short-lived signed file URL

The free download can ask for a captcha (HTTP 400/429). Rose never solves it:
the user is sent to the site's download page instead.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from .base import MarketProvider, champion_key, slugify
from .http import PoliteSession
from .models import CaptchaRequired, DownloadSpec, MarketError, MarketItem, MarketQuery, SearchPage, Unsupported

log = logging.getLogger(__name__)

API_URL = "https://api.divineskins.gg"
SITE_URL = "https://divineskins.gg"
IMAGES_URL = "https://lol-assets.divine-cdn.com"
FACETS_TTL_S = 6 * 3600

CATEGORY_TO_ROSE = {1: "skins", 3: "maps", 4: "sfx", 5: "fonts", 6: "announcers", 7: "ui", 8: "others", 9: "others"}

SORTS = {
    "trending": "downloadCount",
    "new": "approvedDate",
    "updated": "contentUpdatedDate",
    "downloads": "downloadCount",
    "likes": "likeCount",
}

# Divine's feature names -> the shared feature slugs ("Chroma" is a theme there)
FEATURE_SLUGS = {"animations": "animations", "model": "model", "visual_effects": "vfx",
                 "sound_effects": "sfx", "voice_over": "voiceover"}
AI_DISCLOSURES = "ai_media,ai_assisted"


class DivineProvider(MarketProvider):
    name = "divine"
    label = "Celestial (Divine Skins)"
    api_hosts = ("api.divineskins.gg",)
    image_hosts = ("lol-assets.divine-cdn.com", "images.divine-cdn.com")
    page_hosts = ("divineskins.gg", "www.divineskins.gg")

    def __init__(self, http: PoliteSession):
        self.http = http
        self._meta: Optional[dict] = None
        self._meta_at = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ facets
    def _metadata(self) -> dict:
        with self._lock:
            if self._meta and time.monotonic() - self._meta_at < FACETS_TTL_S:
                return self._meta
            try:
                metadata = self.http.get_json(f"{API_URL}/api/catalog/metadata")
                champions_raw = self.http.get_json(f"{API_URL}/api/catalog/champions")
            except Exception as exc:  # noqa: BLE001
                raise MarketError(f"Celestial (Divine Skins) is not reachable: {exc}") from exc

            themes = {}  # slug -> (id, label)
            for theme in metadata.get("themes") or []:
                if isinstance(theme, dict) and theme.get("active", True) and theme.get("id") is not None:
                    slug = slugify(theme.get("name"))
                    if slug and slug != "nsfw":
                        themes[slug] = (int(theme["id"]), str(theme["name"]))
            features = {}  # shared slug -> id
            for feature in metadata.get("features") or []:
                if isinstance(feature, dict) and feature.get("id") is not None:
                    slug = FEATURE_SLUGS.get(slugify(feature.get("name")))
                    if slug:
                        features[slug] = int(feature["id"])
            champions = sorted(
                {str(c["name"]) for c in champions_raw or [] if isinstance(c, dict) and c.get("name")}
            )
            self._meta = {"themes": themes, "features": features, "champions": champions}
            self._meta_at = time.monotonic()
            return self._meta

    def facets(self) -> dict:
        meta = self._metadata()
        feature_slugs = list(meta["features"])
        if "chroma" in meta["themes"]:
            feature_slugs.insert(0, "chroma")
        return {
            "champions": [{"id": None, "name": name} for name in meta["champions"]],
            "maps": [],
            "categories": sorted(set(CATEGORY_TO_ROSE.values())),
            "themes": [{"value": slug, "label": label} for slug, (_id, label) in meta["themes"].items()
                       if slug != "chroma"],
            "features": feature_slugs,
            "gilded": False,
            "aiOnly": False,
        }

    # ------------------------------------------------------------------ search
    def build_params(self, query: MarketQuery) -> dict:
        if query.maps:
            raise Unsupported("map")
        if query.gilded_only:
            raise Unsupported("gilded")
        if query.ai == "only":
            raise Unsupported("ai")
        if len(query.champions) > 1:
            raise Unsupported("champion")

        meta = self._metadata()
        params = {
            "page": query.page,
            "size": query.page_size,
            "sortBy": SORTS.get(query.sort, "downloadCount"),
            "direction": "desc",
            "excludeNsfw": "true",
        }
        if query.search:
            params["search"] = query.search
        if query.champions:
            wanted = champion_key(query.champions[0])
            name = next((n for n in meta["champions"] if champion_key(n) == wanted), None)
            if not name:
                raise Unsupported("champion")
            params["championName"] = name
        if query.categories:
            ids = sorted({cid for cid, rose in CATEGORY_TO_ROSE.items() if rose in query.categories})
            if not ids:
                raise Unsupported("category")
            params["categoryIds"] = ",".join(map(str, ids))

        theme_ids = []
        if query.themes:
            theme_ids = [meta["themes"][t][0] for t in query.themes if t in meta["themes"]]
            if not theme_ids:
                raise Unsupported("theme")
        if query.features:
            feature_ids = [meta["features"][f] for f in query.features if f in meta["features"]]
            chroma = "chroma" in query.features and "chroma" in meta["themes"]
            if not feature_ids and not chroma:
                raise Unsupported("feature")
            if feature_ids:
                params["featureIds"] = ",".join(map(str, feature_ids))
            if chroma:
                theme_ids.append(meta["themes"]["chroma"][0])
        if theme_ids:
            params["themeIds"] = ",".join(map(str, sorted(set(theme_ids))))
        if query.ai == "exclude":
            params["excludeDisclosures"] = AI_DISCLOSURES
        return params

    def search(self, query: MarketQuery) -> SearchPage:
        params = self.build_params(query)
        try:
            data = self.http.get_json(f"{API_URL}/api/catalog/skins", params=params)
        except Exception as exc:  # noqa: BLE001
            raise MarketError(f"Celestial (Divine Skins) search failed: {exc}") from exc
        items = [item for item in (self.parse_skin(s) for s in data.get("content") or []) if item]
        total = int(data.get("totalElements") or 0)
        last = data.get("last")
        has_more = (not last) if isinstance(last, bool) else (query.page + 1) * query.page_size < total
        return SearchPage(items=items, total=total, has_more=has_more)

    @staticmethod
    def parse_skin(skin: dict) -> Optional[MarketItem]:
        if not isinstance(skin, dict) or skin.get("id") is None or not skin.get("name"):
            return None
        if skin.get("nsfw"):
            return None
        artist = str(skin.get("artistUsername") or "")
        slug = str(skin.get("slug") or "")
        image_path = str(skin.get("imagePath") or "").lstrip("/")
        champion = str(skin.get("champion") or "").strip()
        try:
            category_id = int(skin.get("categoryId"))
        except (TypeError, ValueError):
            category_id = None
        return MarketItem(
            provider=DivineProvider.name,
            id=str(skin["id"]),
            name=str(skin["name"]),
            author=artist,
            thumb_url=f"{IMAGES_URL}/{image_path}" if image_path else "",
            page_url=f"{SITE_URL}/{artist}/{slug}" if artist and slug else SITE_URL,
            category=CATEGORY_TO_ROSE.get(category_id),
            source_category=str(skin.get("category") or ""),
            champions=[{"id": None, "name": champion}] if champion else [],
            ai=bool(skin.get("disclosures")),
            downloads=int(skin.get("downloadCount") or 0),
            likes=int(skin.get("likeCount") or 0),
            updated_at=str(skin.get("contentUpdatedDate") or skin.get("lastUpdatedDate") or ""),
        )

    # ---------------------------------------------------------------- download
    def resolve_download(self, item_id: str) -> DownloadSpec:
        if not str(item_id).isdigit():
            raise MarketError("Invalid Celestial (Divine Skins) mod id")
        try:
            skin = self.http.get_json(f"{API_URL}/api/skins/{item_id}")
        except Exception as exc:  # noqa: BLE001
            raise MarketError(f"Celestial (Divine Skins) mod unavailable: {exc}") from exc

        page_url = SITE_URL
        if skin.get("artistUsername") and skin.get("slug"):
            page_url = f"{SITE_URL}/download/{skin['artistUsername']}/{skin['slug']}"
        version = self.latest_version(skin.get("versions") or [])
        if not version:
            raise MarketError("This Celestial (Divine Skins) mod has no downloadable version")

        response = self.http.get(
            f"{API_URL}/api/celestial/manual/{item_id}/versions/{version['id']}/download-url",
            params={"turnstileToken": ""},
        )
        if response.status_code in (400, 401, 403, 429):
            raise CaptchaRequired(
                "Celestial (Divine Skins) asks for a captcha: download this mod from its page",
                page_url,
            )
        try:
            response.raise_for_status()
            url = response.json().get("url")
        except Exception as exc:  # noqa: BLE001
            raise MarketError(f"Celestial (Divine Skins) download failed: {exc}") from exc
        if not url:
            raise MarketError("Celestial (Divine Skins) returned no download link")

        content_hash = version.get("contentHash")
        return DownloadSpec(
            url=url,
            filename="",
            version=str(version.get("title") or version["id"]),
            sha256=str(content_hash).lower() if content_hash else None,
            size=version.get("fileSize") if isinstance(version.get("fileSize"), int) else None,
        )

    @staticmethod
    def latest_version(versions: list) -> Optional[dict]:
        usable = [v for v in versions if isinstance(v, dict) and v.get("id") is not None]
        if not usable:
            return None
        return max(usable, key=lambda v: (str(v.get("uploadDate") or ""), int(v["id"])))
