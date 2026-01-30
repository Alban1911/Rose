#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Signal handlers for graceful shutdown
"""

import os
import signal
import sys

import utils.integration.pengu_loader as pengu_loader

from .state import get_app_state


def signal_handler(signum, frame):
    """Handle system signals for graceful shutdown"""
    app_state = get_app_state()
    if app_state.shutting_down:
        return  # Prevent multiple shutdown attempts
    app_state.shutting_down = True
    
    print(f"\nReceived signal {signum}, initiating graceful shutdown...")
    try:
        pengu_loader.deactivate_on_exit()
    except Exception:
        pass
    # Force exit if we're stuck
    os._exit(0)


def force_quit_handler():
    """Force quit handler that can be called from anywhere"""
    app_state = get_app_state()
    if app_state.shutting_down:
        return
    app_state.shutting_down = True
    
    print("\nForce quit initiated...")
    try:
        pengu_loader.deactivate_on_exit()
    except Exception:
        pass
    os._exit(0)


def _start_shutdown_watcher() -> None:
    """Spawn a hidden top-level window that deactivates Pengu on WM_ENDSESSION.

    Windows delivers WM_QUERYENDSESSION / WM_ENDSESSION to every top-level
    window when the session is ending (logoff, restart, shutdown).  This is
    the only reliable way to run cleanup in a tray / GUI application —
    SetConsoleCtrlHandler is not guaranteed to fire.

    The window and its message pump live on a daemon thread so they don't
    block normal shutdown through Python's exit machinery.
    """
    import ctypes
    from ctypes import wintypes
    import threading

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    WM_QUERYENDSESSION = 0x0011
    WM_ENDSESSION = 0x0016

    # -- Minimal type scaffolding ------------------------------------------------
    pointer_size = ctypes.sizeof(ctypes.c_void_p)
    LRESULT = (
        getattr(wintypes, "LRESULT", None)
        or (ctypes.c_longlong if pointer_size == 8 else ctypes.c_long)
    )
    WPARAM = getattr(wintypes, "WPARAM", ctypes.c_ulonglong if pointer_size == 8 else ctypes.c_ulong)
    LPARAM = getattr(wintypes, "LPARAM", ctypes.c_longlong if pointer_size == 8 else ctypes.c_long)

    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)

    HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
    HICON = getattr(wintypes, "HICON", wintypes.HANDLE)
    HBRUSH = getattr(wintypes, "HBRUSH", wintypes.HANDLE)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", HICON),
            ("hCursor", HCURSOR),
            ("hbrBackground", HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", HICON),
        ]

    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
    user32.DefWindowProcW.restype = LRESULT

    # -- Window procedure --------------------------------------------------------
    @WNDPROC
    def _wnd_proc(hwnd, msg, wparam, lparam):
        if msg == WM_QUERYENDSESSION:
            return 1  # agree to end the session
        if msg == WM_ENDSESSION:
            if wparam:  # session is actually ending
                app_state = get_app_state()
                if not app_state.shutting_down:
                    app_state.shutting_down = True
                    try:
                        pengu_loader.deactivate_on_exit()
                    except Exception:
                        pass
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # prevent GC of the callback
    _start_shutdown_watcher._prevent_gc = _wnd_proc  # type: ignore[attr-defined]

    # -- Thread body -------------------------------------------------------------
    def _run() -> None:
        class_name = "RoseShutdownWatcher"
        h_instance = kernel32.GetModuleHandleW(None)

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = _wnd_proc
        wc.hInstance = h_instance
        wc.lpszClassName = class_name

        if not user32.RegisterClassExW(ctypes.byref(wc)):
            return

        # Create a regular (non-message-only) top-level window so it receives
        # broadcast messages like WM_QUERYENDSESSION.  It is never shown.
        hwnd = user32.CreateWindowExW(
            0,             # no extended style
            class_name,
            "Rose Shutdown Watcher",
            0,             # no visible style flags
            0, 0, 0, 0,   # position / size irrelevant
            None,          # no parent → top-level
            None,
            h_instance,
            None,
        )
        if not hwnd:
            return

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    t = threading.Thread(target=_run, name="ShutdownWatcher", daemon=True)
    t.start()


def setup_signal_handlers() -> None:
    """Set up signal handlers"""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # On Windows, create a hidden top-level window whose sole purpose is to
    # receive WM_QUERYENDSESSION / WM_ENDSESSION when the user logs off or
    # shuts down the PC.  SetConsoleCtrlHandler does NOT reliably fire for
    # tray / GUI applications, but WM_ENDSESSION is always delivered to
    # top-level windows.
    if sys.platform == "win32":
        _start_shutdown_watcher()

