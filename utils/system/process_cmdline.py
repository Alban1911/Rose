#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Read another process' command line with a query-only handle.

psutil.Process.cmdline() first opens the process with
PROCESS_QUERY_INFORMATION | PROCESS_VM_READ and reads the command line out of
its PEB. Anti-cheat handle callbacks (Vanguard) strip PROCESS_VM_READ from
handles to League processes and log the attempt. This module asks only for
PROCESS_QUERY_LIMITED_INFORMATION and uses
NtQueryInformationProcess(ProcessCommandLineInformation), which needs no
memory access (Windows 8.1+).
"""

import ctypes
import os
from ctypes import wintypes
from typing import List, Optional

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_COMMAND_LINE_INFORMATION = 60
_MAX_ATTEMPTS = 3

_api = None


class _UnicodeString(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", ctypes.c_void_p),
    ]


def _load_api():
    global _api
    if _api is not None:
        return _api

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    ntdll.NtQueryInformationProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG),
    ]
    ntdll.NtQueryInformationProcess.restype = ctypes.c_long  # NTSTATUS, signed

    shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)

    _api = (kernel32, ntdll, shell32)
    return _api


def _split_command_line(text: str) -> List[str]:
    """Split like psutil's use_peb=False path (CommandLineToArgvW)."""
    if not text:
        return []
    kernel32, _, shell32 = _load_api()
    argc = ctypes.c_int(0)
    argv = shell32.CommandLineToArgvW(text, ctypes.byref(argc))
    if not argv:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return [argv[i] for i in range(argc.value)]
    finally:
        kernel32.LocalFree(argv)


def _read_command_line(handle) -> Optional[str]:
    _, ntdll, _ = _load_api()
    size = wintypes.ULONG(0)
    # First call reports the needed size (STATUS_INFO_LENGTH_MISMATCH).
    ntdll.NtQueryInformationProcess(
        handle, _PROCESS_COMMAND_LINE_INFORMATION, None, 0, ctypes.byref(size)
    )
    for _ in range(_MAX_ATTEMPTS):
        if size.value < ctypes.sizeof(_UnicodeString):
            return None
        buffer = ctypes.create_string_buffer(size.value)
        status = ntdll.NtQueryInformationProcess(
            handle, _PROCESS_COMMAND_LINE_INFORMATION, buffer, size, ctypes.byref(size)
        )
        if status >= 0:
            string = _UnicodeString.from_buffer(buffer)
            if not string.Buffer or not string.Length:
                return ""
            return ctypes.wstring_at(string.Buffer, string.Length // 2)
        # Size grew between calls: retry with the size just reported.
    return None


def query_cmdline(pid: int) -> Optional[List[str]]:
    """Return *pid*'s argv, or None if it cannot be read.

    Never requests PROCESS_VM_READ. Returns None on non-Windows systems.
    """
    if os.name != "nt" or pid <= 0:
        return None
    kernel32, _, _ = _load_api()
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        text = _read_command_line(handle)
    finally:
        kernel32.CloseHandle(handle)
    if text is None:
        return None
    return _split_command_line(text)
