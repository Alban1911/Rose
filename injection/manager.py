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
from .prebuilder import ChampionPreBuilder
from utils.logging import get_logger
from constants import INJECTION_THRESHOLD_SECONDS

log = get_logger()


class InjectionManager:
    """Manages skin injection with automatic triggering"""
    
    def __init__(self, tools_dir: Path = None, mods_dir: Path = None, zips_dir: Path = None, game_dir: Optional[Path] = None):
        self.tools_dir = tools_dir
        self.mods_dir = mods_dir
        self.zips_dir = zips_dir
        self.game_dir = game_dir
        self.injector = None  # Will be initialized lazily
        self.prebuilder = None  # Will be initialized lazily
        self.last_skin_name = None
        self.last_injection_time = 0.0
        self.injection_threshold = INJECTION_THRESHOLD_SECONDS
        self.injection_lock = threading.Lock()
        self._initialized = False
        self.current_champion = None
        self.prebuilt_overlays = {}  # Store pre-built overlay paths
    
    def _ensure_initialized(self):
        """Initialize the injector and prebuilder lazily when first needed"""
        if not self._initialized:
            with self.injection_lock:
                if not self._initialized:  # Double-check inside lock
                    log.info("[INJECT] Initializing injection system...")
                    self.injector = SkinInjector(self.tools_dir, self.mods_dir, self.zips_dir, self.game_dir)
                    self.prebuilder = ChampionPreBuilder(self.tools_dir, self.mods_dir, self.zips_dir, self.game_dir)
                    self._initialized = True
                    log.info("[INJECT] Injection system initialized successfully")
    
    def on_champion_locked(self, champion_name: str):
        """Called when a champion is locked - starts pre-building all skins"""
        if not champion_name:
            log.debug("[INJECT] on_champion_locked called with empty champion name")
            return
        
        log.info(f"[INJECT] on_champion_locked called for: {champion_name}")
        self._ensure_initialized()
        
        # Cancel any ongoing pre-build for different champion
        if self.current_champion != champion_name:
            if self.current_champion:
                log.info(f"[INJECT] Champion changed from {self.current_champion} to {champion_name}, cancelling previous pre-build")
                self.prebuilder.cancel_current_build()
            
            self.current_champion = champion_name
            
            # Start pre-building in background thread
            def prebuild_worker():
                try:
                    log.info(f"[INJECT] Starting pre-build for {champion_name}")
                    success = self.prebuilder.prebuild_champion_skins(champion_name)
                    if success:
                        log.info(f"[INJECT] Pre-build completed for {champion_name}")
                    else:
                        log.warning(f"[INJECT] Pre-build failed for {champion_name}")
                except Exception as e:
                    log.error(f"[INJECT] Pre-build error for {champion_name}: {e}")
            
            # Start pre-build in background thread
            prebuild_thread = threading.Thread(target=prebuild_worker, daemon=True)
            prebuild_thread.start()
            log.info(f"[INJECT] Pre-build thread started for {champion_name}")
        else:
            log.debug(f"[INJECT] Champion {champion_name} already being pre-built, skipping")
    
    def inject_prebuilt_skin(self, champion_name: str, skin_name: str) -> bool:
        """Inject a skin using pre-built overlay"""
        if not champion_name or not skin_name:
            return False
        
        self._ensure_initialized()
        
        with self.injection_lock:
            # Check if we have a pre-built overlay for this skin
            prebuilt_overlay_path = self.prebuilder.get_prebuilt_overlay_path(champion_name, skin_name)
            
            if prebuilt_overlay_path and prebuilt_overlay_path.exists():
                log.info(f"[INJECT] Using pre-built overlay for {skin_name}")
                
                # Use pre-built overlay directly
                success = self.injector._run_overlay_from_path(prebuilt_overlay_path)
                
                if success:
                    # Clean up unused overlays
                    self.prebuilder.cleanup_unused_overlays(champion_name, skin_name)
                    log.info(f"[INJECT] Successfully injected pre-built skin: {skin_name}")
                    return True
                else:
                    log.error(f"[INJECT] Failed to inject pre-built skin: {skin_name}")
                    return False
            else:
                # Fallback to traditional injection
                log.info(f"[INJECT] No pre-built overlay found for {skin_name}, using traditional injection")
                return self.injector.inject_skin(skin_name)
    
    def cleanup_prebuilt_overlays(self):
        """Clean up all pre-built overlays"""
        if self.prebuilder:
            self.prebuilder.cleanup_all_overlays()
    
    def is_prebuild_in_progress(self, champion_name: str) -> bool:
        """Check if pre-building is currently in progress for a champion"""
        if not self.prebuilder:
            return False
        return not self.prebuilder.is_prebuild_complete(champion_name)
        
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
                
                log.info(f"[INJECT] Starting injection for: {skin_name}")
                injection_start_time = time.time()
                success = self.injector.inject_skin(skin_name)
                
                # Note: The actual injection work duration is logged by the injector itself
                # This duration includes the full process including runoverlay runtime
                total_duration = time.time() - injection_start_time
                
                if success:
                    self.last_skin_name = skin_name
                    self.last_injection_time = current_time
                    log.info(f"[INJECT] Successfully injected: {skin_name} (total process: {total_duration:.2f}s)")
                else:
                    log.error(f"[INJECT] Failed to inject: {skin_name} (total process: {total_duration:.2f}s)")
    
    def inject_skin_immediately(self, skin_name: str, stop_callback=None) -> bool:
        """Immediately inject a specific skin"""
        self._ensure_initialized()
        
        with self.injection_lock:
            log.info(f"[INJECT] Immediate injection for: {skin_name}")
            injection_start_time = time.time()
            success = self.injector.inject_skin(skin_name, stop_callback=stop_callback)
            
            # Note: The actual injection work duration is logged by the injector itself
            # This duration includes the full process including runoverlay runtime
            total_duration = time.time() - injection_start_time
            
            if success:
                self.last_skin_name = skin_name
                self.last_injection_time = time.time()
                log.info(f"[INJECT] Immediate injection successful: {skin_name} (total process: {total_duration:.2f}s)")
            else:
                log.error(f"[INJECT] Immediate injection failed: {skin_name} (total process: {total_duration:.2f}s)")
            return success
    
    def inject_skin_for_testing(self, skin_name: str) -> bool:
        """Inject a skin for testing purposes - stops overlay immediately after mkoverlay"""
        if not skin_name:
            return False
            
        self._ensure_initialized()
        with self.injection_lock:
            log.info(f"[INJECT] Test injection for: {skin_name}")
            injection_start_time = time.time()
            
            # Use the injector's method that stops overlay after mkoverlay
            success = self.injector.inject_skin_for_testing(skin_name)
            
            total_duration = time.time() - injection_start_time
            
            if success:
                self.last_skin_name = skin_name
                self.last_injection_time = time.time()
                log.info(f"[INJECT] Test injection successful: {skin_name} (total process: {total_duration:.2f}s)")
            else:
                log.error(f"[INJECT] Test injection failed: {skin_name} (total process: {total_duration:.2f}s)")
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
            
        try:
            self.injector.kill_all_runoverlay_processes()
        except Exception as e:
            log.warning(f"Injection: Failed to kill runoverlay processes: {e}")