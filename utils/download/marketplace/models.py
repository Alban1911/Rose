#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Marketplace models shared by every provider (RuneForge, Celestial/Divine Skins)

Filters are expressed in one vocabulary so the plugin can show a single filter
panel: Rose's own mod categories, champion names, and slugs for themes and
features. Each provider translates them to its site and reports the filters it
cannot honour, in which case it returns nothing rather than unfiltered mods.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

# Rose's mod categories (injection/mods/storage.py), in menu order
ROSE_CATEGORIES = (
    "skins",
    "maps",
    "fonts",
    "announcers",
    "ui",
    "voiceover",
    "loading_screen",
    "vfx",
    "sfx",
    "others",
)

SORTS = ("trending", "new", "updated", "downloads", "likes")
AI_MODES = ("all", "exclude", "only")

# Most mods fill a page of 24 cards; the API sites serve at most that per call
DEFAULT_PAGE_SIZE = 24
MAX_PAGE_SIZE = 48


class MarketError(Exception):
    """A provider request failed; the message is shown to the user."""


class CaptchaRequired(MarketError):
    """The site wants a captcha (or rate-limited us): the user downloads from the site."""

    def __init__(self, message: str, page_url: Optional[str] = None):
        super().__init__(message)
        self.page_url = page_url


class Unsupported(Exception):
    """A provider cannot apply one of the selected filters."""


@dataclass
class MarketItem:
    provider: str
    id: str
    name: str
    author: str = ""
    thumb_url: str = ""
    page_url: str = ""
    category: Optional[str] = None  # Rose category, None when Rose has no equivalent
    source_category: str = ""
    champions: list = field(default_factory=list)  # [{"id": int|None, "name": str}]
    maps: list = field(default_factory=list)
    themes: list = field(default_factory=list)
    features: list = field(default_factory=list)
    gilded: bool = False
    ai: bool = False
    downloads: int = 0
    likes: int = 0
    updated_at: str = ""

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.id}"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["key"] = self.key
        return data


@dataclass
class MarketQuery:
    providers: list = field(default_factory=list)
    search: str = ""
    sort: str = "trending"
    page: int = 0
    page_size: int = DEFAULT_PAGE_SIZE
    champions: list = field(default_factory=list)  # champion names
    maps: list = field(default_factory=list)  # RuneForge map ids
    categories: list = field(default_factory=list)  # ROSE_CATEGORIES
    themes: list = field(default_factory=list)  # theme slugs
    features: list = field(default_factory=list)  # feature slugs
    gilded_only: bool = False
    ai: str = "all"

    @classmethod
    def from_payload(cls, payload: dict) -> "MarketQuery":
        """Build a query from a plugin message, dropping anything malformed."""

        def strings(key: str, limit: int = 50) -> list:
            raw = payload.get(key)
            if not isinstance(raw, list):
                return []
            out = []
            for value in raw[:limit]:
                if isinstance(value, (str, int)) and not isinstance(value, bool):
                    text = str(value).strip()[:64]
                    if text and text not in out:
                        out.append(text)
            return out

        def integer(key: str, default: int) -> int:
            try:
                return int(payload.get(key, default))
            except (TypeError, ValueError):
                return default

        sort = payload.get("sort")
        ai = payload.get("ai")
        return cls(
            providers=strings("providers", 5),
            search=str(payload.get("search") or "").strip()[:100],
            sort=sort if sort in SORTS else "trending",
            page=max(0, integer("page", 0)),
            page_size=min(MAX_PAGE_SIZE, max(1, integer("pageSize", DEFAULT_PAGE_SIZE))),
            champions=strings("champions"),
            maps=[m for m in strings("maps") if m.lstrip("-").isdigit()],
            categories=[c for c in strings("categories") if c in ROSE_CATEGORIES],
            themes=strings("themes"),
            features=strings("features"),
            gilded_only=payload.get("gildedOnly") is True,
            ai=ai if ai in AI_MODES else "all",
        )

    def cache_key(self) -> tuple:
        return (
            self.search.lower(),
            self.sort,
            self.page,
            self.page_size,
            tuple(sorted(c.lower() for c in self.champions)),
            tuple(sorted(self.maps)),
            tuple(sorted(self.categories)),
            tuple(sorted(self.themes)),
            tuple(sorted(self.features)),
            self.gilded_only,
            self.ai,
        )


@dataclass
class SearchPage:
    items: list
    total: int
    has_more: bool


@dataclass
class DownloadSpec:
    url: str
    filename: str
    version: str = ""
    sha256: Optional[str] = None
    size: Optional[int] = None
