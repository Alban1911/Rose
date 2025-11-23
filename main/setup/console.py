#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Console setup for Windows
Handles DPI awareness, console allocation, and buffer management
"""

import ctypes
import os
import sys
import threading
import time

from config import WINDOWS_DPI_AWARENESS_SYSTEM, CONSOLE_BUFFER_CLEAR_INTERVAL_S


def setup_console() -> None:
    """Setup console for Windows (DPI awareness, allocation, buffer)"""
    if sys.platform != "win32":
        return
    
    try:
        # Set DPI awareness to SYSTEM_AWARE before any GUI operations
        # This prevents Qt from trying to change it later (which causes "Access denied")
        # PROCESS_SYSTEM_DPI_AWARE
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(WINDOWS_DPI_AWARENESS_SYSTEM)
        except (OSError, AttributeError) as e:
            try:
                # Fallback for older Windows versions
                ctypes.windll.user32.SetProcessDPIAware()
            except (OSError, AttributeError) as e2:
                # If both fail, continue anyway - not critical
                pass
        
        # Check if we're in windowed mode (no console attached)
        console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not console_hwnd:
            # Allocate a console for the process to prevent blocking operations
            ctypes.windll.kernel32.AllocConsole()
            # Hide the console window immediately
            console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if console_hwnd:
                ctypes.windll.user32.ShowWindow(console_hwnd, 0)  # SW_HIDE = 0
        
        # Increase console buffer size to prevent blocking (Windows-specific fix)
        # This prevents the console output buffer from filling up and causing writes to block
        try:
            # Get stdout handle
            STD_OUTPUT_HANDLE = -11
            STD_ERROR_HANDLE = -12
            stdout_handle = ctypes.windll.kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            stderr_handle = ctypes.windll.kernel32.GetStdHandle(STD_ERROR_HANDLE)
            
            # Define COORD structure for buffer size
            class COORD(ctypes.Structure):
                _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]
            
            # Set large screen buffer (10000 lines x 200 columns = 2MB buffer)
            # This gives plenty of room for logs without blocking
            new_size = COORD(200, 10000)
            
            # Set buffer size for both stdout and stderr
            ctypes.windll.kernel32.SetConsoleScreenBufferSize(stdout_handle, new_size)
            ctypes.windll.kernel32.SetConsoleScreenBufferSize(stderr_handle, new_size)
        except (OSError, AttributeError):
            # Failed to increase buffer size - not critical, will rely on queue-based logging
            pass
    except (OSError, AttributeError):
        # If console allocation fails, continue with original approach
        pass


def redirect_none_streams() -> None:
    """Redirect None streams to devnull to prevent blocking"""
    if sys.stdin is None:
        sys.stdin = open(os.devnull, 'r', encoding='utf-8')
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w', encoding='utf-8')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w', encoding='utf-8')


def start_console_buffer_manager() -> None:
    """Start background thread to prevent console buffer from blocking"""
    if sys.platform != "win32":
        return
    
    def _console_buffer_manager():
        """
        Background thread to prevent console buffer from blocking
        
        Windows hidden console buffers can fill up and cause writes to block.
        This thread periodically:
        1. Clears the input buffer to prevent buildup
        2. Flushes stdout/stderr to prevent output buffer blocking
        3. Reads from console output buffer to keep it empty
        4. Handles any pending console events
        """
        try:
            import msvcrt
            
            # Get console output handle for buffer manipulation
            try:
                STD_OUTPUT_HANDLE = -11
                stdout_handle = ctypes.windll.kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
                has_console_handle = stdout_handle and stdout_handle != -1
            except (OSError, AttributeError):
                has_console_handle = False
            
            while True:
                time.sleep(CONSOLE_BUFFER_CLEAR_INTERVAL_S)
                
                # Clear any pending console input
                try:
                    while msvcrt.kbhit():
                        msvcrt.getch()
                except (OSError, IOError):
                    pass
                
                # Flush output streams to prevent buffer blocking
                try:
                    if sys.stdout and hasattr(sys.stdout, 'flush'):
                        sys.stdout.flush()
                except (OSError, ValueError, IOError):
                    pass  # Stream is closed or invalid
                
                try:
                    if sys.stderr and hasattr(sys.stderr, 'flush'):
                        sys.stderr.flush()
                except (OSError, ValueError, IOError):
                    pass  # Stream is closed or invalid
                
                # Try to read console buffer info to keep it from filling
                # This is a Windows API call that can help prevent buffer overflow
                if has_console_handle:
                    try:
                        # Define CONSOLE_SCREEN_BUFFER_INFO structure
                        class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
                            _fields_ = [
                                ("dwSize", ctypes.c_uint),
                                ("dwCursorPosition", ctypes.c_uint),
                                ("wAttributes", ctypes.c_ushort),
                                ("srWindow", ctypes.c_uint * 4),
                                ("dwMaximumWindowSize", ctypes.c_uint),
                            ]
                        
                        csbi = CONSOLE_SCREEN_BUFFER_INFO()
                        # Just reading the buffer info can help prevent some blocking scenarios
                        ctypes.windll.kernel32.GetConsoleScreenBufferInfo(stdout_handle, ctypes.byref(csbi))
                    except (OSError, AttributeError):
                        pass  # API call failed, not critical
                    
        except (ImportError, OSError):
            pass  # Thread will exit silently if it fails
    
    _console_thread = threading.Thread(target=_console_buffer_manager, daemon=True, name="ConsoleBufferManager")
    _console_thread.start()


def cleanup_console() -> None:
    """Clean up console if we allocated one"""
    if sys.platform == "win32":
        try:
            console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if console_hwnd:
                # Free the console
                ctypes.windll.kernel32.FreeConsole()
        except (OSError, AttributeError) as e:
            # Logging might not be available at this point
            pass

