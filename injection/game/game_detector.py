#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Game Detector
Handles detection of League of Legends game directory
"""

from pathlib import Path
from typing import Optional, Tuple

# Import psutil with fallback for development environments
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

from utils.core.logging import get_logger, log_success
from ..config.config_manager import ConfigManager

log = get_logger()


class GameDetector:
    """Detects League of Legends game and client directories"""
    
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
    
    def detect_paths(self) -> Tuple[Optional[Path], Optional[Path]]:
        """Auto-detect League of Legends game and client directories.
        Returns (game_path, client_path) tuple. Both can be None if not found."""
        
        # First, try to load from config
        config_league_path = self.config_manager.load_league_path()
        config_client_path = self.config_manager.load_client_path()
        
        if config_league_path and config_client_path:
            league_dir = Path(config_league_path)
            client_dir = Path(config_client_path)
            
            if (league_dir.exists() and (league_dir / "League of Legends.exe").exists() and
                client_dir.exists() and (client_dir / "LeagueClient.exe").exists()):
                log_success(log, f"Using paths from config: league={league_dir}, client={client_dir}", "")
                return league_dir, client_dir
            else:
                log.warning(f"Config paths are invalid: league={config_league_path}, client={config_client_path}")
        
        # If no valid config, try to detect via LeagueClient.exe
        log.debug("Config not found or invalid, detecting via LeagueClient.exe")
        detected_league_path, detected_client_path = self._detect_via_leagueclient()
        
        if detected_league_path and detected_client_path:
            # Save the detected paths to config
            self.config_manager.save_paths(str(detected_league_path), str(detected_client_path))
            return detected_league_path, detected_client_path
        
        # No fallbacks - if we can't detect it, return None
        log.warning("Could not detect League of Legends paths. Please ensure League Client is running or manually set the paths in config.ini")
        return None, None
    
    def detect_game_dir(self) -> Optional[Path]:
        """Auto-detect League of Legends Game directory (backward compatibility).
        Returns None if game directory cannot be found."""
        league_path, _ = self.detect_paths()
        return league_path
    
    def _detect_via_leagueclient(self) -> Tuple[Optional[Path], Optional[Path]]:
        """Detect League paths by finding running LeagueClient.exe process.
        Returns (game_path, client_path) tuple."""
        if not PSUTIL_AVAILABLE:
            log.debug("psutil not available, skipping LeagueClient.exe detection")
            return None, None
            
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
                            
                            # Verify client directory has LeagueClient.exe
                            if not (client_dir / "LeagueClient.exe").exists():
                                continue
                            
                            # League should be in the same directory + "Game" subdirectory
                            league_dir = client_dir / "Game"
                            league_exe = league_dir / "League of Legends.exe"
                            
                            log.debug(f"Checking for League at: {league_exe}")
                            if league_exe.exists():
                                log_success(log, f"Found League via LeagueClient.exe: game={league_dir}, client={client_dir}", "")
                                return league_dir, client_dir
                            else:
                                log.debug(f"League not found at expected location: {league_exe}")
                                
                                # Try parent directory structure (for different installers)
                                parent_dir = client_dir.parent
                                parent_league_dir = parent_dir / "League of Legends" / "Game"
                                parent_league_exe = parent_league_dir / "League of Legends.exe"
                                
                                log.debug(f"Trying parent directory structure: {parent_league_exe}")
                                if parent_league_exe.exists():
                                    log_success(log, f"Found League via parent directory: game={parent_league_dir}, client={client_dir}", "")
                                    return parent_league_dir, client_dir
                                
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            
            log.debug("No LeagueClient.exe process found")
            return None, None
            
        except Exception as e:
            log.warning(f"Error detecting via LeagueClient.exe: {e}")
            return None, None

