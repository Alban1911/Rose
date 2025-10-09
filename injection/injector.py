#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSLOL Skin Injector
Handles the actual skin injection using CSLOL tools
"""

import subprocess
import time
from pathlib import Path
from typing import List, Dict, Optional
import zipfile
import shutil

from utils.logging import get_logger
from utils.paths import get_skins_dir, get_injection_dir
from constants import (
    PROCESS_TERMINATE_TIMEOUT_S, 
    PROCESS_MONITOR_SLEEP_S, 
    ENABLE_PRIORITY_BOOST, 
    ENABLE_GAME_SUSPENSION,
    GAME_RESUME_VERIFICATION_WAIT_S,
    GAME_RESUME_MAX_ATTEMPTS
)

log = get_logger()


class SkinInjector:
    """CSLOL-based skin injector"""
    
    def __init__(self, tools_dir: Path = None, mods_dir: Path = None, zips_dir: Path = None, game_dir: Optional[Path] = None):
        # Use injection folder as base if paths not provided
        injection_dir = Path(__file__).parent
        self.tools_dir = tools_dir or injection_dir / "tools"
        # Use user data directory for mods and skins to avoid permission issues
        self.mods_dir = mods_dir or get_injection_dir() / "mods"
        self.zips_dir = zips_dir or get_skins_dir()
        self.game_dir = game_dir or self._detect_game_dir()
        
        # Create directories if they don't exist
        self.mods_dir.mkdir(parents=True, exist_ok=True)
        self.zips_dir.mkdir(parents=True, exist_ok=True)
        
        # Track current overlay process
        self.current_overlay_process = None
        
        # Store last injection timing data
        self.last_injection_timing = None
        
        # Check for CSLOL tools
        self._download_cslol_tools()
        
    def _detect_game_dir(self) -> Path:
        """Auto-detect League of Legends Game directory"""
        candidates = [
            Path(r"C:\Riot Games\League of Legends\Game"),
            Path(r"C:\Riot Games\League of Legends"),
            Path(r"C:\Program Files\Riot Games\League of Legends\Game"),
            Path(r"C:\Program Files (x86)\Riot Games\League of Legends\Game"),
        ]

        for c in candidates:
            if c.is_dir():
                exe = c / "League of Legends.exe"
                if exe.exists():
                    if c.name.lower() != "game" and (c / "Game" / "League of Legends.exe").exists():
                        gd = c / "Game"
                        log.info(f"[inject] Auto-detected game directory: {gd}")
                        return gd
                    log.info(f"[inject] Auto-detected game directory: {c}")
                    return c if c.name.lower() == "game" else (c / "Game")

        # Last resort: return default
        gd = Path(r"C:\Riot Games\League of Legends\Game")
        log.info(f"[inject] Using default game directory: {gd}")
        return gd
    
    def _download_cslol_tools(self):
        """Download CSLOL tools if not present"""
        required_tools = [
            "mod-tools.exe",
            "cslol-diag.exe", 
            "cslol-dll.dll",
            "wad-extract.exe",
            "wad-make.exe"
        ]
        
        missing_tools = []
        for tool in required_tools:
            if not (self.tools_dir / tool).exists():
                missing_tools.append(tool)
        
        if missing_tools:
            log.warning(f"Missing CSLOL tools: {missing_tools}")
            log.warning("Please download CSLOL tools manually and place them in injection/tools/")
            log.warning("Download from: https://github.com/CommunityDragon/CDTB")
            return False
        
        return True
    
    def _detect_tools(self) -> Dict[str, Path]:
        """Detect CSLOL tools"""
        tools = {
            "diag": self.tools_dir / "cslol-diag.exe",
            "modtools": self.tools_dir / "mod-tools.exe",
        }
        for name, exe in tools.items():
            if not exe.exists():
                log.error(f"[INJECTOR] Missing tool: {exe}")
        return tools
    
    def _resolve_zip(self, zip_arg: str, chroma_id: int = None, skin_name: str = None) -> Path | None:
        """Resolve a ZIP by name or path with fuzzy matching, supporting chroma subdirectories
        
        Args:
            zip_arg: Skin name or path to search for
            chroma_id: Optional chroma ID to look for in chromas subdirectory
            skin_name: Optional base skin name for chroma lookup
        """
        cand = Path(zip_arg)
        if cand.exists():
            return cand

        self.zips_dir.mkdir(parents=True, exist_ok=True)

        # If chroma_id is provided, look in chromas subdirectory structure
        # Structure: skins/{Champion}/chromas/{SkinName}/{SkinName} {ChromaId}.zip
        if chroma_id is not None and skin_name:
            # Try to find chroma file by ID in subdirectory structure
            chroma_pattern = f"{skin_name} {chroma_id}.zip"
            
            # Search for chroma in subdirectories
            chroma_files = list(self.zips_dir.rglob(f"chromas/*/{chroma_pattern}"))
            if chroma_files:
                log.info(f"[inject] Found chroma by ID: {chroma_files[0]}")
                return chroma_files[0]
            
            # Also try without space
            chroma_pattern_nospace = f"{skin_name}{chroma_id}.zip"
            chroma_files = list(self.zips_dir.rglob(f"chromas/*/{chroma_pattern_nospace}"))
            if chroma_files:
                log.info(f"[inject] Found chroma by ID (no space): {chroma_files[0]}")
                return chroma_files[0]
            
            # Try with normalized skin name
            def _norm(s: str) -> str:
                return "".join(ch.lower() for ch in s if ch.isalnum())
            
            skin_norm = _norm(skin_name)
            
            # Search all chroma directories for files containing the chroma ID
            all_chroma_zips = list(self.zips_dir.rglob("chromas/*/*.zip"))
            for zp in all_chroma_zips:
                # Check if filename contains chroma ID
                if str(chroma_id) in zp.stem:
                    # Verify it's for the right skin by checking directory or filename
                    if skin_norm in _norm(zp.parent.name) or skin_norm in _norm(zp.stem):
                        log.info(f"[inject] Found chroma by ID search: {zp}")
                        return zp
            
            log.warning(f"[inject] Chroma file not found for '{skin_name}' with ID {chroma_id}")
            log.debug(f"[inject] Expected path like: skins/.../chromas/{skin_name}/{skin_name} {chroma_id}.zip")

        def _norm(s: str) -> str:
            return "".join(ch.lower() for ch in s if ch.isalnum())

        target = zip_arg
        target_lower = target.lower()
        target_norm = _norm(target)

        all_zips = list(self.zips_dir.rglob("*.zip"))

        if not all_zips:
            return None

        # 1) exact filename (case-insensitive)
        for zp in all_zips:
            if zp.name.lower() == target_lower:
                return zp

        # 2) exact normalized match
        norm_map = {zp: _norm(zp.name) for zp in all_zips}
        exact_norm = [zp for zp, nz in norm_map.items() if nz == target_norm]
        if len(exact_norm) == 1:
            return exact_norm[0]

        # 3) contains normalized
        contains = [zp for zp, nz in norm_map.items() if target_norm and target_norm in nz]
        if len(contains) == 1:
            return contains[0]

        # 4) fuzzy best match
        try:
            import difflib
            best, best_score = None, 0.0
            for zp, nz in norm_map.items():
                score = difflib.SequenceMatcher(None, nz, target_norm).ratio()
                if target_norm and target_norm in nz:
                    score += 0.15
                if score > best_score:
                    best, best_score = zp, score
            return best
        except Exception:
            return None
    
    def _clean_mods_dir(self):
        """Clean the mods directory"""
        if not self.mods_dir.exists():
            self.mods_dir.mkdir(parents=True, exist_ok=True)
            return
        for p in self.mods_dir.iterdir():
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    p.unlink()
                except Exception:
                    pass
    
    def _clean_overlay_dir(self):
        """Clean the overlay directory to prevent file lock issues"""
        overlay_dir = self.mods_dir.parent / "overlay"
        if overlay_dir.exists():
            try:
                shutil.rmtree(overlay_dir, ignore_errors=True)
                log.debug("[inject] Cleaned overlay directory")
            except Exception as e:
                log.warning(f"[inject] Failed to clean overlay directory: {e}")
        overlay_dir.mkdir(parents=True, exist_ok=True)
    
    def _extract_zip_to_mod(self, zp: Path) -> Path:
        """Extract ZIP to mod directory"""
        target = self.mods_dir / zp.stem
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp, "r") as zf:
            zf.extractall(target)
        log.info(f"[inject] Extracted {zp.name} -> {target}")
        return target
    
    def _mk_run_overlay(self, mod_names: List[str], timeout: int = 60, stop_callback=None, injection_manager=None) -> int:
        """Create and run overlay"""
        tools = self._detect_tools()
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
        cmd = [
            str(exe), "mkoverlay", str(self.mods_dir), str(overlay_dir),
            f"--game:{gpath}", f"--mods:{names_str}", "--noTFT"
        ]
        
        log.debug(f"[inject] Creating overlay: {' '.join(cmd)}")
        mkoverlay_start = time.time()
        try:
            # Hide console window on Windows
            import sys
            creationflags = 0
            if sys.platform == "win32":
                import subprocess
                creationflags = subprocess.CREATE_NO_WINDOW
            
            # Don't capture stdout to avoid pipe buffer deadlock - send to devnull instead
            import os
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
            
            # Boost process priority to maximize CPU contention if enabled
            if ENABLE_PRIORITY_BOOST:
                try:
                    import psutil
                    p = psutil.Process(proc.pid)
                    p.nice(psutil.HIGH_PRIORITY_CLASS)
                    log.debug(f"[inject] Boosted mkoverlay process priority (PID={proc.pid})")
                except Exception as e:
                    log.debug(f"[inject] Could not boost process priority: {e}")
            
            # Wait for process to complete (no stdout to read, so no deadlock)
            proc.wait(timeout=timeout)
            mkoverlay_duration = time.time() - mkoverlay_start
            
            if proc.returncode != 0:
                log.error(f"[inject] mkoverlay failed with return code: {proc.returncode}")
                return proc.returncode
            else:
                log.info(f"[inject] mkoverlay completed in {mkoverlay_duration:.2f}s")
                # Store timing data for external access
                self.last_injection_timing = {
                    'mkoverlay_duration': mkoverlay_duration,
                    'timestamp': time.time()
                }
                
                # DON'T resume game yet - keep it frozen until runoverlay starts
                log.info(f"[inject] mkoverlay done - keeping game frozen until runoverlay starts")
                
        except subprocess.TimeoutExpired:
            log.error("[inject] mkoverlay timeout - monitor will auto-resume if needed")
            return 124
        except Exception as e:
            log.error(f"[inject] mkoverlay error: {e} - monitor will auto-resume if needed")
            return 1

        # Run overlay
        cfg = overlay_dir / "cslol-config.json"
        cmd = [
            str(exe), "runoverlay", str(overlay_dir), str(cfg),
            f"--game:{gpath}", "--opts:configless"
        ]
        
        log.info(f"[inject] Running overlay: {' '.join(cmd)}")
        
        try:
            # Hide console window on Windows
            import sys
            import os
            creationflags = 0
            if sys.platform == "win32":
                import subprocess
                creationflags = subprocess.CREATE_NO_WINDOW
            
            # Don't capture stdout to avoid pipe buffer deadlock - send to devnull instead
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
            
            # Boost process priority to maximize CPU contention if enabled
            if ENABLE_PRIORITY_BOOST:
                try:
                    import psutil
                    p = psutil.Process(proc.pid)
                    p.nice(psutil.HIGH_PRIORITY_CLASS)
                    log.debug(f"[inject] Boosted runoverlay process priority (PID={proc.pid})")
                except Exception as e:
                    log.debug(f"[inject] Could not boost process priority: {e}")
            
            self.current_overlay_process = proc
            
            # Resume game NOW - runoverlay started, game can load while runoverlay hooks in
            if injection_manager:
                log.info("[inject] runoverlay started - resuming game")
                injection_manager.resume_game()
            
            # Monitor process with stop callback
            start_time = time.time()
            runoverlay_hooked = False
            while proc.poll() is None:
                # Check if we should stop (game ended)
                if stop_callback and stop_callback():
                    log.info("[inject] Game ended, stopping overlay process")
                    runoverlay_hooked = True  # Assume it hooked if game ended
                    proc.terminate()
                    try:
                        proc.wait(timeout=PROCESS_TERMINATE_TIMEOUT_S)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    self.current_overlay_process = None
                    return 0  # Success - overlay ran through game
                
                # Check timeout
                if time.time() - start_time > timeout:
                    log.warning(f"[inject] runoverlay timeout after {timeout}s - may not have hooked in time")
                    proc.terminate()
                    try:
                        proc.wait(timeout=PROCESS_TERMINATE_TIMEOUT_S)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    self.current_overlay_process = None
                    return 1  # Timeout = likely failed to hook
                
                time.sleep(PROCESS_MONITOR_SLEEP_S)
            
            # Process completed normally (no stdout captured)
            self.current_overlay_process = None
            if proc.returncode != 0:
                log.error(f"[inject] runoverlay failed with return code: {proc.returncode}")
                return proc.returncode
            else:
                log.debug(f"[inject] runoverlay completed successfully")
                return 0
        except Exception as e:
            log.error(f"[inject] runoverlay error: {e}")
            return 1
    
    def _mk_overlay_only(self, mod_names: List[str], timeout: int = 60) -> int:
        """Create overlay using mkoverlay only (no runoverlay) - for testing"""
        try:
            # Build mkoverlay command
            cmd = [
                str(self.tools_dir / "mod-tools.exe"),
                "mkoverlay",
                str(self.mods_dir),
                str(self.mods_dir.parent / "overlay"),
                f"--game:{self.game_dir}",
                f"--mods:{','.join(mod_names)}",
                "--noTFT"
            ]
            
            log.debug(f"[inject] Creating overlay (mkoverlay only): {' '.join(cmd)}")
            mkoverlay_start = time.time()
            
            # Set creation flags for Windows
            import sys
            import os
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW
            
            try:
                # Don't capture stdout to avoid pipe buffer deadlock - send to devnull instead
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
                proc.wait(timeout=timeout)
                mkoverlay_duration = time.time() - mkoverlay_start
                
                if proc.returncode != 0:
                    log.error(f"[inject] mkoverlay failed with return code: {proc.returncode}")
                    return proc.returncode
                else:
                    log.debug(f"[inject] mkoverlay completed in {mkoverlay_duration:.2f}s")
                    self.last_injection_timing = {
                        'mkoverlay_duration': mkoverlay_duration,
                        'timestamp': time.time()
                    }
                    return 0
                    
            except subprocess.TimeoutExpired:
                log.error(f"[inject] mkoverlay timed out after {timeout}s")
                proc.kill()
                return -1
            except Exception as e:
                log.error(f"[inject] mkoverlay failed with exception: {e}")
                return -1
                
        except Exception as e:
            log.error(f"[inject] Failed to create mkoverlay command: {e}")
            return -1
    
    def inject_skin(self, skin_name: str, timeout: int = 60, stop_callback=None, injection_manager=None, chroma_id: int = None) -> bool:
        """Inject a single skin (with optional chroma)
        
        Args:
            skin_name: Name of skin to inject
            timeout: Timeout for injection process
            stop_callback: Callback to check if injection should stop
            injection_manager: InjectionManager instance to call resume_game()
            chroma_id: Optional chroma ID to inject specific chroma variant
        """
        injection_start_time = time.time()
        
        # Game suspension is now handled entirely by the monitor in InjectionManager
        # No need for a separate GameMonitor thread
        
        # Find the skin ZIP (with chroma support)
        zp = self._resolve_zip(skin_name, chroma_id=chroma_id, skin_name=skin_name)
        if not zp:
            log.error(f"[inject] Skin '{skin_name}' not found in {self.zips_dir}")
            avail = list(self.zips_dir.rglob('*.zip'))
            if avail:
                log.info("[inject] Available skins (first 10):")
                for a in avail[:10]:
                    log.info(f"  - {a.name}")
            return False
        
        log.debug(f"[inject] Using skin file: {zp}")
        
        # Clean mods and overlay directories, then extract new skin
        clean_start = time.time()
        self._clean_mods_dir()
        self._clean_overlay_dir()
        clean_duration = time.time() - clean_start
        log.debug(f"[inject] Directory cleanup took {clean_duration:.2f}s")
        
        extract_start = time.time()
        mod_folder = self._extract_zip_to_mod(zp)
        extract_duration = time.time() - extract_start
        log.debug(f"[inject] ZIP extraction took {extract_duration:.2f}s")
        
        # Create and run overlay
        result = self._mk_run_overlay([mod_folder.name], timeout, stop_callback, injection_manager)
        
        # Get mkoverlay duration from stored timing data
        mkoverlay_duration = self.last_injection_timing.get('mkoverlay_duration', 0.0) if self.last_injection_timing else 0.0
        
        total_duration = time.time() - injection_start_time
        runoverlay_duration = total_duration - clean_duration - extract_duration - mkoverlay_duration
        
        # Log timing breakdown
        if result == 0:
            log.info(f"[inject] Completed in {total_duration:.2f}s (mkoverlay: {mkoverlay_duration:.2f}s, runoverlay: {runoverlay_duration:.2f}s)")
        else:
            log.warning(f"[inject] Failed - timeout or error after {total_duration:.2f}s (mkoverlay: {mkoverlay_duration:.2f}s)")
        
        return result == 0
    
    def inject_skin_for_testing(self, skin_name: str) -> bool:
        """Inject a skin for testing - stops overlay immediately after mkoverlay"""
        try:
            log.debug(f"[inject] Starting test injection for: {skin_name}")
            
            # Find the skin ZIP
            zp = self._resolve_zip(skin_name)
            if not zp:
                log.error(f"[inject] Skin '{skin_name}' not found in {self.zips_dir}")
                return False
            
            log.debug(f"[inject] Using skin file: {zp}")
            
            # Clean and extract
            injection_start_time = time.time()
            self._clean_mods_dir()
            clean_duration = time.time() - injection_start_time
            
            extract_start_time = time.time()
            mod_folder = self._extract_zip_to_mod(zp)
            extract_duration = time.time() - extract_start_time
            
            if not mod_folder:
                log.error(f"[inject] Failed to extract skin: {skin_name}")
                return False
            
            # Run mkoverlay only (no runoverlay)
            result = self._mk_overlay_only([mod_folder.name])
            
            # Get mkoverlay duration from stored timing data
            mkoverlay_duration = self.last_injection_timing.get('mkoverlay_duration', 0.0) if self.last_injection_timing else 0.0
            total_duration = time.time() - injection_start_time
            
            if result == 0:
                log.info(f"[inject] Test injection completed in {total_duration:.2f}s (clean: {clean_duration:.2f}s, extract: {extract_duration:.2f}s, mkoverlay: {mkoverlay_duration:.2f}s)")
                return True
            else:
                log.error(f"[inject] Test injection failed with code: {result}")
                return False
                
        except Exception as e:
            log.error(f"[inject] Test injection failed: {e}")
            return False
    
    def _run_overlay_from_path(self, overlay_path: Path) -> bool:
        """Run overlay from an overlay directory"""
        try:
            log.info(f"[inject] Running overlay from: {overlay_path}")
            
            # Check what's in the overlay directory
            overlay_contents = list(overlay_path.iterdir())
            log.debug(f"[inject] Overlay contents: {[f.name for f in overlay_contents]}")
            
            if not overlay_contents:
                log.error(f"[inject] Overlay directory is empty: {overlay_path}")
                return False
            
            # Copy overlay to the main overlay directory
            main_overlay_dir = self.mods_dir.parent / "overlay"
            
            # Clean main overlay directory
            if main_overlay_dir.exists():
                shutil.rmtree(main_overlay_dir, ignore_errors=True)
            main_overlay_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy overlay contents
            log.debug(f"[inject] Copying from {overlay_path} to {main_overlay_dir}")
            for item in overlay_path.iterdir():
                if item.is_file():
                    shutil.copy2(item, main_overlay_dir / item.name)
                    log.debug(f"[inject] Copied file: {item.name}")
                elif item.is_dir():
                    shutil.copytree(item, main_overlay_dir / item.name)
                    log.debug(f"[inject] Copied directory: {item.name}")
            
            # Log what's in the main overlay directory after copying
            overlay_files = list(main_overlay_dir.iterdir())
            log.debug(f"[inject] Main overlay directory contents: {[f.name for f in overlay_files]}")
            
            # Run overlay using runoverlay command
            tools = self._detect_tools()
            exe = tools.get("modtools")
            if not exe or not exe.exists():
                log.error(f"[INJECTOR] Missing mod-tools.exe in {self.tools_dir}")
                return False
            
            # Create configuration file path
            cfg = main_overlay_dir / "cslol-config.json"
            gpath = str(self.game_dir)
            
            cmd = [
                str(exe), "runoverlay", str(main_overlay_dir), str(cfg),
                f"--game:{gpath}", "--opts:configless"
            ]
            
            log.info(f"[inject] Running overlay: {' '.join(cmd)}")
            
            try:
                # Hide console window on Windows
                import sys
                import os
                creationflags = 0
                if sys.platform == "win32":
                    import subprocess
                    creationflags = subprocess.CREATE_NO_WINDOW
                
                # Don't capture stdout to avoid pipe buffer issues - send to devnull instead
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
                self.current_overlay_process = proc
                
                # For pre-built overlays, we don't need to monitor the process long-term
                # Just start it and let it run in the background
                log.info("[inject] Pre-built overlay process started successfully")
                return True
                
            except Exception as e:
                log.error(f"[inject] Error running overlay process: {e}")
                return False
                
        except Exception as e:
            log.error(f"[inject] Error running pre-built overlay: {e}")
            return False
    
    def clean_system(self) -> bool:
        """Clean the injection system"""
        try:
            if self.mods_dir.exists():
                shutil.rmtree(self.mods_dir, ignore_errors=True)
            overlay_dir = self.mods_dir.parent / "overlay"
            if overlay_dir.exists():
                shutil.rmtree(overlay_dir, ignore_errors=True)
            log.debug("[inject] System cleaned successfully")
            return True
        except Exception as e:
            log.error(f"[inject] Failed to clean system: {e}")
            return False
    
    def stop_overlay_process(self):
        """Stop the current overlay process"""
        if self.current_overlay_process and self.current_overlay_process.poll() is None:
            try:
                log.info("[inject] Stopping current overlay process")
                self.current_overlay_process.terminate()
                try:
                    self.current_overlay_process.wait(timeout=PROCESS_TERMINATE_TIMEOUT_S)
                except subprocess.TimeoutExpired:
                    self.current_overlay_process.kill()
                    self.current_overlay_process.wait()
                self.current_overlay_process = None
                log.info("[inject] Overlay process stopped successfully")
            except Exception as e:
                log.warning(f"[inject] Failed to stop overlay process: {e}")
        else:
            log.debug("[inject] No active overlay process to stop")
    
    def kill_all_runoverlay_processes(self):
        """Kill all runoverlay processes (for ChampSelect cleanup)"""
        import psutil
        import signal
        killed_count = 0
        
        try:
            # Find all processes with "runoverlay" in command line
            # Use a timeout to prevent hanging on process_iter
            start_time = time.time()
            timeout = 2.0  # 2 second timeout for process enumeration
            
            # Only get pid and name initially to avoid slow cmdline lookups
            for proc in psutil.process_iter(['pid', 'name']):
                # Check timeout to prevent indefinite hangs
                if time.time() - start_time > timeout:
                    log.warning(f"[inject] Process enumeration timeout after {timeout}s - some processes may not be killed")
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
                            log.info(f"[inject] Killing runoverlay process PID {proc.info['pid']}")
                            try:
                                # Try graceful termination first
                                p.terminate()
                                # Give it a brief moment, then force kill if needed
                                try:
                                    p.wait(timeout=0.3)
                                except:
                                    p.kill()  # Force kill if terminate didn't work
                            except:
                                try:
                                    p.kill()  # Force kill on any error
                                except:
                                    pass  # Process might be gone
                            killed_count += 1
                    except psutil.TimeoutExpired:
                        log.debug(f"[inject] Timeout fetching cmdline for PID {proc.info['pid']}")
                        continue
                    
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # Process might have already ended or we don't have access
                    pass
                except Exception as e:
                    # Log but continue with other processes
                    log.debug(f"[inject] Error processing PID {proc.info.get('pid', '?')}: {e}")
            
            if killed_count > 0:
                log.info(f"[inject] Killed {killed_count} runoverlay process(es)")
            else:
                log.debug("[inject] No runoverlay processes found to kill")
                
        except Exception as e:
            log.warning(f"[inject] Failed to kill runoverlay processes: {e}")
        
        # Also stop our tracked process if it exists
        self.stop_overlay_process()