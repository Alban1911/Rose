#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR backend implementation with EasyOCR + GPU
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
    """OCR backend using EasyOCR with GPU support"""
    
    def __init__(self, lang: str = "eng", psm: int = 7, tesseract_exe: Optional[str] = None, use_gpu: bool = True):
        """Initialize EasyOCR backend
        
        Args:
            lang: Language code (e.g., "eng", "rus", "kor", "chi_sim", etc.)
            psm: Not used for EasyOCR (kept for API compatibility)
            tesseract_exe: Not used for EasyOCR (kept for API compatibility)
            use_gpu: Whether to use GPU acceleration (default: True)
        """
        self.lang = lang
        self.psm = int(psm)  # Keep for compatibility
        self.backend = "easyocr"
        self.reader = None
        self.use_gpu = use_gpu
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
            import torch
            
            # Check GPU availability at system level (independent of PyTorch)
            system_has_nvidia_gpu = self._detect_nvidia_gpu()
            any_gpu = self._detect_any_gpu()
            
            # Check PyTorch GPU availability
            gpu_available = torch.cuda.is_available()
            langs_str = "+".join(easyocr_langs)
            
            if use_gpu and gpu_available:
                print(f"🚀 Initializing EasyOCR: {langs_str} (tesseract lang: {lang})")
                print(f"   🎮 GPU: {torch.cuda.get_device_name(0)} (CUDA {torch.version.cuda})")
            elif use_gpu and not gpu_available:
                print(f"🚀 Initializing EasyOCR: {langs_str} (tesseract lang: {lang})")
                print(f"   ⚠️ GPU requested but not available, falling back to CPU")
                
                # Provide appropriate message based on detected GPU type
                if system_has_nvidia_gpu:
                    # User has NVIDIA GPU but PyTorch can't use it - provide fix
                    print(f"   🔍 Detected: {system_has_nvidia_gpu}")
                    print(f"   ❌ Problem: PyTorch cannot access your NVIDIA GPU")
                    print(f"   💡 PyTorch version: {torch.__version__} (CPU-only)")
                    print(f"   ")
                    print(f"   ✅ Solution: Install CUDA-enabled PyTorch:")
                    print(f"      1. pip uninstall torch torchvision")
                    print(f"      2. pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121")
                    print(f"      3. Restart the app")
                elif any_gpu:
                    # User has AMD/Intel/Other GPU - explain why it won't work
                    gpu_name, gpu_type = any_gpu
                    print(f"   🔍 Detected: {gpu_name}")
                    print(f"   ℹ️  GPU Type: {gpu_type}")
                    print(f"   💡 Note: EasyOCR GPU acceleration only supports NVIDIA GPUs (CUDA)")
                    if gpu_type == "AMD":
                        print(f"   💡 AMD GPUs use ROCm (not supported on Windows for PyTorch)")
                    elif gpu_type == "Intel":
                        print(f"   💡 Intel GPUs have limited PyTorch support (experimental)")
                    print(f"   ✅ CPU mode works perfectly - GPU not required!")
                else:
                    # No GPU detected at all
                    print(f"   💡 No dedicated GPU detected on system")
                    print(f"   💡 PyTorch version: {torch.__version__}")
                    print(f"   ✅ CPU mode works perfectly - GPU not required!")
                
                self.use_gpu = False
            else:
                print(f"🚀 Initializing EasyOCR: {langs_str} (tesseract lang: {lang})")
                print(f"   💻 Using CPU (GPU disabled by user)")
            
            # Initialize EasyOCR reader with GPU/CPU support
            self.reader = easyocr.Reader(
                easyocr_langs,
                gpu=self.use_gpu,           # Use GPU if available
                verbose=False,              # Reduce logging
                quantize=not self.use_gpu,  # Use quantization only on CPU for speed
                model_storage_directory=None,  # Use default cache
                user_network_directory=None,   # Use default networks
                download_enabled=True       # Allow downloading models if needed
            )
            
            print(f"✅ EasyOCR initialized successfully")
            
        except ImportError:
            raise ImportError(
                "EasyOCR is required for OCR functionality.\n"
                "Install with: pip install easyocr torch torchvision\n"
                "For GPU support, install CUDA-enabled PyTorch from: https://pytorch.org"
            )
        except Exception as e:
            # Handle unsupported language
            if "is not supported" in str(e):
                print(f"⚠️ EasyOCR doesn't support '{lang}' language")
                print(f"🔄 Falling back to English (en) for OCR")
                
                # Fallback to English
                import easyocr
                self.reader = easyocr.Reader(["en"], gpu=self.use_gpu, verbose=False)
                print(f"✅ EasyOCR initialized with English fallback")
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
    
    def _detect_nvidia_gpu(self) -> Optional[str]:
        """Detect NVIDIA GPU at system level (independent of PyTorch)
        
        Returns:
            GPU name if NVIDIA GPU found, None otherwise
        """
        import subprocess
        import sys
        
        try:
            # Method 1: Try nvidia-smi (most reliable)
            if sys.platform == "win32":
                # Windows: nvidia-smi is usually in System32 or NVIDIA driver folder
                try:
                    result = subprocess.run(
                        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                        capture_output=True,
                        text=True,
                        timeout=2,
                        creationflags=subprocess.CREATE_NO_WINDOW  # Don't show console window
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        return result.stdout.strip().split('\n')[0]  # Return first GPU
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    pass
            else:
                # Linux/Mac: nvidia-smi should be in PATH
                try:
                    result = subprocess.run(
                        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        return result.stdout.strip().split('\n')[0]
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    pass
            
            # Method 2: Check Windows Registry (Windows-specific fallback)
            if sys.platform == "win32":
                try:
                    import winreg
                    key_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000"
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                    gpu_name, _ = winreg.QueryValueEx(key, "DriverDesc")
                    winreg.CloseKey(key)
                    if "NVIDIA" in gpu_name.upper():
                        return gpu_name
                except (OSError, ImportError):
                    pass
            
            return None
            
        except Exception:
            # Silently fail - GPU detection is just for helpful diagnostics
            return None
    
    def _detect_any_gpu(self) -> Optional[tuple[str, str]]:
        """Detect any GPU (NVIDIA, AMD, Intel) at system level
        
        Returns:
            Tuple of (GPU name, GPU type) if found, None otherwise
            GPU type can be: "NVIDIA", "AMD", "Intel", "Other"
        """
        import subprocess
        import sys
        
        try:
            # Windows: Check registry for any GPU
            if sys.platform == "win32":
                try:
                    import winreg
                    # Standard display adapter registry path
                    key_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000"
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                    gpu_name, _ = winreg.QueryValueEx(key, "DriverDesc")
                    winreg.CloseKey(key)
                    
                    # Determine GPU type
                    gpu_upper = gpu_name.upper()
                    if "NVIDIA" in gpu_upper or "GEFORCE" in gpu_upper or "QUADRO" in gpu_upper or "RTX" in gpu_upper or "GTX" in gpu_upper:
                        return (gpu_name, "NVIDIA")
                    elif "AMD" in gpu_upper or "RADEON" in gpu_upper or "RX " in gpu_upper:
                        return (gpu_name, "AMD")
                    elif "INTEL" in gpu_upper or "UHD" in gpu_upper or "IRIS" in gpu_upper:
                        return (gpu_name, "Intel")
                    else:
                        return (gpu_name, "Other")
                except (OSError, ImportError):
                    pass
            
            # Linux: Try lspci (if available)
            else:
                try:
                    result = subprocess.run(
                        ["lspci"],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if result.returncode == 0:
                        for line in result.stdout.split('\n'):
                            line_upper = line.upper()
                            if "VGA" in line_upper or "3D" in line_upper or "DISPLAY" in line_upper:
                                if "NVIDIA" in line_upper:
                                    return (line.split(': ')[-1], "NVIDIA")
                                elif "AMD" in line_upper or "RADEON" in line_upper:
                                    return (line.split(': ')[-1], "AMD")
                                elif "INTEL" in line_upper:
                                    return (line.split(': ')[-1], "Intel")
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    pass
            
            return None
            
        except Exception:
            # Silently fail - GPU detection is just for helpful diagnostics
            return None
    
