#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Logging configuration and utilities
"""

# Standard library imports
import base64
import json
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Third-party imports
import logging
import urllib3
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from urllib3.exceptions import InsecureRequestWarning

# Local imports
from config import (
    LOG_MAX_FILES_DEFAULT, LOG_MAX_TOTAL_SIZE_MB_DEFAULT,
    LOG_FILE_PATTERN, LOG_TIMESTAMP_FORMAT, LOG_SEPARATOR_WIDTH,
    PRODUCTION_MODE
)

# Add custom TRACE logging level (below DEBUG)
TRACE = 5
logging.addLevelName(TRACE, "TRACE")

def trace(self, message, *args, **kwargs):
    """Log a trace message (ultra-detailed, below DEBUG)"""
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)

# Add trace() method to Logger class
logging.Logger.trace = trace

# Global log mode (set by setup_logging)
_CURRENT_LOG_MODE = 'customer'

def get_log_mode() -> str:
    """Get the current logging mode"""
    return _CURRENT_LOG_MODE


def _get_encryption_key() -> bytes:
    """Get the encryption key from key file, environment variable, or generate from a fixed password"""
    # Priority 1: Try to get key from key file (most secure)
    key_file = Path(__file__).parent.parent / "log_encryption_key.txt"
    if key_file.exists():
        try:
            with open(key_file, 'r') as f:
                key_str = f.read().strip()
            if key_str:
                password = key_str.encode()
            else:
                # Empty file, fall through to default
                password = None
        except Exception:
            # Could not read key file, fall through to default
            password = None
    else:
        password = None
    
    # Priority 2: Try to get key from environment variable
    if password is None:
        key_str = os.environ.get('LEAGUE_UNLOCKED_LOG_KEY')
        if key_str:
            password = key_str.encode()
    
    # Priority 3: Default key derived from a fixed password (developer only)
    if password is None:
        password = b'LeagueUnlocked2024LogEncryptionDefaultKey'
    
    # Derive a 32-byte key using PBKDF2
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'league_unlocked_logs_salt',
        iterations=100000,
        backend=default_backend()
    )
    key = kdf.derive(password)
    
    # Fernet expects a URL-safe base64-encoded 32-byte key
    return base64.urlsafe_b64encode(key)


class EncryptedFileHandler(logging.FileHandler):
    """File handler that encrypts log content using AES"""
    
    def __init__(self, filename, mode='a', encoding='utf-8', delay=False, errors=None):
        # Store encoding BEFORE calling parent __init__ (which may overwrite it for binary mode)
        self._encoding = encoding if encoding else 'utf-8'
        # Open file in binary mode for encryption
        logging.FileHandler.__init__(self, filename, mode='ab', delay=delay, errors=errors)
        # Get encryption key and create Fernet cipher
        key = _get_encryption_key()
        self.cipher = Fernet(key)
    
    def emit(self, record):
        """Write encrypted log to file"""
        try:
            msg = self.format(record)
            # Use our stored encoding attribute
            encoding = getattr(self, '_encoding', 'utf-8')
            # Encrypt the message (Fernet already includes the message in the token)
            encrypted_msg = self.cipher.encrypt(msg.encode(encoding))
            # Write encrypted bytes (no need to add newline as each log is on its own line)
            self.stream.write(encrypted_msg)
            self.stream.write(b'\n')  # Add newline for readability when decrypting
            self.flush()
        except Exception:
            self.handleError(record)


class RSAHybridEncryptedFileHandler(logging.FileHandler):
    """File handler that encrypts logs using RSA-hybrid (RSA-OAEP + Fernet).

    - A random Fernet key is generated per session (per log file)
    - The Fernet key is encrypted with the licensing RSA public key
    - A header line is written: {"v":"rsa1","ek":"<b64_rsa_encrypted_key>"}
    - Each log record line contains a Fernet token (base64 ASCII) only
    """

    def __init__(self, filename, mode='a', encoding='utf-8', delay=False, errors=None):
        # Store encoding BEFORE calling parent __init__ (which may overwrite it for binary mode)
        self._encoding = encoding if encoding else 'utf-8'
        # Open file in binary mode for encryption
        logging.FileHandler.__init__(self, filename, mode='ab', delay=delay, errors=errors)

        # Load RSA public key used for hybrid encryption
        try:
            from .public_key import PUBLIC_KEY
            public_key = serialization.load_pem_public_key(
                PUBLIC_KEY.encode('ascii'),
                backend=default_backend()
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load RSA public key for log encryption: {e}")

        # Generate per-session Fernet key and cipher
        fernet_key: bytes = Fernet.generate_key()
        self._fernet_key = fernet_key
        self._cipher = Fernet(fernet_key)

        # Encrypt the Fernet key with RSA-OAEP (SHA256)
        try:
            encrypted_key_bytes = public_key.encrypt(
                fernet_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                ),
            )
            ek_b64 = base64.urlsafe_b64encode(encrypted_key_bytes).decode('ascii')
        except Exception as e:
            raise RuntimeError(f"Failed to encrypt session key for log encryption: {e}")

        # Write header line with version and encrypted key
        header_obj = {"v": "rsa1", "ek": ek_b64}
        header_line = json.dumps(header_obj, separators=(",", ":")).encode('utf-8')
        self.stream.write(header_line)
        self.stream.write(b"\n")
        self.flush()

    def emit(self, record):
        """Write encrypted log to file using per-session Fernet cipher"""
        try:
            msg = self.format(record)
            encoding = getattr(self, '_encoding', 'utf-8')
            token_bytes = self._cipher.encrypt(msg.encode(encoding))
            # Fernet tokens are already base64-encoded ASCII bytes
            self.stream.write(token_bytes)
            self.stream.write(b"\n")
            self.flush()
        except Exception:
            self.handleError(record)


class SanitizingFilter(logging.Filter):
    """
    Logging filter that sanitizes sensitive information and controls verbosity.
    
    Three modes:
    - customer: Clean, user-friendly logs (INFO+ only, no technical details)
    - verbose: Full technical details (DEBUG+, all pipeline info)
    - debug: Ultra-detailed (TRACE+, function traces, variable dumps)
    """
    
    # Patterns to sanitize (compiled regex for performance)
    PATTERNS = [
        # API URLs and endpoints
        (re.compile(r'https?://[^\s]+'), '[URL_REDACTED]'),
        # File paths - Windows paths only (C:\, D:\, etc. with backslashes)
        (re.compile(r'[A-Za-z]:\\[^\s]*'), '[PATH_REDACTED]'),
        # File paths - Unix paths (multiple slashes)
        (re.compile(r'/[^/\s]+/[^\s]+'), '[PATH_REDACTED]'),
        # Clean up partial path leaks after redaction (very aggressive - remove everything after [PATH_REDACTED])
        (re.compile(r'\[PATH_REDACTED\][^\n]*'), '[PATH_REDACTED]'),
        # Remove entire line with timing (don't leave empty lines)
        (re.compile(r'^\s*⏱️.*$', re.MULTILINE), ''),
        # Remove timing parts from detection messages
        (re.compile(r'\s*\|\s*Matching:.*$', re.MULTILINE), ''),
        (re.compile(r'\s*\|\s*Total:.*$', re.MULTILINE), ''),
        # Remove PID numbers (process IDs)
        (re.compile(r'PID:\s*\d+'), 'PID: [REDACTED]'),
        (re.compile(r'PID=\d+'), 'PID=[REDACTED]'),
        # API tokens/passwords (though these shouldn't be logged anyway)
        (re.compile(r'(token|password|pw|key|auth)["\s:=]+[^\s"]+', re.IGNORECASE), r'\1=[REDACTED]'),
        # Port numbers (could reveal implementation)
        (re.compile(r'port["\s:=]+\d+', re.IGNORECASE), 'port=[REDACTED]'),
        # GitHub repository references
        (re.compile(r'github\.com/[^\s/]+/[^\s/]+'), 'github.com/[REDACTED]'),
        # Specific implementation details
        (re.compile(r'(cslol|wad|injection|inject|dll|suspend|process|runoverlay|mkoverlay)', re.IGNORECASE), '[IMPL_DETAIL]'),
    ]
    
    # Sensitive message prefixes to completely suppress in customer mode
    SUPPRESS_PREFIXES = [
        # File/system initialization
        'File logging initialized',
        'Log file location:',
        '[ws] WebSocket',
        'LCU lockfile',
        '  - VERIFIED actual position:',
        
        # Qt/QWindowsContext messages (harmless COM warnings)
        'QWindowsContext:',
        'OleInitialize()',
        
        # Initialization messages (verbose/debug only)
        'Initializing ',
        '✓ ',
        'System tray manager started',
        'System tray icon started',
        'System ready',
        'Debug Mode:',
        'Thread ready',
        'Found ',
        'Language detected',
        'GPU detected',
        'Downloading ',
        'No new ',
        'Attempting to initialize',
        'WebSocket connected',
        
        # Chroma implementation details (too verbose)
        '[CHROMA] get_preview_path',
        '[CHROMA] Skin directory:',
        '[CHROMA] Looking for',
        '[CHROMA] ✅ Found preview:',
        '[CHROMA] ✅ ChromaPanelWidget parented',
        '[CHROMA] ✅ OpeningButton parented',
        '[CHROMA] Creating UnownedFrame',
        '[CHROMA] ✓ OutlineGold loaded',
        '[CHROMA] ✓ Lock loaded',
        '[CHROMA] ✓ UnownedFrame created',
        '[CHROMA] UnownedFrame creation complete',
        '[CHROMA] Panel widgets created',
        '[CHROMA] ✓ UnownedFrame parented',
        '[CHROMA] UnownedFrame positioned',
        '[CHROMA] Starting fade:',
        '[CHROMA] UnownedFrame fade:',
        '[CHROMA] UnownedFrame starting fade:',
        '[CHROMA] Button:',
        '[CHROMA] First skin detected',
        
        # Implementation details
        '[COMPUTE]',
        '[timing]',
        '[change]',
        '[CACHE-HIT]',
        '[running]',
        '[stopped]',
        
        # Injection implementation details  
        '[inject]',
        '[INJECT] on_champion_locked',
        '[INJECT] Background initialization',
        
        # Loadout timer spam
        '[loadout #',
        'T-',
        '⏰ Loadout ticker',
        
        # Lock details
        '[locks]',
        '🔒 Champion locked:',
        
        # LCU scraper details
        '[LCU-SCRAPER]',
        '[LCU] Loaded',
        'owned skins',
        
        # Thread lifecycle spam
        '✓ Phase thread',
        '✓ LCU Monitor',
        '✓ All threads',
        
        # Chroma checking spam (any [CHROMA] message)
        '[CHROMA]',
        
        # Status icon updates and app status sections (verbose only)
        'Locked icon shown',
        'Golden locked icon shown',
        'Golden unlocked icon shown',
        '[APP STATUS]',
        '📍 System tray',
        '📊 App status',
        '🔒 APP STATUS',
        '🔓 APP STATUS',
        '🔓✨ APP STATUS',
        '   📋 ',  # Detail lines with this prefix
        '   ⏳ ',
        '   ✅ ',
        '   🎯 ',
        '   •',   # Bullet points
        
        # Repository/skin download details
        'Using repository ZIP downloader',
        'skins, skipping download',
        'preview images',
        '📥 STARTING SKIN DOWNLOAD',
        '✅ SKIN DOWNLOAD COMPLETED',
        
        # Skin detection details (show detection, hide verbose sub-details)
        '   📋 Champion:',  # Hide verbose champion detail line
        '   🔍 Source:',    # Hide "Source: LCU API + English DB"
        
        # Initialization details
        '🤖 INITIALIZED',
        'Thread updated',
        '   ⏱️',  # Timing measurements
        
        # Game state details (keep Phase transitions, hide verbose details)
        '👥 Players:',
        '🎮 Entering ChampSelect',
        '   • Mode:',
        '   • Remaining:',
        '   • Hz:',
        '   • Phase:',
        '   • ID:',
        '   • Locked:',
        
        # License warning (keep warning itself, hide details)
        '⚠️  This should only',
        
        # Game process monitoring (reveals technique)
        '👁️ GAME',
        '[[IMPL_DETAIL]] Starting game monitor',
        '🎮 Game [IMPL_DETAIL] found',
        '⏸️ Game',
        '▶️ Game resumed',
        '⚙️ Game loading',
        '❄️ mkoverlay',
        '⚡ mkoverlay',
        '🚀 Running overlay:',
        '   • Auto-resume:',
        'PID=[REDACTED], status=',
        
        # Timing (suppress any message starting with timing emoji)
        '⏱️',
        
        # Phase spam
        '🧹 Killed all',
    ]
    
    def __init__(self, production_mode: bool, log_mode: str = 'customer'):
        """
        Initialize filter
        
        Args:
            production_mode: If True, sanitize paths/PIDs/ports regardless of log mode
            log_mode: 'customer', 'verbose', or 'debug'
        """
        super().__init__()
        self.production_mode = production_mode
        self.log_mode = log_mode
    
    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter log records. Returns False to suppress, True to allow.
        Modifies record.msg to sanitize sensitive information.
        """
        # Get message string for prefix checking
        msg_str = str(record.getMessage())
        
        # Customer mode: Clean, user-friendly logs
        if self.log_mode == 'customer':
            # Only show INFO and above in customer mode
            if record.levelno < logging.INFO:
                return False
            
            # Suppress separator lines (lines that are just "=" repeated)
            if msg_str.strip() and all(c == '=' for c in msg_str.strip()):
                return False
            
            # Suppress based on prefixes
            for prefix in self.SUPPRESS_PREFIXES:
                if msg_str.startswith(prefix):
                    return False
        
        # Verbose mode: Show DEBUG+ but not TRACE
        elif self.log_mode == 'verbose':
            # Show DEBUG and above
            if record.levelno < logging.DEBUG:
                return False
        
        # Debug mode: Show everything (TRACE+)
        else:  # log_mode == 'debug'
            # Show all levels including TRACE
            pass
        
        # Always sanitize paths, PIDs, ports in production mode (regardless of log level)
        if self.production_mode:
            # Also suppress Qt warnings in production mode
            for prefix in self.SUPPRESS_PREFIXES:
                if msg_str.startswith(prefix):
                    return False
            
            sanitized = record.msg
            if isinstance(sanitized, str):
                for pattern, replacement in self.PATTERNS:
                    sanitized = pattern.sub(replacement, sanitized)
                record.msg = sanitized
                
                # Suppress if message is now empty or only whitespace after sanitization
                if not sanitized.strip():
                    return False
        
        return True


def setup_logging(log_mode: str = 'customer', production_mode: bool = None):
    """
    Setup logging configuration with three modes
    
    Args:
        log_mode: 'customer' (clean logs), 'verbose' (developer), or 'debug' (ultra-detailed)
        production_mode: Override PRODUCTION_MODE (None = use config default)
    """
    # Store the log mode globally
    global _CURRENT_LOG_MODE
    
    # Determine production mode
    if production_mode is None:
        production_mode = PRODUCTION_MODE
    
    # In production mode, always use verbose mode for full logging
    if production_mode:
        _CURRENT_LOG_MODE = 'verbose'
    else:
        _CURRENT_LOG_MODE = log_mode
    # Handle windowed mode where stdout/stderr might be None or redirected to devnull
    if sys.stdout is not None and not hasattr(sys.stdout, 'name') or sys.stdout.name != os.devnull:
        try:
            sys.stdout.reconfigure(line_buffering=True)
        except (AttributeError, OSError):
            pass  # stdout doesn't support reconfigure or is redirected
    
    if sys.stderr is not None and not hasattr(sys.stderr, 'name') or sys.stderr.name != os.devnull:
        try:
            sys.stderr.reconfigure(line_buffering=True)
        except (AttributeError, OSError):
            pass  # stderr doesn't support reconfigure or is redirected
    
    # Create a queue-based non-blocking logging handler
    class QueueHandler(logging.Handler):
        """A queue-based handler that never blocks the calling thread"""
        def __init__(self, target_handler):
            super().__init__()
            self.target_handler = target_handler
            self.queue = queue.Queue(maxsize=1000)  # Limit queue size to prevent memory issues
            self.worker_thread = None
            self._stop_event = threading.Event()
            self._start_worker()
        
        def _start_worker(self):
            """Start the worker thread that processes log records"""
            def worker():
                while not self._stop_event.is_set():
                    try:
                        # Get record with timeout to allow checking stop event
                        record = self.queue.get(timeout=0.1)
                        if record is None:  # Sentinel value to stop
                            break
                        # Emit to target handler in worker thread
                        try:
                            self.target_handler.emit(record)
                        except Exception:
                            # If emit fails, silently drop the log message
                            pass
                        finally:
                            self.queue.task_done()
                    except queue.Empty:
                        continue
            
            self.worker_thread = threading.Thread(target=worker, daemon=True, name="LogQueueWorker")
            self.worker_thread.start()
        
        def emit(self, record):
            """Queue the log record without blocking"""
            try:
                # Use put_nowait to never block the calling thread
                self.queue.put_nowait(record)
            except queue.Full:
                # Queue is full - drop the message silently
                # This prevents blocking even under extreme log load
                pass
        
        def close(self):
            """Stop the worker thread gracefully"""
            self._stop_event.set()
            try:
                self.queue.put_nowait(None)  # Sentinel to stop worker
            except queue.Full:
                pass
            if self.worker_thread and self.worker_thread.is_alive():
                self.worker_thread.join(timeout=1.0)
            super().close()
    
    # Create a safe logging handler that works even without console
    class SafeStreamHandler(logging.StreamHandler):
        """A stream handler that safely handles None streams and prevents blocking"""
        def __init__(self, stream=None):
            # If stream is None, create a dummy stream that does nothing
            if stream is None:
                import io
                stream = io.StringIO()
            super().__init__(stream)
        
        def emit(self, record):
            try:
                # Use non-blocking emit with timeout protection
                msg = self.format(record)
                stream = self.stream
                
                # Try to write without blocking (with signal-based timeout on Unix, best-effort on Windows)
                try:
                    stream.write(msg + self.terminator)
                    stream.flush()
                except (BlockingIOError, BrokenPipeError, OSError):
                    # Stream is blocking or broken - skip this message
                    pass
            except (AttributeError, OSError, ValueError):
                # If the stream is broken, silently ignore
                pass
    
    # Use stderr if stdout is None or redirected to devnull (windowed mode), but make it safe
    if sys.stdout is not None and hasattr(sys.stdout, 'name') and sys.stdout.name == os.devnull:
        output_stream = sys.stderr if sys.stderr is not None else sys.stdout
    else:
        output_stream = sys.stdout if sys.stdout is not None else sys.stderr
    
    # Create a safe stream handler
    safe_handler = SafeStreamHandler(output_stream)
    
    # Set up formatter based on log mode
    if log_mode == 'customer':
        # Clean, minimal format for customer logs
        fmt = "%(_when)s | %(message)s"
    elif log_mode == 'verbose':
        # Detailed format for developer logs
        fmt = "%(_when)s | %(levelname)-7s | %(message)s"
    else:  # debug mode
        # Ultra-detailed format for debug logs
        fmt = "%(_when)s | %(levelname)-7s | %(name)-15s | %(funcName)-20s | %(message)s"
    
    class _Fmt(logging.Formatter):
        def format(self, record):
            record._when = time.strftime("%H:%M:%S", time.localtime())
            return super().format(record)
    
    safe_handler.setFormatter(_Fmt(fmt))
    
    # Wrap in queue handler to prevent blocking
    h = QueueHandler(safe_handler)
    
    # Setup file logging
    try:
        # Create logs directory in user data directory
        from .paths import get_user_data_dir
        logs_dir = get_user_data_dir() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Create a unique log file for this session with timestamp
        # Format: dd-mm-yyyy_hh-mm-ss (European format, no colons for Windows compatibility)
        timestamp = datetime.now().strftime(LOG_TIMESTAMP_FORMAT)
        
        # In production mode, use RSA-hybrid encrypted logs with .log.enc extension
        if production_mode:
            log_file = logs_dir / f"leagueunlocked_{timestamp}.log.enc"
            file_handler = RSAHybridEncryptedFileHandler(log_file, encoding='utf-8')
        else:
            log_file = logs_dir / f"leagueunlocked_{timestamp}.log"
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
        
        # File formatter based on log mode
        # In production mode, always use verbose format
        if production_mode:
            file_fmt = "%(_when)s | %(levelname)-7s | %(message)s"
        elif log_mode == 'customer':
            # Clean format for customer logs
            file_fmt = "%(_when)s | %(message)s"
        elif log_mode == 'verbose':
            # Detailed format for developer logs
            file_fmt = "%(_when)s | %(levelname)-7s | %(message)s"
        else:  # debug mode
            # Ultra-detailed format with logger name and function
            file_fmt = "%(_when)s | %(levelname)-7s | %(name)-15s | %(funcName)-20s | %(message)s"
        
        class _FileFmt(logging.Formatter):
            def format(self, record):
                record._when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                return super().format(record)
        
        file_handler.setFormatter(_FileFmt(file_fmt))
        
        # File handler logging level based on mode
        # In production mode, always use verbose level (DEBUG+)
        if production_mode:
            file_handler.setLevel(logging.DEBUG)  # Show DEBUG and above in production
        elif log_mode == 'debug':
            file_handler.setLevel(TRACE)  # Show everything including TRACE
        elif log_mode == 'verbose':
            file_handler.setLevel(logging.DEBUG)  # Show DEBUG and above
        else:  # customer mode
            file_handler.setLevel(logging.INFO)  # Show INFO and above
        
        # Only add sanitizing filter in development mode (not in production)
        if not production_mode:
            file_handler.addFilter(SanitizingFilter(production_mode, log_mode))
        
    except Exception as e:
        # If file logging fails, continue without it
        file_handler = None
        print(f"Warning: Could not setup file logging: {e}", file=sys.stderr)
    
    root = logging.getLogger()
    root.handlers.clear()
    
    # Only add console handler in development mode
    # In production mode, suppress all console output
    if not production_mode:
        root.addHandler(h)
        # Console handler level based on log mode
        if log_mode == 'debug':
            h.setLevel(TRACE)  # Show everything including TRACE
        elif log_mode == 'verbose':
            h.setLevel(logging.DEBUG)  # Show DEBUG and above
        else:  # customer mode
            h.setLevel(logging.INFO)  # Show INFO and above (clean output)
        
        # Add sanitizing filter to console handler
        h.addFilter(SanitizingFilter(production_mode, log_mode))
    
    # Always add file handler
    if file_handler:
        root.addHandler(file_handler)
    
    # Root logger must be at TRACE to allow all handlers to receive all messages
    # This is critical - if root is at INFO, DEBUG/TRACE messages never reach handlers
    root.setLevel(TRACE)
    
    # Add a console print to ensure output is visible (only if we have stdout and it's not redirected)
    # Skip in production mode as we have no console handler
    if not production_mode and sys.stdout is not None and not (hasattr(sys.stdout, 'name') and sys.stdout.name == os.devnull):
        try:
            # Use logging instead of direct print to avoid blocking
            logger = logging.getLogger("startup")
            
            # Show startup message based on log mode
            if _CURRENT_LOG_MODE == 'customer':
                # Clean startup for customer mode
                logger.info(f"✅ LeagueUnlocked Started (Log: {log_file.name})")
            else:
                # Detailed startup for verbose/debug modes
                logger.info("=" * LOG_SEPARATOR_WIDTH)
                logger.info(f"LeagueUnlocked - Starting... (Log file: {log_file.name})")
                logger.info("=" * LOG_SEPARATOR_WIDTH)
                
                # Log mode information
                if _CURRENT_LOG_MODE == 'debug':
                    logger.info("Debug mode: ON (ultra-detailed logs with function traces)")
                    logger.debug(f"Log file location: {log_file.absolute()}")
                elif _CURRENT_LOG_MODE == 'verbose':
                    logger.info("Verbose mode: ON (developer logs with technical details)")
                    logger.debug(f"Log file location: {log_file.absolute()}")
                    
        except (AttributeError, OSError):
            pass  # stdout is broken, ignore
    
    # Suppress HTTPS/HTTP logs
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
    logging.getLogger("requests.packages.urllib3.connectionpool").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    
    # Disable SSL warnings for LCU (self-signed cert)
    urllib3.disable_warnings(InsecureRequestWarning)
    
    # Suppress Qt/QWindowsContext messages (COM errors, etc.) in production mode
    if production_mode:
        logging.getLogger("Qt").setLevel(logging.CRITICAL)
        logging.getLogger("QWindowsContext").setLevel(logging.CRITICAL)


def get_logger(name: str = "tracer") -> logging.Logger:
    """Get a logger instance"""
    return logging.getLogger(name)


def cleanup_logs(max_files: int = LOG_MAX_FILES_DEFAULT, max_total_size_mb: int = LOG_MAX_TOTAL_SIZE_MB_DEFAULT):
    """
    Clean up old log files based on count and total size
    
    Args:
        max_files: Maximum number of log files to keep
        max_total_size_mb: Maximum total size of all log files in MB
    """
    try:
        from .paths import get_user_data_dir
        logs_dir = get_user_data_dir() / "logs"
        if not logs_dir.exists():
            return
        
        # Get all log files matching the new pattern
        log_files = list(logs_dir.glob(LOG_FILE_PATTERN))
        
        # Sort by modification time (oldest first)
        log_files.sort(key=lambda f: f.stat().st_mtime)
        
        # Calculate total size
        total_size = sum(f.stat().st_size for f in log_files)
        max_total_size_bytes = max_total_size_mb * 1024 * 1024
        
        # Remove oldest files if we exceed limits
        files_to_remove = []
        
        # Remove by count limit
        if len(log_files) > max_files:
            files_to_remove.extend(log_files[:-max_files])
        
        # Remove by size limit
        if total_size > max_total_size_bytes:
            current_size = total_size
            for log_file in log_files:
                if log_file not in files_to_remove:
                    current_size -= log_file.stat().st_size
                    files_to_remove.append(log_file)
                    if current_size <= max_total_size_bytes:
                        break
        
        # Remove the files
        for log_file in files_to_remove:
            try:
                log_file.unlink()
            except Exception:
                pass  # Silently ignore removal errors
                
    except Exception as e:
        # Don't log this error to avoid recursion
        print(f"Warning: Failed to cleanup logs: {e}", file=sys.stderr)


def _clear_log_file(log_file: Path):
    """Clear the content of a log file"""
    try:
        if log_file.exists():
            # Truncate the file to 0 bytes
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write("")
            
            # Also clean up backup files
            for backup_file in log_file.parent.glob(f"{log_file.name}.*"):
                if backup_file.is_file():
                    backup_file.unlink()
                    
    except Exception:
        # Silently ignore cleanup errors
        pass


def cleanup_logs_on_startup():
    """Clean up old log files when the application starts"""
    cleanup_logs(max_files=LOG_MAX_FILES_DEFAULT, max_total_size_mb=LOG_MAX_TOTAL_SIZE_MB_DEFAULT)


# ==================== Pretty Logging Helpers ====================

def log_section(logger: logging.Logger, title: str, icon: str = "📌", details: dict = None, mode: str = None):
    """
    Log a beautiful section with title and optional details
    
    Args:
        logger: Logger instance
        title: Main title text (will be uppercased in verbose/debug mode)
        icon: Emoji icon to use
        details: Optional dict of key-value pairs to display
        mode: 'customer' (simple), 'verbose' (detailed), or 'debug' (ultra-detailed).
              If None, uses current global log mode.
    
    Example:
        log_section(log, "LCU Connected", "🔗", {"Port": 2999, "Status": "Ready"})
    """
    # Use global log mode if not specified
    if mode is None:
        mode = get_log_mode()
    
    # In customer mode, use simpler format without separators
    if mode == 'customer':
        if details:
            detail_str = ", ".join(f"{k}: {v}" for k, v in details.items())
            logger.info(f"{icon} {title} ({detail_str})")
        else:
            logger.info(f"{icon} {title}")
    else:
        # Verbose/debug mode: use full format with separators
        logger.info("=" * LOG_SEPARATOR_WIDTH)
        logger.info(f"{icon} {title.upper()}")
        if details:
            for key, value in details.items():
                logger.info(f"   📋 {key}: {value}")
        logger.info("=" * LOG_SEPARATOR_WIDTH)


def log_event(logger: logging.Logger, event: str, icon: str = "✓", details: dict = None):
    """
    Log a single event with optional details
    
    Args:
        logger: Logger instance
        event: Event description
        icon: Icon/emoji to use
        details: Optional dict of key-value pairs
    
    Example:
        log_event(log, "Game process found", "🎮", {"PID": 12345, "Status": "Suspended"})
    """
    logger.info(f"{icon} {event}")
    if details:
        for key, value in details.items():
            logger.info(f"   • {key}: {value}")


def log_action(logger: logging.Logger, action: str, icon: str = "⚡"):
    """
    Log an action being performed
    
    Args:
        logger: Logger instance
        action: Action description
        icon: Icon/emoji to use
    
    Example:
        log_action(log, "Injecting skin...", "💉")
    """
    logger.info(f"{icon} {action}")


def log_success(logger: logging.Logger, message: str, icon: str = "✅"):
    """
    Log a success message
    
    Args:
        logger: Logger instance
        message: Success message
        icon: Icon/emoji to use
    
    Example:
        log_success(log, "Skin injected successfully!")
    """
    logger.info(f"{icon} {message}")


def log_status(logger: logging.Logger, status: str, value: any, icon: str = "ℹ️"):
    """
    Log a status update
    
    Args:
        logger: Logger instance
        status: Status name
        value: Status value
        icon: Icon/emoji to use
    
    Example:
        log_status(log, "Champion", "Ahri", "🎯")
    """
    logger.info(f"{icon} {status}: {value}")