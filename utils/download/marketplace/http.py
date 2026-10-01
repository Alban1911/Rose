#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP session for the marketplace

Both sites ask automated clients to keep off their APIs (robots.txt), so Rose
only calls them when the user browses or downloads, one request per second and
per API host at most, and it caches answers for a few minutes.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import APP_USER_AGENT

log = logging.getLogger(__name__)

USER_AGENT = f"{APP_USER_AGENT} (+https://github.com/Alban1911/Rose)"
API_MIN_INTERVAL_S = 1.0
TIMEOUT = (6, 20)


class PoliteSession:
    """A requests session that spaces out calls to rate-limited API hosts."""

    def __init__(self, rate_limited_hosts: tuple = (), min_interval_s: float = API_MIN_INTERVAL_S):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json, */*"})
        retry = Retry(
            total=2,
            backoff_factor=1.0,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=8)
        self.session.mount("https://", adapter)
        self.rate_limited_hosts = {h.lower() for h in rate_limited_hosts}
        self.min_interval_s = min_interval_s
        self._lock = threading.Lock()
        self._next_slot: dict[str, float] = {}

    def _wait_turn(self, url: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        if host not in self.rate_limited_hosts:
            return
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot.get(host, 0.0))
            self._next_slot[host] = slot + self.min_interval_s
        delay = slot - now
        if delay > 0:
            time.sleep(delay)

    def get(self, url: str, *, params=None, stream: bool = False, allow_redirects: bool = True,
            timeout=TIMEOUT, headers: Optional[dict] = None) -> requests.Response:
        self._wait_turn(url)
        return self.session.get(
            url,
            params=params,
            stream=stream,
            allow_redirects=allow_redirects,
            timeout=timeout,
            headers=headers,
        )

    def get_json(self, url: str, *, params=None):
        response = self.get(url, params=params)
        response.raise_for_status()
        return response.json()
