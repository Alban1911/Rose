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
from constants import INJECTION_THRESHOLD_SECONDS

log = get_logger()


class InjectionManager:
    """Manages skin injection with automatic triggering"""
    
    def __init__(self, tools_dir: Path = None, mods_dir: Path = None, zips_dir: Path = None, game_dir: Optional[Path] = None, name_db=None):
        self.tools_dir = tools_dir
        self.mods_dir = mods_dir
        self.zips_dir = zips_dir
        self.game_dir = game_dir
        self.name_db = name_db
        self.injector = None  # Will be initialized lazily
        self.last_skin_name = None
        self.last_injection_time = 0.0
        self.injection_threshold = INJECTION_THRESHOLD_SECONDS
        self.injection_lock = threading.Lock()
        self._initialized = False
        self.current_champion = None
        self._injection_in_progress = False  # Track if injection is running
        self._cleanup_in_progress = False  # Track if cleanup is running
        self._cleanup_lock = threading.Lock()  # Lock for cleanup operations
    
    def _ensure_initialized(self):
        """Initialize the injector lazily when first needed"""
        if not self._initialized:
            with self.injection_lock:
                if not self._initialized:  # Double-check inside lock
                    log.info("[INJECT] Initializing injection system...")
                    self.injector = SkinInjector(self.tools_dir, self.mods_dir, self.zips_dir, self.game_dir)
                    self._initialized = True
                    log.info("[INJECT] Injection system initialized successfully")
    
    def on_champion_locked(self, champion_name: str, champion_id: int = None, owned_skin_ids: set = None):
        """Called when a champion is locked"""
        if not champion_name:
            log.debug("[INJECT] on_champion_locked called with empty champion name")
            return
        
        log.info(f"[INJECT] on_champion_locked called for: {champion_name} (id={champion_id})")
        self._ensure_initialized()
        
        # Track current champion
        if self.current_champion != champion_name:
            self.current_champion = champion_name
            log.debug(f"[INJECT] Champion locked: {champion_name}")
    
    
    def update_skin(self, skin_name: str):
        """Update the current skin and potentially trigger injection"""
        if not skin_name:
            return
        
        self._ensure_initialized()
            
        with self.injection_lock:
            current_time = time.time()
            
            # If skin changed or enough time passed, trigger injection
            if (skin_name != self.last_skin_name or 
                current_time - self.last_injection_time >= self.injection_threshold):
                
                success = self.injector.inject_skin(skin_name)
                
                if success:
                    self.last_skin_name = skin_name
                    self.last_injection_time = current_time
    
    def inject_skin_immediately(self, skin_name: str, stop_callback=None) -> bool:
        """Immediately inject a specific skin"""
        self._ensure_initialized()
        
        # Check if injection already in progress
        if self._injection_in_progress:
            log.warning(f"[INJECT] Injection already in progress - skipping request for: {skin_name}")
            return False
        
        # Try to acquire lock with timeout to prevent indefinite blocking
        lock_acquired = self.injection_lock.acquire(timeout=2.0)
        if not lock_acquired:
            log.warning(f"[INJECT] Could not acquire injection lock - another injection in progress")
            return False
        
        try:
            self._injection_in_progress = True
            log.debug(f"[INJECT] Injection started - lock acquired for: {skin_name}")
            
            success = self.injector.inject_skin(skin_name, stop_callback=stop_callback)
            
            if success:
                self.last_skin_name = skin_name
                self.last_injection_time = time.time()
            
            return success
        finally:
            self._injection_in_progress = False
            self.injection_lock.release()
            log.debug(f"[INJECT] Injection completed - lock released")
    
    def inject_skin_for_testing(self, skin_name: str) -> bool:
        """Inject a skin for testing purposes - stops overlay immediately after mkoverlay"""
        if not skin_name:
            return False
            
        self._ensure_initialized()
        with self.injection_lock:
            success = self.injector.inject_skin_for_testing(skin_name)
            
            if success:
                self.last_skin_name = skin_name
                self.last_injection_time = time.time()
            
            return success
    
    def clean_system(self) -> bool:
        """Clean the injection system"""
        if not self._initialized:
            return True  # Nothing to clean if not initialized
        
        with self.injection_lock:
            return self.injector.clean_system()
    
    def initialize_when_ready(self):
        """Initialize the injection system when the app is ready (skins downloaded)"""
        if not self._initialized:
            log.info("[INJECT] App ready - initializing injection system in background...")
            # Initialize in a separate thread to avoid blocking
            import threading
            def init_thread():
                try:
                    self._ensure_initialized()
                    log.info("[INJECT] Background initialization completed - injection system ready")
                except Exception as e:
                    log.error(f"[INJECT] Background initialization failed: {e}")
            
            threading.Thread(target=init_thread, daemon=True).start()
    
    def get_last_injected_skin(self) -> Optional[str]:
        """Get the last successfully injected skin"""
        return self.last_skin_name
    
    def stop_overlay_process(self):
        """Stop the current overlay process"""
        if not self._initialized:
            return  # Nothing to stop if not initialized
            
        try:
            self.injector.stop_overlay_process()
        except Exception as e:
            log.warning(f"Injection: Failed to stop overlay process: {e}")
    
    def kill_all_runoverlay_processes(self):
        """Kill all runoverlay processes (for ChampSelect cleanup)"""
        if not self._initialized:
            return  # Nothing to kill if not initialized
        
        # Prevent duplicate cleanup calls from running simultaneously
        if self._cleanup_in_progress:
            log.debug("[INJECT] Cleanup already in progress - skipping duplicate call")
            return
        
        # Try to acquire cleanup lock without blocking
        if not self._cleanup_lock.acquire(blocking=False):
            log.debug("[INJECT] Could not acquire cleanup lock - another cleanup in progress")
            return
        
        # Set flag and release lock immediately so we don't block the caller
        self._cleanup_in_progress = True
        self._cleanup_lock.release()
        
        # Run cleanup in a separate thread to avoid blocking phase transitions
        def cleanup_thread():
            try:
                log.debug("[INJECT] Starting cleanup thread for runoverlay processes")
                self.injector.kill_all_runoverlay_processes()
                log.debug("[INJECT] Cleanup thread completed")
            except Exception as e:
                log.warning(f"Injection: Cleanup thread failed: {e}")
            finally:
                # Clear flag when done
                with self._cleanup_lock:
                    self._cleanup_in_progress = False
        
        cleanup = threading.Thread(target=cleanup_thread, daemon=True, name="CleanupThread")
        cleanup.start()