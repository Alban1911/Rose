#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSLOL Skin Injector
Handles the actual skin injection using CSLOL tools
"""

import subprocess
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

        # Create overlay
        cmd = [
            str(exe), "mkoverlay", str(self.mods_dir), str(overlay_dir),
            f"--game:{gpath}", f"--mods:{names_str}", "--noTFT"
        ]
        
        log.info(f"Injector: Creating overlay: {' '.join(cmd)}")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            stdout, _ = proc.communicate(timeout=timeout)
            if proc.returncode != 0:
                log.error(f"Injector: mkoverlay failed: {stdout}")
                return proc.returncode
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
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.current_overlay_process = proc
            
            # Monitor process with stop callback
            import time
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
    
    def inject_skin(self, skin_name: str, timeout: int = 60, stop_callback=None) -> bool:
        """Inject a single skin"""
        log.info(f"Injector: Starting injection for: {skin_name}")
        
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
        self._clean_mods_dir()
        self._clean_overlay_dir()
        mod_folder = self._extract_zip_to_mod(zp)
        
        # Create and run overlay
        result = self._mk_run_overlay([mod_folder.name], timeout, stop_callback)
        return result == 0
    
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
