#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The running processes, from one Windows snapshot

psutil.process_iter opens every process on each call: 160 ms a scan with 255
processes, seconds under load. That is too slow for the scans Rose repeats
while a game runs. The snapshot opens none of them.
"""

import ctypes
from ctypes import wintypes
from typing import List, Tuple

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_NO_MORE_FILES = 18


class _ProcessEntry(ctypes.Structure):
    """PROCESSENTRY32W"""
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
for _name in ("Process32FirstW", "Process32NextW"):
    _function = getattr(_kernel32, _name)
    _function.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
    _function.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


def running_processes() -> List[Tuple[int, str]]:
    """(PID, executable name) of every running process.

    Raises OSError when Windows gives no complete list.
    """
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        processes = []
        more = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            processes.append((entry.th32ProcessID, entry.szExeFile))
            more = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != ERROR_NO_MORE_FILES:
            raise ctypes.WinError(ctypes.get_last_error())
        return processes
    finally:
        _kernel32.CloseHandle(snapshot)
