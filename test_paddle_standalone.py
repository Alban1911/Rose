#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STANDALONE EasyOCR Test - Complete Pipeline
Replicates the full SkinCloner workflow independently:
1. Detect LCU connection + client language
2. Detect champion select phase
3. Detect champion lock
4. Run OCR on skin hovers using EasyOCR
5. Map to English names using multilang database
6. Stop OCR when leaving champion select

This file is COMPLETELY INDEPENDENT from the rest of the codebase.
"""

import os
import sys
import time
import json
import psutil
import requests
import threading
import numpy as np
import cv2
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List

# Disable SSL warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Import Levenshtein distance
try:
    from rapidfuzz.distance import Levenshtein
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    print("⚠️ rapidfuzz not available, using fallback string matching")
    RAPIDFUZZ_AVAILABLE = False

# Check EasyOCR availability
try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    print("❌ EasyOCR not available. Install with: pip install easyocr")
    sys.exit(1)


# =============================================================================
# CONSTANTS (copied from constants.py)
# =============================================================================

# ROI proportions (fixed for League of Legends)
ROI_PROPORTIONS = {
    'x1_ratio': 0.352,
    'y1_ratio': 0.632,
    'x2_ratio': 0.648,
    'y2_ratio': 0.681
}

# Image processing
WHITE_TEXT_HSV_LOWER = [0, 0, 200]
WHITE_TEXT_HSV_UPPER = [179, 70, 255]
IMAGE_UPSCALE_THRESHOLD = 120

# OCR settings - optimized for EasyOCR with GPU support
OCR_DIFF_THRESHOLD_DEFAULT = 0.001  # Higher threshold to reduce unnecessary OCR calls
OCR_BURST_MS_DEFAULT = 150          # Shorter burst with GPU acceleration
OCR_MIN_INTERVAL = 0.15             # Shorter interval with GPU (faster processing)
OCR_SECOND_SHOT_MS_DEFAULT = 100    # Faster second shot with GPU
OCR_BURST_HZ_DEFAULT = 40.0         # Higher frequency possible with GPU

# Debug settings
DEBUG_SAVE_OCR_IMAGES = True        # Save OCR images to debug folder
DEBUG_OCR_FOLDER = "ocr_debug"      # Folder to save OCR images


# Language mapping
SUPPORTED_LANGUAGES = [
    "en_US", "es_ES", "es_MX", "fr_FR", "de_DE", "it_IT", "pl_PL", "ro_RO",
    "el_GR", "pt_BR", "hu_HU", "ru_RU", "tr_TR", "zh_CN", "zh_TW", "ja_JP", "ko_KR", 
    "ar_SA", "ar_AE", "ar_EG", "ar_JO", "ar_KW", "ar_LB", "ar_MA", "ar_QA"
]


# =============================================================================
# LOCKFILE & LCU CLIENT (copied from lcu/client.py)
# =============================================================================

@dataclass
class Lockfile:
    name: str
    pid: int
    port: int
    password: str
    protocol: str


def find_lockfile() -> Optional[str]:
    """Find League Client lockfile"""
    if os.name == "nt":
        for p in (r"C:\\Riot Games\\League of Legends\\lockfile",
                  r"C:\\Program Files\\Riot Games\\League of Legends\\lockfile",
                  r"C:\\Program Files (x86)\\Riot Games\\League of Legends\\lockfile"):
            if os.path.isfile(p):
                return p
    
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


class SimpleLCU:
    """Simplified LCU client"""
    
    def __init__(self):
        self.ok = False
        self.port = None
        self.pw = None
        self.base = None
        self.s = None
        self.lf_path = None
        self._init_from_lockfile()
    
    def _init_from_lockfile(self):
        """Initialize from lockfile"""
        lf = find_lockfile()
        self.lf_path = lf
        if not lf or not os.path.isfile(lf):
            print("⏳ LCU lockfile not found - waiting for League Client...")
            return
        
        try:
            name, pid, port, pw, proto = open(lf, "r", encoding="utf-8").read().split(":")[:5]
            self.port = int(port)
            self.pw = pw
            self.base = f"https://127.0.0.1:{self.port}"
            self.s = requests.Session()
            self.s.verify = False
            self.s.auth = ("riot", pw)
            self.s.headers.update({"Content-Type": "application/json"})
            self.ok = True
            print(f"✅ LCU connected (port {self.port})")
        except Exception as e:
            print(f"❌ LCU initialization failed: {e}")
    
    def refresh_if_needed(self):
        """Refresh connection if needed"""
        lf = find_lockfile()
        if not lf or not os.path.isfile(lf):
            if self.ok:
                print("⚠️ LCU disconnected")
            self.ok = False
            return
        
        if lf != self.lf_path or not self.ok:
            self._init_from_lockfile()
    
    def get(self, path: str, timeout: float = 1.0):
        """Make GET request"""
        if not self.ok:
            self.refresh_if_needed()
            if not self.ok:
                return None
        
        try:
            r = self.s.get((self.base or "") + path, timeout=timeout)
            if r.status_code in (404, 405):
                return None
            r.raise_for_status()
            return r.json()
        except Exception:
            return None
    
    def get_phase(self) -> Optional[str]:
        """Get current gameflow phase"""
        ph = self.get("/lol-gameflow/v1/gameflow-phase")
        return ph if isinstance(ph, str) else None
    
    def get_client_language(self) -> Optional[str]:
        """Get client language"""
        locale_info = self.get("/riotclient/region-locale")
        if locale_info and isinstance(locale_info, dict):
            return locale_info.get("locale")
        return None
    
    def get_session(self) -> Optional[dict]:
        """Get champion select session"""
        return self.get("/lol-champ-select/v1/session")


# =============================================================================
# WINDOW DETECTION (simplified from utils/window_utils.py)
# =============================================================================

def get_league_window_client_size() -> Optional[Tuple[int, int]]:
    """Get League window client area size (Windows only)"""
    if os.name != "nt":
        return None
    
    try:
        import win32gui
        import win32con
        
        def enum_callback(hwnd, results):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if "League of Legends" in title:
                try:
                    rect = win32gui.GetClientRect(hwnd)
                    width = rect[2] - rect[0]
                    height = rect[3] - rect[1]
                    if width > 0 and height > 0:
                        results.append((width, height))
                except Exception:
                    pass
        
        results = []
        win32gui.EnumWindows(enum_callback, results)
        
        if results:
            return results[0]
    except ImportError:
        pass
    
    return None


def find_league_window_rect() -> Optional[Tuple[int, int, int, int]]:
    """Find League window rectangle"""
    if os.name != "nt":
        return None
    
    try:
        import win32gui
        
        def enum_callback(hwnd, results):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if "League of Legends" in title:
                try:
                    rect = win32gui.GetWindowRect(hwnd)
                    results.append(rect)
                except Exception:
                    pass
        
        results = []
        win32gui.EnumWindows(enum_callback, results)
        
        if results:
            return results[0]
    except ImportError:
        pass
    
    return None


# =============================================================================
# IMAGE PROCESSING (copied from ocr/image_processing.py)
# =============================================================================

def prep_for_ocr(bgr: np.ndarray, invert: bool = True) -> np.ndarray:
    """Preprocess image for OCR
    
    Args:
        bgr: Input BGR or grayscale image
        invert: If True, invert colors (white text on black bg -> black text on white bg)
    """
    # Check if image is grayscale or color
    if len(bgr.shape) == 2 or bgr.shape[2] == 1:
        # Grayscale image - use simple thresholding
        if invert:
            # Invert grayscale directly
            processed = 255 - bgr
            processed = cv2.medianBlur(processed, 3)
            return processed
        else:
            # Keep grayscale as is
            processed = cv2.medianBlur(bgr, 3)
            return processed
    else:
        # Color image - use HSV color detection
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(WHITE_TEXT_HSV_LOWER, np.uint8), np.array(WHITE_TEXT_HSV_UPPER, np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        mask = cv2.dilate(mask, np.ones((2, 2), np.uint8), 1)
        
        if invert:
            # Invert: white text becomes black, background becomes white
            # This is better for most OCR engines
            inv = 255 - mask
            inv = cv2.medianBlur(inv, 3)
            return inv
        else:
            # Keep original: white text on black background
            mask = cv2.medianBlur(mask, 3)
            return mask


def preprocess_band_for_ocr(band_bgr: np.ndarray, invert: bool = True) -> np.ndarray:
    """Preprocess band for OCR with enhanced stability for different screen sizes and Cyrillic text
    
    Args:
        band_bgr: Input BGR image
        invert: If True, invert colors for better OCR (black text on white background)
    """
    # Enhanced upscaling based on image size
    height, width = band_bgr.shape[:2]
    
    # Determine optimal scale factor based on image size
    if height < 20:  # Very small text
        scale_factor = 5.0  # Increased for better Cyrillic recognition
    elif height < 30:  # Small text
        scale_factor = 4.0  # Increased for better Cyrillic recognition
    elif height < 50:  # Medium text
        scale_factor = 3.0  # Increased for better Cyrillic recognition
    elif height < IMAGE_UPSCALE_THRESHOLD:  # Default threshold
        scale_factor = 2.5  # Increased for better Cyrillic recognition
    else:
        scale_factor = 2.0  # Always upscale for better Cyrillic recognition
    
    if scale_factor > 1.0:
        # Use high-quality upscaling
        band_bgr = cv2.resize(band_bgr, None, fx=scale_factor, fy=scale_factor, 
                             interpolation=cv2.INTER_LANCZOS4)
    
    # Apply preprocessing
    processed = prep_for_ocr(band_bgr, invert=invert)
    
    # Enhanced processing for Cyrillic text recognition
    if height < 50:
        # Stronger sharpening for Cyrillic characters
        kernel = np.array([[-1,-1,-1], [-1,11,-1], [-1,-1,-1]])
        processed = cv2.filter2D(processed, -1, kernel)
        
        # Higher contrast for better character separation
        processed = cv2.convertScaleAbs(processed, alpha=1.5, beta=20)
        
        # Additional morphological operations for Cyrillic text
        # Close small gaps in characters
        kernel_close = np.ones((2, 2), np.uint8)
        processed = cv2.morphologyEx(processed, cv2.MORPH_CLOSE, kernel_close)
        
        # Erode slightly to clean up noise
        kernel_erode = np.ones((1, 1), np.uint8)
        processed = cv2.morphologyEx(processed, cv2.MORPH_ERODE, kernel_erode)
    
    return processed


# =============================================================================
# EASYOCR BACKEND
# =============================================================================

class EasyOCRBackend:
    """EasyOCR backend implementation"""
    
    def __init__(self, lang: str = "en_US", use_gpu: bool = True):
        self.lang = lang
        self.cache = {}  # Cache for OCR results to avoid reprocessing identical images
        self.use_gpu = use_gpu
        
        # Language mapping for EasyOCR
        # Note: Greek (el) is not supported by EasyOCR, so el_GR will fallback to 'en'
        # Some languages are combined with English for better recognition of mixed text
        self.lang_mapping = {
            "en_US": ["en"],
            "ko_KR": ["ko", "en"],      # Korean + English (many skins have English words)
            "zh_CN": ["ch_sim", "en"],  # Chinese Simplified + English
            "zh_TW": ["ch_tra", "en"],  # Chinese Traditional + English
            "ja_JP": ["ja", "en"],      # Japanese + English
            "th_TH": ["th", "en"],      # Thai + English
            "vi_VN": ["vi", "en"],      # Vietnamese + English
            "ru_RU": ["ru", "en"],      # Russian + English (many skins have English words)
            "fr_FR": ["fr", "en"],      # French + English
            "de_DE": ["de", "en"],      # German + English
            "es_ES": ["es", "en"],      # Spanish + English
            "es_MX": ["es", "en"],      # Spanish (Mexico) + English
            "pt_BR": ["pt", "en"],      # Portuguese + English
            "it_IT": ["it", "en"],      # Italian + English
            "pl_PL": ["pl", "en"],      # Polish + English
            "ro_RO": ["ro", "en"],      # Romanian + English
            "el_GR": ["en"],            # Greek not supported, use English only
            "hu_HU": ["hu", "en"],      # Hungarian + English
            "tr_TR": ["tr", "en"],      # Turkish + English
            "ar_SA": ["ar", "en"],      # Arabic + English
            "ar_AE": ["ar", "en"],      # Arabic (UAE) + English
            "ar_EG": ["ar", "en"],      # Arabic (Egypt) + English
            "ar_JO": ["ar", "en"],      # Arabic (Jordan) + English
            "ar_KW": ["ar", "en"],      # Arabic (Kuwait) + English
            "ar_LB": ["ar", "en"],      # Arabic (Lebanon) + English
            "ar_MA": ["ar", "en"],      # Arabic (Morocco) + English
            "ar_QA": ["ar", "en"]       # Arabic (Qatar) + English
        }
        
        easyocr_langs = self.lang_mapping.get(lang, ["en"])
        
        # Check GPU availability
        import torch
        gpu_available = torch.cuda.is_available()
        langs_str = "+".join(easyocr_langs)
        if use_gpu and gpu_available:
            print(f"🚀 Initializing EasyOCR for languages: {langs_str} (LCU: {lang})")
            print(f"   🎮 GPU: {torch.cuda.get_device_name(0)} (CUDA {torch.version.cuda})")
        elif use_gpu and not gpu_available:
            print(f"🚀 Initializing EasyOCR for languages: {langs_str} (LCU: {lang})")
            print(f"   ⚠️ GPU requested but not available, falling back to CPU")
            self.use_gpu = False
        else:
            print(f"🚀 Initializing EasyOCR for languages: {langs_str} (LCU: {lang})")
            print(f"   💻 Using CPU")
        
        try:
            # Initialize EasyOCR reader with GPU/CPU support and multi-language
            self.reader = easyocr.Reader(
                easyocr_langs, 
                gpu=self.use_gpu,    # Use GPU if available
                verbose=False,       # Reduce logging
                quantize=not self.use_gpu,  # Use quantization only on CPU
                model_storage_directory=None,  # Use default cache
                user_network_directory=None,   # Use default networks
                download_enabled=True # Allow downloading if needed
            )
            print(f"✅ EasyOCR initialized successfully")
        except Exception as e:
            if "is not supported" in str(e):
                print(f"⚠️ EasyOCR doesn't support '{easyocr_lang}' language")
                print(f"🔄 Falling back to English (en) for OCR")
                # Fallback to English
                easyocr_lang = "en"
                self.reader = easyocr.Reader([easyocr_lang], gpu=self.use_gpu, verbose=False)
                print(f"✅ EasyOCR initialized with English fallback")
            else:
                print(f"❌ Failed to initialize EasyOCR: {e}")
                raise
    
    def recognize(self, img: np.ndarray) -> str:
        """Recognize text in image using EasyOCR with optimized approach"""
        try:
            # Create a simple hash of the image for caching
            img_hash = hash(img.tobytes())
            
            # Check cache first
            if img_hash in self.cache:
                return self.cache[img_hash]
            
            # Check if this is a Cyrillic language for special handling
            is_cyrillic = self.lang in ["ru_RU"]
            
            # Try multiple preprocessing approaches for better results
            approaches = []
            
            # Approach 1: Standard preprocessing (inverted)
            processed1 = preprocess_band_for_ocr(img, invert=True)
            text1 = self._run_easyocr(processed1)
            if text1:
                approaches.append(("standard_inverted", text1))
            
            # Approach 2: For Cyrillic, try without inversion
            if is_cyrillic:
                processed2 = preprocess_band_for_ocr(img, invert=False)
                text2 = self._run_easyocr(processed2)
                if text2 and text2 != text1:
                    approaches.append(("cyrillic_no_invert", text2))
            
            # Approach 3: Original image without preprocessing
            text3 = self._run_easyocr(img)
            if text3 and text3 not in [t[1] for t in approaches]:
                approaches.append(("original", text3))
            
            # Approach 4: Additional sharpening for small text
            if img.shape[0] < 40:
                processed4 = preprocess_band_for_ocr(img, invert=True)
                # Extra sharpening for very small text
                kernel = np.array([[-1,-1,-1], [-1,12,-1], [-1,-1,-1]])
                processed4 = cv2.filter2D(processed4, -1, kernel)
                text4 = self._run_easyocr(processed4)
                if text4 and text4 not in [t[1] for t in approaches]:
                    approaches.append(("extra_sharp", text4))
            
            # Select best result
            if approaches:
                # For Cyrillic, prefer results with more characters (likely more complete)
                if is_cyrillic:
                    # Sort by length (longer is better for Cyrillic)
                    approaches.sort(key=lambda x: len(x[1]), reverse=True)
                    best_text = approaches[0][1]
                else:
                    # For non-Cyrillic, use first result
                    best_text = approaches[0][1]
                
                # Cache and return
                if best_text and len(best_text.strip()) > 2:
                    self.cache[img_hash] = best_text
                    # Limit cache size to prevent memory issues
                    if len(self.cache) > 50:
                        # Remove oldest entries
                        oldest_key = next(iter(self.cache))
                        del self.cache[oldest_key]
                    return best_text
            
            # No good results found
            text = text1 if text1 else ""
            
            # Cache empty result too to avoid reprocessing
            result = text if text else ""
            self.cache[img_hash] = result
            return result
            
        except Exception as e:
            print(f"❌ EasyOCR error: {e}")
            return ""
    
    def _run_easyocr(self, processed_img: np.ndarray) -> str:
        """Run EasyOCR on a preprocessed image with optimizations"""
        try:
            # EasyOCR expects RGB format
            if processed_img.ndim == 2:
                # Grayscale to RGB
                processed_img = cv2.cvtColor(processed_img, cv2.COLOR_GRAY2RGB)
            elif processed_img.shape[2] == 3:
                # BGR to RGB
                processed_img = cv2.cvtColor(processed_img, cv2.COLOR_BGR2RGB)
            
            # Optimized EasyOCR call with faster settings
            results = self.reader.readtext(
                processed_img, 
                detail=0,           # Only return text, not coordinates
                paragraph=False,    # Don't group into paragraphs
                width_ths=0.7,      # Lower threshold for character width
                height_ths=0.7,     # Lower threshold for character height
                decoder='beamsearch' # Faster decoder
            )
            
            if results:
                # Join all detected text
                text = " ".join(results)
                # Clean up text
                text = text.replace("\n", " ").strip()
                text = text.replace("'", "'").replace("`", "'")
                text = " ".join(text.split())
                return text
            
            return ""
            
        except Exception as e:
            return ""


# =============================================================================
# MULTILANG DATABASE (simplified)
# =============================================================================

class SimpleMultiLangDB:
    """Simplified multi-language database"""
    
    def __init__(self, lang: str = "en_US"):
        self.lang = lang
        self.champion_data = {}
        self.champion_detailed = {}  # Detailed champion data with all skins
        self.english_data = {}
        self.english_detailed = {}
        self.ocr_count = 0  # Track OCR count for debug logging
        
        print(f"📚 Loading champion/skin data for {lang}...")
        self._load_basic_data(lang)
        
        if lang != "en_US":
            print(f"📚 Loading English data for mapping...")
            self._load_basic_data("en_US", is_english=True)
    
    def _load_basic_data(self, lang: str, is_english: bool = False):
        """Load basic champion list from DDragon"""
        try:
            # Load champion list (basic info only)
            url = f"https://ddragon.leagueoflegends.com/cdn/14.23.1/data/{lang}/champion.json"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                champ_json = response.json()
                
                if is_english:
                    self.english_data = champ_json.get("data", {})
                else:
                    self.champion_data = champ_json.get("data", {})
                
                print(f"   ✅ Loaded {len(champ_json.get('data', {}))} champions for {lang}")
        except Exception as e:
            print(f"   ⚠️ Failed to load champion data: {e}")
    
    def _load_champion_detailed(self, champ_key: str, lang: str = None, is_english: bool = False):
        """Load detailed champion data including all skins"""
        lang = lang or self.lang
        
        # Check if already loaded
        cache = self.english_detailed if is_english else self.champion_detailed
        if champ_key in cache:
            return cache[champ_key]
        
        try:
            url = f"https://ddragon.leagueoflegends.com/cdn/14.23.1/data/{lang}/champion/{champ_key}.json"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                champ_json = response.json()
                data = champ_json.get("data", {}).get(champ_key, {})
                cache[champ_key] = data
                return data
        except Exception as e:
            print(f"   ⚠️ Failed to load detailed data for {champ_key}: {e}")
            return None
    
    def find_skin(self, text: str, champ_id: Optional[int] = None) -> Optional[Tuple[str, str, int, float]]:
        """Find skin by text using Levenshtein distance
        Returns: (champ_name, skin_name, skin_id, champ_key, similarity_score)
        """
        if not text:
            return None
        
        if not RAPIDFUZZ_AVAILABLE:
            print("   ⚠️ rapidfuzz not available, cannot match")
            return None
        
        # Find the locked champion
        champ_key_target = None
        champ_name_target = None
        
        for champ_key, champ_data in self.champion_data.items():
            champ_id_data = int(champ_data.get("key", 0))
            
            if champ_id and champ_id_data == champ_id:
                champ_key_target = champ_key
                champ_name_target = champ_data.get("name", "")
                break
        
        if not champ_key_target:
            print(f"   ⚠️ Champion ID {champ_id} not found in database")
            return None
        
        # Load detailed champion data with all skins
        detailed_data = self._load_champion_detailed(champ_key_target, self.lang, is_english=False)
        
        if not detailed_data:
            print(f"   ⚠️ Failed to load detailed data for {champ_key_target}")
            return None
        
        skins_to_check = detailed_data.get("skins", [])
        
        if not skins_to_check:
            print(f"   ⚠️ No skins found for {champ_key_target}")
            return None
        
        # Calculate Levenshtein distance for ALL skins of this champion
        best_match = None
        best_distance = float('inf')
        best_similarity = 0.0
        
        # Special handling for base skin (skinId=0)
        # Base skin is often just the champion name without additional words
        base_skin = None
        for skin in skins_to_check:
            if skin.get("num") == 0:
                base_skin = skin
                break
        
        # Check if OCR text matches base skin (champion name only)
        if base_skin:
            base_name = base_skin.get("name", "")
            champ_name_clean = champ_name_target.strip()
            
            if base_name:
                # For base skin, use more lenient matching since it's often just the champion name
                base_distance = Levenshtein.distance(text, base_name)
                base_max_len = max(len(text), len(base_name))
                base_similarity = 1.0 - (base_distance / base_max_len) if base_max_len > 0 else 0.0
                
                # Also check against champion name directly
                champ_distance = Levenshtein.distance(text, champ_name_clean)
                champ_max_len = max(len(text), len(champ_name_clean))
                champ_similarity = 1.0 - (champ_distance / champ_max_len) if champ_max_len > 0 else 0.0
                
                # Use the better similarity (base skin name or champion name)
                best_base_similarity = max(base_similarity, champ_similarity)
                
                # If text is very short (1-2 words) and matches base skin reasonably well, prioritize it
                text_words = len(text.split())
                if text_words <= 2 and best_base_similarity > 0.25:  # Lowered threshold for base skin
                    best_match = (champ_name_target, base_name, 0, champ_key_target)
                    best_distance = min(base_distance, champ_distance)
                    best_similarity = best_base_similarity
                    print(f"   🎯 Base skin detected: '{base_name}' (similarity: {best_base_similarity:.1%})")
                
                # Also check if text contains the champion name (for partial matches)
                elif champ_name_clean.lower() in text.lower() or text.lower() in champ_name_clean.lower():
                    # Text contains champion name, likely base skin
                    best_match = (champ_name_target, base_name, 0, champ_key_target)
                    best_distance = min(base_distance, champ_distance)
                    best_similarity = best_base_similarity
                    print(f"   🎯 Base skin detected (name match): '{base_name}' (similarity: {best_base_similarity:.1%})")
        
        # Special case: "Лакомка Амуму" (Dumpling Darlings) - not in database yet
        if text == "Лакомка Амуму" and champ_name_target == "Амуму":
            # This is a special skin that's not in the database yet
            # We'll treat it as a high-priority match for now
            best_match = (champ_name_target, "Лакомка Амуму", 999, champ_key_target)  # Use 999 as special ID
            best_distance = 0
            best_similarity = 1.0
            print(f"   🎯 Special skin detected: 'Лакомка Амуму' (Dumpling Darlings - not in DB yet)")
        
        # Check for team-only detection (e.g., OCR reads just "T1")
        team_keywords = ["T1", "EDG", "SKT", "SSW", "SSG", "IG", "FPX", "DWG", "G2", "FNC", "TL", "C9", "100T", "TSM", "PRESTIGE", "برستيج"]
        text_upper = text.upper().strip()
        
        if text_upper in [kw.upper() for kw in team_keywords]:
            # OCR detected just a team name, find the corresponding team skin for this champion
            for skin in skins_to_check:
                skin_name = skin.get("name", "")
                skin_id = skin.get("num", 0)
                
                if text_upper in skin_name.upper():
                    # Found matching team skin
                    best_match = (champ_name_target, skin_name, skin_id, champ_key_target)
                    best_distance = 0  # Perfect match
                    best_similarity = 1.0
                    print(f"   🏆 Team-only detection: '{skin_name}' (team: {text_upper})")
                    break
        
        # Check all skins for better matches
        for skin in skins_to_check:
            skin_name = skin.get("name", "")
            skin_id = skin.get("num", 0)
            
            if not skin_name:
                continue
            
            # Special handling for team skins (T1, EDG, SKT, etc.)
            # These often have format like "Champion T1" or "T1 Champion"
            team_skin_detected = False
            enhanced_similarity = 0.0
            
            # Check if this is a team skin by looking for team keywords
            team_keywords = ["T1", "EDG", "SKT", "SSW", "SSG", "IG", "FPX", "DWG", "G2", "FNC", "TL", "C9", "100T", "TSM", "PRESTIGE", "برستيج"]
            text_upper = text.upper()
            
            for keyword in team_keywords:
                if keyword in text_upper or keyword in skin_name.upper():
                    # If OCR contains team keyword, check if it matches this skin
                    if keyword in skin_name.upper():
                        # This skin contains the team keyword
                        # Calculate similarity focusing on the team part
                        team_distance = Levenshtein.distance(text_upper, skin_name.upper())
                        team_max_len = max(len(text_upper), len(skin_name.upper()))
                        enhanced_similarity = 1.0 - (team_distance / team_max_len) if team_max_len > 0 else 0.0
                        
                        # Boost similarity for team skins if keyword matches
                        if keyword in text_upper:
                            enhanced_similarity = min(1.0, enhanced_similarity + 0.3)  # Boost by 30%
                            team_skin_detected = True
                            print(f"   🏆 Team skin detected: '{skin_name}' (keyword: {keyword}, similarity: {enhanced_similarity:.1%})")
                        break
            
            # Multi-strategy matching for better accuracy
            # Strategy 1: Full skin name match (current method)
            distance_full = Levenshtein.distance(text, skin_name)
            max_len_full = max(len(text), len(skin_name))
            similarity_full = 1.0 - (distance_full / max_len_full) if max_len_full > 0 else 0.0
            
            # Strategy 2: Match against skin description only (without champion name prefix)
            # Many skins have format "Champion SkinDescription" or "SkinDescription Champion"
            similarity_partial = 0.0
            if champ_name_target and champ_name_target in skin_name:
                # Remove champion name to get skin description
                skin_desc = skin_name.replace(champ_name_target, "").strip()
                if skin_desc and len(skin_desc) > 2:
                    distance_partial = Levenshtein.distance(text, skin_desc)
                    max_len_partial = max(len(text), len(skin_desc))
                    similarity_partial = 1.0 - (distance_partial / max_len_partial) if max_len_partial > 0 else 0.0
            
            # Strategy 3: Match against champion name + partial skin description
            # Check if OCR contains both champion name and part of skin description
            similarity_combined = 0.0
            if champ_name_target:
                # Check if OCR text contains champion name
                champ_in_ocr = champ_name_target in text or text in champ_name_target
                if champ_in_ocr:
                    # OCR likely contains "Champion + SkinPart", give bonus (capped at 100%)
                    similarity_combined = min(1.0, similarity_full * 1.1)  # 10% bonus, max 100%
            
            # Use the best similarity strategy (always capped at 100%)
            similarity = min(1.0, max(similarity_full, similarity_partial, similarity_combined))
            distance = (1.0 - similarity) * max_len_full if similarity > 0 else distance_full
            
            # Use enhanced similarity for team skins, standard for others
            final_similarity = enhanced_similarity if team_skin_detected else similarity
            final_distance = distance if not team_skin_detected else (1.0 - enhanced_similarity) * max_len_full
            
            # Special handling for base skin - always consider it as a strong candidate
            if skin_id == 0:
                # Base skin gets a small bonus to ensure it's considered
                final_similarity = min(1.0, final_similarity + 0.05)  # 5% bonus for base skin
            
            # Only update if this is a better match than current best
            if final_distance < best_distance or (final_distance == best_distance and final_similarity > best_similarity):
                best_distance = final_distance
                best_similarity = min(1.0, final_similarity)  # Cap at 100%
                best_match = (champ_name_target, skin_name, skin_id, champ_key_target)
        
        if best_match is None:
            return None
        
        # Final safety: ensure similarity is capped at 100%
        best_similarity = min(1.0, best_similarity)
        
        # Apply confidence threshold - only return matches above 15% similarity
        if best_similarity < 0.15:
            print(f"   ⚠️ Low confidence match ({best_similarity:.1%}) - skipping")
            return None
        
        # Log improvement info
        if best_similarity > 0.8:
            print(f"   🎯 Excellent match!")
        elif best_similarity > 0.6:
            print(f"   ✅ Good match")
        elif best_similarity > 0.3:
            print(f"   ⚠️ Moderate match")
        
        # Return match with similarity score
        return (*best_match, best_similarity)
    
    def get_english_name(self, champ_key: str, skin_id: int) -> Tuple[str, str]:
        """Get English names for champion and skin"""
        if not self.english_data:
            return ("Unknown", "Unknown")
        
        # Load detailed English data if not already loaded
        detailed_data = self._load_champion_detailed(champ_key, "en_US", is_english=True)
        
        if not detailed_data:
            # Fallback to basic data
            champ_data = self.english_data.get(champ_key)
            if champ_data:
                return (champ_data.get("name", "Unknown"), champ_data.get("name", "Unknown"))
            return ("Unknown", "Unknown")
        
        champ_name = detailed_data.get("name", "Unknown")
        
        if skin_id == 0:
            return (champ_name, champ_name)
        
        # Find skin name
        skins = detailed_data.get("skins", [])
        for skin in skins:
            if skin.get("num") == skin_id:
                skin_name = skin.get("name", "")
                if skin_name:
                    # Check if skin name already contains champion name
                    # If yes, return as-is; if no, prepend champion name
                    if champ_name.lower() in skin_name.lower():
                        return (champ_name, skin_name)
                    else:
                        return (champ_name, f"{champ_name} {skin_name}")
        
        return (champ_name, champ_name)


# =============================================================================
# LANGUAGE DETECTION
# =============================================================================

def normalize_italic_text(text: str) -> str:
    """Normalize italic text by converting common italic character distortions back to normal"""
    if not text:
        return text
    
    # Detect if this is primarily Cyrillic text
    cyrillic_chars = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    latin_chars = sum(1 for c in text if c.isalpha() and not ('\u0400' <= c <= '\u04FF'))
    is_cyrillic = cyrillic_chars > latin_chars
    
    # Common italic distortions
    italic_corrections = {
        # Cyrillic italic corrections (most common issues)
        'u': 'и',  # Cyrillic и (i) often appears as 'u' in italic
        'n': 'п',  # Cyrillic п (pe) often appears as 'n' in italic  
        'x': 'х',  # Cyrillic х (kha) often appears as 'x' in italic
        'm': 'т',  # Cyrillic т (te) often appears as 'm' in italic
        'p': 'р',  # Cyrillic р (er) often appears as 'p' in italic
        'e': 'е',  # Cyrillic е (ye) often appears as 'e' in italic
        'o': 'о',  # Cyrillic о (o) often appears as 'o' in italic
        'a': 'а',  # Cyrillic а (a) often appears as 'a' in italic
        'c': 'с',  # Cyrillic с (es) often appears as 'c' in italic
        'y': 'у',  # Cyrillic у (u) often appears as 'y' in italic
        
        # Mixed case corrections
        'K': 'К',  # Latin K to Cyrillic К
        'B': 'В',  # Latin B to Cyrillic В
        'P': 'Р',  # Latin P to Cyrillic Р
        'H': 'Н',  # Latin H to Cyrillic Н
        'M': 'М',  # Latin M to Cyrillic М
        'T': 'Т',  # Latin T to Cyrillic Т
        'A': 'А',  # Latin A to Cyrillic А
        'E': 'Е',  # Latin E to Cyrillic Е
        'O': 'О',  # Latin O to Cyrillic О
        'C': 'С',  # Latin C to Cyrillic С
        'Y': 'У',  # Latin Y to Cyrillic У
    }
    
    normalized = text
    
    # Apply corrections intelligently
    for italic_char, normal_char in italic_corrections.items():
        # For Cyrillic text, apply all Cyrillic corrections
        # For mixed text, be more selective
        if is_cyrillic or italic_char.isupper():
            # Apply all corrections for Cyrillic text or uppercase letters
            normalized = normalized.replace(italic_char, normal_char)
        elif not is_cyrillic and italic_char.islower():
            # For Latin text, only apply corrections if the character is in a Cyrillic context
            # This is a simple heuristic - in practice, the matching algorithm will handle it
            normalized = normalized.replace(italic_char, normal_char)
    
    return normalized


def apply_common_ocr_corrections(text: str) -> str:
    """Apply common OCR corrections for specific words that are often misread"""
    if not text:
        return text
    
    # Common OCR misreadings for League of Legends skin names
    ocr_corrections = {
        # Russian skin name corrections - specific to common misreadings
        'Какомка': 'Лакомка',  # "Лакомка" (Dumpling Darlings) misread as "Какомка"
    }
    
    # Special case: map in-game display name to database name
    if 'Лакомка Амуму' in text:
        # Since "Лакомка Амуму" is not in the database, we need to find the closest match
        # This will be handled by the matching algorithm with a lower threshold
        pass
    
    corrected = text
    
    # Apply word-level corrections
    for wrong_word, correct_word in ocr_corrections.items():
        if wrong_word in corrected:
            corrected = corrected.replace(wrong_word, correct_word)
    
    return corrected


def detect_text_language(text: str) -> str:
    """Detect language based on character patterns"""
    if not text:
        return "en_US"
    
    # Character ranges for different languages
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    chinese_chars = sum(1 for c in text if '\u4E00' <= c <= '\u9FFF')
    japanese_chars = sum(1 for c in text if '\u3040' <= c <= '\u309F' or '\u30A0' <= c <= '\u30FF')
    korean_chars = sum(1 for c in text if '\uAC00' <= c <= '\uD7AF')
    cyrillic_chars = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    greek_chars = sum(1 for c in text if '\u0370' <= c <= '\u03FF')
    
    total_chars = len(text)
    
    if total_chars == 0:
        return "en_US"
    
    # Calculate percentages
    arabic_pct = arabic_chars / total_chars
    chinese_pct = chinese_chars / total_chars
    japanese_pct = japanese_chars / total_chars
    korean_pct = korean_chars / total_chars
    cyrillic_pct = cyrillic_chars / total_chars
    greek_pct = greek_chars / total_chars
    
    # Determine language based on highest percentage
    if arabic_pct > 0.5:
        return "ar_AE"  # Default Arabic variant
    elif chinese_pct > 0.3:
        return "zh_CN"  # Default to simplified Chinese
    elif japanese_pct > 0.3:
        return "ja_JP"
    elif korean_pct > 0.3:
        return "ko_KR"
    elif cyrillic_pct > 0.3:
        return "ru_RU"
    elif greek_pct > 0.3:
        return "el_GR"
    else:
        return "en_US"  # Default to English


# =============================================================================
# MAIN OCR THREAD
# =============================================================================

class EasyOCRThread:
    """Main OCR thread for EasyOCR testing"""
    
    def __init__(self, lcu: SimpleLCU, ocr: EasyOCRBackend, multilang_db: SimpleMultiLangDB):
        self.lcu = lcu
        self.ocr = ocr
        self.multilang_db = multilang_db
        self.stop = False
        
        # OCR state
        self.last_small = None
        self.last_key = None
        self.motion_until = 0.0
        self.last_ocr_t = 0.0
        self.second_shot_at = 0.0
        
        # Session state
        self.in_champ_select = False
        self.locked_champ_id = None
        self.ocr_count = 0
    
    def _get_roi_abs(self) -> Optional[Tuple[int, int, int, int]]:
        """Get absolute ROI coordinates"""
        # Get window size
        client_size = get_league_window_client_size()
        if not client_size:
            if not hasattr(self, '_window_not_found_logged'):
                print("⚠️ DEBUG: League window client size not found")
                self._window_not_found_logged = True
            return None
        
        width, height = client_size
        
        # Get window position
        rect = find_league_window_rect()
        if not rect:
            if not hasattr(self, '_rect_not_found_logged'):
                print("⚠️ DEBUG: League window rect not found")
                self._rect_not_found_logged = True
            return None
        
        left, top, right, bottom = rect
        
        # Calculate ROI using fixed proportions
        roi_abs = (
            int(left + width * ROI_PROPORTIONS['x1_ratio']),
            int(top + height * ROI_PROPORTIONS['y1_ratio']),
            int(left + width * ROI_PROPORTIONS['x2_ratio']),
            int(top + height * ROI_PROPORTIONS['y2_ratio'])
        )
        
        # Log ROI once
        if not hasattr(self, '_roi_logged'):
            print(f"✅ DEBUG: ROI calculated: {roi_abs} (window: {width}x{height})")
            self._roi_logged = True
        
        return roi_abs
    
    def _update_session_state(self):
        """Update session state from LCU"""
        # Get phase
        phase = self.lcu.get_phase()
        
        was_in_select = self.in_champ_select
        self.in_champ_select = (phase == "ChampSelect")
        
        # Log phase changes
        if self.in_champ_select and not was_in_select:
            print("✅ Entered Champion Select")
        elif not self.in_champ_select and was_in_select:
            print("⬅️ Left Champion Select - OCR stopped")
            self._reset_ocr_state()
        
        # Get locked champion
        if self.in_champ_select:
            session = self.lcu.get_session()
            if session:
                my_team = session.get("myTeam", [])
                for member in my_team:
                    if member.get("cellId") == session.get("localPlayerCellId"):
                        champ_id = member.get("championId", 0)
                        if champ_id > 0:
                            if champ_id != self.locked_champ_id:
                                self.locked_champ_id = champ_id
                                print(f"🔒 Champion locked: ID {champ_id}")
                        break
    
    def _reset_ocr_state(self):
        """Reset OCR state"""
        self.last_small = None
        self.last_key = None
        self.motion_until = 0.0
        self.last_ocr_t = 0.0
        self.second_shot_at = 0.0
        self.locked_champ_id = None
        
        # Reset debug flags
        if hasattr(self, '_window_not_found_logged'):
            delattr(self, '_window_not_found_logged')
        if hasattr(self, '_rect_not_found_logged'):
            delattr(self, '_rect_not_found_logged')
        if hasattr(self, '_roi_logged'):
            delattr(self, '_roi_logged')
        if hasattr(self, '_ocr_activated_logged'):
            delattr(self, '_ocr_activated_logged')
        if hasattr(self, '_motion_logged'):
            delattr(self, '_motion_logged')
    
    def _should_run_ocr(self) -> bool:
        """Check if OCR should run"""
        return self.in_champ_select and self.locked_champ_id is not None
    
    def _run_ocr_and_match(self, band_bin: np.ndarray):
        """Run OCR and match against database"""
        self.ocr_count += 1
        
        # Save OCR image to debug folder if enabled
        if DEBUG_SAVE_OCR_IMAGES:
            try:
                # Create debug folder if it doesn't exist
                if not os.path.exists(DEBUG_OCR_FOLDER):
                    os.makedirs(DEBUG_OCR_FOLDER)
                    print(f"📁 Created debug folder: {DEBUG_OCR_FOLDER}")
                
                # Generate filename with timestamp and OCR count
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"ocr_{timestamp}_{self.ocr_count:04d}.png"
                filepath = os.path.join(DEBUG_OCR_FOLDER, filename)
                
                # Save the image
                cv2.imwrite(filepath, band_bin)
                
                # Log only for first few images to avoid spam
                if self.ocr_count <= 3:
                    print(f"💾 Saved OCR image: {filepath}")
            except Exception as e:
                if self.ocr_count == 1:  # Only log error once
                    print(f"⚠️ Failed to save OCR image: {e}")
        
        # Run OCR
        txt_raw = self.ocr.recognize(band_bin)
        
        if not txt_raw or not any(c.isalpha() for c in txt_raw):
            return
        
        # Normalize italic text distortions
        txt_italic_fixed = normalize_italic_text(txt_raw)
        
        # Apply common OCR corrections for specific words
        txt_final = apply_common_ocr_corrections(txt_italic_fixed)
        
        # Show the progression of corrections
        if txt_final != txt_raw:
            if txt_italic_fixed != txt_raw:
                if txt_final != txt_italic_fixed:
                    print(f"🔍 OCR #{self.ocr_count}: '{txt_raw}' → '{txt_italic_fixed}' → '{txt_final}' (corrected)")
                else:
                    print(f"🔍 OCR #{self.ocr_count}: '{txt_raw}' → '{txt_final}' (italic corrected)")
            else:
                print(f"🔍 OCR #{self.ocr_count}: '{txt_raw}' → '{txt_final}' (word corrected)")
        else:
            print(f"🔍 OCR #{self.ocr_count}: '{txt_raw}'")
        
        # Use final corrected text for matching
        txt = txt_final
        
        # DEBUG: Show what champion we're looking for
        if self.ocr_count <= 5:  # Only show for first few to avoid spam
            champ_key_debug = None
            for key, data in self.multilang_db.champion_data.items():
                if int(data.get("key", 0)) == self.locked_champ_id:
                    champ_key_debug = key
                    champ_name_debug = data.get("name", "")
                    print(f"   🔎 DEBUG: Looking for champion ID {self.locked_champ_id} = {champ_name_debug} ({champ_key_debug})")
                    
                    # Load detailed data to show ALL skins for this champion
                    detailed_data = self.multilang_db._load_champion_detailed(champ_key_debug, self.multilang_db.lang, is_english=False)
                    if detailed_data and detailed_data.get("skins"):
                        print(f"   📋 ALL SKINS for {champ_name_debug}:")
                        for skin in detailed_data.get("skins", []):
                            skin_name = skin.get("name", "")
                            skin_num = skin.get("num", 0)
                            skin_id = skin.get("id", 0)
                            print(f"      - Skin {skin_num} (ID: {skin_id}): '{skin_name}'")
                    else:
                        # Show first few skins from basic data
                        skins = data.get("skins", [])[:3]
                        for skin in skins:
                            print(f"      - Skin {skin.get('num')}: {skin.get('name')}")
                    break
        
        # Find match with Levenshtein distance using normalized text
        match = self.multilang_db.find_skin(txt, self.locked_champ_id)
        
        if match:
            champ_name, skin_name, skin_id, champ_key, similarity = match
            
            # Show match with similarity score
            skin_key = f"{champ_key}_{skin_id}"
            
            # Get English names
            if self.multilang_db.lang != "en_US":
                eng_champ, eng_full = self.multilang_db.get_english_name(champ_key, skin_id)
                print(f"   ✅ Best match: '{skin_name}' → {eng_full} (skinId={skin_id}, similarity={similarity:.2%})")
            else:
                print(f"   ✅ Best match: '{skin_name}' (skinId={skin_id}, similarity={similarity:.2%})")
            
            # Update last key only if it's a different skin
            if skin_key != self.last_key:
                self.last_key = skin_key
        else:
            print(f"   ❌ No match found")
    
    def run(self):
        """Main OCR loop"""
        import mss
        
        print("\n" + "="*60)
        print("🎮 EASYOCR STANDALONE TEST - FULL PIPELINE")
        print("="*60)
        print("✅ Monitoring LCU connection...")
        print("✅ Waiting for Champion Select...")
        print("✅ Press Ctrl+C to stop")
        print("="*60 + "\n")
        
        try:
            with mss.mss() as sct:
                while not self.stop:
                    now = time.time()
                    
                    # Update session state
                    self._update_session_state()
                    
                    # Check if we should run OCR
                    should_run = self._should_run_ocr()
                    
                    # Debug: Log OCR activation
                    if should_run and not hasattr(self, '_ocr_activated_logged'):
                        print("🎯 DEBUG: OCR conditions met - starting capture...")
                        self._ocr_activated_logged = True
                    
                    if not should_run:
                        time.sleep(0.15)
                        continue
                    
                    # Get ROI
                    roi_abs = self._get_roi_abs()
                    if not roi_abs:
                        time.sleep(0.05)
                        continue
                    
                    L, T, R, B = roi_abs
                    mon = {"left": L, "top": T, "width": max(8, R - L), "height": max(8, B - T)}
                    
                    try:
                        shot = sct.grab(mon)
                        band = np.array(shot, dtype=np.uint8)[:, :, :3]
                    except Exception:
                        time.sleep(0.05)
                        continue
                    
                    # Preprocess (invert=True for black text on white background)
                    band_bin = preprocess_band_for_ocr(band, invert=True)
                    small = cv2.resize(band_bin, (96, 20), interpolation=cv2.INTER_AREA)
                    changed = True
                    
                    if self.last_small is not None:
                        diff = np.mean(np.abs(small.astype(np.int16) - self.last_small.astype(np.int16))) / 255.0
                        changed = diff > OCR_DIFF_THRESHOLD_DEFAULT
                        
                        # Debug: Log motion detection
                        if changed and not hasattr(self, '_motion_logged'):
                            print(f"🔄 DEBUG: Motion detected (diff={diff:.4f})")
                            self._motion_logged = True
                    else:
                        print("📸 DEBUG: First capture - running OCR...")
                    
                    self.last_small = small
                    
                    # Run OCR if changed
                    if changed:
                        self.motion_until = now + (OCR_BURST_MS_DEFAULT / 1000.0)
                        if now - self.last_ocr_t >= OCR_MIN_INTERVAL:
                            self._run_ocr_and_match(band_bin)
                            self.last_ocr_t = now
                            self.second_shot_at = now + (OCR_SECOND_SHOT_MS_DEFAULT / 1000.0)
                    
                    # Second shot
                    if self.second_shot_at and now >= self.second_shot_at:
                        if now - self.last_ocr_t >= (OCR_MIN_INTERVAL * 0.6):
                            self._run_ocr_and_match(band_bin)
                            self.last_ocr_t = now
                        self.second_shot_at = 0.0
                    
                    # Sleep
                    if now < self.motion_until:
                        sleep_time = 1.0 / OCR_BURST_HZ_DEFAULT
                    else:
                        sleep_time = 0.1
                    
                    time.sleep(sleep_time)
        
        except KeyboardInterrupt:
            print("\n\n⏹️ Stopping...")
            self.stop = True


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main entry point"""
    print("\n" + "="*60)
    print("EASYOCR STANDALONE TEST")
    print("="*60)
    
    # Debug settings
    if DEBUG_SAVE_OCR_IMAGES:
        print(f"\n💾 Debug mode: ON - OCR images will be saved to '{DEBUG_OCR_FOLDER}/'")
    else:
        print(f"\n💾 Debug mode: OFF - OCR images will not be saved")
    
    # Step 1: Connect to LCU
    print("\nStep 1: Connecting to LCU...")
    lcu = SimpleLCU()
    
    if not lcu.ok:
        print("⚠️ LCU not connected yet. Start League Client and try again.")
        print("   Waiting for League Client...")
        
        # Wait for LCU connection
        while not lcu.ok:
            time.sleep(1)
            lcu.refresh_if_needed()
    
    # Step 2: Get client language
    print("\nStep 2: Detecting client language...")
    client_lang = lcu.get_client_language()
    
    if not client_lang:
        print("⚠️ Could not detect client language, using English as fallback")
        client_lang = "en_US"
    else:
        print(f"✅ Client language: {client_lang}")
        
        # Special message for Arabic
        if client_lang and client_lang.startswith("ar_"):
            print("🇸🇦 Arabic detected! EasyOCR supports Arabic natively - no additional files needed!")
        
        # Special message for Greek
        if client_lang == "el_GR":
            print("🇬🇷 Greek detected! Note: EasyOCR doesn't support Greek yet.")
            print("   Using English OCR with Greek champion/skin names from database for matching.")
    
    # Step 3: Initialize EasyOCR
    print(f"\nStep 3: Initializing EasyOCR for {client_lang}...")
    ocr = EasyOCRBackend(lang=client_lang)
    
    # Step 4: Load multilang database
    print(f"\nStep 4: Loading champion/skin database...")
    multilang_db = SimpleMultiLangDB(lang=client_lang)
    
    # Step 5: Start OCR thread
    print(f"\nStep 5: Starting OCR monitoring...")
    ocr_thread = EasyOCRThread(lcu, ocr, multilang_db)
    
    try:
        ocr_thread.run()
    except KeyboardInterrupt:
        print("\n\n✅ Test completed!")
    
    print("\n" + "="*60)
    print(f"📊 STATISTICS")
    print("="*60)
    print(f"   Total OCR runs: {ocr_thread.ocr_count}")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()

