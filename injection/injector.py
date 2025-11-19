#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSLOL Skin Injector
Handles the actual skin injection using CSLOL tools
"""

import subprocess
import time
import configparser
from pathlib import Path
from typing import List, Dict, Optional
import zipfile
import shutil

# Import psutil with fallback for development environments
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

from utils.logging import get_logger, log_action, log_success, log_event
from utils.paths import get_skins_dir, get_injection_dir
from config import (
    PROCESS_TERMINATE_TIMEOUT_S, 
    PROCESS_TERMINATE_WAIT_S,
    PROCESS_ENUM_TIMEOUT_S,
    PROCESS_MONITOR_SLEEP_S, 
    ENABLE_PRIORITY_BOOST
)

log = get_logger()


class SkinInjector:
    """CSLOL-based skin injector"""
    
    def __init__(self, tools_dir: Path = None, mods_dir: Path = None, zips_dir: Path = None, game_dir: Optional[Path] = None):
        # Use injection folder as base if paths not provided
        # Handle both frozen (PyInstaller) and development environments
        import sys
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
            injection_dir = Path(__file__).parent
        
        # If tools_dir is provided, use it
        if tools_dir:
            self.tools_dir = tools_dir
        else:
            # Use default "tools" folder
            self.tools_dir = injection_dir / "tools"
        # Use user data directory for mods and skins to avoid permission issues
        self.mods_dir = mods_dir or get_injection_dir() / "mods"
        self.zips_dir = zips_dir or get_skins_dir()
        # Only detect if game_dir not provided - never use invalid fallback paths
        if game_dir is not None:
            self.game_dir = game_dir
        else:
            self.game_dir = self._detect_game_dir()
        # Database no longer needed - LCU provides all data
        
        # Create directories if they don't exist
        self.mods_dir.mkdir(parents=True, exist_ok=True)
        self.zips_dir.mkdir(parents=True, exist_ok=True)
        
        # Track current overlay process
        self.current_overlay_process = None
        
        # Store last injection timing data
        self.last_injection_timing = None
        
        # Check for CSLOL tools
        self._download_cslol_tools()
        
    def _get_config_path(self) -> Path:
        """Get the path to the config.ini file"""
        from config import get_config_file_path

        return get_config_file_path()
    
    def _load_config(self) -> Optional[str]:
        """Load League path from config.ini file"""
        config_path = self._get_config_path()
        if not config_path.exists():
            log.debug("Config file not found, will create one")
            return None
        
        try:
            config = configparser.ConfigParser()
            config.read(config_path)
            if 'General' in config and 'leaguePath' in config['General']:
                league_path = config['General']['leaguePath']
                log.debug(f"Loaded League path from config: {league_path}")
                return league_path
        except Exception as e:
            log.warning(f"Failed to read config file: {e}")
        
        return None
    
    def _save_config(self, league_path: str):
        """Save League path to config.ini file"""
        config_path = self._get_config_path()
        try:
            config = configparser.ConfigParser()
            
            # Load existing config if it exists
            if config_path.exists():
                config.read(config_path)
            
            # Ensure General section exists
            if 'General' not in config:
                config.add_section('General')
            
            # Set the League path
            config.set('General', 'leaguePath', league_path)
            
            # Write to file
            with open(config_path, 'w') as f:
                config.write(f)
            
            log.debug(f"Saved League path to config: {league_path}")
        except Exception as e:
            log.warning(f"Failed to save config file: {e}")
    
    def _detect_game_dir(self) -> Optional[Path]:
        """Auto-detect League of Legends Game directory using config and LeagueClient.exe detection.
        Returns None if game directory cannot be found - never saves invalid paths to config."""
        
        # First, try to load from config
        config_path = self._load_config()
        if config_path:
            config_game_dir = Path(config_path)
            if config_game_dir.exists() and (config_game_dir / "League of Legends.exe").exists():
                log_success(log, f"Using League path from config: {config_game_dir}", "📂")
                return config_game_dir
            else:
                log.warning(f"Config League path is invalid: {config_path}")
        
        # If no valid config, try to detect via LeagueClient.exe
        log.debug("Config not found or invalid, detecting via LeagueClient.exe")
        detected_path = self._detect_via_leagueclient()
        if detected_path:
            # Save the detected path to config only if we actually found a valid path
            self._save_config(str(detected_path))
            return detected_path
        
        # No fallbacks - if we can't detect it, return None
        log.warning("Could not detect League of Legends game directory. Please ensure League Client is running or manually set the path in config.ini")
        return None
    
    def _detect_via_leagueclient(self) -> Optional[Path]:
        """Detect League path by finding running LeagueClient.exe process"""
        if not PSUTIL_AVAILABLE:
            log.debug("psutil not available, skipping LeagueClient.exe detection")
            return None
            
        try:
            log.debug("Looking for LeagueClient.exe process...")
            
            # Find LeagueClient.exe process
            for proc in psutil.process_iter(['pid', 'name', 'exe']):
                try:
                    if proc.info['name'] == 'LeagueClient.exe':
                        exe_path = proc.info['exe']
                        if exe_path:
                            log.debug(f"Found LeagueClient.exe at: {exe_path}")
                            
                            # Convert to Path and get parent directory
                            client_path = Path(exe_path)
                            client_dir = client_path.parent
                            
                            # League should be in the same directory + "Game" subdirectory
                            league_dir = client_dir / "Game"
                            league_exe = league_dir / "League of Legends.exe"
                            
                            log.debug(f"Checking for League at: {league_exe}")
                            if league_exe.exists():
                                log_success(log, f"Found League via LeagueClient.exe: {league_dir}", "📂")
                                return league_dir
                            else:
                                log.debug(f"League not found at expected location: {league_exe}")
                                
                                # Try parent directory structure (for different installers)
                                parent_dir = client_dir.parent
                                parent_league_dir = parent_dir / "League of Legends" / "Game"
                                parent_league_exe = parent_league_dir / "League of Legends.exe"
                                
                                log.debug(f"Trying parent directory structure: {parent_league_exe}")
                                if parent_league_exe.exists():
                                    log_success(log, f"Found League via parent directory: {parent_league_dir}", "📂")
                                    return parent_league_dir
                                
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            
            log.debug("No LeagueClient.exe process found")
            return None
            
        except Exception as e:
            log.warning(f"Error detecting via LeagueClient.exe: {e}")
            return None
    
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
    
    def _resolve_zip(self, zip_arg: str, chroma_id: int = None, skin_name: str = None, champion_name: str = None, champion_id: int = None) -> Path | None:
        """Resolve a ZIP by name or path with fuzzy matching, supporting new merged structure
        
        Args:
            zip_arg: Skin name or path to search for
            chroma_id: Optional chroma ID to look for in chroma subdirectory
            skin_name: Optional base skin name for chroma lookup
            champion_id: Optional champion ID for path construction.
        """
        log.debug(f"[inject] Resolving zip for: '{zip_arg}' (chroma_id: {chroma_id}, skin_name: {skin_name})")
        cand = Path(zip_arg)
        if cand.exists():
            return cand

        self.zips_dir.mkdir(parents=True, exist_ok=True)

        # Handle ID-based naming convention from random selection
        if zip_arg.startswith('skin_'):
            # Format: skin_{skin_id} - check if this is actually a chroma
            skin_id = int(zip_arg.split('_')[1])
            if not champion_id:
                log.warning(f"[inject] No champion_id provided for skin ID: {skin_id}")
                return None
            
            # If chroma_id is provided, this is actually a chroma (Swiftplay case)
            if chroma_id is not None:
                # Look for chroma: {champion_id}/{base_skin_id}/{chroma_id}/{chroma_id}.zip
                champion_dir = self.zips_dir / str(champion_id)
                if not champion_dir.exists():
                    log.warning(f"[inject] Champion directory not found: {champion_dir}")
                    return None
                
                # Search through all skin directories for this champion to find the chroma
                for skin_dir in champion_dir.iterdir():
                    if not skin_dir.is_dir():
                        continue
                    
                    try:
                        base_skin_id = int(skin_dir.name)
                    except ValueError:
                        continue
                    
                    # Look for chroma in this skin's chroma directory
                    chroma_dir = skin_dir / str(chroma_id)
                    if chroma_dir.exists():
                        chroma_zip_path = chroma_dir / f"{chroma_id}.zip"
                        if chroma_zip_path.exists():
                            log.debug(f"[inject] Found chroma ZIP: {chroma_zip_path}")
                            return chroma_zip_path
                
                log.warning(f"[inject] Chroma ZIP not found for ID: {chroma_id}")
                return None
            
            # This is a base skin - Look for {champion_id}/{skin_id}/{skin_id}.zip
            skin_zip_path = self.zips_dir / str(champion_id) / str(skin_id) / f"{skin_id}.zip"
            if skin_zip_path.exists():
                log.debug(f"[inject] Found skin ZIP: {skin_zip_path}")
                return skin_zip_path
            else:
                # Not found as base skin - might be a chroma that was incorrectly labeled as skin_
                # Try searching for it as a chroma in any base skin directory
                log.debug(f"[inject] Base skin not found, checking if {skin_id} is a chroma...")
                champion_dir = self.zips_dir / str(champion_id)
                if champion_dir.exists():
                    for skin_dir in champion_dir.iterdir():
                        if not skin_dir.is_dir():
                            continue
                        try:
                            base_skin_id = int(skin_dir.name)
                        except ValueError:
                            continue
                        
                        # Look for chroma in this skin's chroma directory
                        chroma_dir = skin_dir / str(skin_id)
                        if chroma_dir.exists():
                            chroma_zip_path = chroma_dir / f"{skin_id}.zip"
                            if chroma_zip_path.exists():
                                log.debug(f"[inject] Found chroma ZIP (mislabeled as skin_): {chroma_zip_path}")
                                return chroma_zip_path
                
                log.warning(f"[inject] Skin ZIP not found: {skin_zip_path}")
                return None
        
        elif zip_arg.startswith('chroma_'):
            # Format: chroma_{chroma_id} - this is a chroma
            chroma_id = int(zip_arg.split('_')[1])
            if not champion_id:
                log.warning(f"[inject] No champion_id provided for chroma ID: {chroma_id}")
                return None
            
            # Look for {champion_id}/{skin_id}/{chroma_id}/{chroma_id}.zip
            champion_dir = self.zips_dir / str(champion_id)
            if not champion_dir.exists():
                log.warning(f"[inject] Champion directory not found: {champion_dir}")
                return None
            
            # Search through all skin directories for this champion to find the chroma
            for skin_dir in champion_dir.iterdir():
                if not skin_dir.is_dir():
                    continue
                
                # Check if this is a skin directory (numeric name)
                try:
                    skin_id = int(skin_dir.name)
                except ValueError:
                    continue
                
                # Look for chroma in this skin's chroma directory
                chroma_dir = skin_dir / str(chroma_id)
                if chroma_dir.exists():
                    chroma_zip_path = chroma_dir / f"{chroma_id}.zip"
                    if chroma_zip_path.exists():
                        log.debug(f"[inject] Found chroma ZIP: {chroma_zip_path}")
                        return chroma_zip_path
            
            log.warning(f"[inject] Chroma ZIP not found for ID: {chroma_id}")
            return None

        # For base skins (no chroma_id), we need skin_id
        if chroma_id is None and skin_name:
            if not champion_id:
                log.warning(f"[inject] No champion_id provided for skin lookup: {skin_name}")
                return None
            
            # The UIA system should have already resolved skin_name to skin_id
            # If we're here, it means skin_id wasn't provided, which shouldn't happen
            log.warning(f"[inject] No skin_id provided for skin '{skin_name}' - UIA should have resolved this")
            return None

        # If chroma_id is provided, look in chroma subdirectory structure
        # New structure: {champion_id}/{chroma_id}/{chroma_id}.zip
        if chroma_id is not None:
            # Special handling for Elementalist Lux forms (fake IDs 99991-99999)
            if 99991 <= chroma_id <= 99999:
                log.info(f"[inject] Detected Elementalist Lux form fake ID: {chroma_id}")
                
                # Map fake IDs to form names
                form_names = {
                    99991: 'Air',
                    99992: 'Dark', 
                    99993: 'Ice',
                    99994: 'Magma',
                    99995: 'Mystic',
                    99996: 'Nature',
                    99997: 'Storm',
                    99998: 'Water',
                    99999: 'Fire'
                }
                
                form_name = form_names.get(chroma_id, 'Unknown')
                log.info(f"[inject] Looking for Elementalist Lux {form_name} form")
                
                # Look for the form file in the Lux directory
                form_pattern = f"Lux Elementalist {form_name}.zip"
                form_files = list(self.zips_dir.rglob(f"**/{form_pattern}"))
                if form_files:
                    log_success(log, f"Found Elementalist Lux {form_name} form: {form_files[0].name}", "✨")
                    return form_files[0]
                else:
                    log.warning(f"[inject] Elementalist Lux {form_name} form file not found: {form_pattern}")
                    return None
            
            # For regular chromas, look for {champion_id}/{skin_id}/{chroma_id}/{chroma_id}.zip
            if not champion_id:
                log.warning(f"[inject] No champion_id provided for chroma lookup: {chroma_id}")
                return None
            
            # For chromas, we need to find which skin they belong to
            # Since chromas are stored under their base skin directory, we need to search
            # through all skin directories for this champion to find the chroma
            champion_dir = self.zips_dir / str(champion_id)
            if not champion_dir.exists():
                log.warning(f"[inject] Champion directory not found: {champion_dir}")
                return None
            
            # Search through all skin directories for this champion
            for skin_dir in champion_dir.iterdir():
                if not skin_dir.is_dir():
                    continue
                
                # Check if this is a skin directory (numeric name)
                try:
                    int(skin_dir.name)  # If this succeeds, it's a skin ID directory
                    
                    # Check if chroma directory exists
                    chroma_dir = skin_dir / str(chroma_id)
                    if chroma_dir.exists():
                        chroma_zip = chroma_dir / f"{chroma_id}.zip"
                        if chroma_zip.exists():
                            log_success(log, f"Found chroma: {chroma_zip.name}", "🎨")
                            return chroma_zip
                except ValueError:
                    # Not a skin directory, skip
                    continue
            
            log.warning(f"[inject] Chroma {chroma_id} not found in any skin directory for champion {champion_id}")
            return None

        # For regular skin files (no chroma_id), we need to find by skin_id
        # This is a simplified approach - in practice, you'd want to use LCU data
        log.warning(f"[inject] Base skin lookup by name not fully implemented for new structure: {zip_arg}")
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
        log_success(log, f"Extracted {zp.name}", "📦")
        return target
    
    def _mk_run_overlay(self, mod_names: List[str], timeout: int = 60, stop_callback=None, injection_manager=None) -> int:
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
            if ENABLE_PRIORITY_BOOST and PSUTIL_AVAILABLE:
                try:
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
                log_success(log, f"mkoverlay completed in {mkoverlay_duration:.2f}s", "⚡")
                # Store timing data for external access
                self.last_injection_timing = {
                    'mkoverlay_duration': mkoverlay_duration,
                    'timestamp': time.time()
                }
                
                # DON'T resume game yet - keep it frozen until runoverlay starts
                log_event(log, "mkoverlay done - keeping game frozen until runoverlay starts", "❄️")
                
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
        
        log_action(log, f"Running overlay: {' '.join(cmd)}", "🚀")
        
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
            if ENABLE_PRIORITY_BOOST and PSUTIL_AVAILABLE:
                try:
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
            # No timeout - overlay will run until explicitly killed or game ends
            while proc.poll() is None:
                # Check if we should stop (game ended)
                if stop_callback and stop_callback():
                    log.info("[inject] Game ended, stopping overlay process")
                    proc.terminate()
                    try:
                        proc.wait(timeout=PROCESS_TERMINATE_TIMEOUT_S)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    self.current_overlay_process = None
                    return 0  # Success - overlay ran through game
                
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
        if self.game_dir is None:
            log.error("[INJECTOR] Cannot create overlay - League game directory not found")
            log.error("[INJECTOR] Please ensure League Client is running or manually set the path in config.ini")
            return 127
            
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
    
    def inject_skin(self, skin_name: str, timeout: int = 60, stop_callback=None, injection_manager=None, chroma_id: int = None, champion_name: str = None, champion_id: int = None) -> bool:
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
            timeout = PROCESS_ENUM_TIMEOUT_S
            
            # Only get pid and name initially to avoid slow cmdline lookups
            if not PSUTIL_AVAILABLE:
                log.debug("[inject] psutil not available, skipping process cleanup")
                return
                
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
                                    p.wait(timeout=PROCESS_TERMINATE_WAIT_S)
                                except (psutil.TimeoutExpired, psutil.NoSuchProcess) as wait_e:
                                    p.kill()  # Force kill if terminate didn't work
                                    log.debug(f"Process wait timeout or process gone, force killing: {wait_e}")
                            except Exception as e:
                                try:
                                    p.kill()  # Force kill on any error
                                except (psutil.NoSuchProcess, psutil.AccessDenied) as kill_e:
                                    log.debug(f"[inject] Process already gone or inaccessible: {kill_e}")
                                except Exception as kill_e:
                                    log.debug(f"[inject] Unexpected error force killing process: {kill_e}")
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