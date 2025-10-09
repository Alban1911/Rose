#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR backend implementation with EasyOCR (CPU mode)
"""

import os
import warnings
from typing import Optional
import numpy as np
import cv2

# Suppress ALL numpy/EasyOCR warnings (must be done before imports)
warnings.filterwarnings('ignore', category=RuntimeWarning)
warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=UserWarning)
np.seterr(all='ignore')  # Suppress numpy errors/warnings


class OCR:
    """OCR backend using EasyOCR (CPU mode only)"""
    
    def __init__(self, lang: str = "eng", psm: int = 7, tesseract_exe: Optional[str] = None, use_gpu: bool = False):
        """Initialize EasyOCR backend in CPU mode
        
        Args:
            lang: Language code (e.g., "eng", "rus", "kor", "chi_sim", etc.)
            psm: Not used for EasyOCR (kept for API compatibility)
            tesseract_exe: Not used for EasyOCR (kept for API compatibility)
            use_gpu: Ignored - always uses CPU mode
        """
        self.lang = lang
        self.psm = int(psm)  # Keep for compatibility
        self.backend = "easyocr"
        self.reader = None
        self.use_gpu = False  # Always use CPU
        self.cache = {}  # Cache for OCR results
        
        # Language mapping: tesseract codes → EasyOCR codes
        # EasyOCR supports multiple languages simultaneously
        self.lang_mapping = {
            "eng": ["en"],
            "rus": ["ru", "en"],      # Russian + English (best for mixed content)
            "kor": ["ko", "en"],      # Korean + English
            "chi_sim": ["ch_sim", "en"],  # Chinese Simplified + English
            "chi_tra": ["ch_tra", "en"],  # Chinese Traditional + English
            "jpn": ["ja", "en"],      # Japanese + English
            "ara": ["ar", "en"],      # Arabic + English
            "fra": ["fr", "en"],      # French + English
            "deu": ["de", "en"],      # German + English
            "spa": ["es", "en"],      # Spanish + English
            "por": ["pt", "en"],      # Portuguese + English
            "ita": ["it", "en"],      # Italian + English
            "pol": ["pl", "en"],      # Polish + English
            "ron": ["ro", "en"],      # Romanian + English
            "hun": ["hu", "en"],      # Hungarian + English
            "tur": ["tr", "en"],      # Turkish + English
            "tha": ["th", "en"],      # Thai + English
            "vie": ["vi", "en"],      # Vietnamese + English
            "ell": ["el", "en"],      # Greek + English
        }
        
        # Get EasyOCR language list
        easyocr_langs = self.lang_mapping.get(lang, ["en"])
        
        try:
            import easyocr
            
            langs_str = "+".join(easyocr_langs)
            print(f"🚀 Initializing EasyOCR: {langs_str} (tesseract lang: {lang})")
            print(f"   💻 Mode: CPU only")
            
            # Initialize EasyOCR reader in CPU mode
            self.reader = easyocr.Reader(
                easyocr_langs,
                gpu=False,                  # CPU mode only
                verbose=False,              # Reduce logging
                quantize=True,              # Use quantization for CPU speed
                model_storage_directory=None,  # Use default cache
                user_network_directory=None,   # Use default networks
                download_enabled=True       # Allow downloading models if needed
            )
            
            print(f"✅ EasyOCR initialized successfully (CPU mode)")
            
        except ImportError:
            raise ImportError(
                "EasyOCR is required for OCR functionality.\n"
                "Install with: pip install easyocr torch torchvision"
            )
        except Exception as e:
            # Handle unsupported language
            if "is not supported" in str(e):
                print(f"⚠️ EasyOCR doesn't support '{lang}' language")
                print(f"🔄 Falling back to English (en) for OCR")
                
                # Fallback to English (CPU mode)
                import easyocr
                self.reader = easyocr.Reader(["en"], gpu=False, verbose=False, quantize=True)
                print(f"✅ EasyOCR initialized with English fallback (CPU mode)")
            else:
                raise RuntimeError(f"Failed to initialize EasyOCR: {e}")

    def recognize(self, img: np.ndarray) -> str:
        """Recognize text in image using EasyOCR
        
        Args:
            img: Input image (grayscale or BGR)
            
        Returns:
            Recognized text string
        """
        try:
            # Create a simple hash of the image for caching
            img_hash = hash(img.tobytes())
            
            # Check cache first
            if img_hash in self.cache:
                return self.cache[img_hash]
            
            # Convert image format for EasyOCR (expects RGB)
            if img.ndim == 2:
                # Grayscale to RGB
                processed_img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
            elif img.shape[2] == 3:
                # BGR to RGB
                processed_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            else:
                processed_img = img
            
            # Suppress warnings during OCR processing
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                
                # Run EasyOCR with optimized settings for complete text detection
                results = self.reader.readtext(
                    processed_img,
                    detail=1,           # Return text AND coordinates for proper ordering
                    paragraph=False,    # Don't group into paragraphs
                    width_ths=0.3,      # Very low threshold for character width (detect more text)
                    height_ths=0.3,     # Very low threshold for character height (detect more text)
                    decoder='greedy',   # More accurate for similar characters (к vs u, и vs u, р vs e)
                    batch_size=1,       # Process one image at a time
                    text_threshold=0.3, # Much lower confidence threshold (accept more text)
                    low_text=0.2,       # Very low threshold for detecting small text
                    link_threshold=0.2, # Very low threshold for linking characters
                    canvas_size=2560,   # Higher resolution for better character recognition
                    mag_ratio=2.0       # Higher magnification for better character clarity
                )
            
            if results:
                # Sort text regions by x-coordinate (left to right) to preserve reading order
                # Each result is a tuple: (bbox, text, confidence)
                # bbox is [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                # Sort by the leftmost x-coordinate (x1)
                sorted_results = sorted(results, key=lambda r: r[0][0][0])
                
                # Extract text only (index 1 of each result)
                txt = " ".join([r[1] for r in sorted_results])
            else:
                txt = ""
            
            # Clean up text (same as tesserocr implementation)
            txt = txt.replace("\n", " ").strip()
            txt = txt.replace("'", "'").replace("`", "'")
            txt = " ".join(txt.split())
            
            # Post-process for common Cyrillic OCR errors (especially italic distortions)
            if self.lang == "rus" or "ru" in self.lang_mapping.get(self.lang, []):
                txt = self._fix_cyrillic_ocr_errors(txt)
            
            
            # Cache the result
            if txt and len(txt.strip()) > 2:
                self.cache[img_hash] = txt
                # Limit cache size to prevent memory issues
                if len(self.cache) > 100:
                    # Remove oldest entry
                    oldest_key = next(iter(self.cache))
                    del self.cache[oldest_key]
            
            return txt
            
        except Exception as e:
            # Log error but don't crash - return empty string to continue OCR loop
            import sys
            if not hasattr(self, '_error_logged'):
                print(f"⚠️ EasyOCR error (will continue): {e}", file=sys.stderr)
                self._error_logged = True
            return ""
    
    def _fix_cyrillic_ocr_errors(self, text: str) -> str:
        """Fix common Cyrillic OCR recognition errors (especially italic distortions)
        
        Args:
            text: OCR recognized text
            
        Returns:
            Corrected text with common errors fixed
        """
        if not text:
            return text
            
        # Common EasyOCR confusions for Cyrillic characters (especially in italic)
        corrections = {
            # Italic distortions (most common)
            '^': 'л',  # Caret → Cyrillic л (very common in italic)
            'ш': 'и',  # Cyrillic ш → и (italic distortion)
            'п': 'т',  # Cyrillic п → т (italic distortion)
            'ц': 'и',  # Cyrillic ц → и (italic distortion)
            'ч': 'ч',  # Keep ч as is
            'ъ': 'ъ',  # Keep ъ as is
            'ы': 'ы',  # Keep ы as is
            'ь': 'ь',  # Keep ь as is
            'э': 'э',  # Keep э as is
            'ю': 'ю',  # Keep ю as is
            'я': 'я',  # Keep я as is
            
            # Other common confusions
            'u': 'и',  # Latin u → Cyrillic и
            'e': 'р',  # Latin e → Cyrillic р (in context)
            'k': 'к',  # Latin k → Cyrillic к
            'a': 'а',  # Latin a → Cyrillic а
            'o': 'о',  # Latin o → Cyrillic о
            'p': 'р',  # Latin p → Cyrillic р
            'c': 'с',  # Latin c → Cyrillic с
            'x': 'х',  # Latin x → Cyrillic х
            'y': 'у',  # Latin y → Cyrillic у
            'B': 'В',  # Latin B → Cyrillic В
            'E': 'Е',  # Latin E → Cyrillic Е
            'H': 'Н',  # Latin H → Cyrillic Н
            'I': 'І',  # Latin I → Cyrillic І
            'K': 'К',  # Latin K → Cyrillic К
            'M': 'М',  # Latin M → Cyrillic М
            'O': 'О',  # Latin O → Cyrillic О
            'P': 'Р',  # Latin P → Cyrillic Р
            'C': 'С',  # Latin C → Cyrillic С
            'T': 'Т',  # Latin T → Cyrillic Т
            'X': 'Х',  # Latin X → Cyrillic Х
            'Y': 'У',  # Latin Y → Cyrillic У
        }
        
        # Apply corrections
        corrected = text
        for wrong_char, correct_char in corrections.items():
            corrected = corrected.replace(wrong_char, correct_char)
            
        return corrected
