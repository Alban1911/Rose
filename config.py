#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Global constants for LeagueUnlocked
All arbitrary values are centralized here for easy tracking and modification
"""

import shutil
from typing import TYPE_CHECKING, Optional, Tuple
from pathlib import Path
import configparser

from utils.paths import get_user_data_dir

# =============================================================================
# APPLICATION METADATA
# =============================================================================

APP_VERSION = "Beta_1.3"                         # Application version
APP_USER_AGENT = f"LeagueUnlocked/{APP_VERSION}"  # User-Agent header for HTTP requests

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


# Production mode - controls logging verbosity and sensitive data exposure
# Set to True for releases to prevent reverse engineering via logs
# Set to False for development to get full debug information
PRODUCTION_MODE = False


# =============================================================================
# UI DETECTION CONSTANTS
# =============================================================================

# UI detection polling
UI_POLL_INTERVAL = 0.01  # Seconds between UI detection checks
UI_DETECTION_TIMEOUT = 5.0  # Timeout for finding UI elements
UIA_DELAY_MS = 5 # Milliseconds to wait after champion lock before starting UIA Detection

# UIA Detection coordinates (percentage-based, resolution-independent)
# THESE ARE THE CORRECT VALUES - DO NOT CHANGE WITHOUT TESTING
UI_DETECTION_SKIN_NAME_X_RATIO = 0.4925    # X position as percentage of window width (50% = center)
UI_DETECTION_SKIN_NAME_Y_RATIO = 0.6395  # Y position as percentage of window height (63.9% = constant for all skins of top pixel, +0.05% for safety)

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
MKOVERLAY_PROCESS_TIMEOUT_S = 60        # Timeout for mkoverlay process execution
THREAD_JOIN_TIMEOUT_S = 2               # Timeout for thread.join() on shutdown (increased from 1.0s)
THREAD_FORCE_EXIT_TIMEOUT_S = 4         # Total timeout before forcing app exit
INJECTION_LOCK_TIMEOUT_S = 2.0          # Timeout for acquiring injection lock

# Main loop watchdog timeouts (seconds)
MAIN_LOOP_STALL_THRESHOLD_S = 5.0       # Threshold for detecting main loop stalls
MAIN_LOOP_FORCE_QUIT_TIMEOUT_S = 2.0    # Timeout before forcing quit when stop flag is set
QT_EVENT_PROCESSING_THRESHOLD_S = 1.0   # Warning threshold for Qt event processing
CHROMA_PANEL_PROCESSING_THRESHOLD_S = 1.0  # Warning threshold for chroma panel processing

# Process priority settings
# Note: Lower priority for injection processes can help prevent slowing down game launch
# But the CPU contention also provides a buffer window for late injections to complete

# API request timeouts (seconds)
LCU_API_TIMEOUT_S = 2.0                 # Timeout for LCU API requests
LCU_SKIN_SCRAPER_TIMEOUT_S = 3.0        # Timeout for LCU skin scraper requests
DATA_DRAGON_API_TIMEOUT_S = 8           # Timeout for Data Dragon API requests
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

# UI animation delays (milliseconds)
UI_QTIMER_CALLBACK_DELAY_MS = 50        # Delay before executing QTimer callbacks


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
# CHROMA PANEL UI CONSTANTS - RESOLUTION ADAPTIVE
# =============================================================================

# Reference resolution (UI designed for this resolution)
CHROMA_UI_REFERENCE_WIDTH = 1600
CHROMA_UI_REFERENCE_HEIGHT = 900

# Hard-coded configurations for three supported resolutions
# All values are fixed pixel values relative to League window
CHROMA_PANEL_CONFIGS = {
    (1600, 900): {
        'preview_width': 380,
        'preview_height': 394,
        'circle_radius': 14,
        'window_width': 384,
        'window_height': 464,  # Increased from 438 to accommodate 68px button height
        'circle_spacing': 34,
        'button_size': 54,
        'button_width': 380,
        'button_height': 68,
        'screen_edge_margin': 32,
        'preview_x': 2,
        'preview_y': 2,
        'row_y_offset': 42,
        'panel_x': 608,  # X position from left edge of League window
        'panel_y': 227,  # Y position from top edge of League window
        # Swiftplay mode specific positions
        'swiftplay_panel_x': 872,  # X position for Swiftplay mode
        'swiftplay_panel_y': 271,  # Y position for Swiftplay mode
    },
    (1280, 720): {
        'preview_width': 304,      # 380 * (1280/1600) = 304
        'preview_height': 315,     # 394 * (720/900) = 315.2 ≈ 315
        'circle_radius': 11,       # 14 * (720/900) = 11.2 ≈ 11
        'window_width': 307,       # 384 * (1280/1600) = 307.2 ≈ 307
        'window_height': 371,      # 464 * (720/900) = 371.2 ≈ 371
        'circle_spacing': 27,      # 34 * (720/900) = 27.2 ≈ 27
        'button_size': 43,         # 54 * (720/900) = 43.2 ≈ 43
        'button_width': 304,       # 380 * (1280/1600) = 304
        'button_height': 54,       # 68 * (720/900) = 54.4 ≈ 54
        'screen_edge_margin': 26,  # 32 * (720/900) = 25.6 ≈ 26
        'preview_x': 2,            # 2 * (1280/1600) = 1.6 ≈ 2
        'preview_y': 2,            # 2 * (720/900) = 1.6 ≈ 2
        'row_y_offset': 34,        # 42 * (720/900) = 33.6 ≈ 34
        'panel_x': 487,            # 608 * (1280/1600) = 486.4 ≈ 486
        'panel_y': 180,            # 222 * (720/900) = 177.6 ≈ 178
        # Swiftplay mode specific positions
        'swiftplay_panel_x': 698,  # X position for Swiftplay mode
        'swiftplay_panel_y': 216,  # Y position for Swiftplay mode
    },
    (1024, 576): {
        'preview_width': 243,      # 380 * (1024/1600) = 243.2 ≈ 243
        'preview_height': 252,     # 394 * (576/900) = 252.16 ≈ 252
        'circle_radius': 9,        # 14 * (576/900) = 8.96 ≈ 9
        'window_width': 246,       # 384 * (1024/1600) = 245.76 ≈ 246
        'window_height': 296,      # 464 * (576/900) = 296.96 ≈ 297
        'circle_spacing': 22,      # 34 * (576/900) = 21.76 ≈ 22
        'button_size': 35,         # 54 * (576/900) = 34.56 ≈ 35
        'button_width': 243,       # 380 * (1024/1600) = 243.2 ≈ 243
        'button_height': 43,       # 68 * (576/900) = 43.52 ≈ 43
        'screen_edge_margin': 20,  # 32 * (576/900) = 20.48 ≈ 20
        'preview_x': 1,            # 2 * (1024/1600) = 1.28 ≈ 1
        'preview_y': 1,            # 2 * (576/900) = 1.28 ≈ 1
        'row_y_offset': 27,        # 42 * (576/900) = 26.88 ≈ 27
        'panel_x': 389,            # 608 * (1024/1600) = 389.12 ≈ 389
        'panel_y': 141,            # 222 * (576/900) = 142.08 ≈ 142
        # Swiftplay mode specific positions
        'swiftplay_panel_x': 558,  # X position for Swiftplay mode
        'swiftplay_panel_y': 170,  # Y position for Swiftplay mode
    }
}

# Chroma panel button visual effects (not scaled)
CHROMA_PANEL_GLOW_ALPHA = 60                     # Alpha value for gold glow effect on hover

# Legacy constants for backward compatibility (at reference resolution)
CHROMA_PANEL_PREVIEW_WIDTH = 380
CHROMA_PANEL_PREVIEW_HEIGHT = 394
CHROMA_PANEL_CIRCLE_RADIUS = 9
CHROMA_PANEL_WINDOW_WIDTH = 275
CHROMA_PANEL_WINDOW_HEIGHT = 346
CHROMA_PANEL_CIRCLE_SPACING = 21
CHROMA_PANEL_BUTTON_SIZE = 33
CHROMA_PANEL_SCREEN_EDGE_MARGIN = 20
CHROMA_PANEL_PREVIEW_X = 2
CHROMA_PANEL_PREVIEW_Y = 2
CHROMA_PANEL_ROW_Y_OFFSET = 26
CHROMA_PANEL_GOLD_BORDER_PX = 2
CHROMA_PANEL_DARK_BORDER_PX = 3
CHROMA_PANEL_GRADIENT_RING_PX = 4
CHROMA_PANEL_INNER_DISK_RADIUS_PX = 2.5

# =============================================================================
# CHROMA UI POSITIONING - FINALIZED POSITIONS
# =============================================================================
#
# 🎯 Reference Point: Opening Button Center (locked position)
#
# Positioning uses percentage ratios for resolution-independent placement:
#   - X ratios relative to window WIDTH  (0.0 = center, -0.5 = far left, 0.5 = far right)
#   - Y ratios relative to window HEIGHT (0.0 = center, -0.5 = top, 0.5 = bottom)
#
# Current Setup:
#   - Button: Horizontally centered, positioned ~30% down from League window center
#   - Panel: Horizontally aligned with button, positioned ~22% above button
#
# ⚠️ WARNING: These values are LOCKED. Changing them requires app restart.
#             Widgets are parented to League window as child windows.
#             Position updates only occur during resolution changes (auto-rebuild).
#
# =============================================================================

# Button position (center of League window, 30% down)
CHROMA_UI_ANCHOR_OFFSET_X_RATIO = 0.0           # Horizontally centered
CHROMA_UI_ANCHOR_OFFSET_Y_RATIO = 0.3035        # ~273px down from center at 900p (near bottom)

# Button offset from anchor (keep at 0,0 - button IS the anchor point)
CHROMA_UI_BUTTON_OFFSET_X_RATIO = 0.0           # No horizontal offset
CHROMA_UI_BUTTON_OFFSET_Y_RATIO = 0.0           # No vertical offset

# Panel offset from anchor (positions panel relative to button)
CHROMA_UI_PANEL_OFFSET_X_RATIO = 0.0            # Horizontally aligned with button center
CHROMA_UI_PANEL_OFFSET_Y_BASE_RATIO = -0.22     # ~198px above button at 900p

# Chroma UI fade timing (milliseconds)
CHROMA_FADE_IN_DURATION_MS = 500                # Duration of fade in animation (with gentle logarithmic ease-out curve)
CHROMA_FADE_OUT_DURATION_MS = 50                # Duration of fade out animation (linear, fast)
CHROMA_FADE_DELAY_BEFORE_SHOW_MS = 100          # Wait time between end of fade out and start of fade in

# Legacy constant for backward compatibility (uses fade-in duration)
CHROMA_FADE_DURATION_MS = CHROMA_FADE_IN_DURATION_MS

# Chroma button Lock configuration (fades based on ownership - shown when NOT owned)
CHROMA_BUTTON_LOCK_SIZE_RATIO = 1.7                # Lock size as ratio of button visual size
CHROMA_BUTTON_LOCK_OFFSET_X_RATIO = -0.014         # Lock X offset as ratio of button size (0.0 = centered)
CHROMA_BUTTON_LOCK_OFFSET_Y_RATIO = -0.83          # Lock Y offset as ratio of button size (0.0 = centered)

# Chroma button OutlineGold configuration (carousel border, behind Lock - shown when NOT owned)
CHROMA_BUTTON_OUTLINE_GOLD_SIZE_RATIO = 3.63        # OutlineGold size as ratio of button visual size (keeps aspect ratio)
CHROMA_BUTTON_OUTLINE_GOLD_OFFSET_X_RATIO = CHROMA_BUTTON_LOCK_OFFSET_X_RATIO  # OutlineGold X offset as ratio of button size
CHROMA_BUTTON_OUTLINE_GOLD_OFFSET_Y_RATIO = CHROMA_BUTTON_LOCK_OFFSET_Y_RATIO  # OutlineGold Y offset as ratio of button size

# Chroma button image size (button-chroma.png dimensions at 1600x900 resolution)
CHROMA_BUTTON_IMAGE_WIDTH_PIXELS = 22               # Fixed width in pixels at 1600x900 resolution
CHROMA_BUTTON_IMAGE_HEIGHT_PIXELS = 22              # Fixed height in pixels at 1600x900 resolution


# =============================================================================
# UNOWNED FRAME UI POSITIONING - INDEPENDENT FROM CHROMA BUTTON
# =============================================================================

# UnownedFrame position (ratios based on 1600x900 resolution)
UNOWNED_FRAME_ANCHOR_OFFSET_X_RATIO = 726/1600      # 726/1600 = 0.45375 (45.375% of window width)
UNOWNED_FRAME_ANCHOR_OFFSET_Y_RATIO = 642/900       # 642/900 = 0.713333 (71.33% of window height)

# UnownedFrame size (specific pixel dimensions as ratios)
UNOWNED_FRAME_WIDTH_RATIO = 148/1600                # 148/1600 = 0.0925 (9.25% of window width)
UNOWNED_FRAME_HEIGHT_RATIO = 84/900                 # 84/900 = 0.093333 (9.33% of window height)


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
LOCK_FILE_NAME = "leagueunlocked.lock"

# Log file pattern (handles both .log and .log.enc files)
LOG_FILE_PATTERN = "leagueunlocked_*.log*"
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
# DEFAULT ARGUMENTS
# =============================================================================

# Data Dragon language
DEFAULT_DD_LANG = "en_US"          # Data Dragon language

# Boolean flags
DEFAULT_VERBOSE = False
DEFAULT_WEBSOCKET_ENABLED = True
DEFAULT_MULTILANG_ENABLED = False  # DEPRECATED - Using LCU scraper instead
DEFAULT_DOWNLOAD_SKINS = True
DEFAULT_FORCE_UPDATE_SKINS = False
