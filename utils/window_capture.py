#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Window capture utilities for Windows
"""

import os
import ctypes
from ctypes import wintypes
from typing import Optional, Tuple


def is_windows() -> bool:
    """Check if running on Windows"""
    return os.name == "nt"


if is_windows():
    user32 = ctypes.windll.user32
    try: 
        user32.SetProcessDPIAware()
    except Exception: 
        pass
    
    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.POINTER(ctypes.c_int))
    GetWindowTextW = user32.GetWindowTextW
    GetWindowTextLengthW = user32.GetWindowTextLengthW
    IsWindowVisible = user32.IsWindowVisible
    IsIconic = user32.IsIconic
    GetWindowRect = user32.GetWindowRect

    def _win_text(hwnd):
        n = GetWindowTextLengthW(hwnd)
        if n == 0: 
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def _win_rect(hwnd):
        r = wintypes.RECT()
        if not GetWindowRect(hwnd, ctypes.byref(r)): 
            return None
        return r.left, r.top, r.right, r.bottom

    def find_league_window_rect(hint: str = "League") -> Optional[Tuple[int, int, int, int]]:
        """Find League of Legends window rectangle"""
        rects = []
        
        def cb(hwnd, lparam):
            if not IsWindowVisible(hwnd) or IsIconic(hwnd): 
                return True
            t = _win_text(hwnd).lower()
            # More specific matching for League client
            if (("league of legends" in t or "riot client" in t) and 
                ("champion select" in t or "match found" in t or "ready check" in t or hint.lower() in t)):
                R = _win_rect(hwnd)
                if R:
                    l, t, r, b = R
                    w, h = r - l, b - t
                    # Size requirements for League client (supports lower resolutions)
                    if w >= 640 and h >= 480: 
                        rects.append((l, t, r, b))
            return True
        
        EnumWindows(EnumWindowsProc(cb), 0)
        if rects:
            rects.sort(key=lambda xyxy: (xyxy[2] - xyxy[0]) * (xyxy[3] - xyxy[1]), reverse=True)
            return rects[0]
        return None
else:
    def find_league_window_rect(hint: str = "League") -> Optional[Tuple[int, int, int, int]]:
        """Find League of Legends window rectangle (non-Windows)"""
        return None
