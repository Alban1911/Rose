#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration Manager
Handles loading and saving League path configuration
"""

import configparser
from pathlib import Path
from typing import Optional

from config import get_config_file_path
from utils.logging import get_logger

log = get_logger()


class ConfigManager:
    """Manages League path configuration"""
    
    def __init__(self):
        self._config_path = None
    
    def _get_config_path(self) -> Path:
        """Get the path to the config.ini file"""
        if self._config_path is None:
            self._config_path = get_config_file_path()
        return self._config_path
    
    def load_league_path(self) -> Optional[str]:
        """Load League path from config.ini file"""
        config_path = self._get_config_path()
        if not config_path.exists():
            log.debug("Config file not found, will create one")
            return None
        
        try:
            config = configparser.ConfigParser()
            config.read(config_path)
            if 'General' in config and 'leaguePath' in config['General']:
                league_path = config['General']['leaguePath']
                log.debug(f"Loaded League path from config: {league_path}")
                return league_path
        except Exception as e:
            log.warning(f"Failed to read config file: {e}")
        
        return None
    
    def save_league_path(self, league_path: str):
        """Save League path to config.ini file"""
        config_path = self._get_config_path()
        try:
            config = configparser.ConfigParser()
            
            # Load existing config if it exists
            if config_path.exists():
                config.read(config_path)
            
            # Ensure General section exists
            if 'General' not in config:
                config.add_section('General')
            
            # Set the League path
            config.set('General', 'leaguePath', league_path)
            
            # Write to file
            with open(config_path, 'w') as f:
                config.write(f)
            
            log.debug(f"Saved League path to config: {league_path}")
        except Exception as e:
            log.warning(f"Failed to save config file: {e}")

