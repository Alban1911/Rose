#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Global constants for Rose
All arbitrary values are centralized here for easy tracking and modification
"""

import shutil
from typing import TYPE_CHECKING, Optional, Tuple
from pathlib import Path
import configparser

from utils.core.paths import get_user_data_dir

# =============================================================================
# APPLICATION METADATA
# =============================================================================

APP_VERSION = "1.1.0"                          # Application version
APP_USER_AGENT = f"Rose/{APP_VERSION}"  # User-Agent header for HTTP requests

_CONFIG = configparser.ConfigParser()


def get_config_file_path() -> Path:
    config_dir = get_user_data_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.ini"


def _reload_config() -> None:
    _CONFIG.clear()
    config_path = get_config_file_path()
    if not config_path.exists():
        legacy_path = Path("config.ini")
        if legacy_path.exists():
            try:
                shutil.copy2(legacy_path, config_path)
            except Exception:
                pass
    if config_path.exists():
        try:
            _CONFIG.read(config_path)
        except Exception:
            pass


_reload_config()


def get_config_option(section: str, option: str, fallback: Optional[str] = None) -> Optional[str]:
    _reload_config()
    if _CONFIG.has_option(section, option):
        return _CONFIG.get(section, option)
    return fallback


def get_config_float(section: str, option: str, fallback: float) -> float:
    value = get_config_option(section, option)
    if value is None:
        return fallback
    try:
        return float(value)
    except ValueError:
        return fallback


def set_config_option(section: str, option: str, value: str) -> None:
    config_path = get_config_file_path()
    config = configparser.ConfigParser()
    if config_path.exists():
        try:
            config.read(config_path)
        except Exception:
            pass
    if section not in config:
        config.add_section(section)
    config.set(section, option, value)
    try:
        with open(config_path, "w", encoding="utf-8") as fh:
            config.write(fh)
    except Exception:
        pass


# =============================================================================
# UI DETECTION CONSTANTS
# =============================================================================

# Skin matching
SKIN_NAME_MIN_SIMILARITY = 0.7  # Minimum similarity for fuzzy skin name matching

# =============================================================================
# THREAD POLLING INTERVALS
# =============================================================================

# Phase monitoring
PHASE_POLL_INTERVAL_DEFAULT = 0.5  # Seconds between phase checks
PHASE_HZ_DEFAULT = 2.0             # Phase check frequency (Hz)

# Champion monitoring
CHAMP_POLL_INTERVAL = 0.25  # Seconds between champion state checks

# LCU connection monitoring
LCU_MONITOR_INTERVAL = 1.0  # Seconds between LCU connection checks

# Main loop sleep intervals
MAIN_LOOP_SLEEP = 0.016     # Main loop iteration sleep time (16ms for 60 FPS responsive chroma UI)


# =============================================================================
# WEBSOCKET CONSTANTS
# =============================================================================

WS_PING_INTERVAL_DEFAULT = 20  # Seconds between WebSocket pings
WS_PING_TIMEOUT_DEFAULT = 10   # Seconds before WebSocket ping times out
WS_RECONNECT_DELAY = 1.0       # Seconds to wait before WebSocket reconnect

# Lock detection timing
# Note: Loadout timer ONLY starts on FINALIZATION phase (final countdown before game start)
# This prevents premature timer start in game modes where all champions lock before bans complete
WS_PROBE_ITERATIONS = 8        # Number of LCU timer probe attempts
WS_PROBE_SLEEP_MS = 60         # Milliseconds between probe attempts (0.06s)
WS_PROBE_WINDOW_MS = 480       # Total probe window (8 * 60ms ~= 480ms)


# =============================================================================
# LOADOUT TIMER CONSTANTS
# =============================================================================

TIMER_HZ_DEFAULT = 1000                     # Countdown display frequency (Hz)
TIMER_HZ_MIN = 10                           # Minimum timer frequency
TIMER_HZ_MAX = 2000                         # Maximum timer frequency
TIMER_POLL_PERIOD_S = 0.2                   # Seconds between LCU resync checks
FALLBACK_LOADOUT_MS_DEFAULT = 0             # Fallback countdown duration (ms)

# Skin injection timing
SKIN_THRESHOLD_MS_DEFAULT = 300             # Time before loadout ends to write skin (ms)
BASE_SKIN_VERIFICATION_WAIT_S = 0.15        # Seconds to wait for LCU to process base skin change
PERSISTENT_MONITOR_START_SECONDS = 1        # Seconds remaining when persistent game monitor starts
PERSISTENT_MONITOR_CHECK_INTERVAL_S = 0.05  # Seconds between game process checks
PERSISTENT_MONITOR_IDLE_INTERVAL_S = 0.1    # Seconds to wait when game already suspended
PERSISTENT_MONITOR_WAIT_TIMEOUT_S = 20.0    # Max seconds to wait for persistent monitor to suspend game
PERSISTENT_MONITOR_WAIT_INTERVAL_S = 0.1    # Seconds between checks while waiting for suspension
PERSISTENT_MONITOR_AUTO_RESUME_S = 20.0     # Auto-resume game after this many seconds if still suspended (safety)
GAME_RESUME_VERIFICATION_WAIT_S = 0.1       # Seconds to wait after resume for status verification
GAME_RESUME_MAX_ATTEMPTS = 3                # Max attempts to resume game (handles multiple suspensions)

# Game delay strategies
ENABLE_PRIORITY_BOOST = True         # Boost injection process priority to HIGH
ENABLE_GAME_SUSPENSION = True        # Suspend game process during injection (RISKY - may trigger anti-cheat)


# =============================================================================
# RATE LIMITING CONSTANTS (GitHub API)
# =============================================================================

# Request timing
RATE_LIMIT_MIN_INTERVAL = 1.0        # Minimum seconds between API requests
RATE_LIMIT_REQUEST_TIMEOUT = 30      # Seconds before request times out
RATE_LIMIT_STREAM_TIMEOUT = 60       # Seconds for streaming downloads

# Rate limit thresholds
RATE_LIMIT_LOW_THRESHOLD = 10        # Trigger warning when below this
RATE_LIMIT_WARNING_50 = 50           # Delay threshold 1
RATE_LIMIT_WARNING_100 = 100         # Delay threshold 2
RATE_LIMIT_INITIAL = 5000            # Assumed initial rate limit

# Adaptive delays (seconds)
RATE_LIMIT_DELAY_LOW = 2.0           # Delay when rate limit is very low
RATE_LIMIT_DELAY_MEDIUM = 1.0        # Delay when rate limit is medium
RATE_LIMIT_DELAY_HIGH = 0.5          # Delay when rate limit is high

# Rate limit multipliers
RATE_LIMIT_BACKOFF_MULTIPLIER = 1.5  # Multiply interval by this when low


# =============================================================================
# LOGGING CONSTANTS
# =============================================================================

LOG_MAX_FILE_SIZE_MB_DEFAULT = 10        # Maximum single log file size before rolling (MB)
LOG_CHUNK_SIZE = 8192                    # Chunk size for file downloads
LOG_SEPARATOR_WIDTH = 80                 # Width of separator lines in logs (e.g., "=" * 80)


# =============================================================================
# PROCESS & THREAD TIMEOUT CONSTANTS
# =============================================================================

# Process termination timeouts (seconds)
PROCESS_TERMINATE_TIMEOUT_S = 5         # Timeout for process.wait() after terminate/kill
PROCESS_TERMINATE_WAIT_S = 0.3          # Short timeout for process wait after terminate() before kill()
PROCESS_ENUM_TIMEOUT_S = 2.0            # Timeout for process enumeration when finding runoverlay
THREAD_JOIN_TIMEOUT_S = 2               # Timeout for thread.join() on shutdown (increased from 1.0s)
THREAD_FORCE_EXIT_TIMEOUT_S = 4         # Total timeout before forcing app exit
INJECTION_LOCK_TIMEOUT_S = 2.0          # Timeout for acquiring injection lock

# Main loop watchdog timeouts (seconds)
MAIN_LOOP_STALL_THRESHOLD_S = 5.0       # Threshold for detecting main loop stalls
MAIN_LOOP_FORCE_QUIT_TIMEOUT_S = 2.0    # Timeout before forcing quit when stop flag is set
CHROMA_PANEL_PROCESSING_THRESHOLD_S = 1.0  # Warning threshold for chroma panel processing

# Process priority settings
# Note: Lower priority for injection processes can help prevent slowing down game launch
# But the CPU contention also provides a buffer window for late injections to complete

# API request timeouts (seconds)
LCU_API_TIMEOUT_S = 2.0                 # Timeout for LCU API requests
LCU_SKIN_SCRAPER_TIMEOUT_S = 3.0        # Timeout for LCU skin scraper requests
CHROMA_DOWNLOAD_TIMEOUT_S = 10          # Timeout for chroma preview downloads
DEFAULT_SKIN_DOWNLOAD_TIMEOUT_S = 30    # Timeout for skin downloads
SKIN_DOWNLOAD_STREAM_TIMEOUT_S = 60     # Timeout for streaming skin downloads

# =============================================================================
# SLEEP & DELAY CONSTANTS
# =============================================================================

# General sleep intervals (seconds)
TRAY_INIT_SLEEP_S = 0.2                 # Sleep after tray icon initialization
PROCESS_MONITOR_SLEEP_S = 0.5           # Sleep during process monitoring loop
WINDOW_CHECK_SLEEP_S = 1                # Sleep between window existence checks
API_POLITENESS_DELAY_S = 0.5            # Delay between API calls to be polite
CONSOLE_BUFFER_CLEAR_INTERVAL_S = 0.5   # Interval to clear console buffer on Windows

# =============================================================================
# SYSTEM TRAY CONSTANTS
# =============================================================================

# Tray icon initialization
TRAY_READY_MAX_WAIT_S = 5.0             # Maximum time to wait for tray icon to be ready
TRAY_READY_CHECK_INTERVAL_S = 0.1       # Interval to check if tray icon is ready
TRAY_THREAD_JOIN_TIMEOUT_S = 2.0        # Timeout for tray thread join on shutdown

# Tray icon dimensions
TRAY_ICON_WIDTH = 128                   # Tray icon width in pixels
TRAY_ICON_HEIGHT = 128                  # Tray icon height in pixels
TRAY_ICON_ELLIPSE_COORDS = [16, 16, 112, 112]  # Ellipse coordinates for icon
TRAY_ICON_BORDER_WIDTH = 4              # Border width for icon ellipse

# Tray icon text and indicators
TRAY_ICON_FONT_SIZE = 40                # Font size for "SC" text on icon
TRAY_ICON_TEXT_X = 36                   # X position for text
TRAY_ICON_TEXT_Y = 44                   # Y position for text
TRAY_ICON_DOT_SIZE = 70                 # Size of status indicator dot

# =============================================================================
# WINDOWS API CONSTANTS
# =============================================================================

# Process access rights
WINDOWS_PROCESS_QUERY = 0x1000          # PROCESS_QUERY_LIMITED_INFORMATION

# Window display commands
WINDOWS_SW_HIDE = 0                      # Hide window command

# MessageBox flags
WINDOWS_MB_ICONERROR = 0x10              # Error icon for message box

# DPI Awareness
WINDOWS_DPI_AWARENESS_SYSTEM = 1         # PROCESS_SYSTEM_DPI_AWARE


# =============================================================================
# FILE AND DIRECTORY PATHS
# =============================================================================

# Lock file name
LOCK_FILE_NAME = "rose.lock"

# Log file patterns (handles .log files)
LOG_FILE_PATTERN = "rose_*.log*"
UPDATER_LOG_FILE_PATTERN = "log_updater_*.log*"
LOG_TIMESTAMP_FORMAT = "%d-%m-%Y_%H-%M-%S"  # European format, Windows-compatible


# =============================================================================
# PHASE NAMES
# =============================================================================

# Interesting game phases to log
INTERESTING_PHASES = {
    "Lobby",
    "Matchmaking", 
    "ReadyCheck",
    "ChampSelect",
    "FINALIZATION",
    "GameStart",
    "InProgress",
    "EndOfGame"
}


# =============================================================================
# ANALYTICS CONSTANTS
# =============================================================================

ANALYTICS_SERVER_URL = "https://api.leagueunlocked.net/analytics/ping"  # Analytics server endpoint
ANALYTICS_PING_INTERVAL_S = 300  # Seconds between analytics pings (5 minutes)
ANALYTICS_ENABLED = True  # Enable/disable analytics tracking
ANALYTICS_TIMEOUT_S = 30  # Request timeout in seconds

# =============================================================================
# DEFAULT ARGUMENTS
# =============================================================================


# Boolean flags
DEFAULT_VERBOSE = False
DEFAULT_DOWNLOAD_SKINS = True
DEFAULT_FORCE_UPDATE_SKINS = False
