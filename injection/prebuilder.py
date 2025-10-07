#!/usr/bin/env python3
"""
Pre-builder system for champion skins
Builds all mkoverlay files when a champion is locked for instant injection
"""

import time
import threading
import shutil
import zipfile
import subprocess
import concurrent.futures
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, CancelledError

from .injector import SkinInjector
from utils.paths import get_skins_dir, get_injection_dir
from utils.logging import get_logger
from constants import CHAMPIONS_USE_2_THREADS, CHAMPIONS_USE_3_THREADS, DEFAULT_THREAD_COUNT

log = get_logger()


class ChampionPreBuilder:
    """Pre-builds all mkoverlay files for a champion when locked"""
    
    def __init__(self, tools_dir: Path = None, mods_dir: Path = None, zips_dir: Path = None, game_dir: Optional[Path] = None):
        self.tools_dir = tools_dir
        self.mods_dir = mods_dir or get_injection_dir() / "mods"
        self.zips_dir = zips_dir or get_skins_dir()
        self.game_dir = game_dir
        
        # Pre-built overlays storage
        self.prebuilt_dir = get_injection_dir() / "prebuilt"
        self.prebuilt_dir.mkdir(parents=True, exist_ok=True)
        
        # Thread safety
        self.building_lock = threading.Lock()
        self.current_champion = None
        self.building_futures = []
        self.cancel_requested = threading.Event()
        
        # Initialize base injector for mkoverlay operations
        self.injector = SkinInjector(self.tools_dir, self.mods_dir, self.zips_dir, self.game_dir)
    
    def get_recommended_threads(self, champion_name: str) -> int:
        """Get recommended thread count for champion"""
        if champion_name in CHAMPIONS_USE_2_THREADS:
            return 2
        elif champion_name in CHAMPIONS_USE_3_THREADS:
            return 3
        else:
            return DEFAULT_THREAD_COUNT
    
    def find_champion_skins(self, champion_name: str) -> List[Tuple[str, Path]]:
        """Find all skins for a specific champion"""
        champion_skins = []
        
        # Try different possible champion directory names
        possible_names = [champion_name, champion_name.lower(), champion_name.upper(), champion_name.capitalize()]
        
        skins_dir = self.zips_dir / "skins"
        
        for name in possible_names:
            champion_dir = skins_dir / name
            if champion_dir.is_dir():
                for skin_zip in champion_dir.glob("*.zip"):
                    champion_skins.append((skin_zip.stem, skin_zip))
                break
        
        # If no specific champion directory found, search for champion skins in all directories
        if not champion_skins:
            log.debug(f"No {champion_name} directory found, searching all directories for {champion_name} skins...")
            champion_lower = champion_name.lower()
            for champion_dir in skins_dir.iterdir():
                if champion_dir.is_dir():
                    for skin_zip in champion_dir.glob(f"*{champion_lower}*.zip"):
                        champion_skins.append((skin_zip.stem, skin_zip))
                    for skin_zip in champion_dir.glob(f"*{champion_name}*.zip"):
                        champion_skins.append((skin_zip.stem, skin_zip))
        
        return champion_skins
    
    def _mk_overlay_only_thread_isolated(self, mods_dir: Path, overlay_dir: Path, mod_name: str, timeout: int = 60) -> int:
        """Create overlay using mkoverlay with thread-specific directories"""
        try:
            overlay_exe = self.injector.tools_dir / "mod-tools.exe"
            if not overlay_exe.exists():
                log.error(f"PreBuilder: Overlay executable not found: {overlay_exe}")
                return -1
            
            cmd = [
                str(overlay_exe),
                "mkoverlay",
                str(mods_dir),
                str(overlay_dir),
                "--game:" + str(self.injector.game_dir),
                "--mods:" + mod_name,
                "--noTFT"
            ]
            
            log.debug(f"PreBuilder: Creating overlay: {' '.join(cmd)}")
            
            # Run mkoverlay
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            try:
                stdout, stderr = process.communicate(timeout=timeout)
                
                if process.returncode == 0:
                    log.debug(f"PreBuilder: mkoverlay completed successfully for {mod_name}")
                    return 0
                else:
                    log.error(f"PreBuilder: mkoverlay failed for {mod_name}: stdout={stdout}, stderr={stderr}")
                    return process.returncode
                    
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                log.error(f"PreBuilder: mkoverlay timed out after {timeout}s for {mod_name}")
                return -1
                
        except Exception as e:
            log.error(f"PreBuilder: Error running mkoverlay for {mod_name}: {e}")
            return -1
    
    def build_single_skin_overlay(self, champion_name: str, skin_name: str, skin_path: Path, thread_id: int) -> Dict:
        """Build mkoverlay for a single skin in isolation"""
        result = {
            'skin_name': skin_name,
            'skin_path': str(skin_path),
            'success': False,
            'overlay_dir': None,
            'error': None
        }
        
        # Create champion-specific thread directories to avoid collisions between builds
        thread_base_dir = self.prebuilt_dir / f"{champion_name}_thread_{thread_id}"
        thread_mods_dir = thread_base_dir / "mods"
        thread_overlay_dir = thread_base_dir / "overlay"
        
        try:
            # Clean and create directories
            if thread_base_dir.exists():
                shutil.rmtree(thread_base_dir, ignore_errors=True)
            thread_mods_dir.mkdir(parents=True, exist_ok=True)
            thread_overlay_dir.mkdir(parents=True, exist_ok=True)
            
            # Extract skin to thread-specific mods directory (matching traditional injection)
            target_mod_dir = thread_mods_dir / skin_path.stem
            if target_mod_dir.exists():
                shutil.rmtree(target_mod_dir, ignore_errors=True)
            target_mod_dir.mkdir(parents=True, exist_ok=True)
            
            with zipfile.ZipFile(skin_path, 'r') as zip_ref:
                zip_ref.extractall(target_mod_dir)
            
            log.debug(f"PreBuilder: Extracted {skin_path.name} -> {target_mod_dir}")
            
            # Create overlay using mkoverlay with thread-specific directories
            # Use the target mod directory name (matches traditional injection)
            overlay_result = self._mk_overlay_only_thread_isolated(thread_mods_dir, thread_overlay_dir, target_mod_dir.name, timeout=60)
            
            if overlay_result == 0:
                result['success'] = True
                result['overlay_dir'] = thread_overlay_dir
                
                # Move overlay to final location
                final_overlay_dir = self.prebuilt_dir / f"{champion_name}_{skin_name}"
                if final_overlay_dir.exists():
                    shutil.rmtree(final_overlay_dir, ignore_errors=True)
                shutil.move(str(thread_overlay_dir), str(final_overlay_dir))
                result['overlay_dir'] = final_overlay_dir
                
                log.debug(f"[PREBUILD] Successfully built overlay for {skin_name}")
            else:
                result['error'] = f"mkoverlay failed with code {overlay_result}"
        
        except Exception as e:
            result['error'] = str(e)
            log.error(f"[PREBUILD] Error building {skin_name}: {e}")
        
        finally:
            # Clean up thread directory
            if thread_base_dir.exists():
                shutil.rmtree(thread_base_dir, ignore_errors=True)
        
        return result
    
    def prebuild_champion_skins(self, champion_name: str) -> bool:
        """Pre-build all mkoverlay files for a champion"""
        # Clear any previous cancellation flag
        self.cancel_requested.clear()
        
        # Setup phase - hold lock briefly
        with self.building_lock:
            # Clean up any previous builds for this champion in background (non-blocking)
            # This prevents blocking when old builds are still cleaning up
            def cleanup_background():
                try:
                    self._cleanup_champion_overlays(champion_name)
                except Exception as e:
                    log.debug(f"[PREBUILD] Background cleanup error for {champion_name}: {e}")
            
            cleanup_thread = threading.Thread(target=cleanup_background, daemon=True)
            cleanup_thread.start()
            
            # Find all skins for this champion
            champion_skins = self.find_champion_skins(champion_name)
            if not champion_skins:
                log.warning(f"[PREBUILD] No skins found for {champion_name}")
                return False
            
            # Get recommended thread count
            max_workers = self.get_recommended_threads(champion_name)
            log.info(f"[PREBUILD] Starting pre-build for {champion_name} with {len(champion_skins)} skins using {max_workers} threads")
            
            # Store current champion
            self.current_champion = champion_name
        
        # Pre-build all skins in parallel (without holding lock)
        start_time = time.time()
        successful_builds = 0
        was_cancelled = False
        
        executor = None
        try:
            executor = ThreadPoolExecutor(max_workers=max_workers)
            
            # Submit all build tasks
            future_to_skin = {
                executor.submit(self.build_single_skin_overlay, champion_name, skin_name, skin_path, i): (skin_name, skin_path)
                for i, (skin_name, skin_path) in enumerate(champion_skins)
            }
            
            # Store futures for potential cancellation
            with self.building_lock:
                self.building_futures = list(future_to_skin.keys())
            
            # Collect results with frequent cancellation checks
            completed_count = 0
            total_count = len(future_to_skin)
            
            while completed_count < total_count:
                # Check for cancellation FIRST before waiting
                if self.cancel_requested.is_set():
                    log.info(f"[PREBUILD] Cancellation requested for {champion_name}, stopping immediately")
                    was_cancelled = True
                    # Cancel all remaining futures
                    for f in future_to_skin.keys():
                        if not f.done():
                            f.cancel()
                    break
                
                # Wait for next completed future with timeout to allow cancellation checks
                try:
                    done, _ = concurrent.futures.wait(
                        future_to_skin.keys(),
                        timeout=0.1,  # Short timeout to check cancellation frequently
                        return_when=concurrent.futures.FIRST_COMPLETED
                    )
                    
                    for future in done:
                        if future not in future_to_skin:
                            continue  # Already processed
                        
                        completed_count += 1
                        skin_name, skin_path = future_to_skin[future]
                        
                        try:
                            result = future.result(timeout=0)
                            if result['success']:
                                successful_builds += 1
                                log.debug(f"[PREBUILD] OK {skin_name}")
                            else:
                                log.warning(f"[PREBUILD] FAIL {skin_name}: {result['error']}")
                        except CancelledError:
                            log.debug(f"[PREBUILD] CANCELLED {skin_name}")
                        except Exception as e:
                            if not self.cancel_requested.is_set():
                                log.error(f"[PREBUILD] ERROR {skin_name}: Exception: {e}")
                        
                        # Remove processed future
                        del future_to_skin[future]
                
                except concurrent.futures.TimeoutError:
                    # Timeout is normal, just loop again to check cancellation
                    pass
        
        finally:
            # Shutdown executor
            if executor is not None:
                if was_cancelled:
                    # Shutdown immediately without waiting for running tasks
                    executor.shutdown(wait=False, cancel_futures=True)
                else:
                    # Normal shutdown, wait for completion
                    executor.shutdown(wait=True)
            
            # Clear futures and state
            with self.building_lock:
                self.building_futures = []
                if self.current_champion == champion_name:
                    self.current_champion = None
        
        total_time = time.time() - start_time
        if was_cancelled:
            log.info(f"[PREBUILD] Cancelled {champion_name}: {successful_builds}/{len(champion_skins)} skins built before cancellation in {total_time:.2f}s")
        else:
            log.info(f"[PREBUILD] Completed {champion_name}: {successful_builds}/{len(champion_skins)} skins built in {total_time:.2f}s")
        
        return successful_builds > 0
    
    def _cleanup_champion_overlays(self, champion_name: str):
        """Clean up all pre-built overlays and thread directories for a champion"""
        pattern = f"{champion_name}_*"
        for overlay_dir in self.prebuilt_dir.glob(pattern):
            if overlay_dir.is_dir():
                shutil.rmtree(overlay_dir, ignore_errors=True)
                log.debug(f"[PREBUILD] Cleaned up: {overlay_dir.name}")
    
    def cancel_current_build(self):
        """Cancel any ongoing pre-build operation"""
        # Set cancellation flag first
        self.cancel_requested.set()
        
        with self.building_lock:
            # Cancel all futures
            for future in self.building_futures:
                if not future.done():
                    future.cancel()
            
            if self.current_champion:
                log.info(f"[PREBUILD] Cancelling pre-build for {self.current_champion}")
            
            # Note: Don't clear current_champion or futures here
            # Let the prebuild thread clean up in its finally block
    
    def get_prebuilt_overlay_path(self, champion_name: str, skin_name: str) -> Optional[Path]:
        """Get path to pre-built overlay for a skin"""
        overlay_path = self.prebuilt_dir / f"{champion_name}_{skin_name}"
        if overlay_path.exists():
            return overlay_path
        return None
    
    def cleanup_unused_overlays(self, champion_name: str, used_skin_name: str):
        """Clean up all overlays except the one that was used"""
        pattern = f"{champion_name}_*"
        for overlay_dir in self.prebuilt_dir.glob(pattern):
            if overlay_dir.is_dir():
                # Keep the used skin, delete others
                if overlay_dir.name != f"{champion_name}_{used_skin_name}":
                    shutil.rmtree(overlay_dir, ignore_errors=True)
                    log.debug(f"[PREBUILD] Cleaned up unused overlay: {overlay_dir.name}")
    
    def cleanup_all_overlays(self):
        """Clean up all pre-built overlays"""
        if self.prebuilt_dir.exists():
            for overlay_dir in self.prebuilt_dir.iterdir():
                if overlay_dir.is_dir():
                    shutil.rmtree(overlay_dir, ignore_errors=True)
            log.info("[PREBUILD] Cleaned up all pre-built overlays")
    
    def is_prebuild_complete(self, champion_name: str) -> bool:
        """Check if pre-building is complete for a champion"""
        with self.building_lock:
            return self.current_champion != champion_name or len(self.building_futures) == 0
    
    def wait_for_prebuild_completion(self, champion_name: str, timeout: float = 10.0) -> bool:
        """Wait for pre-building to complete for a champion"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.is_prebuild_complete(champion_name):
                return True
            time.sleep(0.1)
        return False
