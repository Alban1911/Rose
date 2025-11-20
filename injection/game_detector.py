#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Game Detector
Handles detection of League of Legends game directory
"""

from pathlib import Path
from typing import Optional

# Import psutil with fallback for development environments
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

from utils.logging import get_logger, log_success
from .config_manager import ConfigManager

log = get_logger()


class GameDetector:
    """Detects League of Legends game directory"""
    
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
    
    def detect_game_dir(self) -> Optional[Path]:
        """Auto-detect League of Legends Game directory using config and LeagueClient.exe detection.
        Returns None if game directory cannot be found - never saves invalid paths to config."""
        
        # First, try to load from config
        config_path = self.config_manager.load_league_path()
        if config_path:
            config_game_dir = Path(config_path)
            if config_game_dir.exists() and (config_game_dir / "League of Legends.exe").exists():
                log_success(log, f"Using League path from config: {config_game_dir}", "📂")
                return config_game_dir
            else:
                log.warning(f"Config League path is invalid: {config_path}")
        
        # If no valid config, try to detect via LeagueClient.exe
        log.debug("Config not found or invalid, detecting via LeagueClient.exe")
        detected_path = self._detect_via_leagueclient()
        if detected_path:
            # Save the detected path to config only if we actually found a valid path
            self.config_manager.save_league_path(str(detected_path))
            return detected_path
        
        # No fallbacks - if we can't detect it, return None
        log.warning("Could not detect League of Legends game directory. Please ensure League Client is running or manually set the path in config.ini")
        return None
    
    def _detect_via_leagueclient(self) -> Optional[Path]:
        """Detect League path by finding running LeagueClient.exe process"""
        if not PSUTIL_AVAILABLE:
            log.debug("psutil not available, skipping LeagueClient.exe detection")
            return None
            
        try:
            log.debug("Looking for LeagueClient.exe process...")
            
            # Find LeagueClient.exe process
            for proc in psutil.process_iter(['pid', 'name', 'exe']):
                try:
                    if proc.info['name'] == 'LeagueClient.exe':
                        exe_path = proc.info['exe']
                        if exe_path:
                            log.debug(f"Found LeagueClient.exe at: {exe_path}")
                            
                            # Convert to Path and get parent directory
                            client_path = Path(exe_path)
                            client_dir = client_path.parent
                            
                            # League should be in the same directory + "Game" subdirectory
                            league_dir = client_dir / "Game"
                            league_exe = league_dir / "League of Legends.exe"
                            
                            log.debug(f"Checking for League at: {league_exe}")
                            if league_exe.exists():
                                log_success(log, f"Found League via LeagueClient.exe: {league_dir}", "📂")
                                return league_dir
                            else:
                                log.debug(f"League not found at expected location: {league_exe}")
                                
                                # Try parent directory structure (for different installers)
                                parent_dir = client_dir.parent
                                parent_league_dir = parent_dir / "League of Legends" / "Game"
                                parent_league_exe = parent_league_dir / "League of Legends.exe"
                                
                                log.debug(f"Trying parent directory structure: {parent_league_exe}")
                                if parent_league_exe.exists():
                                    log_success(log, f"Found League via parent directory: {parent_league_dir}", "📂")
                                    return parent_league_dir
                                
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            
            log.debug("No LeagueClient.exe process found")
            return None
            
        except Exception as e:
            log.warning(f"Error detecting via LeagueClient.exe: {e}")
            return None

