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
from urllib3.exceptions import InsecureRequestWarning
from logging.handlers import RotatingFileHandler
from pathlib import Path


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
        # Create logs directory if it doesn't exist
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        
        # Setup rotating file handler (max 10MB per file, keep 5 files)
        log_file = logs_dir / "skincloner.log"
        file_handler = RotatingFileHandler(
            log_file, 
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
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
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    
    # Add a console print to ensure output is visible (only if we have stdout and it's not redirected)
    if sys.stdout is not None and not (hasattr(sys.stdout, 'name') and sys.stdout.name == os.devnull):
        try:
            # Use logging instead of direct print to avoid blocking
            logger = logging.getLogger("startup")
            logger.info("=" * 60)
            logger.info("SkinCloner - Starting...")
            logger.info("=" * 60)
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
