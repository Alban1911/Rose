#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Overlay Manager
Handles overlay creation and execution using CSLOL tools

Security Notes:
    - subprocess calls use only internal paths (tools_dir, mods_dir, game_dir)
    - No user-controlled input is passed directly to subprocess commands
    - All paths are constructed from trusted internal configuration
    - Commands only execute mod-tools.exe from the verified tools directory
"""

import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional, Callable

# Import psutil with fallback for development environments
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

from utils.core.logging import get_logger, log_action, log_success, log_event
from utils.core.issue_reporter import report_issue
from config import (
    PROCESS_TERMINATE_TIMEOUT_S,
    PROCESS_MONITOR_SLEEP_S,
    ENABLE_MKOVERLAY_PRIORITY_BOOST,
    ENABLE_RUNOVERLAY_PRIORITY_BOOST
)

log = get_logger()

# mkoverlay needs free space for the generated WAD overlay in addition to the
# extracted mod files. A gigabyte is a conservative lower bound for a normal
# skin, while the extracted mod size catches larger map/voiceover mods.
MIN_FREE_SPACE_BYTES = 1 * 1024 * 1024 * 1024
DISK_SPACE_HEADROOM_BYTES = 512 * 1024 * 1024
DISK_SPACE_ERROR_MARKERS = (
    'not enough space',
    'not enough disk space',
    'insufficient disk space',
    'disk full',
    'no space left',
    'error 112',
    'errno 28',
)


class OverlayManager:
    """Manages overlay creation and execution"""
    
    def __init__(self, tools_dir: Path, mods_dir: Path, game_dir: Optional[Path], process_manager=None):
        self.tools_dir = tools_dir
        self.mods_dir = mods_dir
        self.game_dir = game_dir
        self.process_manager = process_manager
        self.last_injection_timing = None
    
    @property
    def current_overlay_process(self):
        """Get current overlay process from process manager"""
        return self.process_manager.current_overlay_process if self.process_manager else None
    
    @current_overlay_process.setter
    def current_overlay_process(self, value):
        """Set current overlay process on process manager"""
        if self.process_manager:
            self.process_manager.current_overlay_process = value

    @staticmethod
    def _directory_size(directory: Path) -> int:
        '''Return the best-effort size of files below *directory*.'''
        total = 0
        try:
            for path in directory.rglob('*'):
                try:
                    if path.is_file():
                        total += path.stat().st_size
                except OSError:
                    continue
        except OSError:
            return 0
        return total

    @staticmethod
    def _format_bytes(size: int) -> str:
        '''Format a byte count for log and diagnostics messages.'''
        value = float(max(0, size))
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if value < 1024 or unit == 'TB':
                return f'{value:.1f} {unit}'
            value /= 1024
        return f'{value:.1f} TB'

    def _report_low_disk_space_failure(
        self,
        output_lines: Optional[List[str]] = None,
        mod_names: Optional[List[str]] = None,
        result_code: Optional[int] = None,
    ) -> bool:
        '''Report a failed overlay when its output drive is out of space.'''
        output = ' '.join(output_lines or ()).lower()
        tool_reported_disk_error = (
            any(marker in output for marker in DISK_SPACE_ERROR_MARKERS)
            or result_code in (28, 112)
        )

        free_bytes = None
        required_bytes = max(MIN_FREE_SPACE_BYTES, DISK_SPACE_HEADROOM_BYTES)
        try:
            usage = shutil.disk_usage(self.mods_dir.parent)
            free_bytes = usage.free
            extracted_bytes = self._directory_size(self.mods_dir)
            required_bytes = max(
                MIN_FREE_SPACE_BYTES,
                extracted_bytes + DISK_SPACE_HEADROOM_BYTES,
            )
        except (OSError, ValueError) as exc:
            log.debug(f'[INJECT] Could not inspect free disk space after injection failure: {exc}')

        low_disk_space = free_bytes is not None and free_bytes < required_bytes
        if not low_disk_space and not tool_reported_disk_error:
            return False

        free_text = self._format_bytes(free_bytes) if free_bytes is not None else 'an unknown amount'
        required_text = self._format_bytes(required_bytes)
        log.error(
            '[INJECT] Injection failed because disk space is too low '
            f'({free_text} free; approximately {required_text} recommended on {self.mods_dir.parent})'
        )
        report_issue(
            'LOW_DISK_SPACE',
            'error',
            f'Injection failed: not enough disk space for the overlay ({free_text} free).',
            details={
                'free_bytes': free_bytes,
                'required_bytes': required_bytes,
                'overlay_path': str(self.mods_dir.parent),
                'mods': '/'.join(mod_names or ()),
            },
            hint='Free up disk space on the drive containing Rose injection files, then retry the skin.',
        )
        return True
    
    def mk_run_overlay(self, mod_names: List[str], timeout: int = 120, stop_callback: Optional[Callable] = None, injection_manager=None) -> int:
        """Create and run overlay
        
        Args:
            mod_names: List of mod names to inject
            timeout: Unused (kept for backward compatibility) - overlay runs until explicitly killed
            stop_callback: Optional callback to check if game ended
            injection_manager: Optional injection manager for game resume
        """
        if self.game_dir is None:
            log.error("[INJECTOR] Cannot create overlay - League game directory not found")
            log.error("[INJECTOR] Please ensure League Client is running or manually set the path in config.ini")
            return 127
        
        from ..tools.tools_manager import ToolsManager
        tools_manager = ToolsManager(self.tools_dir)
        tools = tools_manager.detect_tools()
        exe = tools.get("modtools")
        if not exe or not exe.exists():
            log.error(f"[INJECTOR] Missing mod-tools.exe in {self.tools_dir}")
            return 127
        
        # Use overlay directory (should already be clean from _clean_overlay_dir)
        overlay_dir = self.mods_dir.parent / "overlay"
        overlay_dir.mkdir(parents=True, exist_ok=True)
        
        names_str = "/".join(mod_names)
        gpath = str(self.game_dir)

        # Create overlay (this is the actual injection work)
        # Based on CSLOL source: flags.contains("--ignoreConflict") in main_mod_tools.cpp:332
        # Documentation: mod-tools.md shows --ignoreConflict flag (camelCase, no --opts: prefix)
        cmd = [
            str(exe), "mkoverlay", str(self.mods_dir), str(overlay_dir),
            f"--game:{gpath}", f"--mods:{names_str}", "--noTFT",
            "--ignoreConflict"
        ]
        
        log.debug(f"[INJECT] Creating overlay: {' '.join(cmd)}")
        mkoverlay_start = time.time()
        output_lines = []
        error_lines = []
        try:
            # Hide console window on Windows
            import sys
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW
            
            # Capture both stdout and stderr - CSLOL uses logi() which may write to stdout
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags, text=True, bufsize=1)
            
            # Boost process priority to maximize CPU contention if enabled
            if ENABLE_MKOVERLAY_PRIORITY_BOOST and PSUTIL_AVAILABLE:
                try:
                    p = psutil.Process(proc.pid)
                    p.nice(psutil.HIGH_PRIORITY_CLASS)
                    log.debug(f"[INJECT] Boosted mkoverlay process priority (PID={proc.pid})")
                except Exception as e:
                    log.debug(f"[INJECT] Could not boost process priority: {e}")
            
            # Wait for process to complete with timeout
            # Read both stdout and stderr in separate threads to see what mkoverlay is doing
            def read_output(pipe, lines_list, prefix):
                try:
                    for line in pipe:
                        if line:
                            stripped = line.strip()
                            if stripped:
                                lines_list.append(stripped)
                except Exception as e:
                    log.debug(f"[INJECT] Error reading {prefix}: {e}")
            
            stdout_thread = threading.Thread(target=read_output, args=(proc.stdout, output_lines, "stdout"), daemon=True)
            stderr_thread = threading.Thread(target=read_output, args=(proc.stderr, error_lines, "stderr"), daemon=True)
            stdout_thread.start()
            stderr_thread.start()
            
            try:
                proc.wait(timeout=timeout)
                # Give threads a moment to finish reading
                stdout_thread.join(timeout=1.0)
                stderr_thread.join(timeout=1.0)
                if output_lines or error_lines:
                    log.debug(f"[INJECT] mkoverlay completed - {len(output_lines)} stdout, {len(error_lines)} stderr lines")
            except subprocess.TimeoutExpired:
                # Process timed out - log what we have so far
                all_lines = output_lines + error_lines
                if all_lines:
                    log.warning(f"[INJECT] mkoverlay timeout - last output: {'; '.join(all_lines[-10:])}")  # Last 10 lines
                else:
                    log.warning("[INJECT] mkoverlay timeout - no output captured")
                proc.kill()
                proc.wait()
                raise
            mkoverlay_duration = time.time() - mkoverlay_start
            
            if proc.returncode != 0:
                self._report_low_disk_space_failure(
                    output_lines + error_lines,
                    mod_names,
                    result_code=proc.returncode,
                )
                log.error(f"[INJECT] mkoverlay failed with return code: {proc.returncode}")
                return proc.returncode
            else:
                log_success(log, f"mkoverlay completed in {mkoverlay_duration:.2f}s", "⚡")
                # Store timing data for external access
                self.last_injection_timing = {
                    'mkoverlay_duration': mkoverlay_duration,
                    'timestamp': time.time()
                }

                # Wipe extracted skin files now that mkoverlay is done with them
                self._wipe_mods_dir()

                # Hide overlay files so they can't be easily browsed
                self._hide_directory(overlay_dir)

                # DON'T resume game yet - keep it frozen until runoverlay starts
                log_event(log, "mkoverlay done - keeping game frozen until runoverlay starts", "❄️")
                
        except subprocess.TimeoutExpired:
            log.error("[INJECT] mkoverlay timeout - monitor will auto-resume if needed")
            report_issue(
                "MKOVERLAY_TIMEOUT",
                "error",
                "Injection timed out while preparing the overlay (took too long).",
                details={"timeout_s": timeout},
                hint="Try increasing Monitor Auto-Resume Timeout and/or using smaller mods.",
            )
            self._report_low_disk_space_failure(output_lines + error_lines, mod_names)
            return 124
        except Exception as e:
            log.error(f"[INJECT] mkoverlay error: {e} - monitor will auto-resume if needed")
            report_issue(
                "MKOVERLAY_ERROR",
                "error",
                "Injection failed while preparing the overlay.",
                details={"error": str(e)},
                hint="Check Rose logs for details, then retry.",
            )
            self._report_low_disk_space_failure(output_lines + error_lines, mod_names)
            return 1

        # Run overlay
        cfg = overlay_dir / "cslol-config.json"
        cmd = [
            str(exe), "runoverlay", str(overlay_dir), str(cfg),
            f"--game:{gpath}", "--opts:configless"
        ]
        
        log.debug(f"[INJECT] Running overlay")
        
        try:
            # Hide console window on Windows
            import sys
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW
            
            # Don't capture stdout to avoid pipe buffer deadlock - send to devnull instead
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
            
            # Boost process priority to maximize CPU contention if enabled
            if ENABLE_RUNOVERLAY_PRIORITY_BOOST and PSUTIL_AVAILABLE:
                try:
                    p = psutil.Process(proc.pid)
                    p.nice(psutil.HIGH_PRIORITY_CLASS)
                    log.debug(f"[INJECT] Boosted runoverlay process priority (PID={proc.pid})")
                except Exception as e:
                    log.debug(f"[INJECT] Could not boost process priority: {e}")
            
            if self.process_manager:
                self.process_manager.current_overlay_process = proc
            
            # Resume game NOW - runoverlay started, game can load while runoverlay hooks in
            if injection_manager:
                log.info("[INJECT] runoverlay started - resuming game")
                injection_manager.resume_game()
            
            # Monitor process with stop callback
            # No timeout - overlay will run until explicitly killed or game ends
            while proc.poll() is None:
                # Check if we should stop (game ended)
                if stop_callback and stop_callback():
                    log.info("[INJECT] Game ended, stopping overlay process")
                    proc.terminate()
                    try:
                        proc.wait(timeout=PROCESS_TERMINATE_TIMEOUT_S)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    if self.process_manager:
                        self.process_manager.current_overlay_process = None
                    self._wipe_overlay_dir(overlay_dir)
                    return 0  # Success - overlay ran through game

                time.sleep(PROCESS_MONITOR_SLEEP_S)

            # Process completed normally (no stdout captured)
            self.current_overlay_process = None
            self._wipe_overlay_dir(overlay_dir)
            if proc.returncode != 0:
                self._report_low_disk_space_failure(
                    mod_names=mod_names,
                    result_code=proc.returncode,
                )
                log.error(f"[INJECT] runoverlay failed with return code: {proc.returncode}")
                return proc.returncode
            else:
                log.debug(f"[INJECT] runoverlay completed successfully")
                return 0
        except Exception as e:
            log.error(f"[INJECT] runoverlay error: {e}")
            return 1
    
    @staticmethod
    def _wipe_overlay_dir(overlay_dir: Path):
        """Delete overlay WAD files after runoverlay finishes"""
        try:
            import shutil
            shutil.rmtree(overlay_dir, ignore_errors=True)
            overlay_dir.mkdir(parents=True, exist_ok=True)
            log.debug("[INJECT] Wiped overlay directory after game ended")
        except Exception as e:
            log.debug(f"[INJECT] Could not wipe overlay directory: {e}")

    def _wipe_mods_dir(self):
        """Delete extracted skin files immediately after mkoverlay consumes them"""
        try:
            import shutil
            for p in self.mods_dir.iterdir():
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
            log.debug("[INJECT] Wiped mods directory after mkoverlay")
        except Exception as e:
            log.debug(f"[INJECT] Could not wipe mods directory: {e}")

    @staticmethod
    def _hide_directory(path: Path):
        """Set hidden + system attributes on a directory and its contents (Windows only)"""
        import sys
        if sys.platform != "win32":
            return
        try:
            import ctypes
            FILE_ATTRIBUTE_HIDDEN = 0x02
            FILE_ATTRIBUTE_SYSTEM = 0x04
            attrs = FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
            # Hide the directory itself
            ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs)
            # Hide all contents recursively
            for item in path.rglob('*'):
                ctypes.windll.kernel32.SetFileAttributesW(str(item), attrs)
            log.debug(f"[INJECT] Hidden overlay directory: {path}")
        except Exception as e:
            log.debug(f"[INJECT] Could not hide overlay directory: {e}")

    def mk_overlay_only(self, mod_names: List[str], timeout: int = 60) -> int:
        """Create overlay using mkoverlay only (no runoverlay) - for testing"""
        if self.game_dir is None:
            log.error("[INJECTOR] Cannot create overlay - League game directory not found")
            log.error("[INJECTOR] Please ensure League Client is running or manually set the path in config.ini")
            return 127
        
        try:
            # Build mkoverlay command
            # Based on CSLOL source: flags.contains("--ignoreConflict") in main_mod_tools.cpp:332
            cmd = [
                str(self.tools_dir / "mod-tools.exe"),
                "mkoverlay",
                str(self.mods_dir),
                str(self.mods_dir.parent / "overlay"),
                f"--game:{self.game_dir}",
                f"--mods:{','.join(mod_names)}",
                "--noTFT",
                "--ignoreConflict"
            ]
            
            log.debug(f"[INJECT] Creating overlay (mkoverlay only): {' '.join(cmd)}")
            mkoverlay_start = time.time()
            
            # Set creation flags for Windows
            import sys
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW
            
            try:
                # Don't capture stdout to avoid pipe buffer deadlock - send to devnull instead
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
                proc.wait(timeout=timeout)
                mkoverlay_duration = time.time() - mkoverlay_start
                
                if proc.returncode != 0:
                    self._report_low_disk_space_failure(
                        mod_names=mod_names,
                        result_code=proc.returncode,
                    )
                    log.error(f"[INJECT] mkoverlay failed with return code: {proc.returncode}")
                    return proc.returncode
                else:
                    log.debug(f"[INJECT] mkoverlay completed in {mkoverlay_duration:.2f}s")
                    self.last_injection_timing = {
                        'mkoverlay_duration': mkoverlay_duration,
                        'timestamp': time.time()
                    }
                    return 0
                    
            except subprocess.TimeoutExpired:
                log.error(f"[INJECT] mkoverlay timed out after {timeout}s")
                proc.kill()
                self._report_low_disk_space_failure(mod_names=mod_names)
                return -1
            except Exception as e:
                self._report_low_disk_space_failure(mod_names=mod_names)
                log.error(f"[INJECT] mkoverlay failed with exception: {e}")
                return -1
                
        except Exception as e:
            log.error(f"[INJECT] Failed to create mkoverlay command: {e}")
            return -1
    
    def run_overlay_from_path(self, overlay_path: Path) -> bool:
        """Run overlay from an overlay directory"""
        try:
            log.info(f"[INJECT] Running overlay from: {overlay_path}")
            
            # Check what's in the overlay directory
            overlay_contents = list(overlay_path.iterdir())
            log.debug(f"[INJECT] Overlay contents: {[f.name for f in overlay_contents]}")
            
            if not overlay_contents:
                log.error(f"[INJECT] Overlay directory is empty: {overlay_path}")
                return False
            
            # Copy overlay to the main overlay directory
            main_overlay_dir = self.mods_dir.parent / "overlay"
            
            # Clean main overlay directory
            if main_overlay_dir.exists():
                import shutil
                shutil.rmtree(main_overlay_dir, ignore_errors=True)
            main_overlay_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy overlay contents
            log.debug(f"[INJECT] Copying from {overlay_path} to {main_overlay_dir}")
            import shutil
            for item in overlay_path.iterdir():
                if item.is_file():
                    shutil.copy2(item, main_overlay_dir / item.name)
                    log.debug(f"[INJECT] Copied file: {item.name}")
                elif item.is_dir():
                    shutil.copytree(item, main_overlay_dir / item.name)
                    log.debug(f"[INJECT] Copied directory: {item.name}")
            
            # Log what's in the main overlay directory after copying
            overlay_files = list(main_overlay_dir.iterdir())
            log.debug(f"[INJECT] Main overlay directory contents: {[f.name for f in overlay_files]}")
            
            # Run overlay using runoverlay command
            from ..tools.tools_manager import ToolsManager
            tools_manager = ToolsManager(self.tools_dir)
            tools = tools_manager.detect_tools()
            exe = tools.get("modtools")
            if not exe or not exe.exists():
                log.error(f"[INJECTOR] Missing mod-tools.exe in {self.tools_dir}")
                return False
            
            # Create configuration file path
            if self.game_dir is None:
                log.error("[INJECTOR] Cannot run overlay - League game directory not found")
                log.error("[INJECTOR] Please ensure League Client is running or manually set the path in config.ini")
                return False
                
            cfg = main_overlay_dir / "cslol-config.json"
            gpath = str(self.game_dir)
            
            cmd = [
                str(exe), "runoverlay", str(main_overlay_dir), str(cfg),
                f"--game:{gpath}", "--opts:configless"
            ]
            
            log.info(f"[INJECT] Running overlay: {' '.join(cmd)}")
            
            try:
                # Hide console window on Windows
                import sys
                creationflags = 0
                if sys.platform == "win32":
                    creationflags = subprocess.CREATE_NO_WINDOW
                
                # Don't capture stdout to avoid pipe buffer issues - send to devnull instead
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
                if self.process_manager:
                    self.process_manager.current_overlay_process = proc
                
                # For pre-built overlays, we don't need to monitor the process long-term
                # Just start it and let it run in the background
                log.info("[INJECT] Pre-built overlay process started successfully")
                return True
                
            except Exception as e:
                log.error(f"[INJECT] Error running overlay process: {e}")
                return False
                
        except Exception as e:
            log.error(f"[INJECT] Error running pre-built overlay: {e}")
            return False
