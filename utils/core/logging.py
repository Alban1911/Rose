#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Logging configuration and utilities
"""

# Standard library imports
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

# Third-party imports
import logging
import urllib3
from urllib3.exceptions import InsecureRequestWarning

# Local imports
from config import (
    LOG_MAX_FILE_SIZE_MB_DEFAULT,
    LOG_FILE_PATTERN,
    LOG_TIMESTAMP_FORMAT,
    LOG_SEPARATOR_WIDTH,
    UPDATER_LOG_FILE_PATTERN,
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
_NAMED_LOGGERS: Dict[str, logging.Logger] = {}

def get_log_mode() -> str:
    """Get the current logging mode"""
    return _CURRENT_LOG_MODE


class SizeRotatingCompositeHandler(logging.Handler):
    """
    A handler that delegates to an inner file handler and rolls over
    to a new file when the current file size reaches a threshold.

    - Creates files as: base.ext, base.ext.1, base.ext.2, ...
    - Does not delete on rotation (retention handled separately on startup)
    """
    def __init__(self, base_path: Path, create_handler_fn, max_bytes: int):
        super().__init__()
        self.base_path = Path(base_path)
        self.create_handler_fn = create_handler_fn
        self.max_bytes = max_bytes
        self._index = 0
        self.current_path = self._compute_current_path()
        self.current_handler = self.create_handler_fn(self.current_path)
        self._stored_formatter = None
        # Ensure the inner handler starts at the same level/filters
        # as this composite handler once they are set by the caller

    def _compute_current_path(self) -> Path:
        if self._index == 0:
            return self.base_path
        return self.base_path.with_name(f"{self.base_path.name}.{self._index}")

    def _apply_stored_config(self):
        try:
            # Level
            self.current_handler.setLevel(self.level)
            # Formatter
            if self._stored_formatter is not None:
                self.current_handler.setFormatter(self._stored_formatter)
            # Filters
            for flt in getattr(self, 'filters', []) or []:
                try:
                    self.current_handler.addFilter(flt)
                except Exception:
                    pass
        except Exception:
            pass

    def _maybe_rotate(self):
        try:
            current_size = self.current_path.stat().st_size if self.current_path.exists() else 0
            if current_size >= self.max_bytes:
                try:
                    self.current_handler.close()
                except Exception:
                    pass
                self._index += 1
                self.current_path = self._compute_current_path()
                self.current_handler = self.create_handler_fn(self.current_path)
                self._apply_stored_config()
        except Exception:
            # Never break logging due to rotation errors
            pass

    def emit(self, record):
        try:
            self._maybe_rotate()
            self.current_handler.emit(record)
        except Exception:
            # Swallow any errors to avoid crashing the app due to logging
            pass

    def setFormatter(self, fmt):
        self._stored_formatter = fmt
        try:
            self.current_handler.setFormatter(fmt)
        except Exception:
            pass
        try:
            super().setFormatter(fmt)
        except Exception:
            pass

    def setLevel(self, level):
        try:
            super().setLevel(level)
        except Exception:
            pass
        try:
            self.current_handler.setLevel(level)
        except Exception:
            pass

    def addFilter(self, filter):
        try:
            super().addFilter(filter)
        except Exception:
            pass
        try:
            self.current_handler.addFilter(filter)
        except Exception:
            pass

    def close(self):
        try:
            self.current_handler.close()
        except Exception:
            pass
        try:
            super().close()
        except Exception:
            pass

def setup_logging(log_mode: str = 'customer', *, write_logs: bool = True):
    """
    Setup logging configuration with three modes.
    
    Args:
        log_mode: 'customer' (clean logs), 'verbose' (developer), or 'debug' (ultra-detailed)
        write_logs: If False, skip creating log files (useful for --dev runs).
    """
    # Store the log mode globally
    global _CURRENT_LOG_MODE
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
    
    # Setup file logging (only if dev mode isn't explicitly suppressing it)
    file_handler = None
    log_file = None
    if write_logs:
        try:
            # Create logs directory in user data directory
            from .paths import get_user_data_dir
            logs_dir = get_user_data_dir() / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            
            # Create a unique log file for this session with timestamp
            # Format: dd-mm-yyyy_hh-mm-ss (European format, no colons for Windows compatibility)
            timestamp = datetime.now().strftime(LOG_TIMESTAMP_FORMAT)
            
            max_bytes = int(LOG_MAX_FILE_SIZE_MB_DEFAULT * 1024 * 1024)
            log_file = logs_dir / f"rose_{timestamp}.log"
            def _factory_plain(p: Path):
                return logging.FileHandler(p, encoding='utf-8')
            file_handler = SizeRotatingCompositeHandler(log_file, _factory_plain, max_bytes)
            
            # File formatter based on log mode
            if log_mode == 'customer':
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
            if log_mode == 'debug':
                file_handler.setLevel(TRACE)  # Show everything including TRACE
            elif log_mode == 'verbose':
                file_handler.setLevel(logging.DEBUG)  # Show DEBUG and above
            else:  # customer mode
                file_handler.setLevel(logging.INFO)  # Show INFO and above
            
        except Exception as e:
            # If file logging fails, continue without it
            file_handler = None
            log_file = None
            print(f"Warning: Could not setup file logging: {e}", file=sys.stderr)
    
    root = logging.getLogger()
    root.handlers.clear()
    
    # Add console handler
    root.addHandler(h)
    # Console handler level based on log mode
    if log_mode == 'debug':
        h.setLevel(TRACE)  # Show everything including TRACE
    elif log_mode == 'verbose':
        h.setLevel(logging.DEBUG)  # Show DEBUG and above
    else:  # customer mode
        h.setLevel(logging.INFO)  # Show INFO and above (clean output)
    
    # Always add file handler
    if file_handler:
        root.addHandler(file_handler)
    
    # Root logger must be at TRACE to allow all handlers to receive all messages
    # This is critical - if root is at INFO, DEBUG/TRACE messages never reach handlers
    root.setLevel(TRACE)
    
    # Add a console print to ensure output is visible (only if we have stdout and it's not redirected)
    if sys.stdout is not None and not (hasattr(sys.stdout, 'name') and sys.stdout.name == os.devnull):
        try:
            # Use logging instead of direct print to avoid blocking
            logger = logging.getLogger("startup")
            
            # Show startup message based on log mode
            if _CURRENT_LOG_MODE == 'customer':
                # Clean startup for customer mode
                if log_file:
                    logger.info(f"Rose Started (Log: {log_file.name})")
                else:
                    logger.info("Rose Started (logs disabled)")
            else:
                # Detailed startup for verbose/debug modes
                logger.info("=" * LOG_SEPARATOR_WIDTH)
                if log_file:
                    logger.info(f"Rose - Starting... (Log file: {log_file.name})")
                else:
                    logger.info("Rose - Starting... (logs disabled)")
                logger.info("=" * LOG_SEPARATOR_WIDTH)
                
                # Log mode information
                if _CURRENT_LOG_MODE == 'debug':
                    logger.info("Debug mode: ON (ultra-detailed logs with function traces)")
                    if log_file:
                        logger.debug(f"Log file location: {log_file.absolute()}")
                elif _CURRENT_LOG_MODE == 'verbose':
                    logger.info("Verbose mode: ON (developer logs with technical details)")
                    if log_file:
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
    


def get_logger(name: str = "tracer") -> logging.Logger:
    """Get a logger instance"""
    return logging.getLogger(name)


def get_named_logger(name: str, prefix: str, log_mode: str = None) -> logging.Logger:
    """
    Create (or return) a dedicated logger that writes to its own rotating file.

    Args:
        name: Logger name (unique key).
        prefix: File prefix (e.g., 'log_updater').
        log_mode: Optional override for formatting levels; defaults to current global mode.
    """
    global _NAMED_LOGGERS

    if name in _NAMED_LOGGERS:
        return _NAMED_LOGGERS[name]

    if log_mode is None:
        log_mode = _CURRENT_LOG_MODE

    try:
        from .paths import get_user_data_dir
        logs_dir = get_user_data_dir() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime(LOG_TIMESTAMP_FORMAT)
        max_bytes = int(LOG_MAX_FILE_SIZE_MB_DEFAULT * 1024 * 1024)

        base_path = logs_dir / f"{prefix}_{timestamp}.log"

        def _factory_plain(p: Path):
            return logging.FileHandler(p, encoding="utf-8")

        file_handler = SizeRotatingCompositeHandler(base_path, _factory_plain, max_bytes)

        if log_mode == "verbose":
            file_fmt = "%(_when)s | %(levelname)-7s | %(message)s"
        elif log_mode == "debug":
            file_fmt = "%(_when)s | %(levelname)-7s | %(name)-15s | %(funcName)-20s | %(message)s"
        else:
            file_fmt = "%(_when)s | %(message)s"

        class _FileFmt(logging.Formatter):
            def format(self, record):
                record._when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                return super().format(record)

        file_handler.setFormatter(_FileFmt(file_fmt))

        if log_mode in ("verbose", "debug"):
            file_handler.setLevel(logging.DEBUG if log_mode != "debug" else TRACE)
        else:
            file_handler.setLevel(logging.INFO)

        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.addHandler(file_handler)
        logger.setLevel(TRACE)
        logger.propagate = False

        _NAMED_LOGGERS[name] = logger
        return logger
    except Exception as exc:  # noqa: BLE001
        fallback_logger = logging.getLogger(name)
        fallback_logger.setLevel(TRACE)
        fallback_logger.propagate = True
        fallback_logger.warning(f"Failed to configure dedicated logger '{name}': {exc}")
        _NAMED_LOGGERS[name] = fallback_logger
        return fallback_logger


def cleanup_logs():
    """
    Clean up old log files based on age.

    New policy:
        - Delete logs older than 1 day
        - No limit on file count or total size
        - Also clean up updater logs (`log_updater_*`)
    """
    try:
        from .paths import get_user_data_dir
        logs_dir = get_user_data_dir() / "logs"
        if not logs_dir.exists():
            return

        log_files = []
        for pattern in (LOG_FILE_PATTERN, UPDATER_LOG_FILE_PATTERN):
            log_files.extend(logs_dir.glob(pattern))
        now = time.time()
        max_age_seconds = 24 * 60 * 60  # 1 day

        for log_file in log_files:
            try:
                mtime = log_file.stat().st_mtime
                if now - mtime > max_age_seconds:
                    log_file.unlink()
            except Exception:
                pass

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
    cleanup_logs()


# ==================== Pretty Logging Helpers ====================

def log_section(logger: logging.Logger, title: str, icon: str = "", details: dict = None, mode: str = None):
    """
    Log a beautiful section with title and optional details
    
    Args:
        logger: Logger instance
        title: Main title text (will be uppercased in verbose/debug mode)
        icon: Icon prefix to use (empty by default)
        details: Optional dict of key-value pairs to display
        mode: 'customer' (simple), 'verbose' (detailed), or 'debug' (ultra-detailed).
              If None, uses current global log mode.
    
    Example:
        log_section(log, "LCU Connected", "", {"Port": 2999, "Status": "Ready"})
    """
    # Use global log mode if not specified
    if mode is None:
        mode = get_log_mode()
    
    # In customer mode, use simpler format without separators
    if mode == 'customer':
        if details:
            detail_str = ", ".join(f"{k}: {v}" for k, v in details.items())
            logger.info(f"{icon} {title} ({detail_str})" if icon else f"{title} ({detail_str})")
        else:
            logger.info(f"{icon} {title}" if icon else title)
    else:
        # Verbose/debug mode: use full format with separators
        logger.info("=" * LOG_SEPARATOR_WIDTH)
        logger.info(f"{icon} {title.upper()}" if icon else title.upper())
        if details:
            for key, value in details.items():
                logger.info(f"   {key}: {value}")
        logger.info("=" * LOG_SEPARATOR_WIDTH)


def log_event(logger: logging.Logger, event: str, icon: str = "", details: dict = None):
    """
    Log a single event with optional details
    
    Args:
        logger: Logger instance
        event: Event description
        icon: Icon prefix to use (empty by default)
        details: Optional dict of key-value pairs
    
    Example:
        log_event(log, "Game process found", "", {"PID": 12345, "Status": "Suspended"})
    """
    logger.info(f"{icon} {event}" if icon else event)
    if details:
        for key, value in details.items():
            logger.info(f"   • {key}: {value}")


def log_action(logger: logging.Logger, action: str, icon: str = ""):
    """
    Log an action being performed
    
    Args:
        logger: Logger instance
        action: Action description
        icon: Icon prefix to use (empty by default)
    
    Example:
        log_action(log, "Injecting skin...", "")
    """
    logger.info(f"{icon} {action}" if icon else action)


def log_success(logger: logging.Logger, message: str, icon: str = ""):
    """
    Log a success message
    
    Args:
        logger: Logger instance
        message: Success message
        icon: Icon prefix to use (empty by default)
    
    Example:
        log_success(log, "Skin injected successfully!")
    """
    logger.info(f"{icon} {message}" if icon else message)


def log_status(logger: logging.Logger, status: str, value: any, icon: str = ""):
    """
    Log a status update
    
    Args:
        logger: Logger instance
        status: Status name
        value: Status value
        icon: Icon prefix to use (empty by default)
    
    Example:
        log_status(log, "Champion", "Ahri", "")
    """
    logger.info(f"{icon} {status}: {value}" if icon else f"{status}: {value}")
