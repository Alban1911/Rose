#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP Request Handler
Handles HTTP requests for previews, assets, and plugin files
"""

import logging
from typing import Optional
from pathlib import Path
from urllib.parse import urlparse, unquote

from utils.core.paths import get_skins_dir, get_asset_path, get_state_dir, get_user_data_dir
from utils.core.security import cors_headers_for_origin, is_loopback_origin

log = logging.getLogger(__name__)


class HTTPHandler:
    """Handles HTTP requests for file serving

    Security Note:
        - Browser requests with an Origin header are only allowed from loopback origins.
        - File-serving routes resolve paths under explicit Rose-owned directories.
    """

    def __init__(self, port: int):
        """Initialize HTTP handler

        Args:
            port: Server port for constructing URLs
        """
        self.port = port

    def _is_safe_path(self, base_dir: Path, requested_path: Path) -> bool:
        """Validate that requested_path is safely within base_dir.

        Prevents path traversal attacks (e.g., ../../etc/passwd).

        Args:
            base_dir: The allowed base directory
            requested_path: The path being requested

        Returns:
            True if path is safe, False if it escapes base_dir
        """
        try:
            target_resolved = requested_path.resolve()
            target_resolved.relative_to(base_dir.resolve())
            return True
        except (OSError, ValueError):
            return False

    def _get_origin(self, request_headers: dict) -> Optional[str]:
        """Read Origin from a dict-like headers object."""
        try:
            return request_headers.get("Origin") or request_headers.get("origin")
        except AttributeError:
            return None

    def _forbidden(self) -> tuple:
        """Return a generic forbidden response."""
        return (403, {"Content-Type": "text/plain"}, b"Forbidden")
    
    def handle_request(self, path: str, request_headers: dict) -> Optional[tuple]:
        """Process HTTP requests
        
        Args:
            path: Request path
            request_headers: Request headers
            
        Returns:
            Tuple of (status_code, headers_dict, body_bytes) for HTTP responses
            None to let WebSocket handshake proceed
        """
        try:
            parsed_path = urlparse(path)
            path_clean = unquote(parsed_path.path)
            origin = self._get_origin(request_headers)
            if origin and not is_loopback_origin(origin):
                log.warning("[SkinMonitor] Blocked HTTP request from origin: %s", origin)
                return self._forbidden()

            cors_headers = cors_headers_for_origin(origin)
            
            log.debug(f"[SkinMonitor] HTTP request: {path_clean}")
            
            # Handle /port endpoint (backward compatibility)
            if path_clean == "/port":
                return (
                    200,
                    {"Content-Type": "text/plain", **cors_headers},
                    str(self.port).encode('utf-8')
                )
            
            # Handle /bridge-port endpoint (for file-based discovery)
            if path_clean == "/bridge-port":
                port_file = get_state_dir() / "bridge_port.txt"
                if port_file.exists():
                    try:
                        port = port_file.read_text(encoding='utf-8').strip()
                        return (
                            200,
                            {"Content-Type": "text/plain", **cors_headers},
                            port.encode('utf-8')
                        )
                    except Exception as e:
                        log.debug(f"[SkinMonitor] Failed to read bridge port file: {e}")
                # Fallback to current port if file doesn't exist
                return (
                    200,
                    {"Content-Type": "text/plain", **cors_headers},
                    str(self.port).encode('utf-8')
                )
            
            # Handle preview requests
            if path_clean.startswith("/preview/"):
                return self._handle_preview_request(path_clean, cors_headers)
            
            # Handle asset requests
            elif path_clean.startswith("/asset/"):
                return self._handle_asset_request(path_clean, cors_headers)

            # Handle mod asset requests (for files under %LOCALAPPDATA%\\Rose\\mods)
            elif path_clean.startswith("/mod-asset/"):
                return self._handle_mod_asset_request(path_clean, cors_headers)

            # Handle plugin file requests
            elif path_clean.startswith("/plugin/"):
                return self._handle_plugin_request(path_clean, cors_headers)
            
            # Return None to let WebSocket handshake proceed
            return None
        except Exception as e:
            log.warning(f"[SkinMonitor] HTTP request error: {e}", exc_info=True)
            return (
                500,
                {"Content-Type": "text/plain"},
                b"Internal Server Error"
            )
    
    def _handle_preview_request(self, path_clean: str, cors_headers: dict[str, str]) -> Optional[tuple]:
        """Handle preview image requests"""
        parts = path_clean.replace("/preview/", "").split("/")
        if len(parts) >= 4:
            champion_id = parts[0]
            skin_id = parts[1]
            chroma_id = parts[2]

            skins_dir = get_skins_dir()
            # Construct file path
            if chroma_id == skin_id:
                # Base skin preview
                file_path = skins_dir / champion_id / skin_id / f"{skin_id}.png"
            else:
                # Chroma preview
                file_path = skins_dir / champion_id / skin_id / chroma_id / f"{chroma_id}.png"

            # Security: Validate path doesn't escape skins directory
            if not self._is_safe_path(skins_dir, file_path):
                log.warning(f"[SkinMonitor] Blocked path traversal attempt: {path_clean}")
                return self._forbidden()

            if file_path.exists():
                log.debug(f"[SkinMonitor] Serving preview: {file_path}")
                with open(file_path, "rb") as f:
                    file_data = f.read()
                return (
                    200,
                    {
                        "Content-Type": "image/png",
                        **cors_headers,
                        "Cache-Control": "public, max-age=3600"
                    },
                    file_data
                )
        return None
    
    def _handle_asset_request(self, path_clean: str, cors_headers: dict[str, str]) -> Optional[tuple]:
        """Handle asset file requests"""
        asset_path = path_clean.replace("/asset/", "")
        asset_file = get_asset_path(asset_path)
        
        if asset_file and asset_file.exists():
            log.debug(f"[SkinMonitor] Serving asset: {asset_file}")
            content_type = self._get_content_type(asset_file)
            
            with open(asset_file, "rb") as f:
                file_data = f.read()
            return (
                200,
                {
                    "Content-Type": content_type,
                    **cors_headers,
                    "Cache-Control": "public, max-age=3600"
                },
                file_data
            )
        return None
    
    def _handle_mod_asset_request(self, path_clean: str, cors_headers: dict[str, str]) -> Optional[tuple]:
        """Handle mod file requests under the local mods directory."""
        relative_path = path_clean.replace("/mod-asset/", "")
        mods_dir = get_user_data_dir() / "mods"
        requested_path = mods_dir / relative_path

        if not self._is_safe_path(mods_dir, requested_path):
            log.warning(f"[SkinMonitor] Blocked path traversal attempt: {path_clean}")
            return (403, {**cors_headers, "Content-Type": "text/plain"}, b"Forbidden")

        if requested_path.exists() and requested_path.is_file():
            log.debug(f"[SkinMonitor] Serving mod asset: {requested_path}")
            content_type = self._get_content_type(requested_path)
            with open(requested_path, "rb") as f:
                file_data = f.read()
            return (
                200,
                {
                    "Content-Type": content_type,
                    **cors_headers,
                    "Cache-Control": "public, max-age=3600",
                },
                file_data,
            )
        return None

    def _handle_plugin_request(self, path_clean: str, cors_headers: dict[str, str]) -> Optional[tuple]:
        """Handle plugin file requests"""
        plugin_path = path_clean.replace("/plugin/", "")
        parts = plugin_path.split("/", 1)
        if len(parts) == 2:
            plugin_name, file_name = parts
            try:
                from utils.core.paths import get_app_dir
                app_dir = get_app_dir()
                plugins_dir = app_dir.parent / "Pengu Loader" / "plugins"
                if not plugins_dir.exists():
                    plugins_dir = app_dir / "Pengu Loader" / "plugins"
                
                if plugins_dir.exists():
                    file_path = plugins_dir / plugin_name / file_name

                    # Security: Validate path doesn't escape plugins directory
                    if not self._is_safe_path(plugins_dir, file_path):
                        log.warning(f"[SkinMonitor] Blocked path traversal attempt: {path_clean}")
                        return self._forbidden()

                    if file_path.exists():
                        log.debug(f"[SkinMonitor] Serving plugin file: {file_path}")
                        content_type = self._get_content_type(file_path)
                        
                        with open(file_path, "rb") as f:
                            file_data = f.read()
                        return (
                            200,
                            {
                                "Content-Type": content_type,
                                **cors_headers,
                                "Cache-Control": "public, max-age=3600"
                            },
                            file_data
                        )
                    else:
                        log.info(f"[SkinMonitor] Plugin file not found: {file_path} (plugins_dir: {plugins_dir}, plugin_name: {plugin_name}, file_name: {file_name})")
                else:
                    log.info(f"[SkinMonitor] Plugins directory not found: {plugins_dir} (app_dir: {app_dir})")
            except Exception as e:
                log.warning(f"[SkinMonitor] Failed to serve plugin file: {e}", exc_info=True)
        else:
            log.info(f"[SkinMonitor] Invalid plugin path format: {path_clean} (parts: {parts})")
        return None
    
    def _get_content_type(self, file_path: Path) -> str:
        """Determine content type from file extension"""
        suffix = file_path.suffix.lower()
        content_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".ttf": "font/ttf",
            ".ogg": "audio/ogg",
            ".js": "application/javascript",
            ".css": "text/css",
        }
        return content_types.get(suffix, "application/octet-stream")

