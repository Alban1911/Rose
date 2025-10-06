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
OCR_BURST_HZ_DEFAULT = 50.0  # OCR frequency during motion/hover
OCR_IDLE_HZ_DEFAULT = 0.0    # OCR frequency when idle (0 = disabled)

# OCR timing intervals (seconds)
OCR_MIN_INTERVAL = 0.11      # Minimum time between OCR operations
OCR_ROI_LOCK_DURATION = 1.5  # Duration to lock ROI after detection

# OCR motion detection (milliseconds)
OCR_BURST_MS_DEFAULT = 280   # Duration to continue burst OCR after motion
OCR_SECOND_SHOT_MS_DEFAULT = 120  # Delay for second OCR attempt for accuracy

# OCR thresholds
OCR_DIFF_THRESHOLD_DEFAULT = 0.001  # Image change threshold to trigger OCR
OCR_MIN_CONFIDENCE_DEFAULT = 0.5    # Minimum confidence score for matches
OCR_FUZZY_MATCH_THRESHOLD = 0.7     # Threshold for fuzzy text matching

# OCR window detection
OCR_WINDOW_LOG_INTERVAL = 1.0  # Seconds between window detection logs


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

# Band detection for text location
BAND_CENTER_PCT = (62.0, 6.5)    # Center position and height percentage
BAND_SPAN_PCT = (52.0, 70.0)     # Vertical scan range percentage
BAND_CANDIDATES_STEPS = 9        # Number of scan positions to try
BAND_MIN_HEIGHT = 24             # Minimum band height in pixels

# Text detection regions (percentages of width)
TEXT_DETECTION_LEFT_PCT = 28.0   # Left boundary for text search
TEXT_DETECTION_RIGHT_PCT = 72.0  # Right boundary for text search

# HSV color ranges for white text detection
WHITE_TEXT_HSV_LOWER = [0, 0, 200]     # Lower HSV bound for white text
WHITE_TEXT_HSV_UPPER = [179, 70, 255]  # Upper HSV bound for white text

# Edge detection (Canny algorithm)
CANNY_THRESHOLD_LOW = 40
CANNY_THRESHOLD_HIGH = 120

# Scoring weights for text detection
SCORE_WEIGHT_MASK = 0.6      # Weight for HSV mask in text scoring
SCORE_WEIGHT_EDGES = 0.4     # Weight for edge detection in text scoring

# Upscaling threshold
IMAGE_UPSCALE_THRESHOLD = 120  # Upscale if band height < this value


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
SKIN_THRESHOLD_MS_DEFAULT = 3000     # Time before loadout ends to write skin (ms)
INJECTION_THRESHOLD_SECONDS = 2.0    # Seconds between injection attempts


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

LOG_MAX_FILES_DEFAULT = 20               # Maximum number of log files to keep
LOG_MAX_TOTAL_SIZE_MB_DEFAULT = 100      # Maximum total log size in MB
LOG_CHUNK_SIZE = 8192                    # Chunk size for file downloads


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

# Default state file name
DEFAULT_SKIN_FILE_NAME = "last_hovered_skin.txt"

# Hover buffer file
HOVER_BUFFER_FILE = "hover_buffer.txt"

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
DEFAULT_MULTILANG_ENABLED = True
DEFAULT_DOWNLOAD_SKINS = True
DEFAULT_FORCE_UPDATE_SKINS = False

