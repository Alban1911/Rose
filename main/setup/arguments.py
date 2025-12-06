#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Command line argument parsing
"""

import argparse

from config import (
    DEFAULT_VERBOSE,
    PHASE_HZ_DEFAULT,
    WS_PING_INTERVAL_DEFAULT,
    TIMER_HZ_DEFAULT,
    FALLBACK_LOADOUT_MS_DEFAULT,
    SKIN_THRESHOLD_MS_DEFAULT,
    DEFAULT_DOWNLOAD_SKINS,
    DEFAULT_FORCE_UPDATE_SKINS,
)


def setup_arguments() -> argparse.Namespace:
    """Parse and return command line arguments"""
    ap = argparse.ArgumentParser(
        description="Rose - Windows UI API skin detection"
    )
    
    # General arguments
    ap.add_argument("--verbose", action="store_true", default=DEFAULT_VERBOSE,
                   help="Enable verbose logging (developer mode - shows all technical details)")
    ap.add_argument("--debug", action="store_true", default=False,
                   help="Enable ultra-detailed debug logging (includes function traces and variable dumps)")
    ap.add_argument("--dev", action="store_true", default=False,
                   help="Skip the Windows launcher so Rose runs directly for development")
    ap.add_argument("--lockfile", type=str, default=None)
    
    
    # Threading arguments
    ap.add_argument("--phase-hz", type=float, default=PHASE_HZ_DEFAULT)
    ap.add_argument("--ws-ping", type=int, default=WS_PING_INTERVAL_DEFAULT)
    
    # Timer arguments
    ap.add_argument("--timer-hz", type=int, default=TIMER_HZ_DEFAULT, 
                   help="Loadout countdown display frequency (Hz)")
    ap.add_argument("--fallback-loadout-ms", type=int, default=FALLBACK_LOADOUT_MS_DEFAULT, 
                   help="(deprecated) Old fallback ms if LCU doesn't provide timer — ignored")
    ap.add_argument("--skin-threshold-ms", type=int, default=SKIN_THRESHOLD_MS_DEFAULT, 
                   help="Write last skin at T<=threshold (ms)")
    ap.add_argument("--inject-batch", type=str, default="", 
                   help="Batch to execute right after skin write (leave empty to disable)")
    
    
    # Skin download arguments
    ap.add_argument("--download-skins", action="store_true", default=DEFAULT_DOWNLOAD_SKINS, 
                   help="Automatically download skins at startup")
    ap.add_argument("--no-download-skins", action="store_false", dest="download_skins", 
                   help="Disable automatic skin downloading")
    ap.add_argument("--force-update-skins", action="store_true", default=DEFAULT_FORCE_UPDATE_SKINS, 
                   help="Force update all skins (re-download existing ones)")
    ap.add_argument("--max-champions", type=int, default=None, 
                   help="Limit number of champions to download skins for (for testing)")
    
    # Log management arguments (none - retention managed by age in utils.logging)
    
    return ap.parse_args()

