#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Injection Manager
Manages the injection process and coordinates with OCR system
"""

import time
import threading
from pathlib import Path
from typing import Optional

from .injector import SkinInjector
from utils.logging import get_logger

log = get_logger()


class InjectionManager:
    """Manages skin injection with automatic triggering"""
    
    def __init__(self, tools_dir: Path = None, mods_dir: Path = None, zips_dir: Path = None, game_dir: Optional[Path] = None):
        self.injector = SkinInjector(tools_dir, mods_dir, zips_dir, game_dir)
        self.last_skin_name = None
        self.last_injection_time = 0.0
        self.injection_threshold = 4.0  # 4 seconds
        self.injection_lock = threading.Lock()
        
    def update_skin(self, skin_name: str):
        """Update the current skin and potentially trigger injection"""
        if not skin_name:
            return
            
        with self.injection_lock:
            current_time = time.time()
            
            # If skin changed or enough time passed, trigger injection
            if (skin_name != self.last_skin_name or 
                current_time - self.last_injection_time >= self.injection_threshold):
                
                log.info(f"[INJECT] Starting injection for: {skin_name}")
                success = self.injector.inject_skin(skin_name)
                
                if success:
                    self.last_skin_name = skin_name
                    self.last_injection_time = current_time
                    log.info(f"[INJECT] Successfully injected: {skin_name}")
                else:
                    log.error(f"[INJECT] Failed to inject: {skin_name}")
    
    def inject_skin_immediately(self, skin_name: str, stop_callback=None) -> bool:
        """Immediately inject a specific skin"""
        with self.injection_lock:
            log.info(f"[INJECT] Immediate injection for: {skin_name}")
            success = self.injector.inject_skin(skin_name, stop_callback=stop_callback)
            if success:
                self.last_skin_name = skin_name
                self.last_injection_time = time.time()
            return success
    
    def clean_system(self) -> bool:
        """Clean the injection system"""
        with self.injection_lock:
            return self.injector.clean_system()
    
    def get_last_injected_skin(self) -> Optional[str]:
        """Get the last successfully injected skin"""
        return self.last_skin_name
    
    def stop_overlay_process(self):
        """Stop the current overlay process"""
        try:
            self.injector.stop_overlay_process()
        except Exception as e:
            log.warning(f"Injection: Failed to stop overlay process: {e}")