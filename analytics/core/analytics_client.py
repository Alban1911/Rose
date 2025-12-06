#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analytics client for sending user tracking pings
"""

import requests
from typing import Optional

from config import APP_USER_AGENT, APP_VERSION, ANALYTICS_SERVER_URL, ANALYTICS_TIMEOUT_S, ANALYTICS_ENABLED
from utils.core.logging import get_logger
from .machine_id import get_machine_id

log = get_logger()


class AnalyticsClient:
    """Client for sending analytics pings to the server"""
    
    def __init__(self, server_url: Optional[str] = None, timeout: Optional[float] = None):
        """
        Initialize analytics client.
        
        Args:
            server_url: Server endpoint URL (defaults to ANALYTICS_SERVER_URL from config)
            timeout: Request timeout in seconds (defaults to ANALYTICS_TIMEOUT_S from config)
        """
        self.server_url = server_url or ANALYTICS_SERVER_URL
        self.timeout = timeout or ANALYTICS_TIMEOUT_S
        self.enabled = ANALYTICS_ENABLED
    
    def send_ping(self, app_version: Optional[str] = None) -> bool:
        """
        Send a ping to the analytics server with machine ID and app version.
        
        Args:
            app_version: Application version (defaults to APP_VERSION from config)
            
        Returns:
            True if ping was sent successfully, False otherwise
        """
        if not self.enabled:
            log.debug("Analytics is disabled, skipping ping")
            return False
        
        try:
            # Get machine ID
            machine_id = get_machine_id()
            
            # Prepare payload
            payload = {
                "machine_id": machine_id,
                "app_version": app_version or APP_VERSION
            }
            
            # Send POST request
            response = requests.post(
                self.server_url,
                json=payload,
                headers={
                    "User-Agent": APP_USER_AGENT,
                    "Content-Type": "application/json"
                },
                timeout=self.timeout
            )
            
            # Check response
            response.raise_for_status()
            log.debug(f"Analytics ping sent successfully: {response.status_code}")
            return True
            
        except requests.exceptions.Timeout:
            log.warning(f"Analytics ping timeout after {self.timeout}s")
            return False
        except requests.exceptions.RequestException as e:
            log.warning(f"Analytics ping failed: {e}")
            return False
        except Exception as e:
            log.warning(f"Unexpected error during analytics ping: {e}")
            return False

