#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Marketplace service: browse RuneForge and Celestial (Divine Skins) from the
client and import a chosen mod the same way "Add custom mods" does

It answers the ROSE-Marketplace plugin over the bridge:
  marketplace-facets   -> marketplace-facets-response
  marketplace-search   -> marketplace-search-response (echoes requestId)
  marketplace-download -> marketplace-download-progress ... marketplace-download-result
  marketplace-open-page   opens the mod's page in the browser

Work runs on its own threads so a long download never delays the bridge or a search.
Downloaded files go to a temporary folder and through ModStorageService's import,
never straight into the mods folder (unregistered folders there are ignored or removed).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from pathlib import Path, PurePosixPath
from typing import Callable, Optional
from urllib.parse import unquote, urlparse

from utils.core.atomic_file import write_text_atomic
from utils.core.paths import get_user_data_dir
from utils.core.safe_extract import MOD_ARCHIVE_SUFFIXES

from .divine import DivineProvider
from .http import PoliteSession
from .repair import repair_archive
from .models import (
    ROSE_CATEGORIES,
    CaptchaRequired,
    DownloadSpec,
    MarketError,
    MarketQuery,
    SearchPage,
    Unsupported,
)
from .base import FEATURE_LABELS, champion_key
from .runeforge import RuneForgeProvider

log = logging.getLogger(__name__)

SEARCH_TTL_S = 300
SEARCH_CACHE_MAX = 200
MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024
PROGRESS_EVERY_S = 0.25
INSTALLED_FILE = "marketplace_installed.json"


def enabled_provider_names(available: list) -> list:
    """Providers switched on in config.ini ([Marketplace] enabled_providers), all by default."""
    try:
        from config import get_config_option

        raw = get_config_option("Marketplace", "enabled_providers")
    except Exception:  # noqa: BLE001
        raw = None
    if not raw:
        return list(available)
    wanted = [name.strip().lower() for name in raw.split(",")]
    return [name for name in available if name in wanted]


def safe_file_stem(name: str) -> str:
    """A Windows-safe file name for the mod (Rose names the imported mod after it)."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", str(name or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")[:80].strip(" .")
    return cleaned or "Marketplace mod"


def archive_suffix(spec_name: str, url: str, content_disposition: str, head: bytes) -> Optional[str]:
    """Find the archive type from the server's file name, the URL or the file itself."""
    candidates = [spec_name]
    if content_disposition:
        message = Message()
        message["content-disposition"] = content_disposition
        candidates.append(message.get_filename() or "")
    parsed = urlparse(url)
    candidates.append(unquote(parsed.path))
    candidates.extend(unquote(part.split("=", 1)[1]) for part in parsed.query.split("&") if part.startswith("filename="))
    for candidate in candidates:
        suffix = PurePosixPath(str(candidate).replace("\\", "/")).suffix.lower()
        if suffix in MOD_ARCHIVE_SUFFIXES:
            return suffix
    if head.startswith(b"_modpkg_"):
        return ".modpkg"
    if head.startswith(b"PK\x03\x04"):
        return ".fantome"
    return None


class InstalledIndex:
    """Which marketplace mods were imported, so cards can say Installed / Update."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._data: Optional[dict] = None

    def _load(self) -> dict:
        if self._data is None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._data = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self._data = {}
        return self._data

    def get(self, key: str) -> Optional[dict]:
        with self._lock:
            entry = self._load().get(key)
        if not isinstance(entry, dict):
            return None
        # The mod may have been deleted from Manage mods since
        mod_path = entry.get("modPath")
        if mod_path and not Path(mod_path).exists():
            return None
        return entry

    def record(self, key: str, entry: dict) -> None:
        with self._lock:
            data = self._load()
            data[key] = entry
            try:
                write_text_atomic(self.path, json.dumps(data, indent=2, ensure_ascii=False))
            except OSError as exc:
                log.warning("[Marketplace] Could not save %s: %s", self.path, exc)


class MarketplaceService:
    def __init__(
        self,
        send: Callable[[dict], None],
        mod_storage,
        providers: Optional[list] = None,
        data_dir: Optional[Path] = None,
    ):
        self.send = send
        self.mod_storage = mod_storage
        if providers is None:
            hosts = RuneForgeProvider.api_hosts + DivineProvider.api_hosts
            http = PoliteSession(rate_limited_hosts=hosts)
            providers = [RuneForgeProvider(http), DivineProvider(http)]
        self.providers = {p.name: p for p in providers}
        self.data_dir = data_dir or get_user_data_dir()
        self.installed = InstalledIndex(self.data_dir / INSTALLED_FILE)
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="Marketplace")
        self._fan_out = ThreadPoolExecutor(max_workers=len(self.providers) or 1, thread_name_prefix="MarketplaceFetch")
        self._cache: dict = {}
        self._cache_lock = threading.Lock()
        self._active_downloads: set = set()
        self._downloads_lock = threading.Lock()

    # ----------------------------------------------------------------- bridge
    def handle(self, payload_type: str, payload: dict) -> None:
        """Start the work for a plugin message; answers arrive through ``send``."""
        if payload_type == "marketplace-facets":
            self._executor.submit(self._guard, "facets", self._send_facets)
        elif payload_type == "marketplace-search":
            self._executor.submit(self._guard, "search", self._send_search, payload)
        elif payload_type == "marketplace-download":
            self._executor.submit(self._guard, "download", self.download, payload)
        elif payload_type == "marketplace-open-page":
            self.open_page(payload.get("url"))

    def _guard(self, what: str, func, *args) -> None:
        try:
            func(*args)
        except Exception:  # noqa: BLE001
            log.exception("[Marketplace] %s failed", what)

    def enabled(self) -> list:
        return enabled_provider_names(list(self.providers))

    # ----------------------------------------------------------------- facets
    def _send_facets(self) -> None:
        self.send({"type": "marketplace-facets-response", **self.facets()})

    def facets(self) -> dict:
        """Merge every enabled provider's filter values; each value lists who supports it."""
        result = {
            "providers": [
                {"name": p.name, "label": p.label, "enabled": p.name in self.enabled()}
                for p in self.providers.values()
            ],
            "champions": [],
            "maps": [],
            "categories": [],
            "themes": [],
            "features": [],
            "gilded": [],
            "aiOnly": [],
            "errors": {},
        }
        champions: dict = {}
        maps: dict = {}
        categories: dict = {}
        themes: dict = {}
        features: dict = {}
        for name in self.enabled():
            provider = self.providers[name]
            try:
                facets = provider.facets()
            except Exception as exc:  # noqa: BLE001
                log.warning("[Marketplace] %s filters unavailable: %s", name, exc)
                result["errors"][name] = str(exc)
                continue
            for champ in facets.get("champions", []):
                entry = champions.setdefault(champion_key(champ["name"]), {"name": champ["name"], "id": None, "providers": []})
                if champ.get("id") is not None:
                    entry["id"] = champ["id"]
                entry["providers"].append(name)
            for game_map in facets.get("maps", []):
                maps.setdefault(game_map["id"], {"value": str(game_map["id"]), "label": game_map["name"], "providers": []})["providers"].append(name)
            for category in facets.get("categories", []):
                categories.setdefault(category, {"value": category, "providers": []})["providers"].append(name)
            for theme in facets.get("themes", []):
                themes.setdefault(theme["value"], {**theme, "providers": []})["providers"].append(name)
            for feature in facets.get("features", []):
                features.setdefault(feature, {"value": feature, "label": FEATURE_LABELS.get(feature, feature), "providers": []})["providers"].append(name)
            if facets.get("gilded"):
                result["gilded"].append(name)
            if facets.get("aiOnly"):
                result["aiOnly"].append(name)

        result["champions"] = sorted(champions.values(), key=lambda c: c["name"].lower())
        result["maps"] = sorted(maps.values(), key=lambda m: m["label"])
        result["categories"] = [categories[c] for c in ROSE_CATEGORIES if c in categories]
        result["themes"] = sorted(themes.values(), key=lambda t: t["label"])
        result["features"] = [features[f] for f in FEATURE_LABELS if f in features]
        return result

    # ----------------------------------------------------------------- search
    def _send_search(self, payload: dict) -> None:
        response = {"type": "marketplace-search-response", "requestId": payload.get("requestId")}
        response.update(self.search(MarketQuery.from_payload(payload)))
        self.send(response)

    def _cached_search(self, name: str, query: MarketQuery) -> SearchPage:
        key = (name, query.cache_key())
        now = time.monotonic()
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < SEARCH_TTL_S:
                return hit[1]
        page = self.providers[name].search(query)
        with self._cache_lock:
            if len(self._cache) >= SEARCH_CACHE_MAX:
                for stale in sorted(self._cache, key=lambda k: self._cache[k][0])[: SEARCH_CACHE_MAX // 4]:
                    self._cache.pop(stale, None)
            self._cache[key] = (now, page)
        return page

    def search(self, query: MarketQuery) -> dict:
        names = [n for n in (query.providers or self.enabled()) if n in self.enabled()]
        skipped, errors = {}, {}
        if not names:
            return {"items": [], "total": 0, "hasMore": False, "page": query.page, "skipped": skipped, "errors": errors}

        # Two sites share one page of cards
        per_provider = max(1, query.page_size // len(names))
        sub_query = MarketQuery(**{**query.__dict__, "page_size": per_provider})
        futures = {name: self._fan_out.submit(self._cached_search, name, sub_query) for name in names}

        pages = {}
        for name, future in futures.items():
            try:
                pages[name] = future.result(timeout=60)
            except Unsupported as exc:
                skipped[name] = str(exc)
            except Exception as exc:  # noqa: BLE001
                log.warning("[Marketplace] %s search failed: %s", name, exc)
                errors[name] = str(exc)

        # Alternate the sites' cards so neither buries the other
        lists = [pages[name].items for name in names if name in pages]
        merged = []
        for index in range(max((len(items) for items in lists), default=0)):
            for items in lists:
                if index < len(items):
                    merged.append(self._card(items[index]))
        return {
            "items": merged,
            "total": sum(p.total for p in pages.values()),
            "hasMore": any(p.has_more for p in pages.values()),
            "page": query.page,
            "skipped": skipped,
            "errors": errors,
        }

    def _card(self, item) -> dict:
        card = item.to_dict()
        # Some mods (skin disablers...) list every champion; the card only needs a few
        card["championCount"] = len(card["champions"])
        card["champions"] = card["champions"][:10]
        installed = self.installed.get(item.key)
        card["installed"] = bool(installed)
        card["updateAvailable"] = bool(
            installed and item.updated_at and installed.get("updatedAt") and item.updated_at > installed["updatedAt"]
        )
        return card

    # --------------------------------------------------------------- download
    def download(self, payload: dict) -> None:
        provider_name = payload.get("provider")
        item_id = str(payload.get("id") or "")
        key = f"{provider_name}:{item_id}"
        result = {"type": "marketplace-download-result", "key": key, "success": False}

        with self._downloads_lock:
            if key in self._active_downloads:
                return
            self._active_downloads.add(key)
        temp_dir = None
        try:
            provider = self.providers.get(provider_name)
            if provider is None or provider_name not in self.enabled() or not item_id:
                raise MarketError("Unknown marketplace mod")
            category, champion_id, skin_ids = self._import_target(payload)

            self._progress(key, 0, None)
            spec = provider.resolve_download(item_id)
            temp_dir = self.data_dir / "cache" / "marketplace" / "tmp" / uuid.uuid4().hex
            archive = self.fetch(spec, temp_dir, safe_file_stem(payload.get("name")), key)
            if category == "skins":
                self.send({"type": "marketplace-download-progress", "key": key, "stage": "repair"})
                repair = repair_archive(archive)
                archive = repair.path
                result.update({"repair": repair.status, "repairApplied": repair.applied})

            if category == "skins":
                mod_folder, _manifest, mod_name = self.mod_storage.import_mod_file(champion_id, archive, skin_ids)
            else:
                mod_folder, mod_name = self.mod_storage.import_category_mod_file(category, archive)
            log.info("[Marketplace] Imported %s as %s mod %s", key, category, mod_name)

            self.installed.record(key, {
                "name": str(payload.get("name") or mod_name),
                "version": spec.version,
                "updatedAt": str(payload.get("updatedAt") or ""),
                "category": category,
                "championId": champion_id,
                "skinIds": skin_ids,
                "modName": mod_name,
                "modPath": str(mod_folder),
                "installedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            result.update({"success": True, "modName": mod_name, "category": category, "version": spec.version})
        except CaptchaRequired as exc:
            result.update({"error": str(exc), "captcha": True, "pageUrl": exc.page_url})
        except Exception as exc:  # noqa: BLE001
            log.warning("[Marketplace] Download of %s failed: %s", key, exc)
            result["error"] = str(exc)
        finally:
            with self._downloads_lock:
                self._active_downloads.discard(key)
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
            self.send(result)

    def _import_target(self, payload: dict) -> tuple:
        category = payload.get("category")
        if category not in ROSE_CATEGORIES:
            raise MarketError("Choose the kind of mod to import")
        if category != "skins":
            return category, None, []
        try:
            champion_id = int(payload.get("championId"))
            skin_ids = []
            for raw in payload.get("skinIds") or []:
                skin_id = int(raw)
                if skin_id > 0 and skin_id not in skin_ids:
                    skin_ids.append(skin_id)
        except (TypeError, ValueError):
            raise MarketError("Champion ID and Skin IDs must be numeric") from None
        if champion_id <= 0 or not skin_ids:
            raise MarketError("Champion ID and at least one Skin ID are required")
        return category, champion_id, skin_ids

    def _progress(self, key: str, received: int, total: Optional[int]) -> None:
        percent = round(received * 100 / total, 1) if total else None
        self.send({"type": "marketplace-download-progress", "key": key, "received": received,
                   "total": total, "percent": percent})

    def fetch(self, spec: DownloadSpec, temp_dir: Path, stem: str, key: str) -> Path:
        """Stream the mod archive into temp_dir and check its size and hash."""
        http = next(iter(self.providers.values())).http
        response = http.get(spec.url, stream=True, timeout=(10, 60))
        if response.status_code in (401, 403, 429):
            raise MarketError(f"The site refused the download (HTTP {response.status_code})")
        response.raise_for_status()
        if urlparse(response.url).scheme != "https":
            raise MarketError("Refusing a download that is not served over HTTPS")

        total = None
        try:
            total = int(response.headers.get("Content-Length") or 0) or spec.size
        except ValueError:
            total = spec.size
        if total and total > MAX_DOWNLOAD_BYTES:
            raise MarketError("This mod is too large to download")

        temp_dir.mkdir(parents=True, exist_ok=True)
        partial = temp_dir / "download.part"
        digest = hashlib.sha256()
        received = 0
        head = b""
        last_report = 0.0
        with open(partial, "wb") as handle:
            for chunk in response.iter_content(256 * 1024):
                if not chunk:
                    continue
                if len(head) < 16:
                    head += chunk[:16]
                received += len(chunk)
                if received > MAX_DOWNLOAD_BYTES:
                    raise MarketError("This mod is too large to download")
                digest.update(chunk)
                handle.write(chunk)
                now = time.monotonic()
                if now - last_report >= PROGRESS_EVERY_S:
                    last_report = now
                    self._progress(key, received, total)
        self._progress(key, received, total or received)

        if received == 0:
            raise MarketError("The downloaded file is empty")
        if spec.sha256 and digest.hexdigest() != spec.sha256:
            raise MarketError("The downloaded file is damaged (checksum mismatch)")
        suffix = archive_suffix(spec.filename, response.url, response.headers.get("Content-Disposition", ""), head)
        if suffix is None:
            raise MarketError("The downloaded file is not a supported mod archive")
        archive = temp_dir / f"{stem}{suffix}"
        partial.replace(archive)
        return archive

    # ------------------------------------------------------------------ pages
    def open_page(self, url) -> bool:
        """Open a mod page in the browser, only on the providers' own sites."""
        if not isinstance(url, str):
            return False
        parsed = urlparse(url)
        allowed = {h for p in self.providers.values() for h in p.page_hosts}
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in allowed:
            log.warning("[Marketplace] Refused to open %s", url)
            return False
        try:
            return bool(webbrowser.open(url))
        except Exception as exc:  # noqa: BLE001
            log.warning("[Marketplace] Could not open %s: %s", url, exc)
            return False

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._fan_out.shutdown(wait=False, cancel_futures=True)
