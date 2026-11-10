#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Logging configuration and utilities

A log call only puts its record on a queue and returns: one background thread
(LogWriter) formats the records and writes them to the log file, and to the
console when there is one. The threads that log (the countdown ticker, the
WebSocket handlers, the injection) never wait on the disk or on each other.

The file is flushed each time the writer has caught up, so a line reaches the
disk within milliseconds of being logged. A path that ends the process without
running the exit handlers (os._exit) calls flush_logging() first.
"""

# Standard library imports
import atexit
import os
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Third-party imports
import logging
import logging.handlers
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

FILE_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
CONSOLE_DATE_FORMAT = "%H:%M:%S"
# How long a flush or the shutdown waits for the writer to catch up
LOG_FLUSH_TIMEOUT_S = 2.0

def get_log_mode() -> str:
    """Get the current logging mode"""
    return _CURRENT_LOG_MODE


def _line_format(log_mode: str) -> str:
    """The line layout of a log mode."""
    if log_mode == 'verbose':
        # Detailed format for developer logs
        return "%(asctime)s | %(levelname)-7s | %(message)s"
    if log_mode == 'debug':
        # Ultra-detailed format with logger name and function
        return "%(asctime)s | %(levelname)-7s | %(name)-15s | %(funcName)-20s | %(message)s"
    # Clean, minimal format for customer logs
    return "%(asctime)s | %(message)s"


def _level_for(log_mode: str) -> int:
    """The lowest level a log mode shows."""
    if log_mode == 'debug':
        return TRACE  # Show everything including TRACE
    if log_mode == 'verbose':
        return logging.DEBUG  # Show DEBUG and above
    return logging.INFO  # Show INFO and above (clean output)


class TimestampFormatter(logging.Formatter):
    """Stamps a line with the time its record was logged, to the millisecond.

    The record's own time (record.created) is used, not the time the line is
    written: the writer thread formats a record after the call that logged it
    returned.
    """

    def __init__(self, fmt: str, datefmt: str):
        super().__init__(fmt)
        self._datefmt = datefmt

    def formatTime(self, record, datefmt=None):
        when = time.strftime(self._datefmt, time.localtime(record.created))
        return f"{when}.{min(int(record.msecs), 999):03d}"


class RotatingLogFileHandler(logging.Handler):
    """
    Writes to a log file and rolls over to a new one when it reaches a size.

    - Creates files as: base.ext, base.ext.1, base.ext.2, ...
    - Does not delete on rotation (retention handled separately on startup)
    - Counts the bytes it writes instead of asking the disk for the size on
      every line
    - autoflush=False leaves the flushing to the caller (the writer thread
      flushes once it has caught up)
    """
    def __init__(self, base_path: Path, max_bytes: int, autoflush: bool = True):
        super().__init__()
        self.base_path = Path(base_path)
        self.baseFilename = str(self.base_path)
        self.max_bytes = max_bytes
        self.autoflush = autoflush
        self._index = 0
        self.current_path = self.base_path
        self._stream = None
        self._size = 0
        self._stream, self._size = self._open(self.current_path)

    @staticmethod
    def _open(path: Path):
        stream = open(path, "ab")
        try:
            size = os.fstat(stream.fileno()).st_size
        except OSError:
            size = 0
        return stream, size

    def _rotate(self):
        index = self._index + 1
        path = self.base_path.with_name(f"{self.base_path.name}.{index}")
        # Open the next file first: if that fails, the current one is kept
        stream, size = self._open(path)
        old = self._stream
        self._index, self.current_path, self._stream, self._size = index, path, stream, size
        try:
            old.close()
        except Exception:
            pass

    def emit(self, record):
        try:
            if self._stream is None:
                return
            data = (self.format(record) + os.linesep).encode("utf-8", "backslashreplace")
            if self._size >= self.max_bytes:
                try:
                    self._rotate()
                except Exception:
                    pass  # Never break logging due to rotation errors
            self._stream.write(data)
            self._size += len(data)
            if self.autoflush:
                self._stream.flush()
        except Exception:
            # Swallow any errors to avoid crashing the app due to logging
            pass

    def flush(self):
        self.acquire()
        try:
            if self._stream is not None:
                self._stream.flush()
        except Exception:
            pass
        finally:
            self.release()

    def close(self):
        self.acquire()
        try:
            stream, self._stream = self._stream, None
            if stream is not None:
                try:
                    stream.flush()
                finally:
                    stream.close()
        except Exception:
            pass
        finally:
            self.release()
        try:
            super().close()
        except Exception:
            pass


class SafeStreamHandler(logging.StreamHandler):
    """A stream handler that drops a line the console cannot take."""

    def emit(self, record):
        try:
            self.stream.write(self.format(record) + self.terminator)
            self.stream.flush()
        except Exception:
            # The stream is blocking, broken or closed - skip this message
            pass


_STOP = object()


class _LogWriter:
    """The thread that writes the queued records to the handlers."""

    def __init__(self, handlers: List[logging.Handler]):
        self.queue: queue.SimpleQueue = queue.SimpleQueue()
        self.handlers = list(handlers)
        self._thread = threading.Thread(target=self._run, daemon=True, name="LogWriter")

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while True:
            item = self.queue.get()
            # Write everything that is waiting, then flush once
            while True:
                if item is _STOP:
                    self._flush()
                    return
                if isinstance(item, threading.Event):
                    self._flush()
                    item.set()
                else:
                    self._write(item)
                try:
                    item = self.queue.get_nowait()
                except queue.Empty:
                    break
            self._flush()

    def _write(self, record) -> None:
        for handler in self.handlers:
            try:
                if record.levelno >= handler.level:
                    handler.handle(record)
            except Exception:
                pass  # a line that cannot be written is dropped

    def _flush(self) -> None:
        for handler in self.handlers:
            try:
                handler.flush()
            except Exception:
                pass

    def _reachable(self) -> bool:
        return self._thread.is_alive() and threading.current_thread() is not self._thread

    def flush(self, timeout: float) -> bool:
        """Wait until every record queued so far is on disk. Whether it is."""
        if not self._reachable():
            return False
        done = threading.Event()
        self.queue.put(done)
        return done.wait(timeout)

    def stop(self, timeout: float) -> None:
        """Write what is queued, then end the thread."""
        if not self._reachable():
            return
        self.queue.put(_STOP)
        self._thread.join(timeout)


# The running writer, the root handler that feeds it, and the handlers it writes to
_WRITER: Optional[_LogWriter] = None
_QUEUE_HANDLER: Optional[logging.Handler] = None
_TARGET_HANDLERS: List[logging.Handler] = []
_LOG_FILE: Optional[Path] = None
_EXIT_HOOK_INSTALLED = False


def get_log_file() -> Optional[Path]:
    """This session's log file, or None when no file is written."""
    return _LOG_FILE


def flush_logging(timeout: float = LOG_FLUSH_TIMEOUT_S) -> bool:
    """Wait until everything logged so far is in the log file.

    Call it before ending the process with os._exit (which runs no exit
    handler), and where a line must not be lost. Returns whether it is written.
    """
    writer = _WRITER
    if writer is None:
        return True
    return writer.flush(timeout)


def shutdown_logging(timeout: float = LOG_FLUSH_TIMEOUT_S) -> None:
    """Write what is queued and stop the writer thread.

    Whatever is logged afterwards (the interpreter's last moments) is written
    directly by the calling thread, so nothing is lost on the way out.
    """
    global _WRITER, _QUEUE_HANDLER
    writer, queue_handler = _WRITER, _QUEUE_HANDLER
    _WRITER = _QUEUE_HANDLER = None
    if writer is None:
        return
    root = logging.getLogger()
    for handler in writer.handlers:
        if isinstance(handler, RotatingLogFileHandler):
            handler.autoflush = True
        root.addHandler(handler)
    if queue_handler is not None:
        root.removeHandler(queue_handler)
    writer.stop(timeout)


def _is_real_stream(stream) -> bool:
    """Whether *stream* shows somewhere (the windowed app's are None or devnull)."""
    return stream is not None and getattr(stream, 'name', None) != os.devnull


def _close_previous_setup() -> None:
    """End an earlier setup_logging: its writer, its handlers."""
    shutdown_logging()
    for handler in _TARGET_HANDLERS:
        try:
            handler.close()
        except Exception:
            pass
    _TARGET_HANDLERS.clear()


def setup_logging(log_mode: str = 'customer', *, write_logs: bool = True):
    """
    Setup logging configuration with three modes.

    Args:
        log_mode: 'customer' (clean logs), 'verbose' (developer), or 'debug' (ultra-detailed)
        write_logs: If False, skip creating log files (useful for --dev runs).
    """
    # Store the log mode globally
    global _CURRENT_LOG_MODE, _WRITER, _QUEUE_HANDLER, _LOG_FILE, _EXIT_HOOK_INSTALLED
    _close_previous_setup()
    _CURRENT_LOG_MODE = log_mode
    _LOG_FILE = None
    level = _level_for(log_mode)
    line_format = _line_format(log_mode)

    for stream in (sys.stdout, sys.stderr):
        if _is_real_stream(stream):
            try:
                stream.reconfigure(line_buffering=True)
            except (AttributeError, OSError, ValueError):
                pass  # the stream doesn't support reconfigure

    targets: List[logging.Handler] = []

    # Console: only when there is one. The windowed app has none (its streams
    # are None or devnull), and formatting every line for it was wasted work
    console_stream = next((s for s in (sys.stdout, sys.stderr) if _is_real_stream(s)), None)
    if console_stream is not None:
        console_handler = SafeStreamHandler(console_stream)
        console_handler.setFormatter(TimestampFormatter(line_format, CONSOLE_DATE_FORMAT))
        console_handler.setLevel(level)
        targets.append(console_handler)

    # Setup file logging (only if dev mode isn't explicitly suppressing it)
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
            # The writer thread flushes it each time it has caught up
            file_handler = RotatingLogFileHandler(log_file, max_bytes, autoflush=False)
            file_handler.setFormatter(TimestampFormatter(line_format, FILE_DATE_FORMAT))
            file_handler.setLevel(level)
            targets.append(file_handler)
            _LOG_FILE = log_file
        except Exception as e:
            # If file logging fails, continue without it
            log_file = None
            print(f"Warning: Could not setup file logging: {e}", file=sys.stderr)

    root = logging.getLogger()
    root.handlers.clear()
    _TARGET_HANDLERS.extend(targets)

    if targets:
        # Every log call queues its record; the writer thread does the rest
        writer = _LogWriter(targets)
        queue_handler = logging.handlers.QueueHandler(writer.queue)
        queue_handler.setLevel(level)
        root.addHandler(queue_handler)
        writer.start()
        _WRITER, _QUEUE_HANDLER = writer, queue_handler
        if not _EXIT_HOOK_INSTALLED:
            # Registered after logging's own exit handler, so it runs before it
            atexit.register(shutdown_logging)
            _EXIT_HOOK_INSTALLED = True
    else:
        root.addHandler(logging.NullHandler())

    # Nothing shows a record below the mode's level, so the root logger turns
    # it away before a record is even built. A logger that needs more (a
    # dedicated one, the updater's routing) sets its own level
    root.setLevel(level)

    # Add a console print to ensure output is visible (only if we have stdout and it's not redirected)
    if _is_real_stream(sys.stdout):
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
    # websocket-client logs "<error> - goodbye" at ERROR after every failed run_forever, even the
    # startup race where the LCU port is up before its WebSocket accepts. The same error already
    # reaches our on_error callback and the retry WARNING, so the library copy is only noise.
    logging.getLogger("websocket").setLevel(logging.CRITICAL)

    # Disable SSL warnings for LCU (self-signed cert)
    urllib3.disable_warnings(InsecureRequestWarning)


class _ThreadExceptionLogger:
    """``threading.excepthook`` that logs the traceback and then delegates to the previous hook."""

    def __init__(self, previous_hook):
        self._previous_hook = previous_hook

    def __call__(self, args: threading.ExceptHookArgs) -> None:
        if args.exc_type is not SystemExit:
            thread_name = args.thread.name if args.thread is not None else "unknown"
            exc_info = args.exc_value if args.exc_value is not None else False
            get_logger().critical("Uncaught exception in thread %s: %s", thread_name, args.exc_type.__name__, exc_info=exc_info)
            flush_logging()  # the traceback must reach the file whatever happens next
        self._previous_hook(args)


def install_uncaught_exception_logging() -> None:
    """Log exceptions that escape thread targets.

    The frozen app runs without a console, so the default hook's stderr output is lost
    and a dead worker thread (phase, ticker, monitor) would leave no trace in the log.
    """
    if isinstance(threading.excepthook, _ThreadExceptionLogger):
        return
    threading.excepthook = _ThreadExceptionLogger(threading.excepthook)


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

        # Written by the calling thread and flushed on every line: a dedicated
        # log is low volume (the updater's), and must survive its os._exit
        file_handler = RotatingLogFileHandler(base_path, max_bytes, autoflush=True)
        file_handler.setFormatter(TimestampFormatter(_line_format(log_mode), FILE_DATE_FORMAT))
        file_handler.setLevel(_level_for(log_mode))

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
