#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU API Request Handler
Handles HTTP requests to LCU API
"""

from typing import Any, Optional

import threading
import time
import requests

from config import LCU_GET_CACHE_TTL_S
from utils.core.logging import get_logger

log = get_logger()

_CACHE_MISS = object()


class LCUAPI:
    """Handles HTTP requests to LCU API"""

    def __init__(self, connection):
        """Initialize API handler

        Args:
            connection: LCUConnection instance
        """
        self.connection = connection
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_lock = threading.Lock()

    def _cache_get(self, path: str, now: float) -> Any:
        with self._cache_lock:
            entry = self._cache.get(path)
            if entry is None:
                return _CACHE_MISS
            expiry, value = entry
            if expiry <= now:
                self._cache.pop(path, None)
                return _CACHE_MISS
            return value

    def _cache_put(self, path: str, value: Any, ttl: float) -> None:
        if ttl <= 0:
            return
        with self._cache_lock:
            self._cache[path] = (time.monotonic() + ttl, value)

    def invalidate(self, path_prefix: str = "") -> None:
        """Invalidate cached GET responses.

        Clears any cache entry whose path starts with ``path_prefix`` AND any
        ancestor of ``path_prefix`` (since a PATCH/PUT on a child resource
        logically mutates its parents too). Passing an empty string clears the
        entire cache.
        """
        with self._cache_lock:
            if not path_prefix:
                self._cache.clear()
                return
            ancestors = set()
            segments = path_prefix.rstrip("/").split("/")
            for i in range(1, len(segments)):
                ancestor = "/".join(segments[:i])
                if ancestor:
                    ancestors.add(ancestor)
            for key in list(self._cache):
                if key.startswith(path_prefix) or key in ancestors:
                    self._cache.pop(key, None)

    def get(self, path: str, timeout: float = 1.0,
            cache_ttl: Optional[float] = None, use_cache: bool = True) -> Optional[dict]:
        """Make GET request to LCU API.

        Responses are cached for ``cache_ttl`` seconds (default
        ``LCU_GET_CACHE_TTL_S``) to de-duplicate bursty polls from multiple
        threads hitting the same endpoint. Pass ``use_cache=False`` to bypass.

        Args:
            path: API endpoint path
            timeout: Request timeout in seconds
            cache_ttl: Override cache TTL in seconds (<= 0 disables caching for
                this call)
            use_cache: If False, skip the cache entirely (neither read nor write)

        Returns:
            JSON response as dict, or None if failed
        """
        ttl = LCU_GET_CACHE_TTL_S if cache_ttl is None else cache_ttl

        if use_cache and ttl > 0:
            cached = self._cache_get(path, time.monotonic())
            if cached is not _CACHE_MISS:
                return cached

        if not self.connection.ok:
            self.connection.refresh_if_needed()
            if not self.connection.ok:
                return None

        def _store(value):
            if use_cache:
                self._cache_put(path, value, ttl)
            return value

        try:
            r = self.connection.session.get((self.connection.base or "") + path, timeout=timeout)
            if r.status_code in (404, 405):
                return _store(None)
            r.raise_for_status()
            try:
                return _store(r.json())
            except (ValueError, requests.exceptions.JSONDecodeError) as e:
                log.debug(f"Failed to decode JSON response: {e}")
                return _store(None)
        except requests.exceptions.RequestException:
            self.connection.refresh_if_needed(force=True)
            if not self.connection.ok:
                return None
            try:
                r = self.connection.session.get((self.connection.base or "") + path, timeout=timeout)
                if r.status_code in (404, 405):
                    return _store(None)
                r.raise_for_status()
                try:
                    return _store(r.json())
                except Exception:
                    return _store(None)
            except requests.exceptions.RequestException:
                return None
    
    def put(self, path: str, json_data, timeout: float, headers: Optional[dict] = None) -> Optional[requests.Response]:
        """Make PUT request to LCU API

        Args:
            path: API endpoint path
            json_data: JSON-serializable data to send (dict or list)
            timeout: Request timeout in seconds
            headers: Optional extra headers to merge into the request

        Returns:
            Response object or None if failed
        """
        if not self.connection.ok:
            self.connection.refresh_if_needed()
            if not self.connection.ok:
                return None

        url = (self.connection.base or "") + path
        self.invalidate(path)

        try:
            t0 = time.perf_counter()
            resp = self.connection.session.put(
                url,
                json=json_data,
                timeout=timeout,
                headers=headers,
            )
            dt_ms = (time.perf_counter() - t0) * 1000.0
            log.info(f"[LCU] PUT {path} -> {getattr(resp, 'status_code', 'None')} in {dt_ms:.1f}ms")
            return resp
        except Exception as exc:
            log.warning(f"[LCU] PUT {path} failed ({type(exc).__name__}): {exc}")
            self.connection.refresh_if_needed(force=True)
            if not self.connection.ok:
                log.warning(f"[LCU] PUT {path} - connection lost after refresh")
                return None
            try:
                t0 = time.perf_counter()
                resp = self.connection.session.put(
                    url,
                    json=json_data,
                    timeout=timeout,
                    headers=headers,
                )
                dt_ms = (time.perf_counter() - t0) * 1000.0
                log.info(f"[LCU] PUT(retry) {path} -> {getattr(resp, 'status_code', 'None')} in {dt_ms:.1f}ms")
                return resp
            except Exception as exc2:
                log.warning(f"[LCU] PUT(retry) {path} also failed ({type(exc2).__name__}): {exc2}")
                return None

    def patch(self, path: str, json_data: dict, timeout: float) -> Optional[requests.Response]:
        """Make PATCH request to LCU API
        
        Args:
            path: API endpoint path
            json_data: JSON data to send
            timeout: Request timeout in seconds
            
        Returns:
            Response object or None if failed
        """
        if not self.connection.ok:
            self.connection.refresh_if_needed()
            if not self.connection.ok:
                return None

        self.invalidate(path)

        try:
            t0 = time.perf_counter()
            resp = self.connection.session.patch(
                (self.connection.base or "") + path,
                json=json_data,
                timeout=timeout,
            )
            dt_ms = (time.perf_counter() - t0) * 1000.0
            try:
                log.debug(f"[LCU] PATCH {path} -> {getattr(resp, 'status_code', 'None')} in {dt_ms:.1f}ms")
            except Exception:
                pass
            return resp
        except requests.exceptions.RequestException:
            self.connection.refresh_if_needed(force=True)
            if not self.connection.ok:
                return None
            try:
                t0 = time.perf_counter()
                resp = self.connection.session.patch(
                    (self.connection.base or "") + path,
                    json=json_data,
                    timeout=timeout,
                )
                dt_ms = (time.perf_counter() - t0) * 1000.0
                try:
                    log.debug(f"[LCU] PATCH(retry) {path} -> {getattr(resp, 'status_code', 'None')} in {dt_ms:.1f}ms")
                except Exception:
                    pass
                return resp
            except requests.exceptions.RequestException:
                return None

