#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Injection Manager
Manages the injection process and coordinates with UI detection system
"""

import threading
import time
import sys
from pathlib import Path
from typing import Optional

from config import (
    INJECTION_LOCK_TIMEOUT_S,
    get_config_file_path
)
from utils.core.logging import get_logger, log_action, log_success
from utils.core.issue_reporter import report_issue

from .injector import SkinInjector
from ..game.game_monitor import GameMonitor
from ..config.threshold_manager import ThresholdManager

log = get_logger()


class InjectionManager:
    """Manages skin injection with automatic triggering"""
    
    def __init__(self, tools_dir: Path = None, mods_dir: Path = None, zips_dir: Path = None, game_dir: Optional[Path] = None, shared_state=None):
        self.tools_dir = tools_dir
        self.mods_dir = mods_dir
        self.zips_dir = zips_dir
        self.game_dir = game_dir
        self.shared_state = shared_state  # Reference to shared state for accessing UISkinThread
        self.injector = None  # Will be initialized lazily
        self.last_skin_name = None
        self.last_injection_time = 0.0
        self.injection_lock = threading.Lock()
        self._initialized = False
        self.current_champion = None
        self._injection_in_progress = False  # Track if injection is running
        self._cleanup_in_progress = False  # Track if cleanup is running
        self._cleanup_lock = threading.Lock()  # Lock for cleanup operations
        
        # Initialize managers
        self.threshold_manager = ThresholdManager(shared_state)
        self.injection_threshold = self.threshold_manager.injection_threshold
        
        # Initialize game monitor with callback for auto-resume timeout
        self.game_monitor = GameMonitor(self._get_monitor_auto_resume_timeout)
    
    def _get_monitor_auto_resume_timeout(self) -> float:
        """Get monitor auto-resume timeout from config."""
        try:
            from config import get_config_float
            timeout = get_config_float("General", "monitor_auto_resume_timeout", 60.0)
            return max(1.0, min(180.0, float(timeout)))  # Clamp between 1 and 180
        except Exception as exc:  # noqa: BLE001
            log.debug(f"[INJECT] Failed to get monitor auto-resume timeout: {exc}")
            return 60.0  # Default fallback
    
    def _refresh_injection_threshold(self) -> None:
        """Reload injection threshold from config so tray changes apply immediately."""
        self.injection_threshold = self.threshold_manager.refresh()
    
    def refresh_injection_threshold(self) -> float:
        """Public helper to reload injection threshold from config."""
        self._refresh_injection_threshold()
        return self.injection_threshold
    
    def _ensure_initialized(self):
        """Initialize the injector lazily when first needed"""
        if not self._initialized:
            with self.injection_lock:
                if not self._initialized:  # Double-check inside lock
                    log_action(log, "Initializing injection system...", "💉")
                    self.injector = SkinInjector(None, self.mods_dir, self.zips_dir, self.game_dir)
                    # Only mark as initialized if we have a valid game directory
                    if self.injector.game_dir is not None:
                        self._initialized = True
                        log_success(log, "Injection system initialized successfully", "✅")
                    else:
                        log.error("[INJECT] Cannot initialize injection system - League game directory not found")
                        log.error("[INJECT] Please ensure League Client is running or manually set the path in config.ini")
                        report_issue(
                            "LEAGUE_DIR_NOT_FOUND",
                            "error",
                            "Injection unavailable: League path not found.",
                            hint="Start League Client, or set the game path in Settings.",
                        )
                        self._initialized = False
    
    def _start_monitor(self):
        """Start game monitor - watches for game and suspends it"""
        self.game_monitor.start()
    
    def _stop_monitor(self):
        """Stop the game monitor"""
        self.game_monitor.stop()
    
    def _get_suspended_game_process(self):
        """Get the currently suspended game process (if any)"""
        return self.game_monitor.get_suspended_game_process()
    
    def resume_game(self):
        """Resume the suspended game (called when runoverlay starts)"""
        self.game_monitor.resume_game()
    
    def resume_if_suspended(self):
        """Resume game if monitor suspended it (for when injection is skipped)"""
        self.game_monitor.resume_if_suspended()
    
    @property
    def _monitor_active(self) -> bool:
        """Check if monitor is active"""
        return self.game_monitor.is_active
    
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
            log.debug("[INJECT] No skin name available - skipping injection (mods-only flow disabled)")
            return
        
        self._ensure_initialized()
        self.refresh_injection_threshold()
        
        # Don't attempt injection if system isn't properly initialized
        if not self._initialized or self.injector is None or self.injector.game_dir is None:
            return
            
        with self.injection_lock:
            current_time = time.time()

            elapsed = current_time - self.last_injection_time
            if self.last_injection_time and elapsed < self.injection_threshold:
                remaining = self.injection_threshold - elapsed
                log.debug(f"[INJECT] Skipping injection for '{skin_name}' (cooldown {remaining:.2f}s remaining)")
                report_issue(
                    "INJECTION_SKIPPED_COOLDOWN",
                    "info",
                    "Injection skipped (cooldown still active).",
                    details={
                        "remaining_s": f"{remaining:.2f}",
                        "threshold_s": f"{self.injection_threshold:.2f}",
                        "skin": skin_name,
                    },
                    hint="Wait a bit, or lower the Injection Cooldown/Threshold in Settings.",
                )
                return

            # Disconnect from UIA window when injection threshold triggers
            # (launcher closes when game starts, so the window is gone)
            if self.shared_state and self.shared_state.ui_skin_thread:
                try:
                    self.shared_state.ui_skin_thread.force_disconnect()
                except Exception as e:
                    log.debug(f"[INJECT] Failed to disconnect UIA: {e}")
            
            # Start monitor now (only when injection actually happens)
            if not self._monitor_active:
                log.info("[INJECT] Starting game monitor for injection")
                self._start_monitor()

            success = self.injector.inject_skin(
                skin_name,
                stop_callback=None,
                injection_manager=self
            )

            if success:
                self.last_skin_name = skin_name
                self.last_injection_time = current_time
            
            # Stop monitor after injection completes
            self._stop_monitor()
    
    def _check_and_inject_mods_only(self):
        """Mods-only injection is disabled because the installed mods directory was removed."""
        log.info("[INJECT] Mods-only injection skipped (installed mods folder removed)")
    
    def on_loadout_countdown(self, seconds_remaining: int):
        """Called during loadout countdown - no longer used (monitor starts with injection)"""
        # Monitor now starts when injection actually begins, not at T-1
        # This prevents unnecessary suspension for base skins and owned skins
        pass
    
    def inject_skin_immediately(self, skin_name: str, stop_callback=None, chroma_id: int = None, champion_name: str = None, champion_id: int = None) -> bool:
        """Immediately inject a specific skin (with optional chroma)
        
        Args:
            skin_name: Name of skin to inject
            stop_callback: Callback to check if injection should stop
            chroma_id: Optional chroma ID for chroma variant
        """
        # Check if this is a base skin (skin_0 or skin name ending with base/default indicators)
        # If skin_name starts with "skin_" and the ID is 0 or matches base skin pattern, inject mods only
        if skin_name and skin_name.startswith("skin_"):
            try:
                skin_id_str = skin_name.split("_")[1] if "_" in skin_name else None
                if skin_id_str:
                    skin_id = int(skin_id_str)
                    # Check if this is a base skin (skin ID 0 or champion's base skin ID like 36000 for champ 36)
                    # Base skins typically have ID = champion_id * 1000
                    if skin_id == 0:
                        log.info("[INJECT] Base skin detected (skinId=0) - injection skipped")
                        report_issue(
                            "INJECTION_SKIPPED_BASE_SKIN",
                            "info",
                            "Injection skipped (base skin selected).",
                            details={"skin": skin_name, "skin_id": 0},
                        )
                        return False
                    # Check if it matches base skin pattern (champion_id * 1000)
                    if champion_id and skin_id == champion_id * 1000:
                        log.info(f"[INJECT] Base skin detected (skinId={skin_id} for champion {champion_id}) - injection skipped")
                        report_issue(
                            "INJECTION_SKIPPED_BASE_SKIN",
                            "info",
                            "Injection skipped (base skin selected).",
                            details={"skin": skin_name, "skin_id": skin_id, "champion_id": champion_id},
                        )
                        return False
            except (ValueError, IndexError):
                pass  # Not a numeric skin ID, continue with normal injection
        
        self._ensure_initialized()
        self.refresh_injection_threshold()
        
        # Don't attempt injection if system isn't properly initialized
        if not self._initialized or self.injector is None or self.injector.game_dir is None:
            log.error("[INJECT] Cannot inject - League game directory not found")
            log.error("[INJECT] Please ensure League Client is running or manually set the path in config.ini")
            return False
        
        # Check if injection already in progress
        if self._injection_in_progress:
            log.warning(f"[INJECT] Injection already in progress - skipping request for: {skin_name}")
            return False
        
        # Try to acquire lock with timeout to prevent indefinite blocking
        lock_acquired = self.injection_lock.acquire(timeout=INJECTION_LOCK_TIMEOUT_S)
        if not lock_acquired:
            log.warning(f"[INJECT] Could not acquire injection lock - another injection in progress")
            report_issue(
                "INJECTION_LOCK_TIMEOUT",
                "warning",
                "Injection skipped (another injection was still running).",
                details={"lock_timeout_s": f"{INJECTION_LOCK_TIMEOUT_S:.1f}", "skin": skin_name},
                hint="Try again in a few seconds.",
            )
            return False
        
        try:
            self._injection_in_progress = True
            log.debug(f"[INJECT] Injection started - lock acquired for: {skin_name}")

            current_time = time.time()
            elapsed = current_time - self.last_injection_time
            if self.last_injection_time and elapsed < self.injection_threshold:
                remaining = self.injection_threshold - elapsed
                log.debug(f"[INJECT] Skipping immediate injection for '{skin_name}' (cooldown {remaining:.2f}s remaining)")
                report_issue(
                    "INJECTION_SKIPPED_COOLDOWN",
                    "info",
                    "Injection skipped (cooldown still active).",
                    details={
                        "remaining_s": f"{remaining:.2f}",
                        "threshold_s": f"{self.injection_threshold:.2f}",
                        "skin": skin_name,
                    },
                    hint="Wait a bit, or lower the Injection Cooldown/Threshold in Settings.",
                )
                return False

            # Disconnect from UIA window when injection happens
            # (launcher closes when game starts, so the window is gone)
            if self.shared_state and self.shared_state.ui_skin_thread:
                try:
                    self.shared_state.ui_skin_thread.force_disconnect()
                except Exception as e:
                    log.debug(f"[INJECT] Failed to disconnect UIA: {e}")
            
            # Start monitor now (only when injection actually happens)
            # Monitor runs in background and will suspend game if/when it finds it
            # Injection proceeds immediately - suspension is optional and helps prevent file locks
            if not self._monitor_active:
                log.info("[INJECT] Starting game monitor for injection")
                self._start_monitor()
            
            # Pass the manager instance so injector can call resume_game()
            success = self.injector.inject_skin(
                skin_name, 
                stop_callback=stop_callback,
                injection_manager=self,
                chroma_id=chroma_id,
                champion_name=champion_name,
                champion_id=champion_id
            )
            
            if success:
                self.last_skin_name = skin_name
                self.last_injection_time = current_time
            
            return success
        finally:
            self._injection_in_progress = False
            self.injection_lock.release()
            log.debug(f"[INJECT] Injection completed - lock released")
            
            # Stop monitor after injection completes (this will resume game if still suspended)
            # Note: Monitor may have already stopped if game ended, but that's fine
            self._stop_monitor()
    
    def inject_skin_for_testing(self, skin_name: str) -> bool:
        """Inject a skin for testing purposes - stops overlay immediately after mkoverlay"""
        if not skin_name:
            return False
            
        self._ensure_initialized()
        self.refresh_injection_threshold()
        
        # Don't attempt injection if system isn't properly initialized
        if not self._initialized or self.injector is None or self.injector.game_dir is None:
            log.error("[INJECT] Cannot inject - League game directory not found")
            return False
            
        with self.injection_lock:
            current_time = time.time()
            elapsed = current_time - self.last_injection_time
            if self.last_injection_time and elapsed < self.injection_threshold:
                remaining = self.injection_threshold - elapsed
                log.debug(f"[INJECT] Skipping testing injection for '{skin_name}' (cooldown {remaining:.2f}s remaining)")
                return False

            success = self.injector.inject_skin(skin_name)

            if success:
                self.last_skin_name = skin_name
                self.last_injection_time = current_time
                log.info(f"[INJECT] Test injection successful for: {skin_name}")
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
            def init_thread():
                try:
                    self._ensure_initialized()
                    log.info("[INJECT] Background initialization completed - injection system ready")
                except Exception as e:
                    log.error(f"[INJECT] Background initialization failed: {e}")
            
            threading.Thread(target=init_thread, daemon=True).start()
    
    @property
    def last_injected_skin(self) -> Optional[str]:
        """Get the last successfully injected skin"""
        return self.last_skin_name
    
    def stop_overlay_process(self):
        """Stop the current overlay process"""
        if not self._initialized:
            return  # Nothing to stop if not initialized
            
        try:
            self.injector.stop_overlay_process()
        except Exception as e:
            log.warning(f"[INJECT] Failed to stop overlay process: {e}")
    
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
                log.warning(f"[INJECT] Cleanup thread failed: {e}")
            finally:
                # Clear flag when done
                with self._cleanup_lock:
                    self._cleanup_in_progress = False
        
        cleanup = threading.Thread(target=cleanup_thread, daemon=True, name="CleanupThread")
        cleanup.start()
    
    def kill_all_modtools_processes(self):
        """Kill all mod-tools.exe processes (for application shutdown)"""
        if not self._initialized:
            return  # Nothing to kill if not initialized
        
        try:
            self.injector.kill_all_modtools_processes()
        except Exception as e:
            log.warning(f"[INJECT] Failed to kill mod-tools.exe processes: {e}")
    
    def _get_injection_dir(self) -> Path:
        """Get the injection directory path (works in both frozen and development environments)"""
        if getattr(sys, 'frozen', False):
            # Running as compiled executable (PyInstaller)
            # Handle both onefile (_MEIPASS) and onedir (_internal) modes
            if hasattr(sys, '_MEIPASS'):
                # One-file mode: tools are in _MEIPASS (temporary extraction directory)
                base_path = Path(sys._MEIPASS)
                injection_dir = base_path / "injection"
            else:
                # One-dir mode: tools are alongside executable
                base_dir = Path(sys.executable).parent
                possible_injection_dirs = [
                    base_dir / "injection",  # Direct path
                    base_dir / "_internal" / "injection",  # _internal folder
                ]
                
                injection_dir = None
                for dir_path in possible_injection_dirs:
                    if dir_path.exists():
                        injection_dir = dir_path
                        break
                
                if not injection_dir:
                    injection_dir = possible_injection_dirs[0]
        else:
            # Running as Python script
            injection_dir = Path(__file__).parent.parent
        
        return injection_dir
