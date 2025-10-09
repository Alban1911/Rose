#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Global constants for SkinCloner
All arbitrary values are centralized here for easy tracking and modification
"""

# =============================================================================
# OCR TIMING CONSTANTS
# =============================================================================

# OCR frequency settings (Hz)
OCR_BURST_HZ_DEFAULT = 40.0  # OCR frequency during motion/hover
OCR_IDLE_HZ_DEFAULT = 0.0    # OCR frequency when idle (0 = disabled)

# OCR timing intervals (seconds)
OCR_MIN_INTERVAL = 0.15      # Minimum time between OCR operations
OCR_ROI_LOCK_DURATION = 1.5  # Duration to lock ROI after detection
OCR_CHAMPION_LOCK_DELAY_S = 0.025  # Delay after champion lock before OCR starts (25ms)

# OCR motion detection (milliseconds)
OCR_BURST_MS_DEFAULT = 150   # Duration to continue burst OCR after motion
OCR_SECOND_SHOT_MS_DEFAULT = 100  # Delay for second OCR attempt for accuracy

# OCR thresholds
OCR_DIFF_THRESHOLD_DEFAULT = 0.001  # Image change threshold to trigger OCR
OCR_MIN_CONFIDENCE_DEFAULT = 0.5    # Minimum confidence score for matches
OCR_FUZZY_MATCH_THRESHOLD = 0.7     # Threshold for fuzzy text matching

# OCR window detection
OCR_WINDOW_LOG_INTERVAL = 1.0  # Seconds between window detection logs

# OCR debugging
DEFAULT_DEBUG_OCR = False  # Save OCR images to debug folder (disabled by default)

# OCR image processing
OCR_SMALL_IMAGE_WIDTH = 96   # Width for small image used in change detection
OCR_SMALL_IMAGE_HEIGHT = 20  # Height for small image used in change detection
OCR_IMAGE_DIFF_NORMALIZATION = 255.0  # Normalization value for image difference calculation


# =============================================================================
# ROI (REGION OF INTEREST) PROPORTIONS
# =============================================================================

# Fixed proportions for League of Legends skin name display area
# Based on exact measurements at 1280x720: 455px from top, 450px from left/right, 230px from bottom
ROI_PROPORTIONS = {
    'x1_ratio': 0.352,  # 450/1280 - left edge
    'y1_ratio': 0.632,  # 455/720  - top edge
    'x2_ratio': 0.648,  # 830/1280 - right edge
    'y2_ratio': 0.681   # 490/720  - bottom edge
}


# =============================================================================
# IMAGE PROCESSING CONSTANTS
# =============================================================================

# HSV color ranges for white text detection (used in hardcoded ROI processing)
WHITE_TEXT_HSV_LOWER = [0, 0, 200]     # Lower HSV bound for white text
WHITE_TEXT_HSV_UPPER = [179, 70, 255]  # Upper HSV bound for white text

# Upscaling threshold for small ROI images
IMAGE_UPSCALE_THRESHOLD = 120  # Upscale if ROI height < this value


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
MAIN_LOOP_SLEEP = 0.2       # Main loop iteration sleep time
OCR_NO_WINDOW_SLEEP = 0.05  # Sleep when no window is found
OCR_NO_CONDITION_SLEEP = 0.15  # Sleep when OCR conditions not met
OCR_MOTION_SLEEP_DIVISOR = 10.0  # Divisor for burst mode sleep calculation
OCR_IDLE_SLEEP_MIN = 5.0    # Minimum frequency for idle mode calculation
OCR_IDLE_SLEEP_DEFAULT = 0.1  # Default sleep when idle mode is off


# =============================================================================
# WEBSOCKET CONSTANTS
# =============================================================================

WS_PING_INTERVAL_DEFAULT = 20  # Seconds between WebSocket pings
WS_PING_TIMEOUT_DEFAULT = 10   # Seconds before WebSocket ping times out
WS_RECONNECT_DELAY = 1.0       # Seconds to wait before WebSocket reconnect

# Lock detection timing
WS_PROBE_ITERATIONS = 8        # Number of LCU timer probe attempts
WS_PROBE_SLEEP_MS = 60         # Milliseconds between probe attempts (0.06s)
WS_PROBE_WINDOW_MS = 480       # Total probe window (8 * 60ms ~= 480ms)


# =============================================================================
# LOADOUT TIMER CONSTANTS
# =============================================================================

TIMER_HZ_DEFAULT = 1000              # Countdown display frequency (Hz)
TIMER_HZ_MIN = 10                    # Minimum timer frequency
TIMER_HZ_MAX = 2000                  # Maximum timer frequency
TIMER_POLL_PERIOD_S = 0.2            # Seconds between LCU resync checks
FALLBACK_LOADOUT_MS_DEFAULT = 0      # Deprecated: fallback countdown duration

# Skin injection timing
SKIN_THRESHOLD_MS_DEFAULT = 500      # Time before loadout ends to write skin (ms)
INJECTION_THRESHOLD_SECONDS = 2.0    # Seconds between injection attempts
BASE_SKIN_VERIFICATION_WAIT_S = 0.15 # Seconds to wait for LCU to process base skin change
PERSISTENT_MONITOR_START_SECONDS = 1 # Seconds remaining when persistent game monitor starts
PERSISTENT_MONITOR_CHECK_INTERVAL_S = 0.05  # Seconds between game process checks
PERSISTENT_MONITOR_IDLE_INTERVAL_S = 0.1    # Seconds to wait when game already suspended
PERSISTENT_MONITOR_WAIT_TIMEOUT_S = 3.0     # Max seconds to wait for persistent monitor to suspend game
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

LOG_MAX_FILES_DEFAULT = 10               # Maximum number of log files to keep
LOG_MAX_TOTAL_SIZE_MB_DEFAULT = 10       # Maximum total log size in MB
LOG_CHUNK_SIZE = 8192                    # Chunk size for file downloads
LOG_SEPARATOR_WIDTH = 80                 # Width of separator lines in logs (e.g., "=" * 80)


# =============================================================================
# PROCESS & THREAD TIMEOUT CONSTANTS
# =============================================================================

# Process termination timeouts (seconds)
PROCESS_TERMINATE_TIMEOUT_S = 5         # Timeout for process.wait() after terminate/kill
MKOVERLAY_PROCESS_TIMEOUT_S = 60        # Timeout for mkoverlay process execution
THREAD_JOIN_TIMEOUT_S = 1.0             # Timeout for thread.join() on shutdown

# Process priority settings
# Note: Lower priority for injection processes can help prevent slowing down game launch
# But the CPU contention also provides a buffer window for late injections to complete

# API request timeouts (seconds)
LCU_API_TIMEOUT_S = 2.0                 # Timeout for LCU API requests
DATA_DRAGON_API_TIMEOUT_S = 8           # Timeout for Data Dragon API requests
GITHUB_API_TIMEOUT_S = 30               # Already defined as RATE_LIMIT_REQUEST_TIMEOUT

# Polling timeouts (seconds)
FUTURE_RESULT_TIMEOUT_S = 0             # Timeout for future.result() (immediate)


# =============================================================================
# SLEEP & DELAY CONSTANTS
# =============================================================================

# General sleep intervals (seconds)
TRAY_INIT_SLEEP_S = 0.2                 # Sleep after tray icon initialization
PROCESS_MONITOR_SLEEP_S = 0.5           # Sleep during process monitoring loop
WINDOW_CHECK_SLEEP_S = 1                # Sleep between window existence checks
API_POLITENESS_DELAY_S = 0.5            # Delay between API calls to be polite

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
TRAY_ICON_CHECK_SCALE_DIVISOR = 28.0    # Divisor for check mark scale factor


# =============================================================================
# CHROMA WHEEL UI CONSTANTS
# =============================================================================

# Chroma wheel window dimensions
CHROMA_WHEEL_PREVIEW_WIDTH = 400        # Width of skin preview area
CHROMA_WHEEL_PREVIEW_HEIGHT = 450       # Height of skin preview area
CHROMA_WHEEL_CIRCLE_RADIUS = 20         # Radius of chroma selection circles
CHROMA_WHEEL_WINDOW_WIDTH = 460         # Total window width
CHROMA_WHEEL_WINDOW_HEIGHT = 600        # Total window height
CHROMA_WHEEL_CIRCLE_SPACING = 45        # Spacing between chroma circles
CHROMA_WHEEL_BUTTON_SIZE = 60           # Size of reopen button

# Chroma wheel positioning
CHROMA_WHEEL_SCREEN_EDGE_MARGIN = 20    # Distance from screen edge
CHROMA_WHEEL_PREVIEW_X = 30             # X position of preview area
CHROMA_WHEEL_PREVIEW_Y = 30             # Y position of preview area
CHROMA_WHEEL_ROW_Y_OFFSET = 60          # Offset from bottom for chroma row

# Chroma wheel visual effects
CHROMA_WHEEL_BORDER_SCALE = 0.9         # Scale factor for border (90%)
CHROMA_WHEEL_GRADIENT_SCALE = 0.8       # Scale factor for gradient ring (80%)
CHROMA_WHEEL_GLOW_ALPHA = 60            # Alpha value for gold glow effect
CHROMA_WHEEL_CONICAL_START_ANGLE = 30   # Start angle for conical gradient
CHROMA_WHEEL_INNER_DARK_BORDER_WIDTH = 2  # Dark border width between gold and gradient


# =============================================================================
# WINDOWS API CONSTANTS
# =============================================================================

# Process access rights
WINDOWS_PROCESS_QUERY = 0x1000          # PROCESS_QUERY_LIMITED_INFORMATION

# Window display commands
WINDOWS_SW_HIDE = 0                      # Hide window command

# MessageBox flags
WINDOWS_MB_ICONERROR = 0x10              # Error icon for message box


# =============================================================================
# FILE AND DIRECTORY PATHS
# =============================================================================

# Lock file name
LOCK_FILE_NAME = "skincloner.lock"

# Log file pattern
LOG_FILE_PATTERN = "skincloner_*.log"
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
    "GameStart",
    "InProgress",
    "EndOfGame"
}


# =============================================================================
# LANGUAGE MAPPING
# =============================================================================

# Map LCU languages to Tesseract OCR languages
OCR_LANG_MAP = {
    "en_US": "eng",
    "es_ES": "spa", 
    "es_MX": "spa",
    "fr_FR": "fra",
    "de_DE": "deu",
    "it_IT": "ita",
    "pt_BR": "por",
    "ru_RU": "rus",
    "pl_PL": "pol",
    "tr_TR": "tur",
    "el_GR": "ell",
    "hu_HU": "hun",
    "ro_RO": "ron",
    "zh_CN": "chi_sim",
    "zh_TW": "chi_tra",
    "ar_AE": "ara",
    "ar_SA": "ara",
    "ar_EG": "ara",
    "ja_JP": "jpn",
    "ko_KR": "kor",
}


# =============================================================================
# DEFAULT ARGUMENTS
# =============================================================================

# OCR defaults
DEFAULT_TESSERACT_PSM = 7              # Page segmentation mode
DEFAULT_OCR_LANG = "auto"              # Auto-detect language
DEFAULT_DD_LANG = "en_US"              # Data Dragon language

# Capture defaults
DEFAULT_CAPTURE_MODE = "window"        # Window capture vs screen capture
DEFAULT_MONITOR = "all"                # Monitor to capture
DEFAULT_WINDOW_HINT = "League"         # Window title hint

# Boolean flags
DEFAULT_VERBOSE = False
DEFAULT_WEBSOCKET_ENABLED = True
DEFAULT_MULTILANG_ENABLED = False  # DEPRECATED - Using LCU scraper instead
DEFAULT_DOWNLOAD_SKINS = True
DEFAULT_FORCE_UPDATE_SKINS = False


