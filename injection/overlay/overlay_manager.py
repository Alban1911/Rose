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
from ..tools.patcher import check_ltk_patcher
from config import (
    PROCESS_TERMINATE_TIMEOUT_S,
    PROCESS_MONITOR_SLEEP_S,
    ENABLE_MKOVERLAY_PRIORITY_BOOST,
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

# LTK patcher host settings (see ltk-manager patcher/host/protocol.rs).
# Flag 4 = CSLOL_HOOK_OPT_OUT_AH_V1: Rose replaces skin0 with the selected
# skin, which the DLL's base-skin check rejects and then disables the whole
# overlay; opting out downgrades that to a warning (same as LTK Manager's
# "enforce skinhack scan" setting turned off). Log level 0x10 = Info.
LTK_PATCHER_FLAGS = 4
LTK_PATCHER_LOG_LEVEL = 0x10
# Printed by the DLL when the game build is newer than its end-of-life date
END_OF_LIFE_MESSAGE = "end of life reached"
LATE_JOIN_MESSAGE = "joined too late"

# WAD v3 header: magic + version (4), RSA signature (256), checksum (8)
WAD_HEADER_SIZE = 268


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
        
        ltk_host = tools_manager.detect_ltk_patcher()
        if not ltk_host:
            log.error("[INJECT] LTK patcher not found (ltk_patcher_host.exe + ltk_patcher_dll.dll)")
            report_issue(
                "LTK_PATCHER_MISSING",
                "error",
                "Injection failed: the LTK patcher is missing.",
                hint="Copy ltk_patcher_host.exe and ltk_patcher_dll.dll into Rose's tools folder.",
            )
            return 1

        # Rose may have been running since before the DLL reached its end of life
        patcher = check_ltk_patcher(ltk_host.parent)
        if patcher.expired:
            eol = time.strftime("%Y-%m-%d %H:%M", time.localtime(patcher.eol))
            log.error(f"[INJECT] LTK patcher reached its end of life on {eol}")
            self._report_ltk_patcher_eol(eol)
            return 1

        # The DLL only overlays games launched after the scan started, so the
        # host must already be scanning when the game starts
        if self.process_manager:
            self.process_manager.stopped_by_user = False
        patcher_session = self._start_ltk_patcher(ltk_host, overlay_dir)
        if not patcher_session:
            return 1

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
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags, text=True, encoding="utf-8", errors="replace", bufsize=1)
            
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
                self._abort_ltk_patcher(patcher_session)
                return proc.returncode
            else:
                log_success(log, f"mkoverlay completed in {mkoverlay_duration:.2f}s", "⚡")
                # Store timing data for external access
                self.last_injection_timing = {
                    'mkoverlay_duration': mkoverlay_duration,
                    'timestamp': time.time()
                }

                self._restore_wad_headers(overlay_dir, Path(gpath))

                # Wipe extracted skin files now that mkoverlay is done with them
                self._wipe_mods_dir()

                # Hide overlay files so they can't be easily browsed
                self._hide_directory(overlay_dir)

                # DON'T resume game yet - keep it frozen until runoverlay starts
                log_event(log, "mkoverlay done - keeping game frozen until the overlay is served", "❄️")
                
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
            self._abort_ltk_patcher(patcher_session)
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
            self._abort_ltk_patcher(patcher_session)
            return 1

        return self._run_ltk_patcher(patcher_session, overlay_dir, stop_callback, injection_manager)

    def _start_ltk_patcher(self, host_exe: Path, overlay_dir: Path) -> Optional[dict]:
        """Start the LTK patcher host and begin scanning for the game.

        The host speaks a line protocol: config/start commands on stdin and
        "status <ts> <state> <msg>" / "error <ts> <msg>" events on stdout.
        It stays alive between sessions, so we stop it once the game exits.
        """
        import sys
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        prefix = str(overlay_dir).rstrip("\\/") + "\\"
        commands = [
            f"config loglevel {LTK_PATCHER_LOG_LEVEL}",
            f"config flags {LTK_PATCHER_FLAGS}",
            f"config prefix {prefix}",
            "start scan",
        ]

        runoverlay_log = self._open_runoverlay_log()
        session = {"state": None, "error": None, "eol": False}

        def read_events(pipe):
            try:
                for line in pipe:
                    line = line.rstrip("\r\n")
                    if not line:
                        continue
                    if runoverlay_log:
                        runoverlay_log.write(line + "\n")
                        runoverlay_log.flush()
                    parts = line.split(" ", 3)
                    if parts[0] == "status" and len(parts) >= 3:
                        session["state"] = parts[2]
                        message = parts[3] if len(parts) > 3 else ""
                        log.info(f"[INJECT] LTK patcher: {parts[2]} {message}".rstrip())
                        if parts[2] == "failed":
                            session["error"] = message or "injection failed"
                    elif parts[0] == "error":
                        session["error"] = line
                        log.error(f"[INJECT] LTK patcher error: {line}")
                    elif parts[0] == "dll" and END_OF_LIFE_MESSAGE in line:
                        # The DLL refuses game builds newer than its end-of-life date
                        session["error"] = line
                        session["eol"] = True
                        log.error("[INJECT] LTK patcher DLL reached its end of life for this game build")
                    elif parts[0] == "dll" and LATE_JOIN_MESSAGE in line:
                        # The game was launched before the host started scanning
                        session["error"] = "the game started before the patcher, overlay not applied"
                        log.error("[INJECT] LTK patcher DLL joined the game too late - overlay not applied")
                    elif parts[0] == "dll" and " ERROR " in line:
                        # e.g. "overlay verification failed, disabling overlay"
                        message = line.split(" ERROR ", 1)[1]
                        log.error(f"[INJECT] LTK patcher DLL: {message}")
                        if "disabling overlay" in message:
                            session["error"] = message
            except Exception as e:
                log.debug(f"[INJECT] Error reading LTK patcher output: {e}")

        log.debug(f"[INJECT] Starting LTK patcher: {host_exe}")
        try:
            proc = subprocess.Popen(
                [str(host_exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=str(host_exe.parent), creationflags=creationflags,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
        except Exception as e:
            log.error(f"[INJECT] Could not start LTK patcher: {e}")
            self._report_ltk_patcher_failure(f"could not start ({e})")
            if runoverlay_log:
                runoverlay_log.close()
            return None

        reader = threading.Thread(target=read_events, args=(proc.stdout,), daemon=True)
        reader.start()
        patcher_session = {"proc": proc, "session": session, "reader": reader, "log": runoverlay_log}
        try:
            for command in commands:
                proc.stdin.write(command + "\n")
            proc.stdin.flush()
        except Exception as e:
            log.error(f"[INJECT] Could not configure LTK patcher: {e}")
            self._abort_ltk_patcher(patcher_session)
            self._report_ltk_patcher_failure(f"could not start ({e})")
            return None

        if self.process_manager:
            self.process_manager.current_overlay_process = proc
        return patcher_session

    def _abort_ltk_patcher(self, patcher_session: dict):
        """Stop a patcher whose injection failed before the overlay was served."""
        self._stop_ltk_patcher(patcher_session["proc"])
        if self.process_manager:
            self.process_manager.current_overlay_process = None
        if patcher_session["log"]:
            patcher_session["log"].close()

    def _run_ltk_patcher(self, patcher_session: dict, overlay_dir: Path,
                         stop_callback: Optional[Callable] = None, injection_manager=None) -> int:
        """Resume the game and serve the overlay until the game exits."""
        proc = patcher_session["proc"]
        session = patcher_session["session"]
        reader = patcher_session["reader"]
        runoverlay_log = patcher_session["log"]
        try:
            # The host cannot find a frozen game; it hooks it right after resume
            if injection_manager:
                log.info("[INJECT] Overlay ready - resuming game for the LTK patcher")
                injection_manager.resume_game()

            game_ended = False
            while proc.poll() is None:
                if session["state"] in ("exited", "failed"):
                    break
                if stop_callback and stop_callback():
                    log.info("[INJECT] Game ended, stopping LTK patcher")
                    game_ended = True
                    break
                time.sleep(PROCESS_MONITOR_SLEEP_S)

            self._stop_ltk_patcher(proc)
            reader.join(timeout=1.0)

            if self.process_manager and self.process_manager.stopped_by_user:
                log.info("[INJECT] LTK patcher stopped by the user")
                return 0
            if session["eol"]:
                self._log_runoverlay_tail(runoverlay_log)
                self._report_ltk_patcher_eol()
                return 1
            if session["error"]:
                log.error(f"[INJECT] LTK patcher failed: {session['error']}")
                self._log_runoverlay_tail(runoverlay_log)
                self._report_ltk_patcher_failure(session["error"])
                return 1
            if not game_ended and session["state"] != "exited" and proc.returncode not in (0, None):
                log.error(f"[INJECT] LTK patcher exited with return code: {proc.returncode}")
                self._log_runoverlay_tail(runoverlay_log)
                self._report_ltk_patcher_failure(f"exited with code {proc.returncode}")
                return proc.returncode
            log.debug("[INJECT] LTK patcher session completed successfully")
            return 0
        except Exception as e:
            log.error(f"[INJECT] LTK patcher error: {e}")
            self._stop_ltk_patcher(proc)
            self._report_ltk_patcher_failure(str(e))
            return 1
        finally:
            if self.process_manager:
                self.process_manager.current_overlay_process = None
            self._wipe_overlay_dir(overlay_dir)
            if runoverlay_log:
                runoverlay_log.close()

    @staticmethod
    def _report_ltk_patcher_eol(eol: str = ""):
        """Show an expired LTK patcher DLL in Troubleshooting."""
        since = f" on {eol}" if eol else ""
        report_issue(
            "LTK_PATCHER_EOL",
            "error",
            f"Injection failed: LTK patcher reached its end of life{since}.",
            hint="Update LTK Manager, copy its new ltk_patcher_host.exe and ltk_patcher_dll.dll into Rose's tools folder, then restart Rose.",
        )

    @staticmethod
    def _report_ltk_patcher_failure(reason: str):
        """Show an LTK patcher failure in Troubleshooting."""
        report_issue(
            "LTK_PATCHER_FAILED",
            "error",
            f"Injection failed: LTK patcher error: {reason}",
            hint="Make sure your LTK patcher files are up to date, then retry. Details are in rose_runoverlay_*.log.",
        )

    @staticmethod
    def _restore_wad_headers(overlay_dir: Path, game_dir: Path):
        """Copy the game's WAD signature + checksum into each overlay WAD.

        mkoverlay writes its own signature and a zero checksum. Since 16.19 the
        game rejects such WADs as corrupt ("WadFile mount failed") and flags the
        install for repair. LTK Manager keeps the original header when it
        rebases a WAD, so we do the same.
        """
        restored = 0
        for wad in overlay_dir.rglob("*.wad.client"):
            original = game_dir / wad.relative_to(overlay_dir)
            try:
                with open(original, "rb") as f:
                    header = f.read(WAD_HEADER_SIZE)
                if len(header) != WAD_HEADER_SIZE or header[:2] != b"RW":
                    continue
                with open(wad, "r+b") as f:
                    if f.read(4) != header[:4]:
                        log.warning(f"[INJECT] WAD version mismatch, header not restored: {wad.name}")
                        continue
                    f.seek(4)
                    f.write(header[4:])
                restored += 1
            except OSError as e:
                log.warning(f"[INJECT] Could not restore WAD header for {wad.name}: {e}")
        log.debug(f"[INJECT] Restored original headers on {restored} overlay WAD(s)")

    @staticmethod
    def _stop_ltk_patcher(proc):
        """Ask the LTK patcher host to stop, force-killing it after a grace period."""
        if proc.poll() is not None:
            return
        try:
            proc.stdin.write("stop\n")
            proc.stdin.flush()
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=PROCESS_TERMINATE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    @staticmethod
    def _open_runoverlay_log():
        """Open a log file for runoverlay output, or None if it cannot be created."""
        try:
            from utils.core.paths import get_user_data_dir
            logs_dir = get_user_data_dir() / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%d-%m-%Y_%H-%M-%S")
            return open(logs_dir / f"rose_runoverlay_{timestamp}.log", "w+", encoding="utf-8", errors="replace")
        except Exception as e:
            log.debug(f"[INJECT] Could not create runoverlay log: {e}")
            return None

    @staticmethod
    def _log_runoverlay_tail(runoverlay_log, max_lines: int = 20):
        """Log the last lines of runoverlay output after a failure."""
        if not runoverlay_log:
            return
        try:
            runoverlay_log.flush()
            runoverlay_log.seek(0)
            lines = [line.strip() for line in runoverlay_log.read().splitlines() if line.strip()]
            if lines:
                log.error(f"[INJECT] runoverlay output (last {min(len(lines), max_lines)} lines):")
                for line in lines[-max_lines:]:
                    log.error(f"[INJECT]   {line}")
            else:
                log.error("[INJECT] runoverlay produced no output")
            log.error(f"[INJECT] Full runoverlay log: {runoverlay_log.name}")
        except Exception as e:
            log.debug(f"[INJECT] Could not read runoverlay log: {e}")

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
