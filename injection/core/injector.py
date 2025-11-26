#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSLOL Skin Injector
Handles the actual skin injection using CSLOL tools
"""

import sys
import time
import shutil
from pathlib import Path
from typing import List, Optional

from utils.core.logging import get_logger, log_action, log_success
from utils.core.paths import get_skins_dir, get_injection_dir

from ..config.config_manager import ConfigManager
from ..game.game_detector import GameDetector
from ..tools.tools_manager import ToolsManager
from ..mods.zip_resolver import ZipResolver
from ..mods.mod_manager import ModManager
from ..overlay.overlay_manager import OverlayManager
from ..overlay.process_manager import ProcessManager

log = get_logger()


class SkinInjector:
    """CSLOL-based skin injector"""
    
    def __init__(self, tools_dir: Path = None, mods_dir: Path = None, zips_dir: Path = None, game_dir: Optional[Path] = None):
        # Use injection folder as base if paths not provided
        # Handle both frozen (PyInstaller) and development environments
        if getattr(sys, 'frozen', False):
            # Running as compiled executable (PyInstaller)
            # Handle both onefile (_MEIPASS) and onedir (_internal) modes
            if hasattr(sys, '_MEIPASS'):
                # One-file mode: tools are in _MEIPASS (temporary extraction directory)
                base_path = Path(sys._MEIPASS)
                injection_dir = base_path / "injection"
                log.debug(f"Found injection directory at: {injection_dir} (onefile mode)")
            else:
                # One-dir mode: tools are alongside executable
                base_dir = Path(sys.executable).parent
                
                # Check multiple locations for injection tools (PyInstaller can place them in different spots)
                possible_injection_dirs = [
                    base_dir / "injection",  # Direct path
                    base_dir / "_internal" / "injection",  # _internal folder
                ]
                
                injection_dir = None
                for dir_path in possible_injection_dirs:
                    if dir_path.exists():
                        injection_dir = dir_path
                        log.debug(f"Found injection directory at: {injection_dir}")
                        break
                
                if not injection_dir:
                    # Fallback to first option if neither exists
                    injection_dir = possible_injection_dirs[0]
                    log.warning(f"Injection directory not found, using default: {injection_dir}")
        else:
            # Running as Python script
            injection_dir = Path(__file__).parent.parent
        
        # If tools_dir is provided, use it
        if tools_dir:
            self.tools_dir = tools_dir
        else:
            self.tools_dir = injection_dir / "tools"
        
        # Use user data directory for mods and skins to avoid permission issues
        self.mods_dir = mods_dir or get_injection_dir() / "mods"
        self.zips_dir = zips_dir or get_skins_dir()
        
        # Initialize managers
        self.config_manager = ConfigManager()
        self.game_detector = GameDetector(self.config_manager)
        
        # Only detect if game_dir not provided - never use invalid fallback paths
        if game_dir is not None:
            self.game_dir = game_dir
        else:
            self.game_dir = self.game_detector.detect_game_dir()
        
        # Create directories if they don't exist
        self.mods_dir.mkdir(parents=True, exist_ok=True)
        self.zips_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize managers
        self.tools_manager = ToolsManager(self.tools_dir)
        self.zip_resolver = ZipResolver(self.zips_dir)
        self.mod_manager = ModManager(self.mods_dir)
        self.process_manager = ProcessManager()
        # Pass process_manager to overlay_manager so they share the process reference
        self.overlay_manager = OverlayManager(self.tools_dir, self.mods_dir, self.game_dir, self.process_manager)
        
        # Store last injection timing data
        self.last_injection_timing = None
        
        # Check for CSLOL tools
        self.tools_manager.check_tools_available()
    
    def _resolve_zip(self, zip_arg: str, chroma_id: int = None, skin_name: str = None, champion_name: str = None, champion_id: int = None) -> Optional[Path]:
        """Resolve a ZIP by name or path with fuzzy matching"""
        return self.zip_resolver.resolve_zip(zip_arg, chroma_id, skin_name, champion_name, champion_id)
    
    def _clean_mods_dir(self):
        """Clean the mods directory"""
        self.mod_manager.clean_mods_dir()
    
    def _clean_overlay_dir(self):
        """Clean the overlay directory to prevent file lock issues"""
        self.mod_manager.clean_overlay_dir()
    
    def _extract_zip_to_mod(self, zp: Path) -> Path:
        """Extract ZIP to mod directory"""
        return self.mod_manager.extract_zip_to_mod(zp)
    
    def _mk_run_overlay(self, mod_names: List[str], timeout: int = 120, stop_callback=None, injection_manager=None) -> int:
        """Create and run overlay"""
        result = self.overlay_manager.mk_run_overlay(mod_names, timeout, stop_callback, injection_manager)
        # Sync timing data
        self.last_injection_timing = self.overlay_manager.last_injection_timing
        return result
    
    def _mk_overlay_only(self, mod_names: List[str], timeout: int = 60) -> int:
        """Create overlay using mkoverlay only (no runoverlay) - for testing"""
        result = self.overlay_manager.mk_overlay_only(mod_names, timeout)
        # Sync timing data
        self.last_injection_timing = self.overlay_manager.last_injection_timing
        return result
    
    def inject_skin(self, skin_name: str, timeout: int = 120, stop_callback=None, injection_manager=None, chroma_id: int = None, champion_name: str = None, champion_id: int = None) -> bool:
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
        # Extract base skin name (remove skin ID if present) for chroma path construction
        base_skin_name = skin_name
        if skin_name and skin_name.split()[-1].isdigit():
            base_skin_name = ' '.join(skin_name.split()[:-1])
        
        zp = self._resolve_zip(skin_name, chroma_id=chroma_id, skin_name=base_skin_name, champion_name=champion_name, champion_id=champion_id)
        if not zp:
            log.error(f"[INJECT] Skin '{skin_name}' not found in {self.zips_dir}")
            avail_zip = list(self.zips_dir.rglob('*.zip'))
            avail_fantome = list(self.zips_dir.rglob('*.fantome'))
            avail = avail_zip + avail_fantome
            if avail:
                log.info("[INJECT] Available skins (first 10):")
                for a in avail[:10]:
                    log.info(f"  - {a.name}")
            return False
        
        log.debug(f"[INJECT] Using skin file: {zp}")
        
        # Clean mods and overlay directories, then extract new skin
        clean_start = time.time()
        self._clean_mods_dir()
        self._clean_overlay_dir()
        clean_duration = time.time() - clean_start
        log.debug(f"[INJECT] Directory cleanup took {clean_duration:.2f}s")
        
        extract_start = time.time()
        mod_folder = self._extract_zip_to_mod(zp)
        extract_duration = time.time() - extract_start
        log.debug(f"[INJECT] ZIP extraction took {extract_duration:.2f}s")
        
        # Create list of mods to inject (skin only)
        mod_names = [mod_folder.name]
        
        # Create and run overlay
        result = self._mk_run_overlay(mod_names, timeout, stop_callback, injection_manager)
        
        # Get mkoverlay duration from stored timing data
        mkoverlay_duration = self.last_injection_timing.get('mkoverlay_duration', 0.0) if self.last_injection_timing else 0.0
        
        total_duration = time.time() - injection_start_time
        runoverlay_duration = total_duration - clean_duration - extract_duration - mkoverlay_duration
        
        # Log timing breakdown
        if result == 0:
            log.info(f"[INJECT] Completed in {total_duration:.2f}s (mkoverlay: {mkoverlay_duration:.2f}s, runoverlay: {runoverlay_duration:.2f}s)")
        else:
            log.warning(f"[INJECT] Failed - timeout or error after {total_duration:.2f}s (mkoverlay: {mkoverlay_duration:.2f}s)")
        
        return result == 0
    
    def inject_mods_only(self, timeout: int = 60, stop_callback=None, injection_manager=None) -> bool:
        """Disabled: installed mods folder removed"""
        log.warning("[INJECT] Mods-only injection is disabled (installed mods folder removed)")
        return False
    
    def inject_skin_for_testing(self, skin_name: str) -> bool:
        """Inject a skin for testing - stops overlay immediately after mkoverlay"""
        try:
            log.debug(f"[INJECT] Starting test injection for: {skin_name}")
            
            # Find the skin ZIP
            zp = self._resolve_zip(skin_name)
            if not zp:
                log.error(f"[INJECT] Skin '{skin_name}' not found in {self.zips_dir}")
                return False
            
            log.debug(f"[INJECT] Using skin file: {zp}")
            
            # Clean and extract
            injection_start_time = time.time()
            self._clean_mods_dir()
            clean_duration = time.time() - injection_start_time
            
            extract_start_time = time.time()
            mod_folder = self._extract_zip_to_mod(zp)
            extract_duration = time.time() - extract_start_time
            
            if not mod_folder:
                log.error(f"[INJECT] Failed to extract skin: {skin_name}")
                return False
            
            # Run mkoverlay only (no runoverlay)
            result = self._mk_overlay_only([mod_folder.name])
            
            # Get mkoverlay duration from stored timing data
            mkoverlay_duration = self.last_injection_timing.get('mkoverlay_duration', 0.0) if self.last_injection_timing else 0.0
            total_duration = time.time() - injection_start_time
            
            if result == 0:
                log.info(f"[INJECT] Test injection completed in {total_duration:.2f}s (clean: {clean_duration:.2f}s, extract: {extract_duration:.2f}s, mkoverlay: {mkoverlay_duration:.2f}s)")
                return True
            else:
                log.error(f"[INJECT] Test injection failed with code: {result}")
                return False
                
        except Exception as e:
            log.error(f"[INJECT] Test injection failed: {e}")
            return False
    
    def _run_overlay_from_path(self, overlay_path: Path) -> bool:
        """Run overlay from an overlay directory"""
        return self.overlay_manager.run_overlay_from_path(overlay_path)
    
    def clean_system(self) -> bool:
        """Clean the injection system"""
        try:
            if self.mods_dir.exists():
                shutil.rmtree(self.mods_dir, ignore_errors=True)
            overlay_dir = self.mods_dir.parent / "overlay"
            if overlay_dir.exists():
                shutil.rmtree(overlay_dir, ignore_errors=True)
            log.debug("[INJECT] System cleaned successfully")
            return True
        except Exception as e:
            log.error(f"[INJECT] Failed to clean system: {e}")
            return False
    
    def stop_overlay_process(self):
        """Stop the current overlay process"""
        # Since they share the same reference, stopping via process_manager updates both
        self.process_manager.stop_overlay_process()
    
    def kill_all_runoverlay_processes(self):
        """Kill all runoverlay processes (for ChampSelect cleanup)"""
        self.process_manager.kill_all_runoverlay_processes()
