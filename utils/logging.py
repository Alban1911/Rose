#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Logging configuration and utilities
"""

import os
import sys
import time
import logging
import urllib3
import threading
import queue
import re
from datetime import datetime
from urllib3.exceptions import InsecureRequestWarning
from pathlib import Path
from config import (
    LOG_MAX_FILES_DEFAULT, LOG_MAX_TOTAL_SIZE_MB_DEFAULT,
    LOG_FILE_PATTERN, LOG_TIMESTAMP_FORMAT, LOG_SEPARATOR_WIDTH,
    PRODUCTION_MODE
)


class SanitizingFilter(logging.Filter):
    """
    Logging filter that sanitizes sensitive information in production mode.
    Prevents reverse engineering by removing implementation details from logs.
    """
    
    # Patterns to sanitize (compiled regex for performance)
    PATTERNS = [
        # API URLs and endpoints
        (re.compile(r'https?://[^\s]+'), '[URL_REDACTED]'),
        # File paths - Windows paths only (C:\, D:\, etc. with backslashes)
        (re.compile(r'[A-Za-z]:\\[^\s]*'), '[PATH_REDACTED]'),
        # File paths - Unix paths (multiple slashes)
        (re.compile(r'/[^/\s]+/[^\s]+'), '[PATH_REDACTED]'),
        # Clean up partial path leaks after redaction
        (re.compile(r'\[PATH_REDACTED\][^\s]*'), '[PATH_REDACTED]'),
        # API tokens/passwords (though these shouldn't be logged anyway)
        (re.compile(r'(token|password|pw|key|auth)["\s:=]+[^\s"]+', re.IGNORECASE), r'\1=[REDACTED]'),
        # Port numbers (could reveal implementation)
        (re.compile(r'port["\s:=]+\d+', re.IGNORECASE), 'port=[REDACTED]'),
        # GitHub repository references
        (re.compile(r'github\.com/[^\s/]+/[^\s/]+'), 'github.com/[REDACTED]'),
        # Specific implementation details
        (re.compile(r'(cslol|wad|injection|inject|dll|suspend|process)', re.IGNORECASE), '[IMPL_DETAIL]'),
    ]
    
    # Sensitive message prefixes to completely suppress in production
    SUPPRESS_PREFIXES = [
        # File/system initialization
        'File logging initialized',
        'Log file location:',
        '[ws] WebSocket',
        'LCU lockfile',
        '  - VERIFIED actual position:',
        
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
        
        # OCR implementation details
        '[OCR:COMPUTE]',
        '[OCR:timing]',
        '[OCR:change]',
        '[OCR:CACHE-HIT]',
        '[ocr] OCR running',
        '[ocr] OCR stopped',
        
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
        
        # Chroma checking spam
        '[CHROMA] Checking skin_id=',
        '[CHROMA] Showing button',
        '[CHROMA] Updated last_hovered_skin_id',
        '[CHROMA] Chroma selected:',
        '[CHROMA] Panel widgets destroyed',
        
        # Status icon updates (just UI noise)
        'Locked icon shown',
        'Golden locked icon shown',
        'Golden unlocked icon shown',
        '[APP STATUS]',
        
        # Repository/skin download details
        'Using repository ZIP downloader',
        'skins, skipping download',
        'preview images',
    ]
    
    def __init__(self, production_mode: bool):
        super().__init__()
        self.production_mode = production_mode
    
    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter log records. Returns False to suppress, True to allow.
        Modifies record.msg to sanitize sensitive information.
        """
        if not self.production_mode:
            # In development mode, allow everything through unchanged
            return True
        
        # Suppress DEBUG messages in production
        if record.levelno < logging.INFO:
            return False
        
        # Check if message should be completely suppressed
        msg_str = str(record.getMessage())
        for prefix in self.SUPPRESS_PREFIXES:
            if msg_str.startswith(prefix):
                return False
        
        # Sanitize the message
        sanitized = record.msg
        if isinstance(sanitized, str):
            for pattern, replacement in self.PATTERNS:
                sanitized = pattern.sub(replacement, sanitized)
            record.msg = sanitized
        
        return True


def setup_logging(verbose: bool):
    """Setup logging configuration"""
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
    
    # Set up formatter
    fmt = "%(_when)s | %(levelname)-7s | %(message)s"
    
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
        log_file = logs_dir / f"leagueunlocked_{timestamp}.log"
        
        # Setup file handler (no rotation needed since each session has its own file)
        file_handler = logging.FileHandler(
            log_file, 
            encoding='utf-8'
        )
        
        # File formatter with full timestamp and more details
        file_fmt = "%(_when)s | %(levelname)-7s | %(name)-15s | %(message)s"
        
        class _FileFmt(logging.Formatter):
            def format(self, record):
                record._when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                return super().format(record)
        
        file_handler.setFormatter(_FileFmt(file_fmt))
        # IMPORTANT: File handler logging level depends on production mode
        # Production: INFO+ only (prevent reverse engineering)
        # Development: DEBUG level (full verbose output for troubleshooting)
        if PRODUCTION_MODE:
            file_handler.setLevel(logging.INFO)
        else:
            file_handler.setLevel(logging.DEBUG)
        
        # Add sanitizing filter to file handler
        file_handler.addFilter(SanitizingFilter(PRODUCTION_MODE))
        
    except Exception as e:
        # If file logging fails, continue without it
        file_handler = None
        print(f"Warning: Could not setup file logging: {e}", file=sys.stderr)
    
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(h)
    if file_handler:
        root.addHandler(file_handler)
    
    # Console handler respects verbose flag (only shows INFO and above by default)
    # This keeps console output clean unless user explicitly wants verbose mode
    # In production mode, always use INFO level regardless of verbose flag
    if PRODUCTION_MODE:
        h.setLevel(logging.INFO)
    else:
        h.setLevel(logging.DEBUG if verbose else logging.INFO)
    
    # Add sanitizing filter to console handler
    h.addFilter(SanitizingFilter(PRODUCTION_MODE))
    
    # Root logger must be at DEBUG to allow file handler to receive all messages
    # This is critical - if root is at INFO, DEBUG messages never reach the file handler
    root.setLevel(logging.DEBUG)
    
    # Add a console print to ensure output is visible (only if we have stdout and it's not redirected)
    if sys.stdout is not None and not (hasattr(sys.stdout, 'name') and sys.stdout.name == os.devnull):
        try:
            # Use logging instead of direct print to avoid blocking
            logger = logging.getLogger("startup")
            logger.info("=" * LOG_SEPARATOR_WIDTH)
            logger.info(f"LeagueUnlocked - Starting... (Log file: {log_file.name})")
            logger.info("=" * LOG_SEPARATOR_WIDTH)
            # Log a DEBUG message to verify verbose file logging is working
            logger.debug("File logging initialized - all DEBUG messages will be saved to log file")
            logger.debug(f"Log file location: {log_file.absolute()}")
            if verbose:
                logger.info("Verbose mode: ON (console shows DEBUG messages)")
            else:
                logger.info("Verbose mode: OFF (console shows INFO and above, file captures all DEBUG)")
        except (AttributeError, OSError):
            pass  # stdout is broken, ignore
    
    # Suppress HTTPS/HTTP logs
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
    logging.getLogger("requests.packages.urllib3.connectionpool").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    
    # Disable SSL warnings for LCU (self-signed cert)
    urllib3.disable_warnings(InsecureRequestWarning)


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

def log_section(logger: logging.Logger, title: str, icon: str = "📌", details: dict = None):
    """
    Log a beautiful section with title and optional details
    
    Args:
        logger: Logger instance
        title: Main title text (will be uppercased)
        icon: Emoji icon to use
        details: Optional dict of key-value pairs to display
    
    Example:
        log_section(log, "LCU Connected", "🔗", {"Port": 2999, "Status": "Ready"})
    """
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