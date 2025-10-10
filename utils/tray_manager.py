#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System tray manager for SkinCloner
"""

import os
import threading
from typing import Optional, Callable
import pystray
from PIL import Image, ImageDraw
from utils.logging import get_logger
from constants import (
    TRAY_READY_MAX_WAIT_S, TRAY_READY_CHECK_INTERVAL_S,
    TRAY_THREAD_JOIN_TIMEOUT_S, TRAY_ICON_WIDTH, TRAY_ICON_HEIGHT,
    TRAY_ICON_ELLIPSE_COORDS, TRAY_ICON_BORDER_WIDTH,
    TRAY_ICON_FONT_SIZE, TRAY_ICON_TEXT_X, TRAY_ICON_TEXT_Y,
    TRAY_ICON_DOT_SIZE, TRAY_ICON_CHECK_SCALE_DIVISOR
)

log = get_logger()


class TrayManager:
    """Manages the system tray icon for SkinCloner"""
    
    def __init__(self, quit_callback: Optional[Callable] = None):
        """
        Initialize the tray manager
        
        Args:
            quit_callback: Function to call when user clicks "Quit"
        """
        self.quit_callback = quit_callback
        self.icon = None
        self.tray_thread = None
        self._stop_event = threading.Event()
        self._is_downloading = False
        self._base_icon_image = None
        
    def _create_icon_image(self) -> Image.Image:
        """Create a simple icon image for the tray"""
        # Create a 128x128 icon with a simple design (doubled from 64x64)
        width, height = TRAY_ICON_WIDTH, TRAY_ICON_HEIGHT
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # Draw a simple "SC" logo (SkinCloner)
        # Background circle (scaled 2x)
        draw.ellipse(TRAY_ICON_ELLIPSE_COORDS, fill=(0, 100, 200, 255), outline=(0, 50, 100, 255), width=TRAY_ICON_BORDER_WIDTH)
        
        # "SC" text
        try:
            # Try to use a font if available
            from PIL import ImageFont
            font = ImageFont.truetype("arial.ttf", TRAY_ICON_FONT_SIZE)
        except:
            # Fallback to default font
            font = ImageFont.load_default()
        
        # Draw "SC" text (scaled 2x)
        draw.text((TRAY_ICON_TEXT_X, TRAY_ICON_TEXT_Y), "SC", fill=(255, 255, 255, 255), font=font)
        
        return image
    
    def _load_icon_from_file(self) -> Optional[Image.Image]:
        """Try to load icon from icon.ico file"""
        try:
            icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icon.ico")
            if os.path.exists(icon_path):
                # Convert ICO to PNG for pystray
                with Image.open(icon_path) as img:
                    # Convert to RGBA and resize to 128x128 (doubled from 64x64)
                    img = img.convert('RGBA')
                    img = img.resize((128, 128), Image.Resampling.LANCZOS)
                    return img
        except Exception as e:
            log.debug(f"Failed to load icon from file: {e}")
        return None
    
    def _get_icon_image(self) -> Image.Image:
        """Get the icon image, trying file first, then creating a default one"""
        # Try to load from icon.ico file first
        icon_image = self._load_icon_from_file()
        if icon_image:
            return icon_image
        
        # Fallback to created icon
        return self._create_icon_image()
    
    def _add_orange_dot(self, base_image: Image.Image) -> Image.Image:
        """Add an orange dot to the icon to indicate downloading"""
        # Create a copy to avoid modifying the original
        image = base_image.copy()
        draw = ImageDraw.Draw(image)
        
        # Draw orange dot in bottom-left corner (bigger size)
        dot_size = TRAY_ICON_DOT_SIZE
        x = 4
        y = image.height - dot_size - 4
        
        # Draw the dot with a black border and orange fill
        # First draw black border (scaled 2x)
        draw.ellipse([x-2, y-2, x + dot_size + 2, y + dot_size + 2], 
                    fill=(0, 0, 0, 255),  # Black border
                    outline=None)
        
        # Then draw the orange dot on top
        draw.ellipse([x, y, x + dot_size, y + dot_size], 
                    fill=(255, 140, 0, 255),  # Orange
                    outline=None)
        
        return image
    
    def _add_green_checkmark(self, base_image: Image.Image) -> Image.Image:
        """Add a green circle with white checkmark to the icon"""
        # Create a copy to avoid modifying the original
        image = base_image.copy()
        draw = ImageDraw.Draw(image)
        
        # Draw green circle in bottom-left corner (same size as orange dot)
        dot_size = TRAY_ICON_DOT_SIZE
        x = 4
        y = image.height - dot_size - 4
        
        # Draw the circle with a black border and green fill
        # First draw black border (scaled 2x)
        draw.ellipse([x-2, y-2, x + dot_size + 2, y + dot_size + 2], 
                    fill=(0, 0, 0, 255),  # Black border
                    outline=None)
        
        # Then draw the green circle on top
        draw.ellipse([x, y, x + dot_size, y + dot_size], 
                    fill=(34, 197, 94, 255),  # Green (modern green color)
                    outline=None)
        
        # Draw a white checkmark inside the circle
        # Calculate checkmark coordinates (scaled to fit inside the circle)
        center_x = x + dot_size // 2
        center_y = y + dot_size // 2
        
        # Checkmark path: short line going down-right, then longer line going up-right
        check_scale = dot_size / TRAY_ICON_CHECK_SCALE_DIVISOR  # Scale factor based on dot size
        
        # Start point (left side of checkmark)
        x1 = center_x - int(5 * check_scale)
        y1 = center_y + int(1 * check_scale)
        
        # Middle point (bottom of checkmark)
        x2 = center_x - int(1 * check_scale)
        y2 = center_y + int(5 * check_scale)
        
        # End point (top-right of checkmark)
        x3 = center_x + int(6 * check_scale)
        y3 = center_y - int(4 * check_scale)
        
        # Draw the checkmark with thick white lines
        line_width = max(2, int(3 * check_scale))
        draw.line([x1, y1, x2, y2], fill=(255, 255, 255, 255), width=line_width)
        draw.line([x2, y2, x3, y3], fill=(255, 255, 255, 255), width=line_width)
        
        return image
    
    def _on_quit(self, icon, item):
        """Handle quit menu item click"""
        log.info("Quit requested from system tray")
        try:
            # Set stop event immediately to signal shutdown
            self._stop_event.set()
            
            # Call the quit callback (sets state.stop = True)
            if self.quit_callback:
                self.quit_callback()
        except SystemExit:
            # Handle sys.exit() calls gracefully
            log.info("System exit requested from quit callback")
        except Exception as e:
            log.error(f"Error in quit callback: {e}")
        finally:
            # Stop the tray icon (this will hide it from system tray)
            try:
                icon.stop()
                log.debug("Tray icon stopped from quit handler")
            except Exception as e:
                log.debug(f"Error stopping tray icon: {e}")
    
    def _on_icon_click(self, icon, item):
        """Handle left click on tray icon - do nothing"""
        # Left click does nothing, only right click shows menu
        pass
    
    def _on_enable_autostart(self, icon, item):
        """Handle enable auto-start menu item click"""
        log.info("Enable auto-start requested from system tray")
        try:
            from utils.admin_utils import (
                is_admin, register_autostart, show_autostart_success_dialog,
                show_message_box_threaded
            )
            
            if not is_admin():
                # Show error message using threaded message box
                show_message_box_threaded(
                    "Administrator privileges are required to register auto-start.\n\n"
                    "SkinCloner is already running as Administrator, but something went wrong.\n\n"
                    "Please try restarting the application.",
                    "Admin Rights Required",
                    0x10  # MB_ICONERROR
                )
                return
            
            success, message = register_autostart()
            
            if success:
                log.info(f"Auto-start registered: {message}")
                show_autostart_success_dialog()
                # Update menu to show new status
                if self.icon:
                    self.icon.menu = self._create_menu()
            else:
                log.error(f"Failed to register auto-start: {message}")
                show_message_box_threaded(
                    f"Failed to register auto-start:\n\n{message}",
                    "Auto-Start Registration Failed",
                    0x10  # MB_ICONERROR
                )
        except Exception as e:
            log.error(f"Error enabling auto-start: {e}")
            from utils.admin_utils import show_message_box_threaded
            show_message_box_threaded(
                f"An error occurred:\n\n{e}",
                "Error",
                0x10  # MB_ICONERROR
            )
    
    def _on_disable_autostart(self, icon, item):
        """Handle disable auto-start menu item click"""
        log.info("Disable auto-start requested from system tray")
        try:
            from utils.admin_utils import (
                is_admin, unregister_autostart, show_autostart_removed_dialog,
                show_message_box_threaded
            )
            
            if not is_admin():
                # Show error message using threaded message box
                show_message_box_threaded(
                    "Administrator privileges are required to unregister auto-start.\n\n"
                    "SkinCloner is already running as Administrator, but something went wrong.\n\n"
                    "Please try restarting the application.",
                    "Admin Rights Required",
                    0x10  # MB_ICONERROR
                )
                return
            
            success, message = unregister_autostart()
            
            if success:
                log.info(f"Auto-start unregistered: {message}")
                show_autostart_removed_dialog()
                # Update menu to show new status
                if self.icon:
                    self.icon.menu = self._create_menu()
            else:
                log.error(f"Failed to unregister auto-start: {message}")
                show_message_box_threaded(
                    f"Failed to unregister auto-start:\n\n{message}",
                    "Auto-Start Removal Failed",
                    0x10  # MB_ICONERROR
                )
        except Exception as e:
            log.error(f"Error disabling auto-start: {e}")
            from utils.admin_utils import show_message_box_threaded
            show_message_box_threaded(
                f"An error occurred:\n\n{e}",
                "Error",
                0x10  # MB_ICONERROR
            )
    
    def _create_menu(self) -> pystray.Menu:
        """Create the context menu for the tray icon"""
        try:
            from utils.admin_utils import is_registered_for_autostart
            is_autostart_enabled = is_registered_for_autostart()
        except Exception:
            is_autostart_enabled = False
        
        if is_autostart_enabled:
            autostart_item = pystray.MenuItem("Remove Auto-Start", self._on_disable_autostart)
        else:
            autostart_item = pystray.MenuItem("Enable Auto-Start", self._on_enable_autostart)
        
        return pystray.Menu(
            pystray.MenuItem("SkinCloner", None, enabled=False),
            pystray.Menu.SEPARATOR,
            autostart_item,
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on_quit)
        )
    
    def _run_tray(self):
        """Run the tray icon in a separate thread"""
        try:
            # Store base icon for later use
            self._base_icon_image = self._get_icon_image()
            icon_image = self._base_icon_image
            menu = self._create_menu()
            
            self.icon = pystray.Icon(
                "SkinCloner",
                icon_image,
                "SkinCloner",
                menu,
                default_action=self._on_icon_click
            )
            
            log.info("System tray icon started")
            # Use run_detached to prevent blocking the main thread
            self.icon.run_detached()
        except Exception as e:
            log.error(f"Failed to start system tray: {e}")
    
    def start(self):
        """Start the system tray icon"""
        if self.tray_thread and self.tray_thread.is_alive():
            log.warning("System tray is already running")
            return
        
        try:
            self.tray_thread = threading.Thread(target=self._run_tray, daemon=True)
            self.tray_thread.start()
            log.info("System tray manager started - no console window")
        except Exception as e:
            log.error(f"Failed to start system tray manager: {e}")
    
    def stop(self):
        """Stop the system tray icon"""
        if self.icon:
            try:
                self.icon.stop()
                log.info("System tray icon stopped")
            except Exception as e:
                log.error(f"Failed to stop system tray icon: {e}")
        
        if self.tray_thread and self.tray_thread.is_alive():
            self.tray_thread.join(timeout=TRAY_THREAD_JOIN_TIMEOUT_S)
    
    def is_running(self) -> bool:
        """Check if the tray icon is running"""
        return self.icon is not None and self.tray_thread is not None and self.tray_thread.is_alive()
    
    def wait_for_quit(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for quit signal from tray
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if quit was requested, False if timeout
        """
        return self._stop_event.wait(timeout)
    
    def set_downloading(self, is_downloading: bool):
        """
        Update the tray icon to show downloading status
        
        Args:
            is_downloading: True to show orange dot, False to show green checkmark icon
        """
        # Wait for tray icon to be ready (up to 5 seconds)
        max_wait = TRAY_READY_MAX_WAIT_S
        wait_interval = TRAY_READY_CHECK_INTERVAL_S
        elapsed = 0.0
        
        while (not self.icon or not self._base_icon_image) and elapsed < max_wait:
            threading.Event().wait(wait_interval)
            elapsed += wait_interval
        
        if not self.icon or not self._base_icon_image:
            log.warning(f"Tray icon not ready, cannot set downloading status to {is_downloading}")
            return
        
        try:
            self._is_downloading = is_downloading
            
            if is_downloading:
                # Show icon with orange dot
                new_icon = self._add_orange_dot(self._base_icon_image)
                self.icon.icon = new_icon
                log.info("Orange icon on")
            else:
                # Show green checkmark icon
                new_icon = self._add_green_checkmark(self._base_icon_image)
                self.icon.icon = new_icon
                log.info("Orange icon off - showing green checkmark")
        except Exception as e:
            log.error(f"Failed to update tray icon: {e}")
