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
from utils.core.logging import get_logger

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
        """Load league path (League of Legends.exe directory) from config.ini file"""
        config_path = self._get_config_path()
        if not config_path.exists():
            log.debug("Config file not found, will create one")
            return None
        
        try:
            config = configparser.ConfigParser()
            config.read(config_path)
            if 'General' in config and 'leaguePath' in config['General']:
                league_path = config['General']['leaguePath']
                log.debug(f"Loaded league path from config: {league_path}")
                return league_path
        except Exception as e:
            log.warning(f"Failed to read config file: {e}")
        
        return None
    
    def load_client_path(self) -> Optional[str]:
        """Load client path (LeagueClient.exe directory) from config.ini file"""
        config_path = self._get_config_path()
        if not config_path.exists():
            return None
        
        try:
            config = configparser.ConfigParser()
            config.read(config_path)
            if 'General' in config and 'clientPath' in config['General']:
                client_path = config['General']['clientPath']
                log.debug(f"Loaded client path from config: {client_path}")
                return client_path
        except Exception as e:
            log.warning(f"Failed to read config file: {e}")
        
        return None
    
    def save_league_path(self, league_path: str):
        """Save league path to config.ini file"""
        config_path = self._get_config_path()
        try:
            config = configparser.ConfigParser()
            
            # Load existing config if it exists
            if config_path.exists():
                config.read(config_path)
            
            # Ensure General section exists
            if 'General' not in config:
                config.add_section('General')
            
            # Set the league path
            config.set('General', 'leaguePath', league_path)
            
            # Write to file
            with open(config_path, 'w') as f:
                config.write(f)
            
            log.debug(f"Saved league path to config: {league_path}")
        except Exception as e:
            log.warning(f"Failed to save config file: {e}")
    
    def save_client_path(self, client_path: str):
        """Save client path to config.ini file"""
        config_path = self._get_config_path()
        try:
            config = configparser.ConfigParser()
            
            # Load existing config if it exists
            if config_path.exists():
                config.read(config_path)
            
            # Ensure General section exists
            if 'General' not in config:
                config.add_section('General')
            
            # Set the client path
            config.set('General', 'clientPath', client_path)
            
            # Write to file
            with open(config_path, 'w') as f:
                config.write(f)
            
            log.debug(f"Saved client path to config: {client_path}")
        except Exception as e:
            log.warning(f"Failed to save config file: {e}")
    
    def save_paths(self, league_path: str, client_path: str):
        """Save both league and client paths to config.ini file"""
        config_path = self._get_config_path()
        try:
            config = configparser.ConfigParser()
            
            # Load existing config if it exists
            if config_path.exists():
                config.read(config_path)
            
            # Ensure General section exists
            if 'General' not in config:
                config.add_section('General')
            
            # Set both paths
            config.set('General', 'leaguePath', league_path)
            config.set('General', 'clientPath', client_path)
            
            # Write to file
            with open(config_path, 'w') as f:
                config.write(f)
            
            log.debug(f"Saved paths to config: league={league_path}, client={client_path}")
        except Exception as e:
            log.warning(f"Failed to save config file: {e}")
    
    @staticmethod
    def infer_client_path_from_league_path(league_path: str) -> Optional[str]:
        """Infer client path from league path.
        League path is typically in a 'Game' subdirectory, so client path is the parent.
        Returns None if inference is not possible."""
        if not league_path or not league_path.strip():
            return None
        
        try:
            league_dir = Path(league_path.strip())
            # If league path ends with "Game", client is the parent
            if league_dir.name == "Game":
                client_dir = league_dir.parent
                client_exe = client_dir / "LeagueClient.exe"
                if client_exe.exists():
                    return str(client_dir)
            
            # Try parent directory structure
            parent_dir = league_dir.parent
            client_exe = parent_dir / "LeagueClient.exe"
            if client_exe.exists():
                return str(parent_dir)
            
            return None
        except Exception:
            return None

