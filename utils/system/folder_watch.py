"""Block until a file is created or written in some folders.

A Windows change notification: nothing runs while the folders stay quiet,
where looking again on a timer would wake every few seconds for hours.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Iterable, Optional

from utils.core.logging import get_logger

log = get_logger()

CHANGED = "changed"  # a file in a folder was created, renamed, deleted or written
READY = "ready"      # the check made once the folders were watched passed
WOKEN = "woken"      # wake() was called
TIMEOUT = "timeout"

_FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
_FILE_NOTIFY_CHANGE_LAST_WRITE = 0x00000010
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class FolderWatch:
    """Waits for a change directly in one of the folders (not their subfolders),
    a wake() from another thread, or the timeout."""

    def __init__(self) -> None:
        self._kernel = None
        self._wake = None
        if os.name != "nt":
            return
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateEventW.restype = wintypes.HANDLE
        kernel.SetEvent.argtypes = [wintypes.HANDLE]
        kernel.SetEvent.restype = wintypes.BOOL
        kernel.FindFirstChangeNotificationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
        kernel.FindFirstChangeNotificationW.restype = wintypes.HANDLE
        kernel.FindCloseChangeNotification.argtypes = [wintypes.HANDLE]
        kernel.FindCloseChangeNotification.restype = wintypes.BOOL
        kernel.WaitForMultipleObjects.argtypes = [
            wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD,
        ]
        kernel.WaitForMultipleObjects.restype = wintypes.DWORD
        # Manual reset: once woken (Rose stops), every later wait returns at once
        wake = kernel.CreateEventW(None, True, False, None)
        if wake:
            self._kernel, self._wake = kernel, wake

    def wake(self) -> None:
        """End the current wait and every later one."""
        if self._kernel is not None:
            self._kernel.SetEvent(self._wake)

    def wait(self, folders: Iterable[Path], timeout_s: float,
             ready: Optional[Callable[[], bool]] = None) -> Optional[str]:
        """Wait for a change in *folders*; None when none of them can be watched.

        *ready* is called once the folders are watched, before waiting: what
        changed between the caller's last look and the watch sends no
        notification, so it is looked at there. True ends the wait (READY).
        """
        if self._kernel is None:
            return None
        kernel = self._kernel
        handles = []
        try:
            for folder in folders:
                handle = kernel.FindFirstChangeNotificationW(
                    str(folder), False, _FILE_NOTIFY_CHANGE_FILE_NAME | _FILE_NOTIFY_CHANGE_LAST_WRITE,
                )
                if handle and handle != _INVALID_HANDLE_VALUE:
                    handles.append(handle)
                else:
                    log.debug(f"[WATCH] Cannot watch {folder} (error {ctypes.get_last_error()})")
            if not handles:
                return None
            if ready is not None and ready():
                return READY
            objects = (wintypes.HANDLE * (len(handles) + 1))(self._wake, *handles)
            result = kernel.WaitForMultipleObjects(len(objects), objects, False, max(0, int(timeout_s * 1000)))
            if result == _WAIT_OBJECT_0:
                return WOKEN
            if _WAIT_OBJECT_0 < result < _WAIT_OBJECT_0 + len(objects):
                return CHANGED
            if result == _WAIT_TIMEOUT:
                return TIMEOUT
            log.debug(f"[WATCH] Wait failed (error {ctypes.get_last_error()})")
            return None
        finally:
            for handle in handles:
                kernel.FindCloseChangeNotification(handle)
