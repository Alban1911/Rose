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
from datetime import datetime
from urllib3.exceptions import InsecureRequestWarning
from logging.handlers import RotatingFileHandler
from pathlib import Path
from constants import (
    LOG_MAX_FILES_DEFAULT, LOG_MAX_TOTAL_SIZE_MB_DEFAULT,
    LOG_FILE_PATTERN, LOG_TIMESTAMP_FORMAT
)


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
    
    # Create a safe logging handler that works even without console
    class SafeStreamHandler(logging.StreamHandler):
        """A stream handler that safely handles None streams"""
        def __init__(self, stream=None):
            # If stream is None, create a dummy stream that does nothing
            if stream is None:
                import io
                stream = io.StringIO()
            super().__init__(stream)
        
        def emit(self, record):
            try:
                super().emit(record)
            except (AttributeError, OSError):
                # If the stream is broken, silently ignore
                pass
    
    # Use stderr if stdout is None or redirected to devnull (windowed mode), but make it safe
    if sys.stdout is not None and hasattr(sys.stdout, 'name') and sys.stdout.name == os.devnull:
        output_stream = sys.stderr if sys.stderr is not None else sys.stdout
    else:
        output_stream = sys.stdout if sys.stdout is not None else sys.stderr
    h = SafeStreamHandler(output_stream)
    fmt = "%(_when)s | %(levelname)-7s | %(message)s"
    
    class _Fmt(logging.Formatter):
        def format(self, record):
            record._when = time.strftime("%H:%M:%S", time.localtime())
            return super().format(record)
    
    h.setFormatter(_Fmt(fmt))
    
    # Setup file logging
    try:
        # Create logs directory in user data directory
        from .paths import get_user_data_dir
        logs_dir = get_user_data_dir() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Create a unique log file for this session with timestamp
        # Format: dd-mm-yyyy_hh-mm-ss (European format, no colons for Windows compatibility)
        timestamp = datetime.now().strftime(LOG_TIMESTAMP_FORMAT)
        log_file = logs_dir / f"skincloner_{timestamp}.log"
        
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
        file_handler.setLevel(logging.DEBUG)  # Log everything to file
        
    except Exception as e:
        # If file logging fails, continue without it
        file_handler = None
        print(f"Warning: Could not setup file logging: {e}", file=sys.stderr)
    
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(h)
    if file_handler:
        root.addHandler(file_handler)
    
    # Set console level based on verbose flag
    h.setLevel(logging.DEBUG if verbose else logging.INFO)
    
    # Always set root level to DEBUG for file logging (good for debugging)
    root.setLevel(logging.DEBUG)
    
    # Add a console print to ensure output is visible (only if we have stdout and it's not redirected)
    if sys.stdout is not None and not (hasattr(sys.stdout, 'name') and sys.stdout.name == os.devnull):
        try:
            # Use logging instead of direct print to avoid blocking
            logger = logging.getLogger("startup")
            logger.info("=" * LOG_SEPARATOR_WIDTH)
            logger.info(f"SkinCloner - Starting... (Log file: {log_file.name})")
            logger.info("=" * LOG_SEPARATOR_WIDTH)
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