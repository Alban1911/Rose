#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Window utilities for League of Legends - Combined capture and monitoring
Provides window detection, size monitoring, and ROI calculation utilities
"""

import os
import time
import sys
import ctypes
from ctypes import wintypes
from typing import Optional, Tuple
from config import WINDOW_CHECK_SLEEP_S


def is_windows() -> bool:
    """Check if running on Windows"""
    return os.name == "nt"


# Windows API setup
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
        """Get window text"""
        n = GetWindowTextLengthW(hwnd)
        if n == 0: 
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def _win_rect(hwnd):
        """Get window rectangle"""
        r = wintypes.RECT()
        if not GetWindowRect(hwnd, ctypes.byref(r)): 
            return None
        return r.left, r.top, r.right, r.bottom

    def find_league_window_rect(hint: str = "League") -> Optional[Tuple[int, int, int, int]]:
        """
        Find League of Legends window rectangle - CLIENT AREA ONLY
        
        Args:
            hint: Window title hint for searching
            
        Returns:
            Tuple of (left, top, right, bottom) coordinates or None if not found
        """
        rects = []
        window_info = []
        
        def cb(hwnd, lparam):
            if not IsWindowVisible(hwnd) or IsIconic(hwnd): 
                return True
            t = _win_text(hwnd).lower()
            # Look for League client window - be more specific
            # We want the actual client window, not splash screens or other components
            # Must be EXACTLY "League of Legends" - nothing else
            if t == "league of legends" and "splash" not in t:
                # Get window rect (with borders)
                window_rect = _win_rect(hwnd)
                
                # Get client area coordinates (not window coordinates with borders)
                try:
                    from ctypes import windll
                    client_rect = wintypes.RECT()
                    windll.user32.GetClientRect(hwnd, ctypes.byref(client_rect))
                    
                    # Convert client rect to screen coordinates
                    point = wintypes.POINT()
                    point.x = 0
                    point.y = 0
                    windll.user32.ClientToScreen(hwnd, ctypes.byref(point))
                    
                    # Client area coordinates
                    l = point.x
                    t = point.y
                    r = l + client_rect.right
                    b = t + client_rect.bottom
                    
                    w, h = r - l, b - t
                    # Size requirements for League client
                    if w >= 640 and h >= 480: 
                        rects.append((l, t, r, b))
                        window_info.append({
                            'title': _win_text(hwnd),
                            'window_rect': window_rect,
                            'client_rect': (l, t, r, b),
                            'client_size': (w, h),
                            'hwnd': hwnd  # Store hwnd for focus checking
                        })
                except Exception:
                    # Fallback to window rect if client rect fails
                    R = _win_rect(hwnd)
                    if R:
                        l, t, r, b = R
                        w, h = r - l, b - t
                        if w >= 640 and h >= 480: 
                            rects.append((l, t, r, b))
                            window_info.append({
                                'title': _win_text(hwnd),
                                'window_rect': R,
                                'client_rect': (l, t, r, b),
                                'client_size': (w, h),
                                'hwnd': hwnd  # Store hwnd for focus checking
                            })
            return True
        
        EnumWindows(EnumWindowsProc(cb), 0)
        if rects:
            rects.sort(key=lambda xyxy: (xyxy[2] - xyxy[0]) * (xyxy[3] - xyxy[1]), reverse=True)
            # Store window info globally for debugging
            find_league_window_rect.window_info = window_info
            
            # DEBUG: Log all detected League windows (only when multiple found)
            if len(window_info) > 1:
                print(f"[DEBUG] Found {len(window_info)} League windows:")
                for i, info in enumerate(window_info):
                    print(f"  {i+1}. Title: '{info['title']}' | Client: {info['client_size']} | Window: {info['window_rect']}")
            
            return rects[0]
        return None


    def is_league_window_active() -> bool:
        """
        Check if League of Legends window is currently active (focused)
        
        Returns:
            True if League window is active, False otherwise
        """
        try:
            from ctypes import windll
            # Get the currently active window
            active_hwnd = windll.user32.GetForegroundWindow()
            if not active_hwnd:
                return False
            
            # Get the window title of the active window
            length = windll.user32.GetWindowTextLengthW(active_hwnd)
            if length == 0:
                return False
                
            buffer = ctypes.create_unicode_buffer(length + 1)
            windll.user32.GetWindowTextW(active_hwnd, buffer, length + 1)
            active_title = buffer.value.lower()
            
            # Check if it's the League of Legends window
            return active_title == "league of legends"
            
        except Exception:
            # If we can't determine focus, assume it's not focused for safety
            return False

else:
    def find_league_window_rect(hint: str = "League") -> Optional[Tuple[int, int, int, int]]:
        """Find League of Legends window rectangle (non-Windows)"""
        return None

    def is_league_window_active() -> bool:
        """Check if League of Legends window is active (non-Windows - always False)"""
        return False


def get_league_window_client_size(hint: str = "League") -> Optional[Tuple[int, int]]:
    """
    Get League of Legends window client area size (width, height)
    Returns the actual client area dimensions for ROI calculations
    
    Args:
        hint: Window title hint for searching
        
    Returns:
        Tuple of (width, height) or None if window not found
    """
    rect = find_league_window_rect(hint)
    if rect:
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top
        return (width, height)
    return None


def get_window_size() -> Optional[Tuple[int, int]]:
    """
    Alias for get_league_window_client_size for backward compatibility
    
    Returns:
        Tuple[int, int]: (width, height) or None if window is not found
    """
    return get_league_window_client_size()


def monitor_league_window():
    """
    Monitor League of Legends window size every second
    """
    print("Starting League of Legends window monitoring...")
    print("Press Ctrl+C to stop")
    print("-" * 80)
    
    try:
        while True:
            rect = find_league_window_rect()
            
            if rect:
                # Display size for ROI calculations
                if hasattr(find_league_window_rect, 'window_info') and find_league_window_rect.window_info:
                    for info in find_league_window_rect.window_info:
                        # Use client area size (perfect for ROI calculations)
                        client_w, client_h = info['client_size']
                        print(f"League of Legends window size: {client_w}x{client_h} pixels")
                        break
                
                print("-" * 40)
            else:
                print("League of Legends window not found")
            
            # Wait 1 second before next check
            time.sleep(WINDOW_CHECK_SLEEP_S)
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")


def calculate_roi_from_proportions(window_rect: Tuple[int, int, int, int], 
                                 proportions: dict) -> Optional[Tuple[int, int, int, int]]:
    """
    Calculate ROI coordinates from window rectangle and proportions
    
    Args:
        window_rect: (left, top, right, bottom) window coordinates
        proportions: Dict with 'x1_ratio', 'y1_ratio', 'x2_ratio', 'y2_ratio'
        
    Returns:
        Tuple of ROI coordinates (left, top, right, bottom) or None if invalid
    """
    if not window_rect or not proportions:
        return None
    
    left, top, right, bottom = window_rect
    width = right - left
    height = bottom - top
    
    roi_abs = (
        int(left + width * proportions.get('x1_ratio', 0)),
        int(top + height * proportions.get('y1_ratio', 0)),
        int(left + width * proportions.get('x2_ratio', 1)),
        int(top + height * proportions.get('y2_ratio', 1))
    )
    
    return roi_abs


def main():
    """Main entry point for monitoring script"""
    if len(sys.argv) > 1 and sys.argv[1] in ['-h', '--help']:
        print("Window utilities for League of Legends")
        print("Usage: python utils/window_utils.py")
        print("The script displays window size every second")
        print("Press Ctrl+C to stop")
        return
    
    monitor_league_window()


if __name__ == "__main__":
    main()
