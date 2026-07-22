#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP client for Rose's pseudonymous analytics activity and presence."""

from typing import Literal, Optional

import requests

from config import (
    ANALYTICS_ENABLED,
    ANALYTICS_SERVER_URL,
    ANALYTICS_TIMEOUT_S,
    APP_USER_AGENT,
    APP_VERSION,
)
from utils.core.logging import get_logger
from .install_id import get_install_id

log = get_logger()
AnalyticsEvent = Literal["startup", "heartbeat", "close"]


class AnalyticsClient:
    """Send analytics activity and presence notifications."""

    def __init__(
        self,
        server_url: Optional[str] = None,
        timeout: Optional[float] = None,
        enabled: Optional[bool] = None,
    ):
        self.server_url = server_url or ANALYTICS_SERVER_URL
        self.timeout = ANALYTICS_TIMEOUT_S if timeout is None else timeout
        self.enabled = ANALYTICS_ENABLED if enabled is None else enabled

    def send_ping(
        self,
        app_version: Optional[str] = None,
        event: AnalyticsEvent = "heartbeat",
        timeout: Optional[float] = None,
    ) -> bool:
        """Send one activity or presence notification."""
        if not self.enabled:
            log.debug("Analytics is disabled, skipping ping")
            return False

        payload = {
            "install_id": get_install_id(),
            "app_version": app_version or APP_VERSION,
            "event": event,
        }
        request_timeout = self.timeout if timeout is None else timeout

        try:
            response = requests.post(
                self.server_url,
                json=payload,
                headers={
                    "User-Agent": APP_USER_AGENT,
                    "Accept": "application/json",
                },
                timeout=request_timeout,
            )
            response.raise_for_status()
            log.debug("Analytics ping sent successfully: %s", response.status_code)
            return True
        except requests.exceptions.Timeout:
            log.warning("Analytics ping timed out after %ss", request_timeout)
        except requests.exceptions.RequestException as exc:
            log.warning("Analytics ping failed: %s", exc)
        except Exception as exc:
            log.warning("Unexpected error during analytics ping: %s", exc)

        return False
