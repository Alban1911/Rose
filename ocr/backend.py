#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR backend implementation with EasyOCR (GPU/CPU mode)
"""

import warnings
from typing import Optional
import numpy as np
import cv2
from utils.logging import get_logger

# Suppress ALL numpy/EasyOCR warnings (must be done before imports)
warnings.filterwarnings('ignore', category=RuntimeWarning)
warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=UserWarning)
np.seterr(all='ignore')  # Suppress numpy errors/warnings

log = get_logger()


class OCR:
    """OCR backend using EasyOCR with GPU support"""
    
    def __init__(self, lang: str = "eng", use_gpu: bool = True, measure_time: bool = True):
        """Initialize EasyOCR backend with GPU support
        
        Args:
            lang: Language code (e.g., "eng", "rus", "kor", "chi_sim", etc.)
            use_gpu: Try to use GPU if available (default True, fallback to CPU)
            measure_time: Enable timing measurements for OCR operations (default True)
        """
        self.lang = lang
        self.backend = "easyocr"
        self.reader = None
        self.use_gpu = False  # Will be set based on actual initialization
        self.cache = {}  # Cache for OCR results
        self.measure_time = measure_time  # Enable timing measurements
        
        # Timing statistics
        self.last_ocr_time = 0.0
        self.avg_ocr_time = 0.0
        self.ocr_call_count = 0
        
        # Check if GPU is available
        gpu_available = False
        if use_gpu:
            try:
                import torch
                gpu_available = torch.cuda.is_available()
                if gpu_available:
                    log.info(f"GPU detected: {torch.cuda.get_device_name(0)}")
                else:
                    log.info("No GPU detected, will use CPU mode")
            except ImportError:
                log.info("PyTorch not configured for GPU, will use CPU mode")
            except Exception as e:
                log.debug(f"GPU check failed: {e}, will use CPU mode")
        
        # Language mapping: OCR language codes → EasyOCR codes
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
            log.info(f"Initializing EasyOCR: {langs_str} (lang: {lang})")
            
            # Try GPU mode first if requested and available
            if use_gpu and gpu_available:
                try:
                    log.info("Attempting to initialize EasyOCR in GPU mode...")
                    self.reader = easyocr.Reader(
                        easyocr_langs,
                        gpu=True,                   # GPU mode
                        verbose=False,              # Reduce logging
                        quantize=False,             # No quantization for GPU (not needed)
                        model_storage_directory=None,  # Use default cache
                        user_network_directory=None,   # Use default networks
                        download_enabled=True       # Allow downloading models if needed
                    )
                    self.use_gpu = True
                    log.info(f"✓ EasyOCR initialized successfully (GPU mode)")
                except Exception as gpu_error:
                    log.warning(f"GPU initialization failed: {gpu_error}")
                    log.info("Falling back to CPU mode...")
                    gpu_available = False  # Mark GPU as unavailable for fallback
            
            # Use CPU mode if GPU not requested or failed
            if not self.use_gpu:
                log.info("Initializing EasyOCR in CPU mode...")
                self.reader = easyocr.Reader(
                    easyocr_langs,
                    gpu=False,                  # CPU mode
                    verbose=False,              # Reduce logging
                    quantize=True,              # Use quantization for CPU speed
                    model_storage_directory=None,  # Use default cache
                    user_network_directory=None,   # Use default networks
                    download_enabled=True       # Allow downloading models if needed
                )
                log.info(f"✓ EasyOCR initialized successfully (CPU mode)")
            
            # Log timing measurement status
            if self.measure_time:
                log.info(f"⏱️  OCR timing measurements: ENABLED")
            
        except ImportError:
            raise ImportError(
                "EasyOCR is required for OCR functionality.\n"
                "Install with: pip install easyocr torch torchvision"
            )
        except Exception as e:
            # Handle unsupported language
            if "is not supported" in str(e):
                log.warning(f"EasyOCR doesn't support '{lang}' language")
                log.info(f"Falling back to English (en) for OCR")
                
                # Fallback to English (try GPU first if available, then CPU)
                import easyocr
                if use_gpu and gpu_available:
                    try:
                        self.reader = easyocr.Reader(["en"], gpu=True, verbose=False)
                        self.use_gpu = True
                        log.info(f"✓ EasyOCR initialized with English fallback (GPU mode)")
                    except Exception:
                        self.reader = easyocr.Reader(["en"], gpu=False, verbose=False, quantize=True)
                        log.info(f"✓ EasyOCR initialized with English fallback (CPU mode)")
                else:
                    self.reader = easyocr.Reader(["en"], gpu=False, verbose=False, quantize=True)
                    log.info(f"✓ EasyOCR initialized with English fallback (CPU mode)")
            else:
                raise RuntimeError(f"Failed to initialize EasyOCR: {e}")

    def recognize(self, img: np.ndarray) -> str:
        """Recognize text in image using EasyOCR
        
        Args:
            img: Input image (grayscale or BGR)
            
        Returns:
            Recognized text string
        """
        import time
        start_time = time.perf_counter() if self.measure_time else 0
        
        try:
            # Create a simple hash of the image for caching
            img_hash = hash(img.tobytes())
            
            # Check cache first
            if img_hash in self.cache:
                cached_text = self.cache[img_hash]
                if self.measure_time:
                    cache_time = (time.perf_counter() - start_time) * 1000
                    log.info(f"[OCR:CACHE-HIT] Instant return: {cache_time:.2f}ms | Text: '{cached_text}'")
                    # Update timing stats for cache hits too
                    self.last_ocr_time = cache_time
                    self.ocr_call_count += 1
                    self.avg_ocr_time = ((self.avg_ocr_time * (self.ocr_call_count - 1)) + cache_time) / self.ocr_call_count
                return cached_text
            
            # Convert image format for EasyOCR (expects RGB)
            preprocess_start = time.perf_counter() if self.measure_time else 0
            if img.ndim == 2:
                # Grayscale to RGB
                processed_img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
            elif img.shape[2] == 3:
                # BGR to RGB
                processed_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            else:
                processed_img = img
            
            if self.measure_time:
                preprocess_time = (time.perf_counter() - preprocess_start) * 1000
                log.debug(f"[OCR:timing] Image preprocessing: {preprocess_time:.2f}ms")
            
            # Suppress warnings during OCR processing
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                
                # Run EasyOCR with optimized settings for complete text detection
                ocr_start = time.perf_counter() if self.measure_time else 0
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
                
                if self.measure_time:
                    ocr_time = (time.perf_counter() - ocr_start) * 1000
                    log.info(f"[OCR:COMPUTE] Processing image: {ocr_time:.2f}ms")
            
            postprocess_start = time.perf_counter() if self.measure_time else 0
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
            
            if self.measure_time:
                postprocess_time = (time.perf_counter() - postprocess_start) * 1000
                total_time = (time.perf_counter() - start_time) * 1000
                
                # Update statistics
                self.last_ocr_time = total_time
                self.ocr_call_count += 1
                self.avg_ocr_time = ((self.avg_ocr_time * (self.ocr_call_count - 1)) + total_time) / self.ocr_call_count
                
                log.debug(f"[OCR:timing] Text postprocessing: {postprocess_time:.2f}ms")
                log.info(f"[OCR:timing] Total OCR time: {total_time:.2f}ms | Avg: {self.avg_ocr_time:.2f}ms | Count: {self.ocr_call_count}")
                if txt:
                    log.info(f"[OCR:timing] Detected text: '{txt}'")
            
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
            if not hasattr(self, '_error_logged'):
                log.warning(f"EasyOCR error (will continue): {e}")
                self._error_logged = True
            return ""
    
    def get_timing_stats(self) -> dict:
        """Get OCR timing statistics
        
        Returns:
            Dictionary with timing statistics:
            - last_ocr_time: Time of last OCR operation (ms)
            - avg_ocr_time: Average OCR operation time (ms)
            - ocr_call_count: Total number of OCR calls
        """
        return {
            'last_ocr_time': self.last_ocr_time,
            'avg_ocr_time': self.avg_ocr_time,
            'ocr_call_count': self.ocr_call_count,
            'measure_time': self.measure_time
        }
    
    def reset_timing_stats(self):
        """Reset OCR timing statistics"""
        self.last_ocr_time = 0.0
        self.avg_ocr_time = 0.0
        self.ocr_call_count = 0
        log.info("[OCR:timing] Timing statistics reset")
    
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
