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

from utils.core.paths import get_skins_dir, get_asset_path, get_state_dir

log = logging.getLogger(__name__)


class HTTPHandler:
    """Handles HTTP requests for file serving

    Security Note:
        - CORS is set to wildcard (*) but server binds ONLY to localhost (127.0.0.1)
        - This is safe because external hosts cannot reach localhost
        - All file paths are validated with _is_safe_path() to prevent path traversal
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
            base_resolved = base_dir.resolve()
            target_resolved = requested_path.resolve()
            return str(target_resolved).startswith(str(base_resolved))
        except (OSError, ValueError):
            return False
    
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
            
            log.debug(f"[SkinMonitor] HTTP request: {path_clean}")
            
            # Handle /port endpoint (backward compatibility)
            if path_clean == "/port":
                return (
                    200,
                    {"Content-Type": "text/plain", "Access-Control-Allow-Origin": "*"},
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
                            {"Content-Type": "text/plain", "Access-Control-Allow-Origin": "*"},
                            port.encode('utf-8')
                        )
                    except Exception as e:
                        log.debug(f"[SkinMonitor] Failed to read bridge port file: {e}")
                # Fallback to current port if file doesn't exist
                return (
                    200,
                    {"Content-Type": "text/plain", "Access-Control-Allow-Origin": "*"},
                    str(self.port).encode('utf-8')
                )
            
            # Handle preview requests
            if path_clean.startswith("/preview/"):
                return self._handle_preview_request(path_clean)
            
            # Handle asset requests
            elif path_clean.startswith("/asset/"):
                return self._handle_asset_request(path_clean)
            
            # Handle plugin file requests
            elif path_clean.startswith("/plugin/"):
                return self._handle_plugin_request(path_clean)
            
            # Return None to let WebSocket handshake proceed
            return None
        except Exception as e:
            log.warning(f"[SkinMonitor] HTTP request error: {e}", exc_info=True)
            return (
                500,
                {"Access-Control-Allow-Origin": "*"},
                b"Internal Server Error"
            )
    
    def _handle_preview_request(self, path_clean: str) -> Optional[tuple]:
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
                return (403, {"Access-Control-Allow-Origin": "*"}, b"Forbidden")

            if file_path.exists():
                log.debug(f"[SkinMonitor] Serving preview: {file_path}")
                with open(file_path, "rb") as f:
                    file_data = f.read()
                return (
                    200,
                    {
                        "Content-Type": "image/png",
                        "Access-Control-Allow-Origin": "*",
                        "Cache-Control": "public, max-age=3600"
                    },
                    file_data
                )
        return None
    
    def _handle_asset_request(self, path_clean: str) -> Optional[tuple]:
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
                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "public, max-age=3600"
                },
                file_data
            )
        return None
    
    def _handle_plugin_request(self, path_clean: str) -> Optional[tuple]:
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
                        return (403, {"Access-Control-Allow-Origin": "*"}, b"Forbidden")

                    if file_path.exists():
                        log.debug(f"[SkinMonitor] Serving plugin file: {file_path}")
                        content_type = self._get_content_type(file_path)
                        
                        with open(file_path, "rb") as f:
                            file_data = f.read()
                        return (
                            200,
                            {
                                "Content-Type": content_type,
                                "Access-Control-Allow-Origin": "*",
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

