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
from constants import (
    INJECTION_THRESHOLD_SECONDS, 
    PERSISTENT_MONITOR_START_SECONDS,
    PERSISTENT_MONITOR_CHECK_INTERVAL_S,
    PERSISTENT_MONITOR_IDLE_INTERVAL_S,
    PERSISTENT_MONITOR_WAIT_TIMEOUT_S,
    PERSISTENT_MONITOR_WAIT_INTERVAL_S,
    PERSISTENT_MONITOR_AUTO_RESUME_S
)

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
        
        # Game monitor for suspension/resume
        self._monitor_active = False
        self._monitor_thread = None
        self._suspended_game_process = None
    
    def _ensure_initialized(self):
        """Initialize the injector lazily when first needed"""
        if not self._initialized:
            with self.injection_lock:
                if not self._initialized:  # Double-check inside lock
                    log.info("[INJECT] Initializing injection system...")
                    self.injector = SkinInjector(self.tools_dir, self.mods_dir, self.zips_dir, self.game_dir)
                    self._initialized = True
                    log.info("[INJECT] Injection system initialized successfully")
    
    def _start_monitor(self):
        """Start game monitor - watches for game and suspends it"""
        # Stop any existing monitor first
        self._stop_monitor()
        
        self._monitor_active = True
        self._suspended_game_process = None
        
        def game_monitor():
            """Monitor for game process and suspend immediately when found"""
            try:
                import psutil
                import time
                
                log.info("[monitor] Started - watching for game process...")
                suspension_start_time = None
                
                while self._monitor_active:
                    # If we've already suspended the game, check for safety timeout
                    if self._suspended_game_process is not None:
                        # Check safety timeout to auto-resume
                        if suspension_start_time is not None:
                            elapsed = time.time() - suspension_start_time
                            if elapsed >= PERSISTENT_MONITOR_AUTO_RESUME_S:
                                log.warning(f"[monitor] AUTO-RESUME after {PERSISTENT_MONITOR_AUTO_RESUME_S:.0f}s (safety timeout)")
                                log.warning(f"[monitor] Injection took too long - releasing game to prevent freeze")
                                try:
                                    self._suspended_game_process.resume()
                                    self._suspended_game_process = None
                                    suspension_start_time = None
                                except Exception as e:
                                    log.error(f"[monitor] Auto-resume error: {e}")
                            break
                        
                        time.sleep(PERSISTENT_MONITOR_IDLE_INTERVAL_S)
                        continue
                    
                    # Look for game process
                    for proc in psutil.process_iter(['name', 'pid']):
                        if not self._monitor_active:
                            break
                            
                        if proc.info['name'] == 'League of Legends.exe':
                            try:
                                game_proc = psutil.Process(proc.info['pid'])
                                log.info(f"[monitor] Found game (PID={proc.info['pid']})")
                                
                                # Try to suspend immediately
                                try:
                                    game_proc.suspend()
                                    self._suspended_game_process = game_proc
                                    suspension_start_time = time.time()  # Start safety timer
                                    log.info(f"[monitor] Game suspended (PID={proc.info['pid']})")
                                    log.info(f"[monitor] Will auto-resume after {PERSISTENT_MONITOR_AUTO_RESUME_S:.0f}s if not manually resumed")
                                    break
                                except psutil.AccessDenied:
                                    log.error("[monitor] ACCESS DENIED - Cannot suspend game")
                                    log.error("[monitor] Try running SkinCloner as Administrator")
                                    self._monitor_active = False
                                    break
                                except Exception as e:
                                    log.error(f"[monitor] Failed to suspend: {e}")
                                    break
                                    
                            except psutil.NoSuchProcess:
                                continue
                            except Exception as e:
                                log.error(f"[monitor] Error: {e}")
                                break
                    
                    time.sleep(PERSISTENT_MONITOR_CHECK_INTERVAL_S)
                
                log.debug("[monitor] Stopped")
                
            except Exception as e:
                log.error(f"[monitor] Fatal error: {e}")
        
        self._monitor_thread = threading.Thread(target=game_monitor, daemon=True, name="GameMonitor")
        self._monitor_thread.start()
        log.debug("[monitor] Background thread started")
    
    def _stop_monitor(self):
        """Stop the game monitor"""
        if self._monitor_active:
            log.debug("[monitor] Stopping...")
            self._monitor_active = False
            
            # Resume game if still suspended
            if self._suspended_game_process is not None:
                try:
                    import psutil
                    if self._suspended_game_process.status() == psutil.STATUS_STOPPED:
                        self._suspended_game_process.resume()
                        log.info("[monitor] Resumed suspended game on cleanup")
                except:
                    pass
                
            self._suspended_game_process = None
    
    def _get_suspended_game_process(self):
        """Get the currently suspended game process (if any)"""
        return self._suspended_game_process
    
    def resume_game(self):
        """Resume the suspended game (called when runoverlay starts)"""
        if self._suspended_game_process is not None:
            try:
                import psutil
                from constants import GAME_RESUME_MAX_ATTEMPTS, GAME_RESUME_VERIFICATION_WAIT_S
                import time
                
                game_proc = self._suspended_game_process
                
                # Resume until no longer suspended (handles multiple suspensions)
                for attempt in range(1, GAME_RESUME_MAX_ATTEMPTS + 1):
                    try:
                        status_before = game_proc.status()
                        if status_before != psutil.STATUS_STOPPED:
                            log.debug(f"[monitor] Game already running (status={status_before})")
                            break
                        
                        game_proc.resume()
                        time.sleep(GAME_RESUME_VERIFICATION_WAIT_S)
                        
                        status_after = game_proc.status()
                        if status_after != psutil.STATUS_STOPPED:
                            if attempt == 1:
                                log.info(f"[monitor] Game resumed (PID={game_proc.pid}, status={status_after})")
                            else:
                                log.info(f"[monitor] Game resumed after {attempt} attempts (PID={game_proc.pid})")
                            log.info(f"[monitor] Game loading while overlay hooks in...")
                            break
                        else:
                            if attempt < GAME_RESUME_MAX_ATTEMPTS:
                                log.debug(f"[monitor] Still suspended after attempt {attempt}, retrying...")
                            else:
                                log.error(f"[monitor] Failed to resume after {GAME_RESUME_MAX_ATTEMPTS} attempts")
                    except psutil.NoSuchProcess:
                        log.debug("[monitor] Game process ended")
                        break
                    except Exception as e:
                        log.warning(f"[monitor] Resume attempt {attempt} error: {e}")
                        if attempt >= GAME_RESUME_MAX_ATTEMPTS:
                            break
                
                # Clear the suspended process reference and stop monitoring
                self._suspended_game_process = None
                self._monitor_active = False
                log.debug("[monitor] Game resumed - stopping monitor")
                
            except Exception as e:
                log.error(f"[monitor] Error resuming game: {e}")
    
    def resume_if_suspended(self):
        """Resume game if monitor suspended it (for when injection is skipped)"""
        if self._suspended_game_process is not None:
            log.info("[INJECT] Injection skipped - resuming suspended game")
            self.resume_game()
            self._stop_monitor()
    
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
    
    def on_loadout_countdown(self, seconds_remaining: int):
        """Called during loadout countdown - no longer used (monitor starts with injection)"""
        # Monitor now starts when injection actually begins, not at T-1
        # This prevents unnecessary suspension for base skins and owned skins
        pass
    
    def inject_skin_immediately(self, skin_name: str, stop_callback=None, chroma_id: int = None) -> bool:
        """Immediately inject a specific skin (with optional chroma)
        
        Args:
            skin_name: Name of skin to inject
            stop_callback: Callback to check if injection should stop
            chroma_id: Optional chroma ID for chroma variant
        """
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
            
            # Start monitor now (only when injection actually happens)
            if not self._monitor_active:
                log.info("[INJECT] Starting game monitor for injection")
                self._start_monitor()
            
            # Wait briefly for monitor to find and suspend game
            if self._monitor_active and self._suspended_game_process is None:
                import time
                log.debug("[INJECT] Waiting for monitor to suspend game...")
                wait_start = time.time()
                while time.time() - wait_start < PERSISTENT_MONITOR_WAIT_TIMEOUT_S and self._suspended_game_process is None:
                    time.sleep(PERSISTENT_MONITOR_WAIT_INTERVAL_S)
                
                if self._suspended_game_process is not None:
                    log.debug(f"[INJECT] Game suspended by monitor after {time.time() - wait_start:.2f}s")
                else:
                    log.debug(f"[INJECT] Monitor didn't suspend game in {PERSISTENT_MONITOR_WAIT_TIMEOUT_S}s - will wait during injection")
            
            # Pass the manager instance so injector can call resume_game()
            success = self.injector.inject_skin(
                skin_name, 
                stop_callback=stop_callback,
                injection_manager=self,
                chroma_id=chroma_id
            )
            
            if success:
                self.last_skin_name = skin_name
                self.last_injection_time = time.time()
            
            return success
        finally:
            self._injection_in_progress = False
            self.injection_lock.release()
            log.debug(f"[INJECT] Injection completed - lock released")
            
            # Stop monitor after injection completes
            self._stop_monitor()
    
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
            log.warning(f"[inject] Failed to stop overlay process: {e}")
    
    def kill_all_runoverlay_processes(self):
        """Kill all runoverlay processes (for ChampSelect cleanup)"""
        if not self._initialized:
            return  # Nothing to kill if not initialized
        
        # Stop game monitor when exiting champ select
        self._stop_monitor()
        
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
                log.warning(f"[inject] Cleanup thread failed: {e}")
            finally:
                # Clear flag when done
                with self._cleanup_lock:
                    self._cleanup_in_progress = False
        
        cleanup = threading.Thread(target=cleanup_thread, daemon=True, name="CleanupThread")
        cleanup.start()