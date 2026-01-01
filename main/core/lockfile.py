#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lock file management for single instance enforcement
"""

import atexit
import ctypes
import os
import sys
import time
from pathlib import Path

from utils.core.logging import get_logger
from utils.core.paths import get_state_dir
from config import SINGLE_INSTANCE_MUTEX_NAME, LOCK_FILE_NAME

from .state import get_app_state

log = get_logger()

# Win32 constant
ERROR_ALREADY_EXISTS = 183


class LockFile:
    """Context manager for application lock file"""
    
    def __init__(self, lock_path: Path):
        self.path = lock_path
        self.file_handle = None
        self._acquired = False
        
    def __enter__(self):
        """Acquire lock file"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # Try to create lock file exclusively
            self.file_handle = open(self.path, 'x')
            self.file_handle.write(f"{os.getpid()}\n")
            self.file_handle.write(f"{time.time()}\n")
            self.file_handle.flush()
            self._acquired = True
            app_state = get_app_state()
            app_state.lock_file = self.file_handle
            app_state.lock_file_path = self.path
            return self
        except FileExistsError:
            # Check if stale lock
            if self._is_stale_lock():
                self.path.unlink()
                return self.__enter__()  # Retry
            raise RuntimeError("Another instance is already running")
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release lock file"""
        try:
            if self.file_handle:
                self.file_handle.close()
            if self.path.exists():
                self.path.unlink()
        except (IOError, OSError, PermissionError) as e:
            log.debug(f"Lock file cleanup error (non-critical): {e}")
        return False
    
    def _is_stale_lock(self) -> bool:
        """Check if lock file is from a dead process"""
        try:
            with open(self.path, 'r') as f:
                lines = f.readlines()
                if len(lines) >= 1:
                    old_pid = int(lines[0].strip())
                    # Check if process is still running
                    try:
                        import psutil
                        return not psutil.pid_exists(old_pid)
                    except ImportError:
                        # Fallback for Windows
                        try:
                            ctypes.windll.kernel32.OpenProcess(0x1000, False, old_pid)
                            return False  # Process exists
                        except OSError:
                            return True  # Process doesn't exist
        except (IOError, ValueError):
            return True  # Assume stale if can't read
        return False


def create_lock_file() -> bool:
    """Create a lock file to prevent multiple instances"""
    try:
        # Create a lock file in the state directory
        state_dir = get_state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        
        lock_file_path = state_dir / "rose.lock"
        app_state = get_app_state()
        app_state.lock_file_path = lock_file_path
        
        # Windows-only approach using file creation
        try:
            # Try to create the lock file exclusively
            app_state.lock_file = open(lock_file_path, 'x')
            app_state.lock_file.write(f"{os.getpid()}\n")
            app_state.lock_file.write(f"{time.time()}\n")
            app_state.lock_file.flush()
            
            # Register cleanup function
            atexit.register(cleanup_lock_file)
            
            return True
        except FileExistsError:
            # Lock file exists, check if process is still running
            try:
                with open(lock_file_path, 'r') as f:
                    lines = f.readlines()
                    if len(lines) >= 1:
                        old_pid = int(lines[0].strip())
                        # Check if process is still running (Windows)
                        try:
                            import psutil
                            if psutil.pid_exists(old_pid):
                                return False  # Another instance is running
                        except ImportError:
                            # Fallback: try to check if process exists
                            try:
                                ctypes.windll.kernel32.OpenProcess(0x1000, False, old_pid)  # PROCESS_QUERY_LIMITED_INFORMATION
                                return False  # Process exists
                            except OSError:
                                # Process doesn't exist, we can proceed
                                log.debug(f"Old process {old_pid} no longer exists")
                    
                    # Old lock file is stale, remove it
                    os.remove(lock_file_path)
                    
                    # Try again
                    app_state.lock_file = open(lock_file_path, 'x')
                    app_state.lock_file.write(f"{os.getpid()}\n")
                    app_state.lock_file.write(f"{time.time()}\n")
                    app_state.lock_file.flush()
                    atexit.register(cleanup_lock_file)
                    return True
                    
            except (IOError, ValueError) as e:
                # If we can't read the lock file, assume it's stale
                log.debug(f"Lock file read error: {e}, assuming stale")
                try:
                    os.remove(lock_file_path)
                    app_state.lock_file = open(lock_file_path, 'x')
                    app_state.lock_file.write(f"{os.getpid()}\n")
                    app_state.lock_file.write(f"{time.time()}\n")
                    app_state.lock_file.flush()
                    atexit.register(cleanup_lock_file)
                    return True
                except (IOError, OSError) as cleanup_error:
                    log.error(f"Failed to create lock file after cleanup: {cleanup_error}")
                    return False
                
    except (IOError, OSError, PermissionError) as e:
        log.error(f"Failed to create lock file: {e}")
        return False


def create_single_instance_mutex() -> bool:
    """Create a Windows named mutex (kernel-managed) to enforce single instance."""
    if sys.platform != "win32":
        return True

    app_state = get_app_state()

    try:
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX_NAME)
        if not handle:
            log.error("CreateMutexW failed; falling back to lock file.")
            return True  # allow fallback path to decide

        last_error = ctypes.windll.kernel32.GetLastError()
        if last_error == ERROR_ALREADY_EXISTS:
            # Another instance already created it
            ctypes.windll.kernel32.CloseHandle(handle)
            return False

        # Keep handle alive for process lifetime
        app_state.mutex_handle = handle

        # Optional: clean up old stale lock file left from previous versions
        try:
            stale_lock_path = get_state_dir() / LOCK_FILE_NAME
            if stale_lock_path.exists():
                stale_lock_path.unlink()
        except Exception:
            pass

        atexit.register(cleanup_lock_file)  # reuse existing cleanup hook
        return True
    except Exception as e:
        log.error(f"Failed to create mutex: {e}; falling back to lock file.")
        return True


def cleanup_lock_file() -> None:
    """Clean up the lock file (and now also the mutex handle)."""
    try:
        app_state = get_app_state()

        # release mutex handle if we own it
        if sys.platform == "win32" and app_state.mutex_handle:
            try:
                ctypes.windll.kernel32.CloseHandle(app_state.mutex_handle)
            except Exception:
                pass
            app_state.mutex_handle = None

        if app_state.lock_file:
            app_state.lock_file.close()
            app_state.lock_file = None

        # Remove the lock file
        if app_state.lock_file_path and app_state.lock_file_path.exists():
            app_state.lock_file_path.unlink()
    except (IOError, OSError, PermissionError) as e:
        log.debug(f"Lock file cleanup error (non-critical): {e}")


def check_single_instance() -> None:
    """Check if another instance is already running"""

    # Prefer OS mutex on Windows
    if sys.platform == "win32":
        if not create_single_instance_mutex():
            try:
                ctypes.windll.user32.MessageBoxW(
                    0,
                    "Another instance of Rose is already running!\n\nPlease close the existing instance before starting a new one.",
                    "Rose - Instance Already Running",
                    0x50010,
                )
            except Exception:
                log.error("Another instance of Rose is already running!")
            sys.exit(1)
        return

    # Existing behavior for non-Windows
    if not create_lock_file():
        # Show error message using Windows MessageBox since console might not be visible
        if sys.platform == "win32":
            try:
                # MB_OK (0x0) + MB_ICONERROR (0x10) + MB_SETFOREGROUND (0x10000) + MB_TOPMOST (0x40000)
                # = 0x50010 - Ensures dialog appears on top and gets focus
                ctypes.windll.user32.MessageBoxW(
                    0, 
                    "Another instance of Rose is already running!\n\nPlease close the existing instance before starting a new one.",
                    "Rose - Instance Already Running",
                    0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                )
            except (OSError, AttributeError) as e:
                # Fallback to logging if MessageBox fails
                log.error(f"Failed to show message box: {e}")
                log.error("Another instance of Rose is already running!")
                log.error("Please close the existing instance before starting a new one.")
        else:
            log.error("Another instance of Rose is already running!")
            log.error("Please close the existing instance before starting a new one.")
        sys.exit(1)

