#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Process Manager
Handles process management utilities for overlay processes
"""

import subprocess
import time
from pathlib import Path

# Import psutil with fallback for development environments
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

from utils.core.logging import get_logger
from config import (
    PROCESS_TERMINATE_TIMEOUT_S,
    PROCESS_TERMINATE_WAIT_S,
    PROCESS_ENUM_TIMEOUT_S
)

log = get_logger()


class ProcessManager:
    """Manages overlay process lifecycle"""
    
    def __init__(self):
        self.current_overlay_process = None
    
    def stop_overlay_process(self):
        """Stop the current overlay process"""
        if self.current_overlay_process and self.current_overlay_process.poll() is None:
            try:
                log.info("[INJECT] Stopping current overlay process")
                self.current_overlay_process.terminate()
                try:
                    self.current_overlay_process.wait(timeout=PROCESS_TERMINATE_TIMEOUT_S)
                except subprocess.TimeoutExpired:
                    self.current_overlay_process.kill()
                    self.current_overlay_process.wait()
                self.current_overlay_process = None
                log.info("[INJECT] Overlay process stopped successfully")
            except Exception as e:
                log.warning(f"[INJECT] Failed to stop overlay process: {e}")
        else:
            log.debug("[INJECT] No active overlay process to stop")
    
    def kill_all_runoverlay_processes(self):
        """Kill all runoverlay processes (for ChampSelect cleanup)"""
        killed_count = 0
        
        try:
            # Find all processes with "runoverlay" in command line
            # Use a timeout to prevent hanging on process_iter
            start_time = time.time()
            timeout = PROCESS_ENUM_TIMEOUT_S
            
            # Only get pid and name initially to avoid slow cmdline lookups
            if not PSUTIL_AVAILABLE:
                log.debug("[INJECT] psutil not available, skipping process cleanup")
                return
                
            for proc in psutil.process_iter(['pid', 'name']):
                # Check timeout to prevent indefinite hangs
                if time.time() - start_time > timeout:
                    log.warning(f"[INJECT] Process enumeration timeout after {timeout}s - some processes may not be killed")
                    break
                
                try:
                    # Skip if not mod-tools.exe (avoid expensive cmdline check on unrelated processes)
                    if proc.info.get('name') != 'mod-tools.exe':
                        continue
                    
                    # Only fetch cmdline for mod-tools.exe processes with a timeout
                    try:
                        # Create Process object for cmdline access
                        p = psutil.Process(proc.info['pid'])
                        # Use a short timeout on cmdline() to prevent hanging
                        cmdline = p.cmdline()
                        
                        if cmdline and any('runoverlay' in arg for arg in cmdline):
                            log.info(f"[INJECT] Killing runoverlay process PID {proc.info['pid']}")
                            try:
                                # Try graceful termination first
                                p.terminate()
                                # Give it a brief moment, then force kill if needed
                                try:
                                    p.wait(timeout=PROCESS_TERMINATE_WAIT_S)
                                except (psutil.TimeoutExpired, psutil.NoSuchProcess) as wait_e:
                                    p.kill()  # Force kill if terminate didn't work
                                    log.debug(f"Process wait timeout or process gone, force killing: {wait_e}")
                            except Exception as e:
                                try:
                                    p.kill()  # Force kill on any error
                                except (psutil.NoSuchProcess, psutil.AccessDenied) as kill_e:
                                    log.debug(f"[INJECT] Process already gone or inaccessible: {kill_e}")
                                except Exception as kill_e:
                                    log.debug(f"[INJECT] Unexpected error force killing process: {kill_e}")
                            killed_count += 1
                    except psutil.TimeoutExpired:
                        log.debug(f"[INJECT] Timeout fetching cmdline for PID {proc.info['pid']}")
                        continue
                    
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # Process might have already ended or we don't have access
                    pass
                except Exception as e:
                    # Log but continue with other processes
                    log.debug(f"[INJECT] Error processing PID {proc.info.get('pid', '?')}: {e}")
            
            if killed_count > 0:
                log.info(f"[INJECT] Killed {killed_count} runoverlay process(es)")
            else:
                log.debug("[INJECT] No runoverlay processes found to kill")
                
        except Exception as e:
            log.warning(f"[INJECT] Failed to kill runoverlay processes: {e}")
        
        # Also stop our tracked process if it exists
        self.stop_overlay_process()
    
    def kill_all_modtools_processes(self):
        """Kill all mod-tools.exe processes (for application shutdown)"""
        killed_count = 0
        
        try:
            # Use a timeout to prevent hanging on process_iter
            start_time = time.time()
            timeout = PROCESS_ENUM_TIMEOUT_S
            
            # Only get pid and name initially to avoid slow cmdline lookups
            if not PSUTIL_AVAILABLE:
                log.debug("[INJECT] psutil not available, skipping mod-tools cleanup")
                return
            
            for proc in psutil.process_iter(['pid', 'name']):
                # Check timeout to prevent indefinite hangs
                if time.time() - start_time > timeout:
                    log.warning(f"[INJECT] Process enumeration timeout after {timeout}s - some processes may not be killed")
                    break
                
                try:
                    # Only kill mod-tools.exe processes
                    if proc.info.get('name') != 'mod-tools.exe':
                        continue
                    
                    # Kill all mod-tools.exe processes regardless of command
                    log.info(f"[INJECT] Killing mod-tools.exe process PID {proc.info['pid']}")
                    try:
                        # Create Process object
                        p = psutil.Process(proc.info['pid'])
                        # Try graceful termination first
                        p.terminate()
                        # Give it a brief moment, then force kill if needed
                        try:
                            p.wait(timeout=PROCESS_TERMINATE_WAIT_S)
                        except (psutil.TimeoutExpired, psutil.NoSuchProcess) as wait_e:
                            p.kill()  # Force kill if terminate didn't work
                            log.debug(f"Process wait timeout or process gone, force killing: {wait_e}")
                    except Exception as e:
                        try:
                            p.kill()  # Force kill on any error
                        except (psutil.NoSuchProcess, psutil.AccessDenied) as kill_e:
                            log.debug(f"[INJECT] Process already gone or inaccessible: {kill_e}")
                        except Exception as kill_e:
                            log.debug(f"[INJECT] Unexpected error force killing process: {kill_e}")
                    killed_count += 1
                    
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # Process might have already ended or we don't have access
                    pass
                except Exception as e:
                    # Log but continue with other processes
                    log.debug(f"[INJECT] Error processing PID {proc.info.get('pid', '?')}: {e}")
            
            if killed_count > 0:
                log.info(f"[INJECT] Killed {killed_count} mod-tools.exe process(es)")
            else:
                log.debug("[INJECT] No mod-tools.exe processes found to kill")
                
        except Exception as e:
            log.warning(f"[INJECT] Failed to kill mod-tools.exe processes: {e}")
        
        # Also stop our tracked process if it exists
        self.stop_overlay_process()

