#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU API Request Handler
Handles HTTP requests to LCU API
"""

from typing import Optional

import time
import requests

from utils.core.logging import get_logger

log = get_logger()


class LCUAPI:
    """Handles HTTP requests to LCU API"""
    
    def __init__(self, connection):
        """Initialize API handler
        
        Args:
            connection: LCUConnection instance
        """
        self.connection = connection
    
    def get(self, path: str, timeout: float = 1.0) -> Optional[dict]:
        """Make GET request to LCU API
        
        Args:
            path: API endpoint path
            timeout: Request timeout in seconds
            
        Returns:
            JSON response as dict, or None if failed
        """
        if not self.connection.ok:
            self.connection.refresh_if_needed()
            if not self.connection.ok: 
                return None
        
        try:
            r = self.connection.session.get((self.connection.base or "") + path, timeout=timeout)
            if r.status_code in (404, 405): 
                return None
            r.raise_for_status()
            try: 
                return r.json()
            except (ValueError, requests.exceptions.JSONDecodeError) as e:
                log.debug(f"Failed to decode JSON response: {e}")
                return None
        except requests.exceptions.RequestException:
            self.connection.refresh_if_needed(force=True)
            if not self.connection.ok: 
                return None
            try:
                r = self.connection.session.get((self.connection.base or "") + path, timeout=timeout)
                if r.status_code in (404, 405): 
                    return None
                r.raise_for_status()
                try: 
                    return r.json()
                except Exception: 
                    return None
            except requests.exceptions.RequestException:
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

