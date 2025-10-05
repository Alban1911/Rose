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
            # Look for League client window
            if "league of legends" in t or "riot client" in t:
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
                            'client_size': (w, h)
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
                                'client_size': (w, h)
                            })
            return True
        
        EnumWindows(EnumWindowsProc(cb), 0)
        if rects:
            rects.sort(key=lambda xyxy: (xyxy[2] - xyxy[0]) * (xyxy[3] - xyxy[1]), reverse=True)
            # Store window info globally for debugging
            find_league_window_rect.window_info = window_info
            return rects[0]
        return None

else:
    def find_league_window_rect(hint: str = "League") -> Optional[Tuple[int, int, int, int]]:
        """Find League of Legends window rectangle (non-Windows)"""
        return None


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
        Tuple[int, int]: (largeur, hauteur) ou None si la fenêtre n'est pas trouvée
    """
    return get_league_window_client_size()


def monitor_league_window():
    """
    Surveille la taille de la fenêtre League of Legends toutes les secondes
    """
    print("Démarrage de la surveillance de la fenêtre League of Legends...")
    print("Appuyez sur Ctrl+C pour arrêter")
    print("-" * 80)
    
    try:
        while True:
            rect = find_league_window_rect()
            
            if rect:
                # Afficher la taille pour les calculs de ROI
                if hasattr(find_league_window_rect, 'window_info') and find_league_window_rect.window_info:
                    for info in find_league_window_rect.window_info:
                        # Utiliser la taille de la zone client (parfaite pour les calculs de ROI)
                        client_w, client_h = info['client_size']
                        print(f"Taille de la fenêtre League of Legends: {client_w}x{client_h} pixels")
                        break
                
                print("-" * 40)
            else:
                print("Fenêtre League of Legends non trouvée")
            
            # Attendre 1 seconde avant la prochaine vérification
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nSurveillance arrêtée.")


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
    """Point d'entrée principal pour le script de surveillance"""
    if len(sys.argv) > 1 and sys.argv[1] in ['-h', '--help']:
        print("Window utilities for League of Legends")
        print("Usage: python utils/window_utils.py")
        print("Le script affiche la taille de la fenêtre toutes les secondes")
        print("Appuyez sur Ctrl+C pour arrêter")
        return
    
    monitor_league_window()


if __name__ == "__main__":
    main()
