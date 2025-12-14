#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Game Monitor
Handles game process monitoring, suspension, and resumption
"""

import threading
import time
from typing import Optional

# Import psutil with fallback for development environments
try:
    import psutil
    PSUTIL_AVAILABLE = True
    # Define constants for safe access
    STATUS_STOPPED = psutil.STATUS_STOPPED
    NoSuchProcess = psutil.NoSuchProcess
    AccessDenied = psutil.AccessDenied
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None
    # Define fallback constants when psutil is not available
    STATUS_STOPPED = 'stopped'  # String fallback for comparison
    NoSuchProcess = Exception  # Fallback exception type
    AccessDenied = PermissionError  # Fallback exception type

from config import (
    PERSISTENT_MONITOR_CHECK_INTERVAL_S,
    PERSISTENT_MONITOR_IDLE_INTERVAL_S,
    GAME_RESUME_MAX_ATTEMPTS,
    GAME_RESUME_VERIFICATION_WAIT_S,
    get_config_float
)
from utils.core.logging import get_logger, log_section, log_event, log_success
from utils.core.issue_reporter import report_issue

log = get_logger()


class GameMonitor:
    """Monitors and controls game process suspension/resume"""
    
    def __init__(self, get_auto_resume_timeout_callback):
        """Initialize game monitor
        
        Args:
            get_auto_resume_timeout_callback: Callback function to get auto-resume timeout from config
        """
        self._monitor_active = False
        self._monitor_thread = None
        self._suspended_game_process = None
        self._runoverlay_started = False
        self._get_auto_resume_timeout = get_auto_resume_timeout_callback
    
    def start(self):
        """Start game monitor - watches for game and suspends it"""
        # Stop any existing monitor first
        self.stop()
        
        self._monitor_active = True
        self._suspended_game_process = None
        self._runoverlay_started = False  # Reset flag when starting new monitor
        
        def game_monitor():
            """Monitor for game process and suspend immediately when found"""
            try:
                if not PSUTIL_AVAILABLE:
                    log.error("[monitor] psutil not available - cannot monitor game process")
                    self._monitor_active = False
                    return
                
                log_section(log, "Game Process Monitor Started", "👁️")
                suspension_start_time = None
                
                # Immediately check for existing game process when monitor starts
                # This prevents the game from starting before we can suspend it
                # Do multiple rapid checks to catch the game as soon as it starts
                log.debug("[monitor] Starting immediate game process checks...")
                for immediate_check in range(10):  # Check 10 times immediately (very fast)
                    if not self._monitor_active:
                        break
                    try:
                        for proc in psutil.process_iter(['name', 'pid']):
                            if not self._monitor_active:
                                break
                            if proc.info['name'] == 'League of Legends.exe':
                                try:
                                    game_proc = psutil.Process(proc.info['pid'])
                                    # Check if already suspended
                                    if game_proc.status() == STATUS_STOPPED:
                                        # Already suspended, just track it
                                        if self._suspended_game_process is None:
                                            self._suspended_game_process = game_proc
                                            suspension_start_time = time.time()
                                            log_event(log, "Game already suspended - tracking", "⏸️", {"PID": proc.info['pid']})
                                        break
                                    
                                    log_event(log, "Game process found - suspending immediately", "🎮", {"PID": proc.info['pid']})
                                    
                                    try:
                                        game_proc.suspend()
                                        self._suspended_game_process = game_proc
                                        suspension_start_time = time.time()
                                        auto_resume_timeout = self._get_auto_resume_timeout()
                                        log_event(log, "Game suspended immediately", "⏸️", {
                                            "PID": proc.info['pid'],
                                            "Auto-resume": f"{auto_resume_timeout:.0f}s"
                                        })
                                        break
                                    except AccessDenied:
                                        log.error("[monitor] ACCESS DENIED - Cannot suspend game")
                                        log.error("[monitor] Try running Rose as Administrator")
                                        self._monitor_active = False
                                        break
                                    except Exception as e:
                                        log.error(f"[monitor] Failed to suspend existing game: {e}")
                                except (NoSuchProcess, AccessDenied):
                                    continue
                                except Exception as e:
                                    log.debug(f"[monitor] Error checking existing process: {e}")
                    except Exception as e:
                        log.debug(f"[monitor] Error in immediate check {immediate_check}: {e}")
                    
                    # If we found and suspended the game, break out of immediate checks
                    if self._suspended_game_process is not None:
                        break
                    
                    # Very short sleep between immediate checks (5ms)
                    if immediate_check < 9:  # Don't sleep after last check
                        time.sleep(0.005)
                
                while self._monitor_active:
                    # Don't suspend if runoverlay has already started - exit monitor entirely
                    if self._runoverlay_started:
                        log.debug("[monitor] runoverlay started - stopping monitor")
                        self._monitor_active = False
                        break
                    
                    # If we've already suspended the game, check for safety timeout
                    if self._suspended_game_process is not None:
                        # Check safety timeout to auto-resume (prevent permanent freeze)
                        if suspension_start_time is not None:
                            elapsed = time.time() - suspension_start_time
                            auto_resume_timeout = self._get_auto_resume_timeout()
                            if elapsed >= auto_resume_timeout:
                                log.warning(f"[monitor] AUTO-RESUME after {auto_resume_timeout:.0f}s (safety timeout)")
                                log.warning(f"[monitor] Injection took too long - releasing game to prevent freeze")
                                report_issue(
                                    "AUTO_RESUME_TRIGGERED",
                                    "warning",
                                    f"Injection stopped waiting after {auto_resume_timeout:.0f}s (auto-resume safety).",
                                    details={
                                        "auto_resume_timeout_s": f"{auto_resume_timeout:.0f}",
                                        "elapsed_s": f"{elapsed:.1f}",
                                    },
                                    hint="Settings → Monitor Auto-Resume Timeout → increase it (ex: 60s).",
                                )
                                try:
                                    self._suspended_game_process.resume()
                                    log.info("[monitor] Auto-resumed game successfully")
                                except Exception as e:
                                    log.error(f"[monitor] Auto-resume error: {e}")
                                    # Try to resume one more time, but don't block on it
                                    try:
                                        # Check if process still exists
                                        if PSUTIL_AVAILABLE and self._suspended_game_process.status() == STATUS_STOPPED:
                                            self._suspended_game_process.resume()
                                            log.info("[monitor] Auto-resume retry succeeded")
                                    except Exception as retry_e:
                                        log.error(f"[monitor] Auto-resume retry failed: {retry_e}")
                                # Always clear reference and stop monitor after auto-resume attempt
                                # Even if resume failed, we can't keep trying forever
                                self._suspended_game_process = None
                                suspension_start_time = None
                                log.info("[monitor] Stopping monitor after auto-resume - runoverlay should have hooked")
                                self._monitor_active = False
                                break
                        
                        # Keep monitoring while game is suspended (wait for runoverlay to finish)
                        time.sleep(PERSISTENT_MONITOR_IDLE_INTERVAL_S)
                        continue
                    
                    # Look for game process (in case it starts after monitor begins)
                    found_processes = []
                    for proc in psutil.process_iter(['name', 'pid']):
                        if not self._monitor_active:
                            break
                        
                        # Log all processes for debugging (first few iterations only)
                        if len(found_processes) < 5:
                            found_processes.append(proc.info.get('name', 'unknown'))
                        
                        if proc.info['name'] == 'League of Legends.exe':
                            try:
                                game_proc = psutil.Process(proc.info['pid'])
                                log_event(log, "Game process found", "🎮", {"PID": proc.info['pid']})
                                
                                # Try to suspend immediately
                                try:
                                    game_proc.suspend()
                                    self._suspended_game_process = game_proc
                                    suspension_start_time = time.time()  # Start safety timer
                                    auto_resume_timeout = self._get_auto_resume_timeout()
                                    log_event(log, "Game suspended", "⏸️", {
                                        "PID": proc.info['pid'],
                                        "Auto-resume": f"{auto_resume_timeout:.0f}s"
                                    })
                                    break
                                except AccessDenied:
                                    log.error("[monitor] ACCESS DENIED - Cannot suspend game")
                                    log.error("[monitor] Try running Rose as Administrator")
                                    self._monitor_active = False
                                    # Clear reference if we couldn't suspend (game is running anyway)
                                    self._suspended_game_process = None
                                    break
                                except Exception as e:
                                    log.error(f"[monitor] Failed to suspend: {e}")
                                    # Clear reference on error (game might not be suspended)
                                    self._suspended_game_process = None
                                    break
                                
                            except NoSuchProcess:
                                continue
                            except Exception as e:
                                log.error(f"[monitor] Error: {e}")
                                # Clear reference on error to prevent leaving game suspended
                                self._suspended_game_process = None
                                break
                    
                    # Sleep after checking all processes (not after each process)
                    time.sleep(PERSISTENT_MONITOR_CHECK_INTERVAL_S)
                
                log.debug("[monitor] Stopped")
                
            except Exception as e:
                log.error(f"[monitor] Fatal error: {e}")
        
        self._monitor_thread = threading.Thread(target=game_monitor, daemon=True, name="GameMonitor")
        self._monitor_thread.start()
        log.debug("[monitor] Background thread started")
    
    def stop(self):
        """Stop the game monitor"""
        if self._monitor_active:
            log.debug("[monitor] Stopping...")
            self._monitor_active = False
            
            # Resume game if still suspended
            if self._suspended_game_process is not None and PSUTIL_AVAILABLE:
                try:
                    if self._suspended_game_process.status() == STATUS_STOPPED:
                        self._suspended_game_process.resume()
                        log_success(log, "Resumed suspended game on cleanup", "▶️")
                except (NoSuchProcess, AccessDenied, AttributeError) as e:
                    log.debug(f"[INJECT] Could not resume suspended process: {e}")
                except Exception as e:
                    log.debug(f"[INJECT] Unexpected error resuming process: {e}")
                
            self._suspended_game_process = None
    
    def get_suspended_game_process(self):
        """Get the currently suspended game process (if any)"""
        return self._suspended_game_process
    
    def resume_game(self):
        """Resume the suspended game (called when runoverlay starts)"""
        # Set flag to prevent monitor from suspending after runoverlay starts
        self._runoverlay_started = True
        
        if self._suspended_game_process is not None and PSUTIL_AVAILABLE:
            try:
                game_proc = self._suspended_game_process
                
                # Always try to resume, even if status appears to be running
                # The status check can be unreliable when runoverlay starts (race condition)
                # It's safer to always call resume() if we have a suspended process reference
                status_before = None
                try:
                    status_before = game_proc.status()
                except (NoSuchProcess, AttributeError):
                    log.debug("[monitor] Game process no longer exists")
                    self._suspended_game_process = None
                    self._monitor_active = False
                    return
                
                # Resume until no longer suspended (handles multiple suspensions)
                for attempt in range(1, GAME_RESUME_MAX_ATTEMPTS + 1):
                    try:
                        current_status = game_proc.status()
                        
                        # If already running, log but still try resume() once to be safe
                        # This handles cases where status is misleading
                        if current_status != STATUS_STOPPED:
                            if attempt == 1:
                                log.debug(f"[monitor] Game status is {current_status} (not stopped) - attempting resume anyway to be safe")
                            else:
                                # Already tried, status still not stopped, assume it's running
                                log.debug(f"[monitor] Game already running (status={current_status})")
                                break
                        
                        # Always call resume() - it's safe to call even if already running
                        game_proc.resume()
                        time.sleep(GAME_RESUME_VERIFICATION_WAIT_S)
                        
                        status_after = game_proc.status()
                        if status_after != STATUS_STOPPED:
                            if attempt == 1:
                                log_success(log, f"Game resumed (PID={game_proc.pid}, status={status_after})", "▶️")
                            else:
                                log_success(log, f"Game resumed after {attempt} attempts (PID={game_proc.pid})", "▶️")
                            log_event(log, "Game loading while overlay hooks in...", "⚙️")
                            break
                        else:
                            if attempt < GAME_RESUME_MAX_ATTEMPTS:
                                log.debug(f"[monitor] Still suspended after attempt {attempt}, retrying...")
                            else:
                                log.error(f"[monitor] Failed to resume after {GAME_RESUME_MAX_ATTEMPTS} attempts - game may be stuck")
                                # Force clear reference even on failure to prevent permanent lock
                                log.warning("[monitor] Clearing suspended process reference - auto-resume will handle if needed")
                    except NoSuchProcess:
                        log.debug("[monitor] Game process ended during resume")
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
                # CRITICAL: Clear reference even on error to prevent permanent lock
                # If resume failed, stop() will try again later
                self._suspended_game_process = None
                self._monitor_active = False
        elif self._suspended_game_process is not None and not PSUTIL_AVAILABLE:
            # Clear reference if psutil is not available
            log.warning("[monitor] Cannot resume game - psutil not available")
            self._suspended_game_process = None
            self._monitor_active = False
    
    def resume_if_suspended(self):
        """Resume game if monitor suspended it (for when injection is skipped)"""
        if self._suspended_game_process is not None:
            log.info("[INJECT] Injection skipped - resuming suspended game")
            self.resume_game()
            self.stop()
    
    @property
    def is_active(self) -> bool:
        """Check if monitor is currently active"""
        return self._monitor_active

