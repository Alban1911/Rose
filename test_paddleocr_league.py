#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
All-in-One PaddleOCR Test for League of Legends Client

Tests PaddleOCR with GPU support on the League Client with COMPLETE pipeline:
- Window detection (League Client window)
- LCU connection (phase detection, champion lock, language detection)
- Automatic language detection (27 League languages supported)
- ROI extraction (skin selection area)
- Image preprocessing (band detection, HSV filtering, edge detection)
- OCR with GPU/CPU support
- Text normalization & fuzzy matching (Levenshtein distance)
- Skin matching against database with detailed logs
- Debug mode (saves images to ocr_debug_paddle/)

Matching Pipeline (SECURE Multi-Language):
1. Lock Champion → Detect champion ID from LCU
2. LCU API → Load skins in CLIENT LANGUAGE (e.g., Korean: "생체공학 다리우스")
3. OCR → Detect text in CLIENT LANGUAGE
4. Text normalization (lowercase, remove artifacts, etc.)
5. Levenshtein distance calculation against all LCU skins (in client language)
6. Best match selection (threshold: 0.7) → Get skin_id
7. English DB → Convert skin_id to English name (e.g., 122002 → "Bioforge Darius")
8. Detailed logging of all comparisons and final match

This ensures accurate matching regardless of client language!

Supported Languages:
- English (en_US, en_GB, en_AU, en_PH, en_SG)
- European: German, Spanish, French, Italian, Polish, Portuguese, Romanian, Turkish, Russian, Czech, Greek, Hungarian
- Asian: Japanese, Korean, Chinese (Simplified/Traditional), Thai, Vietnamese
- Fallback: Malay, Indonesian (uses English)

Dependencies:
- paddlepaddle-gpu or paddlepaddle
- paddleocr
- python-Levenshtein (recommended for accurate matching)
- opencv-python
- numpy
- mss

Usage:
1. Launch League of Legends
2. Enter Champion Select
3. Lock a champion (currently supports: Bard, Ahri in test DB)
4. Run this script: python test_paddleocr_league.py
5. Hover over skins to test OCR and matching
"""

import os
import sys
import time
import ctypes
from ctypes import wintypes
from typing import Optional, Tuple, Dict, List
import numpy as np
import cv2
import requests
import psutil
from pathlib import Path
import re

# Add project root to path to import database
sys.path.insert(0, str(Path(__file__).parent))

try:
    import Levenshtein
    HAS_LEVENSHTEIN = True
except ImportError:
    HAS_LEVENSHTEIN = False
    print("⚠️  python-Levenshtein not installed. Install with: pip install python-Levenshtein")
    print("   Falling back to basic string matching")

# Import NameDB for English skin names
try:
    from database.name_db import NameDB
    HAS_NAME_DB = True
except ImportError as e:
    HAS_NAME_DB = False
    print(f"⚠️  Failed to import NameDB: {e}")
    print("   Will use fallback SimpleSkinDB")


# =============================================================================
# CONSTANTS
# =============================================================================

# ROI Proportions (fixed for all resolutions)
ROI_PROPORTIONS = {
    'x1_ratio': 0.352,  # 450/1280 - left edge
    'y1_ratio': 0.632,  # 455/720  - top edge
    'x2_ratio': 0.648,  # 830/1280 - right edge
    'y2_ratio': 0.681   # 490/720  - bottom edge
}

# Image processing constants
BAND_CENTER_PCT = (62.0, 6.5)
BAND_SPAN_PCT = (52.0, 70.0)
BAND_CANDIDATES_STEPS = 9
BAND_MIN_HEIGHT = 24
TEXT_DETECTION_LEFT_PCT = 28.0
TEXT_DETECTION_RIGHT_PCT = 72.0
WHITE_TEXT_HSV_LOWER = [0, 0, 200]
WHITE_TEXT_HSV_UPPER = [179, 70, 255]
CANNY_THRESHOLD_LOW = 40
CANNY_THRESHOLD_HIGH = 120
SCORE_WEIGHT_MASK = 0.6
SCORE_WEIGHT_EDGES = 0.4
IMAGE_UPSCALE_THRESHOLD = 120

# OCR settings
OCR_DIFF_THRESHOLD = 0.001
OCR_MIN_INTERVAL = 0.15
OCR_FUZZY_MATCH_THRESHOLD = 0.5  # Threshold for fuzzy text matching (lowered for better tolerance)
OCR_MIN_CONFIDENCE = 0.5  # Minimum confidence score for matches
DEBUG_OCR = True  # Always save images in test mode

# Language mapping: League locale -> PaddleOCR language code
# PaddleOCR supported languages: https://github.com/PaddlePaddle/PaddleOCR/blob/release/2.6/doc/doc_en/multi_languages_en.md
LEAGUE_TO_PADDLE_LANG = {
    # English variants
    'en_US': 'en',      # English (United States)
    'en_GB': 'en',      # English (United Kingdom)
    'en_AU': 'en',      # English (Australia)
    'en_PH': 'en',      # English (Philippines)
    'en_SG': 'en',      # English (Singapore)
    
    # European languages
    'de_DE': 'german',  # German (Germany)
    'es_ES': 'es',      # Spanish (Spain)
    'es_MX': 'es',      # Spanish (Mexico)
    'es_AR': 'es',      # Spanish (Argentina)
    'fr_FR': 'french',  # French (France)
    'it_IT': 'it',      # Italian (Italy)
    'pl_PL': 'polish',  # Polish (Poland)
    'pt_BR': 'pt',      # Portuguese (Brazil)
    'ro_RO': 'ro',      # Romanian (Romania)
    'tr_TR': 'tr',      # Turkish (Turkey)
    'ru_RU': 'cyrillic',  # Russian (Russia) - uses Cyrillic script
    'cs_CZ': 'latin',     # Czech (Czech Republic) - uses Latin script
    'el_GR': 'cyrillic',  # Greek (Greece) - Greek alphabet is similar to Cyrillic for OCR
    'hu_HU': 'latin',     # Hungarian (Hungary) - uses Latin script
    
    # Asian languages
    'ja_JP': 'japan',   # Japanese (Japan)
    'ko_KR': 'korean',  # Korean (Korea)
    'zh_CN': 'ch',      # Chinese Simplified (China)
    'zh_TW': 'chinese_cht',  # Chinese Traditional (Taiwan)
    'zh_MY': 'ch',      # Chinese (Malaysia) - using simplified
    'th_TH': 'th',      # Thai (Thailand)
    'vi_VN': 'vi',      # Vietnamese (Vietnam) - Note: League uses 'vn_VN' not 'vi_VN'
    'vn_VN': 'vi',      # Vietnamese (Vietnam) - Alternative spelling
    
    # Southeast Asian languages (fallback to English if PaddleOCR doesn't support)
    'ms_MY': 'en',      # Malay (Malaysia) - PaddleOCR doesn't support Malay, fallback to English
    'id_ID': 'en',      # Indonesian (Indonesia) - PaddleOCR doesn't support Indonesian, fallback to English
}


# =============================================================================
# WINDOW DETECTION
# =============================================================================

def init_windows_api():
    """Initialize Windows API"""
    if os.name != "nt":
        print("❌ This script only works on Windows")
        sys.exit(1)
    
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass
    
    return user32


def get_window_text(hwnd, user32):
    """Get window text"""
    n = user32.GetWindowTextLengthW(hwnd)
    if n == 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def get_window_rect(hwnd, user32):
    """Get window rectangle"""
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return r.left, r.top, r.right, r.bottom


def find_league_window(user32, verbose: bool = False) -> Optional[Tuple[int, int, int, int]]:
    """Find League of Legends window - CLIENT AREA ONLY"""
    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.POINTER(ctypes.c_int))
    IsWindowVisible = user32.IsWindowVisible
    IsIconic = user32.IsIconic
    
    windows = []
    
    def callback(hwnd, lparam):
        if not IsWindowVisible(hwnd) or IsIconic(hwnd):
            return True
        
        title = get_window_text(hwnd, user32).lower()
        
        # Look for exact "League of Legends" window
        if title == "league of legends":
            try:
                # Get client area coordinates
                client_rect = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(client_rect))
                
                # Convert to screen coordinates
                point = wintypes.POINT()
                point.x = 0
                point.y = 0
                user32.ClientToScreen(hwnd, ctypes.byref(point))
                
                # Calculate client area
                l = point.x
                t = point.y
                r = l + client_rect.right
                b = t + client_rect.bottom
                
                w, h = r - l, b - t
                
                # Size requirements
                if w >= 640 and h >= 480:
                    windows.append((l, t, r, b, w, h, hwnd))
                    if verbose:
                        print(f"✅ Found League window: {w}x{h} at ({l}, {t})")
            except Exception as e:
                if verbose:
                    print(f"⚠️ Error getting client rect: {e}")
        
        return True
    
    EnumWindows(EnumWindowsProc(callback), 0)
    
    if windows:
        # Sort by size (largest first)
        windows.sort(key=lambda x: x[4] * x[5], reverse=True)
        l, t, r, b, w, h, hwnd = windows[0]
        return (l, t, r, b)
    
    return None


def is_league_window_focused(user32, league_rect) -> bool:
    """Check if League window is focused"""
    try:
        active_hwnd = user32.GetForegroundWindow()
        if not active_hwnd:
            return False
        
        title = get_window_text(active_hwnd, user32).lower()
        return title == "league of legends"
    except Exception:
        return False


# =============================================================================
# LCU CLIENT (Phase Detection)
# =============================================================================

class LCUClient:
    """Minimal LCU client for phase detection"""
    
    def __init__(self):
        self.ok = False
        self.port = None
        self.pw = None
        self.base = None
        self.session = None
        self._init_from_lockfile()
    
    def _find_lockfile(self) -> Optional[str]:
        """Find League Client lockfile"""
        # Common locations
        paths = [
            r"C:\Riot Games\League of Legends\lockfile",
            r"C:\Program Files\Riot Games\League of Legends\lockfile",
            r"C:\Program Files (x86)\Riot Games\League of Legends\lockfile"
        ]
        
        for path in paths:
            if os.path.isfile(path):
                return path
        
        # Search via process
        try:
            for proc in psutil.process_iter(attrs=["name", "exe"]):
                nm = (proc.info.get("name") or "").lower()
                if "leagueclient" in nm:
                    exe = proc.info.get("exe") or ""
                    for d in (os.path.dirname(exe), os.path.dirname(os.path.dirname(exe))):
                        p = os.path.join(d, "lockfile")
                        if os.path.isfile(p):
                            return p
        except Exception:
            pass
        
        return None
    
    def _init_from_lockfile(self):
        """Initialize from lockfile"""
        lf = self._find_lockfile()
        if not lf:
            print("⚠️ LCU lockfile not found (League Client not running?)")
            return
        
        try:
            with open(lf, "r", encoding="utf-8") as f:
                parts = f.read().split(":")
                name, pid, port, pw, proto = parts[:5]
            
            self.port = int(port)
            self.pw = pw
            self.base = f"https://127.0.0.1:{self.port}"
            self.session = requests.Session()
            self.session.verify = False
            self.session.auth = ("riot", pw)
            self.session.headers.update({"Content-Type": "application/json"})
            self.ok = True
            print(f"✅ LCU connected (port {self.port})")
        except Exception as e:
            print(f"❌ Failed to initialize LCU: {e}")
    
    def get_phase(self) -> Optional[str]:
        """Get current game phase"""
        if not self.ok:
            return None
        
        try:
            resp = self.session.get(f"{self.base}/lol-gameflow/v1/gameflow-phase", timeout=2.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        
        return None
    
    def get_locked_champion(self) -> Optional[int]:
        """Get locked champion ID in champion select"""
        if not self.ok:
            return None
        
        try:
            resp = self.session.get(f"{self.base}/lol-champ-select/v1/session", timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                
                # Find local player's cell ID
                local_cell_id = data.get('localPlayerCellId')
                if local_cell_id is None:
                    return None
                
                # Check actions for locked champion
                for action_group in data.get('actions', []):
                    for action in action_group:
                        if action.get('actorCellId') == local_cell_id and action.get('completed'):
                            champ_id = action.get('championId')
                            if champ_id and champ_id > 0:
                                return champ_id
                
        except Exception:
            pass
        
        return None
    
    def get_language(self) -> Optional[str]:
        """Get client language (e.g. 'en_US', 'fr_FR', 'ko_KR')"""
        if not self.ok:
            return None
        
        try:
            resp = self.session.get(f"{self.base}/riotclient/region-locale", timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                locale = data.get('locale', 'en_US')
                return locale
        except Exception:
            pass
        
        return 'en_US'  # Default fallback
    
    def get_champion_skins_from_lcu(self, champ_id: int) -> Optional[Dict[int, str]]:
        """Get champion skins from LCU in client language
        
        Returns: Dict[skin_id, skin_name_in_client_lang]
        Example: {432000: "바드", 432001: "고목 바드", ...}
        """
        if not self.ok:
            return None
        
        try:
            # Get champion data from LCU
            resp = self.session.get(
                f"{self.base}/lol-game-data/assets/v1/champions/{champ_id}.json",
                timeout=3.0
            )
            
            if resp.status_code == 200:
                data = resp.json()
                skins_dict = {}
                champion_name = data.get('name', '')
                
                # Extract skins from champion data
                for skin in data.get('skins', []):
                    skin_id = skin.get('id')
                    skin_name = skin.get('name', '')
                    
                    if skin_id is not None and skin_name:
                        # Handle "default" skin name - use champion name
                        if skin_name.lower() == 'default':
                            skin_name = champion_name
                        
                        skins_dict[skin_id] = skin_name
                        
                        # For base skin (ID ending in 000), also add champion name as alias
                        # This helps matching when OCR detects just the champion name
                        if skin_id % 1000 == 0 and skin_name != champion_name and champion_name:
                            # The base skin name might already be the champion name, 
                            # but if it's different (shouldn't happen), keep both
                            pass
                
                print(f"📥 Loaded {len(skins_dict)} skins from LCU for champion {champ_id}")
                for skin_id, skin_name in list(skins_dict.items())[:3]:
                    is_base = "(BASE)" if skin_id % 1000 == 0 else ""
                    print(f"   {skin_id}: {skin_name} {is_base}")
                if len(skins_dict) > 3:
                    print(f"   ... and {len(skins_dict) - 3} more")
                
                return skins_dict
        except Exception as e:
            print(f"⚠️ Failed to get skins from LCU: {e}")
        
        return None


# =============================================================================
# TEXT NORMALIZATION & MATCHING
# =============================================================================

def normalize_text(s: str) -> str:
    """NO normalization - keep original text for multi-language support"""
    if not s:
        return ""
    # Just strip whitespace
    return s.strip()


def levenshtein_score(ocr_text: str, skin_text: str) -> float:
    """Calculate similarity score between two texts (0.0 to 1.0) - NO normalization"""
    if not ocr_text or not skin_text:
        return 0.0
    
    # Strip whitespace only
    ocr_clean = ocr_text.strip()
    skin_clean = skin_text.strip()
    
    if not ocr_clean or not skin_clean:
        return 0.0
    
    # Use Levenshtein distance if available
    if HAS_LEVENSHTEIN:
        distance = Levenshtein.distance(ocr_clean, skin_clean)
        max_len = max(len(ocr_clean), len(skin_clean))
        if max_len == 0:
            return 1.0
        score = 1.0 - (distance / max_len)
        return max(0.0, score)
    else:
        # Fallback: simple substring matching
        if ocr_clean == skin_clean:
            return 1.0
        elif ocr_clean in skin_clean or skin_clean in ocr_clean:
            return 0.8
        else:
            return 0.0


def match_skin_name(ocr_text: str, available_skins: Dict[int, str], champ_slug: str) -> Optional[Tuple[int, str, float]]:
    """Match OCR text against available skins - ALWAYS returns best match (no threshold)
    
    Args:
        ocr_text: Text detected by OCR
        available_skins: Dict of skin_id -> skin_name
        champ_slug: Champion slug for logging
    
    Returns: (skin_id, skin_name, similarity) or None if no skins available
    """
    if not ocr_text or not available_skins:
        return None
    
    print(f"\n{'='*80}")
    print(f"🔍 MATCHING PIPELINE (No Threshold - Best Match Only)")
    print(f"{'='*80}")
    print(f"📝 OCR Text: '{ocr_text}'")
    print(f"   Normalized: '{normalize_text(ocr_text)}'")
    print(f"🎮 Champion: {champ_slug}")
    print(f"🎨 Available skins: {len(available_skins)}")
    print(f"{'='*80}")
    
    best_match = None
    best_similarity = 0.0
    
    for skin_id, skin_name in available_skins.items():
        similarity = levenshtein_score(ocr_text, skin_name)
        
        # Log all comparisons (highlight current best)
        if similarity > best_similarity:
            status = "🏆"  # New best
            best_match = (skin_id, skin_name, similarity)
            best_similarity = similarity
        else:
            status = "  "  # Not better
        
        print(f"{status} '{ocr_text}' vs '{skin_name}' = {similarity:.3f}")
    
    print(f"{'='*80}")
    if best_match:
        skin_id, skin_name, similarity = best_match
        is_base = (skin_id % 1000 == 0)
        print(f"✅ BEST MATCH: '{skin_name}' (ID: {skin_id}, similarity: {similarity:.1%}, base: {is_base})")
    else:
        print(f"❌ NO MATCH FOUND (no skins available)")
    print(f"{'='*80}\n")
    
    return best_match


# =============================================================================
# SKIN DATABASE WRAPPER
# =============================================================================

class SkinDBWrapper:
    """Wrapper to unify NameDB and SimpleSkinDB interfaces"""
    
    def __init__(self, db):
        self.db = db
        self._is_name_db = HAS_NAME_DB and isinstance(db, NameDB)
    
    def get_champion_slug(self, champ_id: int) -> Optional[str]:
        """Get champion slug by ID"""
        return self.db.slug_by_id.get(champ_id)
    
    def get_english_name_by_skin_id(self, skin_id: int) -> Optional[str]:
        """Get English skin name by skin ID"""
        if self._is_name_db:
            # NameDB: load champion skins if needed
            champ_id = (skin_id // 1000)
            slug = self.db.slug_by_id.get(champ_id)
            if slug and slug not in self.db._skins_loaded:
                self.db.load_champion_skins_by_id(champ_id)
            return self.db.skin_name_by_id.get(skin_id)
        else:
            # SimpleSkinDB
            return self.db.skin_name_by_id.get(skin_id)


# =============================================================================
# SIMPLE SKIN DATABASE (for testing/fallback)
# =============================================================================

class SimpleSkinDB:
    """Simplified skin database for testing (English names only)"""
    
    def __init__(self):
        self.champion_skins: Dict[str, Dict[int, str]] = {}
        self.slug_by_id: Dict[int, str] = {}
        self.skin_name_by_id: Dict[int, str] = {}  # skin_id -> English name
        self._init_sample_data()
    
    def _init_sample_data(self):
        """Initialize with sample champion data (English names)"""
        # Bard (ID: 432)
        self.slug_by_id[432] = "bard"
        self.champion_skins["bard"] = {
            432000: "Bard",  # Base skin
            432001: "Elderwood Bard",
            432002: "Bard Bard",
            432003: "Snow Day Bard",
            432004: "Astronaut Bard",
            432005: "Cafe Cuties Bard",
            432006: "Bio Forge Bard",
        }
        
        # Ahri (ID: 103)
        self.slug_by_id[103] = "ahri"
        self.champion_skins["ahri"] = {
            103000: "Ahri",
            103001: "Dynasty Ahri",
            103002: "Midnight Ahri",
            103003: "Foxfire Ahri",
            103004: "Popstar Ahri",
            103005: "Challenger Ahri",
            103006: "Academy Ahri",
            103007: "Arcade Ahri",
            103008: "Star Guardian Ahri",
            103009: "K/DA Ahri",
            103014: "Spirit Blossom Ahri",
            103015: "K/DA ALL OUT Ahri",
        }
        
        # Darius (ID: 122)
        self.slug_by_id[122] = "darius"
        self.champion_skins["darius"] = {
            122000: "Darius",
            122001: "Lord Darius",
            122002: "Bioforge Darius",
            122003: "Woad King Darius",
            122004: "Dunkmaster Darius",
            122005: "Academy Darius",
            122006: "Dreadnova Darius",
            122008: "God-King Darius",
            122009: "High Noon Darius",
            122010: "Lunar Beast Darius",
        }
        
        # Nilah (ID: 895)
        self.slug_by_id[895] = "nilah"
        self.champion_skins["nilah"] = {
            895000: "Nilah",
            895001: "Star Guardian Nilah",
            895011: "Crime City Nightmare Nilah",
            895012: "Prestige Star Guardian Nilah",
        }
        
        # Rumble (ID: 68)
        self.slug_by_id[68] = "rumble"
        self.champion_skins["rumble"] = {
            68000: "Rumble",
            68001: "Rumble in the Jungle",
            68002: "Bilgewater Rumble",
            68003: "Super Galaxy Rumble",
            68004: "Badlands Baron Rumble",
            68005: "Space Groove Rumble",
            68011: "Cafe Cuties Rumble",
        }
        
        # Build reverse mapping: skin_id -> English name
        for champ_slug, skins in self.champion_skins.items():
            for skin_id, skin_name in skins.items():
                self.skin_name_by_id[skin_id] = skin_name
        
        print(f"📚 English DB loaded: {len(self.champion_skins)} champions, {len(self.skin_name_by_id)} skins")
    
    def get_champion_skins(self, champ_id: int) -> Dict[int, str]:
        """Get English skins for a champion"""
        slug = self.slug_by_id.get(champ_id)
        if not slug:
            return {}
        return self.champion_skins.get(slug, {})
    
    def get_champion_slug(self, champ_id: int) -> Optional[str]:
        """Get champion slug by ID"""
        return self.slug_by_id.get(champ_id)
    
    def get_english_name_by_skin_id(self, skin_id: int) -> Optional[str]:
        """Get English skin name by skin ID"""
        return self.skin_name_by_id.get(skin_id)


# =============================================================================
# IMAGE PROCESSING
# =============================================================================

def band_candidates(h: int) -> list:
    """Generate band candidates for text detection"""
    centre_pct, span = BAND_CENTER_PCT, BAND_SPAN_PCT
    height = max(4.0, min(centre_pct[1], 12.0))
    ts = np.linspace(span[0], span[1] - height, BAND_CANDIDATES_STEPS)
    return [(float(t), float(t + height)) for t in ts]


def score_white_text(bgr_band: np.ndarray) -> float:
    """Score band for white text content"""
    hsv = cv2.cvtColor(bgr_band, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(WHITE_TEXT_HSV_LOWER, np.uint8), 
                      np.array(WHITE_TEXT_HSV_UPPER, np.uint8))
    g = cv2.cvtColor(bgr_band, cv2.COLOR_BGR2GRAY)
    e = cv2.Canny(g, CANNY_THRESHOLD_LOW, CANNY_THRESHOLD_HIGH)
    return SCORE_WEIGHT_MASK * (mask > 0).mean() + SCORE_WEIGHT_EDGES * (e > 0).mean()


def choose_band(frame: np.ndarray) -> Tuple[int, int, int, int]:
    """Choose the best band for text detection"""
    h, w = frame.shape[:2]
    x1 = int(w * (TEXT_DETECTION_LEFT_PCT / 100.0))
    x2 = int(w * (TEXT_DETECTION_RIGHT_PCT / 100.0))
    best = (-1.0, 0, 0)
    
    for T, B in band_candidates(h):
        y1 = int(h * (T / 100.0))
        y2 = int(h * (B / 100.0))
        if y2 - y1 < BAND_MIN_HEIGHT:
            continue
        sc = score_white_text(frame[y1:y2, x1:x2])
        if sc > best[0]:
            best = (sc, y1, y2)
    
    y1, y2 = (int(h * 0.58), int(h * 0.66)) if best[0] < 0 else (best[1], best[2])
    return x1, y1, x2, y2


# Removed old preprocessing functions - now using Research-Based preprocessing only


def prep_for_ocr_ultra_sharp(input_img: np.ndarray) -> np.ndarray:
    """Preprocess image for OCR - RESEARCH-BASED optimal version for Chinese/Asian text"""
    # Handle both BGR (3-channel) and grayscale (1-channel) input
    if len(input_img.shape) == 3 and input_img.shape[2] == 3:
        # Input is BGR (3-channel), convert to grayscale
        gray = cv2.cvtColor(input_img, cv2.COLOR_BGR2GRAY)
    else:
        # Input is already grayscale (1-channel)
        gray = input_img.copy()
    
    # STEP 1: Noise Removal with Bilateral Filtering (preserves edges!)
    # This is CRUCIAL for Chinese characters - removes noise while keeping character structure
    denoised = cv2.bilateralFilter(gray, 9, 75, 75)
    
    # STEP 2: Contrast Enhancement (CLAHE - Contrast Limited Adaptive Histogram Equalization)
    # Improves visibility of characters, especially in varying lighting
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
    enhanced = clahe.apply(denoised)
    
    # STEP 3: Image Scaling to optimal DPI (300 DPI equivalent)
    # Scale up if too small for better character recognition
    height, width = enhanced.shape
    if height < 48:  # Minimum height for good OCR
        scale_factor = 48 / height
        new_width = int(width * scale_factor)
        enhanced = cv2.resize(enhanced, (new_width, 48), interpolation=cv2.INTER_CUBIC)
    
    # STEP 4: Advanced Binarization (OTSU + Adaptive)
    # First try OTSU for automatic threshold
    _, binary_otsu = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Then apply adaptive threshold for better local contrast
    binary_adaptive = cv2.adaptiveThreshold(enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                           cv2.THRESH_BINARY, 11, 2)
    
    # Combine both methods (OTSU for global, adaptive for local)
    combined = cv2.bitwise_and(binary_otsu, binary_adaptive)
    
    # STEP 5: Morphological Operations (clean up characters)
    # Remove small noise while preserving character structure
    kernel_clean = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    cleaned = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel_clean)
    
    # STEP 6: Final sharpening (light) to enhance character edges
    kernel_sharp = np.array([[0,-1,0],
                            [-1,5,-1],
                            [0,-1,0]])
    final = cv2.filter2D(cleaned, -1, kernel_sharp)
    
    # Convert to 3-channel for PaddleOCR
    result = cv2.cvtColor(final, cv2.COLOR_GRAY2BGR)
    return result


# Removed preprocess_band_for_ocr - now using direct Research-Based preprocessing


# =============================================================================
# PADDLEOCR INITIALIZATION
# =============================================================================

def init_paddleocr(use_gpu: bool = True, lang: str = 'en'):
    """Initialize PaddleOCR with GPU support and language detection
    
    Args:
        use_gpu: Whether to use GPU
        lang: PaddleOCR language code (e.g. 'en', 'french', 'korean', 'ch')
    """
    print("\n" + "="*80)
    print("🚀 Initializing PaddleOCR...")
    print("="*80)
    
    try:
        from paddleocr import PaddleOCR
        import paddle
        
        # Display language info
        print(f"📝 Language: {lang}")
        
        # Check GPU availability and set device
        device = 'cpu'
        if use_gpu:
            try:
                if paddle.device.cuda.device_count() > 0:
                    device = 'gpu'
                    gpu_name = paddle.device.cuda.get_device_properties(0).name
                    print(f"✅ GPU detected: {gpu_name}")
                    try:
                        cuda_version = paddle.version.cuda()
                        print(f"   CUDA version: {cuda_version}")
                    except:
                        print(f"   CUDA: Available")
                else:
                    print("⚠️ No GPU detected, falling back to CPU")
                    print("\n💡 Pour activer le GPU:")
                    print("   1. Désinstaller: pip uninstall paddlepaddle paddlepaddle-gpu")
                    print("   2. Installer GPU: pip install paddlepaddle-gpu -i https://pypi.tuna.tsinghua.edu.cn/simple")
                    print("   3. Vérifier CUDA installé (11.2+)")
                    device = 'cpu'
            except Exception as e:
                print(f"⚠️ GPU check failed: {e}")
                print("\n💡 Vous avez probablement la version CPU de PaddlePaddle")
                print("   Réinstallez avec: pip uninstall paddlepaddle && pip install paddlepaddle-gpu")
                device = 'cpu'
        
        # Set Paddle device
        if device == 'gpu':
            paddle.device.set_device('gpu:0')
        else:
            paddle.device.set_device('cpu')
        
        # Initialize PaddleOCR with current API (minimal params)
        print(f"\n📦 Loading PaddleOCR models (device: {device}, lang: {lang})...")
        
        # Try different initialization methods based on version
        # Force use_gpu parameter based on device choice
        use_gpu_param = (device == 'gpu')
        
        try:
            # Method 1: Latest API (with use_gpu for older versions)
            ocr = PaddleOCR(
                lang=lang,
                use_gpu=use_gpu_param,
                use_textline_orientation=True,
                text_det_box_thresh=0.3,
                text_det_unclip_ratio=1.6,
                text_recognition_batch_size=6
            )
        except Exception as e1:
            print(f"   Method 1 failed: {e1}")
            try:
                # Method 2: Older API
                ocr = PaddleOCR(
                    lang=lang,
                    use_gpu=use_gpu_param,
                    use_angle_cls=True,
                    det_db_box_thresh=0.3,
                    det_db_unclip_ratio=1.6,
                    rec_batch_num=6
                )
            except Exception as e2:
                print(f"   Method 2 failed: {e2}")
                try:
                    # Method 3: Minimal API
                    ocr = PaddleOCR(lang=lang, use_gpu=use_gpu_param)
                except Exception as e3:
                    print(f"   Method 3 failed: {e3}")
                    raise Exception(f"All PaddleOCR initialization methods failed. Last error: {e3}")
        
        print("✅ PaddleOCR initialized successfully!")
        print(f"   Device: {device.upper()}")
        print(f"   Language: {lang}")
        print("="*80 + "\n")
        
        return ocr, (device == 'gpu')
        
    except ImportError as e:
        print(f"❌ Failed to import PaddleOCR: {e}")
        print("\n💡 Install PaddleOCR:")
        print("   GPU: pip install paddlepaddle-gpu paddleocr")
        print("   CPU: pip install paddlepaddle paddleocr")
        print("\n💡 For GPU support, you need:")
        print("   - CUDA 11.2 or higher")
        print("   - cuDNN 8.1 or higher")
        print("   - Compatible NVIDIA GPU")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to initialize PaddleOCR: {e}")
        print(f"\n💡 Error details: {type(e).__name__}")
        import traceback
        print(traceback.format_exc())
        sys.exit(1)


def recognize_text_paddleocr(ocr, image: np.ndarray) -> str:
    """Run PaddleOCR on image"""
    try:
        # Try different API methods based on PaddleOCR version
        result = None
        
        # Method 1: Try predict() (newer API)
        try:
            result = ocr.predict(image)
        except AttributeError:
            # Method 2: Try ocr() (older API)
            try:
                result = ocr.ocr(image)
            except Exception:
                # Method 3: Try ocr() with cls parameter
                result = ocr.ocr(image, cls=True)
        
        if not result:
            return ""
        
        # Handle different result formats
        if isinstance(result, dict):
            # New API format
            ocr_results = result.get('ocr_text', [])
            if ocr_results:
                texts = []
                for item in ocr_results:
                    if isinstance(item, dict):
                        text = item.get('text', '')
                        conf = item.get('score', 0.0)
                        if text and conf > 0.5:
                            texts.append(text)
                    elif isinstance(item, (list, tuple)) and len(item) >= 2:
                        text = item[0] if isinstance(item[0], str) else str(item[0])
                        conf = float(item[1]) if len(item) > 1 else 0.0
                        if text and conf > 0.5:
                            texts.append(text)
                return " ".join(texts) if texts else ""
        
        elif isinstance(result, list) and result:
            # Old API format
            texts = []
            for line in result[0]:
                if line and len(line) >= 2:
                    text, conf = line[1]
                    if conf > 0.5:
                        texts.append(text)
            return " ".join(texts) if texts else ""
        
        return ""
    except Exception as e:
        import traceback
        print(f"❌ OCR error: {e}")
        print(f"   Debug: {traceback.format_exc()}")
        return ""


# =============================================================================
# DEBUG UTILITIES
# =============================================================================

def save_debug_image(image: np.ndarray, text: str, counter: int):
    """Save OCR debug image"""
    if not DEBUG_OCR:
        return
    
    try:
        debug_dir = Path("ocr_debug_paddle")
        debug_dir.mkdir(exist_ok=True)
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"paddle_{timestamp}_{counter:04d}.png"
        filepath = debug_dir / filename
        
        cv2.imwrite(str(filepath), image)
        
        # Also save text result
        text_file = filepath.with_suffix('.txt')
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write(text)
        
        print(f"💾 Saved: {filename} - '{text}'")
    except Exception as e:
        print(f"⚠️ Failed to save debug image: {e}")


# =============================================================================
# MAIN TEST LOOP
# =============================================================================

def main():
    """Main test loop"""
    print("\n" + "="*80)
    print("🎮 PaddleOCR League of Legends Test")
    print("="*80)
    print("\nThis script will:")
    print("  1. Detect League of Legends window")
    print("  2. Connect to LCU for phase detection")
    print("  3. Extract ROI from skin selection area")
    print("  4. Run PaddleOCR with GPU support")
    print("  5. Save debug images to 'ocr_debug_paddle/' folder")
    print("\n⚠️  Make sure you're in Champion Select and hovering over skins!")
    print("="*80 + "\n")
    
    # Initialize components
    user32 = init_windows_api()
    lcu = LCUClient()
    
    # Detect League client language
    league_locale = lcu.get_language()
    print(f"🌍 League Client Language: {league_locale}")
    
    # Map to PaddleOCR language
    paddle_lang = LEAGUE_TO_PADDLE_LANG.get(league_locale, 'en')
    if league_locale not in LEAGUE_TO_PADDLE_LANG:
        print(f"⚠️  Language '{league_locale}' not in mapping, using English (en)")
    else:
        print(f"📝 PaddleOCR Language: {paddle_lang}")
        # Warn if using fallback for unsupported languages
        if league_locale in ['ms_MY', 'id_ID'] and paddle_lang == 'en':
            print(f"   ⚠️  {league_locale} not supported by PaddleOCR, using English fallback")
    
    # Ask user for GPU preference
    use_gpu_input = input("\nUse GPU for OCR? (Y/n): ").strip().lower()
    use_gpu = use_gpu_input != 'n'
    
    # Use Research-Based preprocessing by default (optimal for all languages)
    skip_preprocessing = False
    use_sharp_preprocessing = True
    use_ultra_sharp = True
    print("🔬 Using RESEARCH-BASED preprocessing (bilateral filter + CLAHE + OTSU + adaptive) - OPTIMAL FOR ALL LANGUAGES")
    
    ocr, gpu_enabled = init_paddleocr(use_gpu, lang=paddle_lang)
    
    # Initialize skin database (use real NameDB if available)
    if HAS_NAME_DB:
        print("\n📥 Loading DDragon English database...")
        try:
            real_db = NameDB(lang="en_US")
            skin_db = SkinDBWrapper(real_db)
            print(f"✅ Loaded DDragon database: {len(real_db.slug_by_id)} champions")
        except Exception as e:
            print(f"⚠️  Failed to load NameDB: {e}")
            print("   Falling back to SimpleSkinDB")
            skin_db = SkinDBWrapper(SimpleSkinDB())
    else:
        print("\n⚠️  NameDB not available, using SimpleSkinDB")
        skin_db = SkinDBWrapper(SimpleSkinDB())
    
    # Initialize mss for screen capture
    try:
        import mss
    except ImportError:
        print("❌ mss not installed. Install with: pip install mss")
        sys.exit(1)
    
    print("🔄 Starting OCR loop...")
    print("   Press Ctrl+C to stop\n")
    print("-"*80)
    
    last_small = None
    last_text = ""
    last_matched_skin = None  # Track last matched skin to avoid duplicate logs
    lcu_skins_cache = {}  # Cache LCU skins per champion: {champ_id: {skin_id: skin_name_in_lang}}
    ocr_counter = 0
    loop_counter = 0
    window_found = False
    last_window_info_loop = 0
    
    try:
        with mss.mss() as sct:
            while True:
                loop_counter += 1
                now = time.time()
                
                # Find League window (no verbose spam)
                window_rect = find_league_window(user32, verbose=False)
                
                if not window_rect:
                    if window_found:  # Only print if we lost the window
                        print("⏳ League window lost, waiting...")
                        window_found = False
                    time.sleep(1.0)
                    continue
                
                # Mark window as found (only log once on state change)
                if not window_found:
                    l, t, r, b = window_rect
                    print(f"✅ League window detected: {r-l}x{b-t} at ({l}, {t})")
                    window_found = True
                
                # Check if window is focused
                if not is_league_window_focused(user32, window_rect):
                    if loop_counter % 20 == 0:  # Log every 20 loops
                        print("⏸️  League window not focused (Alt+Tab detected)")
                    time.sleep(0.2)
                    continue
                
                # Check game phase
                phase = lcu.get_phase()
                if phase != "ChampSelect":
                    if loop_counter % 20 == 0:
                        print(f"⏸️  Waiting for ChampSelect (current: {phase or 'Unknown'})")
                    time.sleep(0.5)
                    continue
                
                # Check if champion is locked
                locked_champ = lcu.get_locked_champion()
                if not locked_champ:
                    if loop_counter % 20 == 0:
                        print("⏸️  Waiting for champion lock...")
                    time.sleep(0.2)
                    continue
                
                # Log when champion is locked (only once)
                if loop_counter == 1 or not hasattr(lcu, '_last_locked_champ') or lcu._last_locked_champ != locked_champ:
                    print(f"🔒 Champion locked (ID: {locked_champ}) - OCR now active!")
                    lcu._last_locked_champ = locked_champ
                
                # Calculate ROI using fixed proportions
                l, t, r, b = window_rect
                width = r - l
                height = b - t
                
                roi_l = int(l + width * ROI_PROPORTIONS['x1_ratio'])
                roi_t = int(t + height * ROI_PROPORTIONS['y1_ratio'])
                roi_r = int(l + width * ROI_PROPORTIONS['x2_ratio'])
                roi_b = int(t + height * ROI_PROPORTIONS['y2_ratio'])
                
                # Capture ROI
                monitor = {
                    "left": roi_l,
                    "top": roi_t,
                    "width": max(8, roi_r - roi_l),
                    "height": max(8, roi_b - roi_t)
                }
                
                try:
                    shot = sct.grab(monitor)
                    frame = np.array(shot, dtype=np.uint8)[:, :, :3]  # BGR
                except Exception as e:
                    print(f"❌ Capture error: {e}")
                    time.sleep(0.2)
                    continue
                
                # Preprocess for OCR using Research-Based method (optimal for all languages)
                # Apply upscaling if needed, then Research-Based preprocessing
                if frame.shape[0] < IMAGE_UPSCALE_THRESHOLD:
                    frame = cv2.resize(frame, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                processed = prep_for_ocr_ultra_sharp(frame)
                
                # Check if image changed
                small = cv2.resize(processed, (96, 20), interpolation=cv2.INTER_AREA)
                changed = True
                
                if last_small is not None:
                    diff = np.mean(np.abs(small.astype(np.int16) - last_small.astype(np.int16))) / 255.0
                    changed = diff > OCR_DIFF_THRESHOLD
                
                last_small = small
                
                # Run OCR if image changed
                if changed:
                    ocr_counter += 1
                    print(f"\n[{ocr_counter}] 🔍 Running OCR (image changed, RESEARCH-BASED)...")
                    
                    # Run PaddleOCR
                    start_time = time.time()
                    text = recognize_text_paddleocr(ocr, processed)
                    ocr_time = (time.time() - start_time) * 1000
                    
                    if text and text != last_text:
                        print(f"   ✅ Detected: '{text}'")
                        print(f"   ⏱️  OCR time: {ocr_time:.1f}ms")
                        print(f"   🎯 GPU: {gpu_enabled}")
                        last_text = text
                        
                        # Save debug image
                        save_debug_image(processed, text, ocr_counter)
                        
                        # ============================================================
                        # SECURE MATCHING PIPELINE (Multi-Language Support)
                        # ============================================================
                        # 1. Lock Champion → Get champion ID
                        # 2. LCU API → Get skins in CLIENT LANGUAGE (KR, FR, etc.)
                        # 3. OCR → Detect text in CLIENT LANGUAGE
                        # 4. Match OCR text → LCU skins → Get skin_id
                        # 5. English DB → skin_id → English name
                        # ============================================================
                        
                        if locked_champ and text:
                            # Load skins from LCU if not cached
                            if locked_champ not in lcu_skins_cache:
                                print(f"\n🔄 Loading skins from LCU for champion {locked_champ}...")
                                lcu_skins = lcu.get_champion_skins_from_lcu(locked_champ)
                                if lcu_skins:
                                    lcu_skins_cache[locked_champ] = lcu_skins
                                else:
                                    print(f"   ⚠️  Failed to load skins from LCU, falling back to English DB")
                            
                            # Get skins in client language (KR, FR, etc.)
                            client_lang_skins = lcu_skins_cache.get(locked_champ)
                            
                            if client_lang_skins:
                                # Use champion ID as slug if not in DB
                                champ_slug = skin_db.get_champion_slug(locked_champ) or f"champ_{locked_champ}"
                                
                                # STEP 1: Match OCR text against skins in CLIENT LANGUAGE
                                # No threshold - always returns best match
                                match_result = match_skin_name(text, client_lang_skins, champ_slug)
                                
                                if match_result:
                                    skin_id, skin_name_client_lang, similarity = match_result
                                    
                                    # STEP 2: Try to get ENGLISH name from database (optional)
                                    english_skin_name = skin_db.get_english_name_by_skin_id(skin_id)
                                    
                                    # Use english name if available, otherwise use client language name
                                    display_name = english_skin_name or f"{skin_name_client_lang} (ID: {skin_id})"
                                    has_english = english_skin_name is not None
                                    
                                    skin_key = f"{champ_slug}_{skin_id}"
                                    
                                    # Only log if different from last match
                                    if skin_key != last_matched_skin:
                                        last_matched_skin = skin_key
                                        is_base = (skin_id % 1000 == 0)
                                        
                                        print(f"\n{'='*80}")
                                        print(f"🎯 SKIN MATCHED! (Multi-Language Pipeline)")
                                        print(f"{'='*80}")
                                        print(f"   Champion ID: {locked_champ} ({champ_slug})")
                                        print(f"   OCR Text (Client Lang): '{text}'")
                                        print(f"   Matched (Client Lang): '{skin_name_client_lang}'")
                                        if has_english:
                                            print(f"   English Name: '{english_skin_name}'")
                                        else:
                                            print(f"   English Name: NOT IN TEST DB (use skin_id: {skin_id})")
                                        print(f"   Skin ID: {skin_id}")
                                        print(f"   Similarity: {similarity:.1%}")
                                        print(f"   Base Skin: {is_base}")
                                        print(f"{'='*80}\n")
                            else:
                                print(f"   ⚠️  Failed to load skins from LCU for champion {locked_champ}")
                    elif text:
                        print(f"   🔄 Same text: '{text}' ({ocr_time:.1f}ms)")
                    else:
                        print(f"   ⚠️  No text detected ({ocr_time:.1f}ms)")
                
                # Small sleep to reduce CPU usage
                time.sleep(0.1)
                
    except KeyboardInterrupt:
        print("\n\n" + "="*80)
        print("🛑 Test stopped by user")
        print(f"   Total OCR runs: {ocr_counter}")
        if DEBUG_OCR:
            print(f"   Debug images saved to: ocr_debug_paddle/")
        print("="*80)


if __name__ == "__main__":
    # Disable urllib3 warnings for self-signed certificates
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    main()

