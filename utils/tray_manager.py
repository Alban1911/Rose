#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System tray manager for SkinCloner
"""

import os
import sys
import threading
import ctypes
from ctypes import wintypes
from typing import Optional, Callable
import pystray
from PIL import Image, ImageDraw
from utils.logging import get_logger

log = get_logger()


class TrayManager:
    """Manages the system tray icon for SkinCloner"""
    
    def __init__(self, quit_callback: Optional[Callable] = None, toggle_terminal_callback: Optional[Callable] = None):
        """
        Initialize the tray manager
        
        Args:
            quit_callback: Function to call when user clicks "Quit"
            toggle_terminal_callback: Function to call when user clicks "Toggle Terminal"
        """
        self.quit_callback = quit_callback
        self.toggle_terminal_callback = toggle_terminal_callback
        self.icon = None
        self.tray_thread = None
        self._stop_event = threading.Event()
        self._terminal_visible = False  # Track terminal visibility state
        self._console_ctrl_handler = None  # Store console control handler
        
    def _create_icon_image(self) -> Image.Image:
        """Create a simple icon image for the tray"""
        # Create a 64x64 icon with a simple design
        width, height = 64, 64
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # Draw a simple "SC" logo (SkinCloner)
        # Background circle
        draw.ellipse([8, 8, 56, 56], fill=(0, 100, 200, 255), outline=(0, 50, 100, 255), width=2)
        
        # "SC" text
        try:
            # Try to use a font if available
            from PIL import ImageFont
            font = ImageFont.truetype("arial.ttf", 20)
        except:
            # Fallback to default font
            font = ImageFont.load_default()
        
        # Draw "SC" text
        draw.text((18, 22), "SC", fill=(255, 255, 255, 255), font=font)
        
        return image
    
    def _load_icon_from_file(self) -> Optional[Image.Image]:
        """Try to load icon from icon.ico file"""
        try:
            icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icon.ico")
            if os.path.exists(icon_path):
                # Convert ICO to PNG for pystray
                with Image.open(icon_path) as img:
                    # Convert to RGBA and resize to 64x64
                    img = img.convert('RGBA')
                    img = img.resize((64, 64), Image.Resampling.LANCZOS)
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
    
    def _create_terminal_window(self):
        """Create a new terminal window for logging"""
        try:
            if sys.platform == "win32":
                # Check if console already exists (allocated at startup)
                console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                if not console_hwnd:
                    # Create a new console window
                    ctypes.windll.kernel32.AllocConsole()
                    console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                
                # Set up console window to hide instead of close
                self._setup_console_close_handler()
                
                # Redirect stdout and stderr to the console
                import msvcrt
                import os
                
                # Get handles for the console
                stdout_handle = ctypes.windll.kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
                stderr_handle = ctypes.windll.kernel32.GetStdHandle(-12)  # STD_ERROR_HANDLE
                
                # Create file objects for stdout and stderr
                stdout_fd = msvcrt.open_osfhandle(stdout_handle, os.O_WRONLY | os.O_TEXT)
                stderr_fd = msvcrt.open_osfhandle(stderr_handle, os.O_WRONLY | os.O_TEXT)
                
                # Replace stdout and stderr
                sys.stdout = os.fdopen(stdout_fd, 'w')
                sys.stderr = os.fdopen(stderr_fd, 'w')
                
                # Set console title
                ctypes.windll.kernel32.SetConsoleTitleW("SkinCloner - Log Terminal")
                
                # Reinitialize logging to use the new stdout/stderr
                from utils.logging import setup_logging
                setup_logging(True)  # Use verbose logging in terminal
                
                self._terminal_visible = True
                log.info("=" * 60)
                log.info("SkinCloner Terminal - Application Logs")
                log.info("=" * 60)
                log.info("Application is running in the background.")
                log.info("Close this window to hide logs (app continues running).")
                log.info("=" * 60)
                log.info("Terminal window shown and stdout/stderr redirected")
        except Exception as e:
            log.error(f"Failed to create terminal window: {e}")
    
    def _setup_console_close_handler(self):
        """Set up handler to prevent console window from closing the app"""
        try:
            if sys.platform == "win32":
                # Get the console window handle
                console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                if console_hwnd:
                    # Use SetConsoleCtrlHandler to intercept console close events
                    CTRL_CLOSE_EVENT = 2
                    
                    def console_ctrl_handler(ctrl_type):
                        if ctrl_type == CTRL_CLOSE_EVENT:
                            # Hide the console instead of closing
                            ctypes.windll.user32.ShowWindow(console_hwnd, 0)  # SW_HIDE = 0
                            self._terminal_visible = False
                            log.info("Terminal window hidden (close intercepted)")
                            return True  # Indicate we handled the event
                        return False  # Let other handlers process other events
                    
                    # Set up the console control handler
                    PHANDLER_ROUTINE = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
                    self._console_ctrl_handler = PHANDLER_ROUTINE(console_ctrl_handler)
                    
                    # Install the handler
                    result = ctypes.windll.kernel32.SetConsoleCtrlHandler(self._console_ctrl_handler, True)
                    if result:
                        log.info("Console close handler installed")
                    else:
                        log.warning("Failed to install console close handler")
        except Exception as e:
            log.error(f"Failed to setup console close handler: {e}")
    
    def _destroy_terminal_window(self):
        """Destroy the terminal window"""
        try:
            if sys.platform == "win32" and self._terminal_visible:
                # Remove console control handler if we installed one
                if hasattr(self, '_console_ctrl_handler'):
                    ctypes.windll.kernel32.SetConsoleCtrlHandler(self._console_ctrl_handler, False)
                
                # Free the console
                ctypes.windll.kernel32.FreeConsole()
                self._terminal_visible = False
                log.info("Terminal window destroyed")
        except Exception as e:
            log.error(f"Failed to destroy terminal window: {e}")
    
    def _on_toggle_terminal(self, icon, item):
        """Handle toggle terminal menu item click"""
        try:
            if self.toggle_terminal_callback:
                self.toggle_terminal_callback()
            else:
                # Default behavior - toggle terminal window
                if self._terminal_visible:
                    # Check if console window is still visible
                    console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                    if console_hwnd and ctypes.windll.user32.IsWindowVisible(console_hwnd):
                        # Hide the console window
                        ctypes.windll.user32.ShowWindow(console_hwnd, 0)  # SW_HIDE = 0
                        self._terminal_visible = False
                        log.info("Terminal window hidden")
                    else:
                        # Console was already closed/hidden, just update state
                        self._terminal_visible = False
                        log.info("Terminal window was already hidden")
                else:
                    self._create_terminal_window()
        except Exception as e:
            log.error(f"Error in toggle terminal callback: {e}")
    
    def _on_quit(self, icon, item):
        """Handle quit menu item click"""
        log.info("Quit requested from system tray")
        try:
            if self.quit_callback:
                self.quit_callback()
            else:
                # Default behavior - set stop event
                self._stop_event.set()
        except SystemExit:
            # Handle sys.exit() calls gracefully
            log.info("System exit requested from quit callback")
            self._stop_event.set()
        except Exception as e:
            log.error(f"Error in quit callback: {e}")
            self._stop_event.set()
        finally:
            icon.stop()
    
    def _create_menu(self) -> pystray.Menu:
        """Create the context menu for the tray icon"""
        return pystray.Menu(
            pystray.MenuItem("SkinCloner", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Toggle Terminal", self._on_toggle_terminal),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on_quit, default=True)
        )
    
    def _run_tray(self):
        """Run the tray icon in a separate thread"""
        try:
            icon_image = self._get_icon_image()
            menu = self._create_menu()
            
            self.icon = pystray.Icon(
                "SkinCloner",
                icon_image,
                "SkinC",
                menu
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
            self.tray_thread.join(timeout=2.0)
    
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
