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
                        log.info(f"Injector: Auto-detected game directory: {gd}")
                        return gd
                    log.info(f"Injector: Auto-detected game directory: {c}")
                    return c if c.name.lower() == "game" else (c / "Game")

        # Last resort: return default
        gd = Path(r"C:\Riot Games\League of Legends\Game")
        log.info(f"Injector: Using default game directory: {gd}")
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
    
    def _resolve_zip(self, zip_arg: str) -> Path | None:
        """Resolve a ZIP by name or path with fuzzy matching"""
        cand = Path(zip_arg)
        if cand.exists():
            return cand

        self.zips_dir.mkdir(parents=True, exist_ok=True)

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
                log.debug("Injector: Cleaned overlay directory")
            except Exception as e:
                log.warning(f"Injector: Failed to clean overlay directory: {e}")
        overlay_dir.mkdir(parents=True, exist_ok=True)
    
    def _extract_zip_to_mod(self, zp: Path) -> Path:
        """Extract ZIP to mod directory"""
        target = self.mods_dir / zp.stem
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp, "r") as zf:
            zf.extractall(target)
        log.info(f"Injector: Extracted {zp.name} -> {target}")
        return target
    
    def _mk_run_overlay(self, mod_names: List[str], timeout: int = 60, stop_callback=None) -> int:
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
        
        log.info(f"Injector: Creating overlay: {' '.join(cmd)}")
        mkoverlay_start = time.time()
        try:
            # Hide console window on Windows
            import sys
            creationflags = 0
            if sys.platform == "win32":
                import subprocess
                creationflags = subprocess.CREATE_NO_WINDOW
            
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=creationflags)
            stdout, _ = proc.communicate(timeout=timeout)
            mkoverlay_duration = time.time() - mkoverlay_start
            
            if proc.returncode != 0:
                log.error(f"Injector: mkoverlay failed: {stdout}")
                return proc.returncode
            else:
                log.info(f"Injector: mkoverlay completed in {mkoverlay_duration:.2f}s - injection applied, game can start")
                # Store timing data for external access
                self.last_injection_timing = {
                    'mkoverlay_duration': mkoverlay_duration,
                    'timestamp': time.time()
                }
        except subprocess.TimeoutExpired:
            log.error("Injector: mkoverlay timeout")
            return 124
        except Exception as e:
            log.error(f"Injector: mkoverlay error: {e}")
            return 1

        # Run overlay
        cfg = overlay_dir / "cslol-config.json"
        cmd = [
            str(exe), "runoverlay", str(overlay_dir), str(cfg),
            f"--game:{gpath}", "--opts:configless"
        ]
        
        log.info(f"Injector: Running overlay: {' '.join(cmd)}")
        
        try:
            # Hide console window on Windows
            import sys
            creationflags = 0
            if sys.platform == "win32":
                import subprocess
                creationflags = subprocess.CREATE_NO_WINDOW
            
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=creationflags)
            self.current_overlay_process = proc
            
            # Monitor process with stop callback
            start_time = time.time()
            while proc.poll() is None:
                # Check if we should stop (game ended)
                if stop_callback and stop_callback():
                    log.info("Injector: Terminating overlay process")
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    self.current_overlay_process = None
                    return 0  # Return success since injection was applied
                
                # Check timeout
                if time.time() - start_time > timeout:
                    log.warning("Injector: Overlay timeout, but injection may have succeeded")
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    self.current_overlay_process = None
                    return 0  # Return success since injection was likely applied
                
                time.sleep(0.5)
            
            # Process completed normally
            stdout, _ = proc.communicate()
            self.current_overlay_process = None
            if proc.returncode != 0:
                log.error(f"Injector: runoverlay failed: {stdout}")
                return proc.returncode
            else:
                log.info(f"Injector: Injection successful: {mod_names}")
                return 0
        except Exception as e:
            log.error(f"Injector: runoverlay error: {e}")
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
            
            log.info(f"Injector: Creating overlay (mkoverlay only): {' '.join(cmd)}")
            mkoverlay_start = time.time()
            
            # Set creation flags for Windows
            import sys
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW
            
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=creationflags)
                stdout, _ = proc.communicate(timeout=timeout)
                mkoverlay_duration = time.time() - mkoverlay_start
                
                if proc.returncode != 0:
                    log.error(f"Injector: mkoverlay failed: {stdout}")
                    return proc.returncode
                else:
                    log.info(f"Injector: mkoverlay completed in {mkoverlay_duration:.2f}s - injection applied, game can start")
                    self.last_injection_timing = {
                        'mkoverlay_duration': mkoverlay_duration,
                        'timestamp': time.time()
                    }
                    return 0
                    
            except subprocess.TimeoutExpired:
                log.error(f"Injector: mkoverlay timed out after {timeout}s")
                proc.kill()
                return -1
            except Exception as e:
                log.error(f"Injector: mkoverlay failed with exception: {e}")
                return -1
                
        except Exception as e:
            log.error(f"Injector: Failed to create mkoverlay command: {e}")
            return -1
    
    def inject_skin(self, skin_name: str, timeout: int = 60, stop_callback=None) -> bool:
        """Inject a single skin"""
        log.info(f"Injector: Starting injection for: {skin_name}")
        injection_start_time = time.time()
        
        # Find the skin ZIP
        zp = self._resolve_zip(skin_name)
        if not zp:
            log.error(f"Injector: Skin '{skin_name}' not found in {self.zips_dir}")
            avail = list(self.zips_dir.rglob('*.zip'))
            if avail:
                log.info("Injector: Available skins (first 10):")
                for a in avail[:10]:
                    log.info(f"  - {a.name}")
            return False
        
        log.info(f"Injector: Using skin file: {zp}")
        
        # Clean mods and overlay directories, then extract new skin
        clean_start = time.time()
        self._clean_mods_dir()
        self._clean_overlay_dir()
        clean_duration = time.time() - clean_start
        log.debug(f"Injector: Directory cleanup took {clean_duration:.2f}s")
        
        extract_start = time.time()
        mod_folder = self._extract_zip_to_mod(zp)
        extract_duration = time.time() - extract_start
        log.debug(f"Injector: ZIP extraction took {extract_duration:.2f}s")
        
        # Create and run overlay
        injection_work_start = time.time()
        result = self._mk_run_overlay([mod_folder.name], timeout, stop_callback)
        
        # Calculate injection work duration (up to mkoverlay completion, not including runoverlay runtime)
        injection_work_duration = time.time() - injection_work_start
        
        total_duration = time.time() - injection_start_time
        log.info(f"Injector: Injection work completed in {injection_work_duration:.2f}s (clean: {clean_duration:.2f}s, extract: {extract_duration:.2f}s, mkoverlay: {injection_work_duration:.2f}s)")
        log.debug(f"Injector: Total process time: {total_duration:.2f}s (includes runoverlay runtime)")
        
        return result == 0
    
    def inject_skin_for_testing(self, skin_name: str) -> bool:
        """Inject a skin for testing - stops overlay immediately after mkoverlay"""
        try:
            log.info(f"Injector: Starting test injection for: {skin_name}")
            
            # Find the skin ZIP
            zp = self._resolve_zip(skin_name)
            if not zp:
                log.error(f"Injector: Skin '{skin_name}' not found in {self.zips_dir}")
                return False
            
            log.info(f"Injector: Using skin file: {zp}")
            
            # Clean and extract
            injection_start_time = time.time()
            self._clean_mods_dir()
            clean_duration = time.time() - injection_start_time
            
            extract_start_time = time.time()
            mod_folder = self._extract_zip_to_mod(zp)
            extract_duration = time.time() - extract_start_time
            
            if not mod_folder:
                log.error(f"Injector: Failed to extract skin: {skin_name}")
                return False
            
            # Run mkoverlay only (no runoverlay)
            injection_work_start = time.time()
            result = self._mk_overlay_only([mod_folder.name])
            injection_work_duration = time.time() - injection_work_start
            
            total_duration = time.time() - injection_start_time
            
            if result == 0:
                log.info(f"Injector: Test injection successful: ['{skin_name}']")
                log.info(f"Injector: Test injection work completed in {injection_work_duration:.2f}s (clean: {clean_duration:.2f}s, extract: {extract_duration:.2f}s, mkoverlay: {injection_work_duration:.2f}s)")
                log.debug(f"Injector: Total process time: {total_duration:.2f}s")
                return True
            else:
                log.error(f"Injector: Test injection failed with code: {result}")
                return False
                
        except Exception as e:
            log.error(f"Injector: Test injection failed: {e}")
            return False
    
    def _run_overlay_from_path(self, overlay_path: Path) -> bool:
        """Run overlay from a pre-built overlay directory"""
        try:
            log.info(f"Injector: Running pre-built overlay from: {overlay_path}")
            
            # Check what's in the pre-built overlay directory
            prebuilt_contents = list(overlay_path.iterdir())
            log.debug(f"Injector: Pre-built overlay contents: {[f.name for f in prebuilt_contents]}")
            
            if not prebuilt_contents:
                log.error(f"Injector: Pre-built overlay directory is empty: {overlay_path}")
                return False
            
            # Copy pre-built overlay to the main overlay directory
            main_overlay_dir = self.mods_dir.parent / "overlay"
            
            # Clean main overlay directory
            if main_overlay_dir.exists():
                shutil.rmtree(main_overlay_dir, ignore_errors=True)
            main_overlay_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy pre-built overlay contents
            log.debug(f"Injector: Copying from {overlay_path} to {main_overlay_dir}")
            for item in overlay_path.iterdir():
                if item.is_file():
                    shutil.copy2(item, main_overlay_dir / item.name)
                    log.debug(f"Injector: Copied file: {item.name}")
                elif item.is_dir():
                    shutil.copytree(item, main_overlay_dir / item.name)
                    log.debug(f"Injector: Copied directory: {item.name}")
            
            # Log what's in the main overlay directory after copying
            overlay_files = list(main_overlay_dir.iterdir())
            log.debug(f"Injector: Main overlay directory contents: {[f.name for f in overlay_files]}")
            
            # For pre-built overlays, we don't need to run runoverlay
            # The overlay files are already created and ready to use
            # The game will automatically pick them up when it starts
            log.info("Injector: Pre-built overlay files copied successfully - ready for game")
            return True
                
        except Exception as e:
            log.error(f"Injector: Error running pre-built overlay: {e}")
            return False
    
    def clean_system(self) -> bool:
        """Clean the injection system"""
        try:
            if self.mods_dir.exists():
                shutil.rmtree(self.mods_dir, ignore_errors=True)
            overlay_dir = self.mods_dir.parent / "overlay"
            if overlay_dir.exists():
                shutil.rmtree(overlay_dir, ignore_errors=True)
            log.debug("Injector: System cleaned successfully")
            return True
        except Exception as e:
            log.error(f"Injector: Failed to clean system: {e}")
            return False
    
    def stop_overlay_process(self):
        """Stop the current overlay process"""
        if self.current_overlay_process and self.current_overlay_process.poll() is None:
            try:
                log.info("Injector: Stopping current overlay process")
                self.current_overlay_process.terminate()
                try:
                    self.current_overlay_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.current_overlay_process.kill()
                    self.current_overlay_process.wait()
                self.current_overlay_process = None
                log.info("Injector: Overlay process stopped successfully")
            except Exception as e:
                log.warning(f"Injector: Failed to stop overlay process: {e}")
        else:
            log.debug("Injector: No active overlay process to stop")
    
    def kill_all_runoverlay_processes(self):
        """Kill all runoverlay processes (for ChampSelect cleanup)"""
        import psutil
        killed_count = 0
        
        try:
            # Find all processes with "runoverlay" in command line
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.info.get('cmdline', [])
                    if cmdline and any('runoverlay' in arg for arg in cmdline):
                        log.info(f"Injector: Killing runoverlay process PID {proc.info['pid']}")
                        proc.kill()
                        killed_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # Process might have already ended or we don't have access
                    pass
            
            if killed_count > 0:
                log.info(f"Injector: Killed {killed_count} runoverlay process(es)")
            else:
                log.debug("Injector: No runoverlay processes found to kill")
                
        except Exception as e:
            log.warning(f"Injector: Failed to kill runoverlay processes: {e}")
        
        # Also stop our tracked process if it exists
        self.stop_overlay_process()