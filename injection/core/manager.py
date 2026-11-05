#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Injection Manager
Manages the injection process and coordinates with UI detection system
"""

import shutil
import threading
import time
import sys
import uuid
from pathlib import Path
from typing import Optional

from config import (
    INJECTION_LOCK_TIMEOUT_S,
    get_config_file_path
)
from utils.core.logging import get_logger, log_action, log_success
from utils.core.issue_reporter import report_issue

from .injector import SkinInjector
from .stage_plan import PARTY_SKINS_LABEL, StagePlan, describe, prepare_plan, skin_plan
from ..classic import is_classic_game_mode
from ..config.threshold_manager import ThresholdManager

log = get_logger()

# A selection is staged once it has rested this long (hovering through the
# skins stages only the one the player stops on)
STAGE_SETTLE_S = 0.5
# The staging worker exits after this long without anything to stage
STAGE_WORKER_IDLE_S = 30.0


class InjectionManager:
    """Manages skin injection with automatic triggering"""
    
    def __init__(self, tools_dir: Path = None, mods_dir: Path = None, zips_dir: Path = None, game_dir: Optional[Path] = None, shared_state=None):
        self.tools_dir = tools_dir
        self.mods_dir = mods_dir
        self.zips_dir = zips_dir
        self.game_dir = game_dir
        self.shared_state = shared_state  # Reference to shared state for accessing UISkinThread
        self.injector = None  # Will be initialized lazily
        self.last_skin_name = None
        self.last_injection_time = 0.0
        self.injection_lock = threading.Lock()
        self._initialized = False
        self.current_champion = None
        self._injection_in_progress = False  # Track if injection is running
        self._cleanup_in_progress = False  # Track if cleanup is running
        self._cleanup_lock = threading.Lock()  # Lock for cleanup operations
        
        # Initialize managers
        self.threshold_manager = ThresholdManager(shared_state)
        self.injection_threshold = self.threshold_manager.injection_threshold
        
        # Staging during the countdown (stage_plan): the latest selection
        # wins. A preparer extracts and packs it at once, an installer puts it
        # in LTK Manager once it has rested STAGE_SETTLE_S
        self._stage_cond = threading.Condition()
        self._stage_wanted: Optional[StagePlan] = None
        self._stage_wanted_at = 0.0
        # Whether the wanted pick waits STAGE_SETTLE_S before its install: not
        # when it could not rest that long before the injection threshold
        self._stage_wanted_settles = True
        self._stage_done = None
        self._stage_generation = 0
        self._stage_thread = None
        self._prepare_thread = None
        # (wanted, generation, prepared): prepared is (stage_dir, mod_names,
        # archives), or None when there is nothing to stage for it
        self._stage_prepared = None
        # (wanted, generation) the installer is putting in LTK Manager
        self._stage_installing = None

    def _refresh_injection_threshold(self) -> None:
        """Reload injection threshold from config so tray changes apply immediately."""
        self.injection_threshold = self.threshold_manager.refresh()
    
    def refresh_injection_threshold(self) -> float:
        """Public helper to reload injection threshold from config."""
        self._refresh_injection_threshold()
        return self.injection_threshold
    
    def _ensure_initialized(self):
        """Initialize the injector lazily when first needed"""
        if not self._initialized:
            with self.injection_lock:
                if not self._initialized:  # Double-check inside lock
                    log_action(log, "Initializing injection system...", "")
                    self.injector = SkinInjector(None, self.mods_dir, self.zips_dir, self.game_dir)
                    # Only mark as initialized if we have a valid game directory
                    if self.injector.game_dir is not None:
                        self._initialized = True
                        log_success(log, "Injection system initialized successfully", "")
                    else:
                        log.error("[INJECT] Cannot initialize injection system - League game directory not found")
                        log.error("[INJECT] Please ensure League Client is running or manually set the path in config.ini")
                        report_issue(
                            "LEAGUE_DIR_NOT_FOUND",
                            "error",
                            "Injection unavailable: League path not found.",
                            hint="Start League Client, or set the game path in Settings.",
                        )
                        self._initialized = False
    
    def start_patcher_in_background(self):
        """Bring LTK Manager and its bridge up when the loadout countdown begins.

        Starting LTK Manager takes seconds, and its patcher must already scan
        when the client creates the game: the countdown stages the selected
        skin on this session (stage_plan). In the background: starting it must
        not hold up the countdown.
        """
        if not self._initialized or self.injector is None:
            return

        def start():
            try:
                self.injector.overlay_manager.start_patcher_early()
            except Exception as e:
                log.warning(f"[INJECT] Could not start the LTK patcher early: {e}")

        threading.Thread(target=start, daemon=True, name="LTKPatcherStart").start()

    def discard_early_patcher(self):
        """Stop the patcher started for a countdown that ends without an injection."""
        self.cancel_staging()
        if self.injector:
            self.injector.overlay_manager.discard_early_patcher()

    # -- staging during the loadout countdown ---------------------------------
    #
    # From a pick to the patcher's scan, every second counts: the patcher only
    # overlays a game created after its scan started, and LTK Manager builds
    # the overlay first (seconds for a skin that also changes a map file).
    # So a pick is extracted and packed at once by the preparer, while it
    # settles and while an abandoned pick's import still runs; the installer
    # then only has to import it into LTK Manager and start the patcher.

    def _stage_root(self) -> Path:
        """Where the picks are prepared, each in a folder of its own."""
        return Path(self.injector.mods_dir).parent / "stage"

    @staticmethod
    def _alive(thread) -> bool:
        return thread is not None and thread.is_alive()

    def _ensure_stage_threads(self):
        """Start the preparer and the installer if they are not running (under _stage_cond)."""
        if not self._alive(self._prepare_thread):
            self._prepare_thread = threading.Thread(
                target=self._prepare_worker, daemon=True, name="LTKStagePreparer"
            )
            self._prepare_thread.start()
        if not self._alive(self._stage_thread):
            self._stage_thread = threading.Thread(target=self._stage_worker, daemon=True, name="LTKStager")
            self._stage_thread.start()

    def _take_prepared(self):
        """The prepared pick, removed from its slot (under _stage_cond)."""
        slot, self._stage_prepared = self._stage_prepared, None
        return slot

    @staticmethod
    def _discard_prepared(slot):
        if slot is not None and slot[2] is not None:
            shutil.rmtree(slot[2][0], ignore_errors=True)

    def _stage_still_wanted(self, wanted, generation) -> bool:
        with self._stage_cond:
            return generation == self._stage_generation and self._stage_wanted == wanted

    def begin_staging(self):
        """A loadout countdown began: let stage_plan prepare LTK Manager for it."""
        if not self._initialized or self.injector is None:
            return
        with self._stage_cond:
            self._stage_generation += 1
            self._stage_wanted = None
            self._stage_wanted_settles = True
            self._stage_done = None
            stale = self._take_prepared()
            idle = not self._alive(self._stage_thread) and not self._alive(self._prepare_thread)
        self._discard_prepared(stale)
        if idle:
            # Left behind by a crash: nothing prepares or installs from it now
            shutil.rmtree(self._stage_root(), ignore_errors=True)
        self.injector.overlay_manager.open_staging()

    def stage_skin(self, skin_name: str, champion_name: str = None, champion_id: int = None,
                   threshold_in_s: Optional[float] = None):
        """Stage this skin alone (see stage_plan)."""
        if not skin_name:
            return
        classic = is_classic_game_mode(getattr(self.shared_state, "current_game_mode", None))
        self.stage_plan(skin_plan(skin_name, champion_name, champion_id, classic), threshold_in_s)

    def stage_plan(self, plan: StagePlan, threshold_in_s: Optional[float] = None):
        """Stage in LTK Manager what the injection will install for this selection.

        LTK Manager's patcher only overlays a game the client creates after
        its scan started, and the client creates the game about a second
        after the injection begins. So while the countdown runs, the mods of
        the *plan* (the skin, the custom and saved mods, friends' skins: see
        injection.core.stage_plan) are installed and the patcher started (see
        OverlayManager.stage_mods); the injection then finds them in place.
        In the background: prepared at once, installed once the selection
        has rested STAGE_SETTLE_S. *threshold_in_s* is the time left before
        the injection threshold: a pick that cannot rest that long is
        installed at once, as the injection would install it anyway.
        """
        if not self._initialized or self.injector is None or not plan or not plan.steps:
            return
        wanted = plan
        with self._stage_cond:
            if wanted == self._stage_wanted:
                return
            self._stage_wanted = wanted
            self._stage_wanted_at = time.monotonic()
            self._stage_wanted_settles = threshold_in_s is None or threshold_in_s > STAGE_SETTLE_S
            self._ensure_stage_threads()
            self._stage_cond.notify_all()

    def cancel_staging(self, keep: Optional[str] = None):
        """Stage nothing more: the injection (or a discard) takes over.

        *keep* is the skin the injection installs. When the countdown was
        staging that very pick, it is installed at once and left to finish:
        nothing is picked after the threshold, and the injection waits for
        it instead of installing it again from the start.
        """
        with self._stage_cond:
            kept = keep is not None and self._stage_wanted is not None and self._stage_wanted[0] == keep
            if kept:
                self._stage_wanted_settles = False
                stale = None
            else:
                self._stage_generation += 1
                self._stage_wanted = None
                stale = self._take_prepared()
            self._stage_cond.notify_all()
        self._discard_prepared(stale)
        if kept:
            log.debug(f"[STAGE] The injection takes {keep}, which is being staged - letting it finish")
            return
        if self.injector:
            self.injector.overlay_manager.close_staging()

    def _prepare_worker(self):
        """Extract and pack each new pick as soon as it is made."""
        idle_since = time.monotonic()
        while True:
            stale = None
            with self._stage_cond:
                wanted, generation = self._stage_wanted, self._stage_generation
                slot = self._stage_prepared
                ready = slot is not None and slot[0] == wanted and slot[1] == generation
                installing = self._stage_installing == (wanted, generation)
                if wanted is None or wanted == self._stage_done or ready or installing:
                    if slot is not None and not ready:
                        stale = self._take_prepared()  # prepared for a pick that is gone
                    elif time.monotonic() - idle_since > STAGE_WORKER_IDLE_S:
                        self._prepare_thread = None
                        return
                    else:
                        self._stage_cond.wait(timeout=1.0)
                        continue
            if stale is not None:
                self._discard_prepared(stale)
                continue

            prepared = self._prepare_stage(wanted, generation)
            idle_since = time.monotonic()
            with self._stage_cond:
                if generation == self._stage_generation and wanted == self._stage_wanted:
                    stale = self._take_prepared()
                    self._stage_prepared = (wanted, generation, prepared)
                    self._stage_cond.notify_all()
                else:
                    stale = (wanted, generation, prepared)
            self._discard_prepared(stale)

    def _prepare_stage(self, wanted: StagePlan, generation):
        """Extract the plan's mods (the skin, its loading screen name, the
        other mods) into a folder of its own and pack them:
        (stage_dir, mod_names, archives), or None when there is nothing to
        stage for it."""
        stage_dir = self._stage_root() / uuid.uuid4().hex
        try:
            stage_dir.mkdir(parents=True, exist_ok=True)
            mod_names = prepare_plan(self.injector, wanted, stage_dir)
            if not mod_names:
                shutil.rmtree(stage_dir, ignore_errors=True)
                return None
            archives = {}
            if self._stage_still_wanted(wanted, generation):
                archives = self.injector.overlay_manager.pack_mods(stage_dir, mod_names)
            return stage_dir, mod_names, archives
        except Exception as e:
            log.warning(f"[STAGE] Could not prepare {wanted.label}: {e}")
            shutil.rmtree(stage_dir, ignore_errors=True)
            return None

    def _stage_worker(self):
        """Install the prepared pick in LTK Manager once it has rested."""
        idle_since = time.monotonic()
        while True:
            with self._stage_cond:
                wanted, at, generation = self._stage_wanted, self._stage_wanted_at, self._stage_generation
                if wanted is None or wanted == self._stage_done:
                    if time.monotonic() - idle_since > STAGE_WORKER_IDLE_S:
                        self._stage_thread = None
                        return
                    self._stage_cond.wait(timeout=1.0)
                    continue
                rest = STAGE_SETTLE_S if self._stage_wanted_settles else 0.0
                settle = at + rest - time.monotonic()
                if settle > 0:
                    # Hovering through the skins: stage the one the player stops on
                    self._stage_cond.wait(timeout=settle)
                    continue
                slot = self._stage_prepared
                if slot is None or slot[0] != wanted or slot[1] != generation:
                    # Still being prepared: the preparer notifies when it is done
                    self._ensure_stage_threads()
                    self._stage_cond.wait(timeout=1.0)
                    continue
                self._stage_prepared = None
                self._stage_installing = (wanted, generation)
            outcome = False
            try:
                if slot[2] is not None:
                    outcome = self._install_prepared(wanted, generation, at, slot[2])
            finally:
                self._discard_prepared(slot)
            idle_since = time.monotonic()
            with self._stage_cond:
                self._stage_installing = None
                if generation == self._stage_generation and outcome is not None:
                    # Done even when it failed: the injection installs it then.
                    # Not when the player moved on: coming back stages it again
                    self._stage_done = wanted
                self._stage_cond.notify_all()  # the preparer may have one to prepare again

    def _install_prepared(self, wanted, generation, selected_at, prepared) -> Optional[bool]:
        """Stage the prepared pick: True when staged, False when it failed,
        None when it was given up because the player moved on."""
        skin_name = wanted.label
        stage_dir, mod_names, archives = prepared
        moved_on = []

        def still_wanted() -> bool:
            wanted_now = self._stage_still_wanted(wanted, generation)
            if not wanted_now:
                moved_on.append(True)
            return wanted_now

        if not still_wanted():
            return None
        try:
            log.info(f"[STAGE] Staging {skin_name}{describe(wanted)} in LTK Manager")
            staged = self.injector.overlay_manager.stage_mods(
                stage_dir, mod_names, still_wanted, archives=archives, selected_at=selected_at
            )
        except Exception as e:
            log.warning(f"[STAGE] Could not stage {skin_name}: {e}")
            return False
        if not staged and moved_on:
            return None
        return bool(staged)

    def on_champion_locked(self, champion_name: str, champion_id: int = None, owned_skin_ids: set = None):
        """Called when a champion is locked"""
        if not champion_name:
            log.debug("[INJECT] on_champion_locked called with empty champion name")
            return
        
        log.info(f"[INJECT] on_champion_locked called for: {champion_name} (id={champion_id})")
        self._ensure_initialized()
        
        # Track current champion
        if self.current_champion != champion_name:
            self.current_champion = champion_name
            log.debug(f"[INJECT] Champion locked: {champion_name}")
    
    
    def update_skin(self, skin_name: str):
        """Update the current skin and potentially trigger injection"""
        if not skin_name:
            log.debug("[INJECT] No skin name available - skipping injection (mods-only flow disabled)")
            return
        
        self._ensure_initialized()
        self.refresh_injection_threshold()
        
        # Don't attempt injection if system isn't properly initialized
        if not self._initialized or self.injector is None or self.injector.game_dir is None:
            return
            
        with self.injection_lock:
            current_time = time.time()

            elapsed = current_time - self.last_injection_time
            if self.last_injection_time and elapsed < self.injection_threshold:
                remaining = self.injection_threshold - elapsed
                log.debug(f"[INJECT] Skipping injection for '{skin_name}' (cooldown {remaining:.2f}s remaining)")
                report_issue(
                    "INJECTION_SKIPPED_COOLDOWN",
                    "info",
                    "Injection skipped (cooldown still active).",
                    details={
                        "remaining_s": f"{remaining:.2f}",
                        "threshold_s": f"{self.injection_threshold:.2f}",
                        "skin": skin_name,
                    },
                    hint="Wait a bit, or lower the Injection Cooldown/Threshold in Settings.",
                )
                return

            # Disconnect from UIA window when injection threshold triggers
            # (launcher closes when game starts, so the window is gone)
            if self.shared_state and self.shared_state.ui_skin_thread:
                try:
                    self.shared_state.ui_skin_thread.force_disconnect()
                except Exception as e:
                    log.debug(f"[INJECT] Failed to disconnect UIA: {e}")
            
            # LTK Manager takes seconds to start: bring it up now if the
            # countdown did not already (the injection waits for that connect)
            self.start_patcher_in_background()

            success = self.injector.inject_skin(
                skin_name,
                stop_callback=None,
            )

            if success:
                self.last_skin_name = skin_name
                self.last_injection_time = current_time
            
            # The injection took the countdown's session over: staging ends
            self.discard_early_patcher()
    
    def _check_and_inject_mods_only(self):
        """Mods-only injection is disabled because the installed mods directory was removed."""
        log.info("[INJECT] Mods-only injection skipped (installed mods folder removed)")
    
    def on_loadout_countdown(self, seconds_remaining: int):
        """Called during loadout countdown - no longer used (monitor starts with injection)"""
        # Monitor now starts when injection actually begins, not at T-1
        # This prevents unnecessary suspension for base skins and owned skins
        pass
    
    def inject_skin_immediately(self, skin_name: str, stop_callback=None, chroma_id: int = None, champion_name: str = None, champion_id: int = None) -> bool:
        """Immediately inject a specific skin (with optional chroma)
        
        Args:
            skin_name: Name of skin to inject
            stop_callback: Callback to check if injection should stop
            chroma_id: Optional chroma ID for chroma variant
        """
        # Check if this is a base skin (skin_0 or skin name ending with base/default indicators)
        # If skin_name starts with "skin_" and the ID is 0 or matches base skin pattern, inject mods only
        if skin_name and skin_name.startswith("skin_"):
            try:
                skin_id_str = skin_name.split("_")[1] if "_" in skin_name else None
                if skin_id_str:
                    skin_id = int(skin_id_str)
                    # Check if this is a base skin (skin ID 0 or champion's base skin ID like 36000 for champ 36)
                    # Base skins typically have ID = champion_id * 1000
                    if skin_id == 0:
                        log.info("[INJECT] Base skin detected (skinId=0) - injection skipped")
                        report_issue(
                            "INJECTION_SKIPPED_BASE_SKIN",
                            "info",
                            "Injection skipped (base skin selected).",
                            details={"skin": skin_name, "skin_id": 0},
                        )
                        return False
                    # Check if it matches base skin pattern (champion_id * 1000)
                    if champion_id and skin_id == champion_id * 1000:
                        log.info(f"[INJECT] Base skin detected (skinId={skin_id} for champion {champion_id}) - injection skipped")
                        report_issue(
                            "INJECTION_SKIPPED_BASE_SKIN",
                            "info",
                            "Injection skipped (base skin selected).",
                            details={"skin": skin_name, "skin_id": skin_id, "champion_id": champion_id},
                        )
                        return False
            except (ValueError, IndexError):
                pass  # Not a numeric skin ID, continue with normal injection

        classic = is_classic_game_mode(getattr(self.shared_state, "current_game_mode", None))

        def inject(extra_mods_callback):
            return self.injector.inject_skin(
                skin_name,
                stop_callback=stop_callback,
                chroma_id=chroma_id,
                champion_name=champion_name,
                champion_id=champion_id,
                extra_mods_callback=extra_mods_callback,
                classic=classic,
            )

        success = self._run_injection(skin_name, inject)
        if success:
            self.last_skin_name = skin_name
        return success

    def inject_party_skins_only(self, stop_callback=None) -> bool:
        """Inject only party members' skins (our own champion keeps its default skin)

        Args:
            stop_callback: Callback to check if injection should stop
        """
        def inject(extra_mods_callback):
            if not extra_mods_callback:
                log.info("[INJECT] No party skins to inject")
                return False
            return self.injector.inject_extra_mods(
                extra_mods_callback,
                stop_callback=stop_callback,
            )

        return self._run_injection(PARTY_SKINS_LABEL, inject)

    def _run_injection(self, label: str, inject) -> bool:
        """Run one injection under the injection lock

        Args:
            label: What is injected (for logs and issue reports)
            inject: callback(extra_mods_callback) -> bool doing the injection;
                extra_mods_callback adds party member skins (None without party)
        """
        self._ensure_initialized()
        self.refresh_injection_threshold()

        # Don't attempt injection if system isn't properly initialized
        if not self._initialized or self.injector is None or self.injector.game_dir is None:
            log.error("[INJECT] Cannot inject - League game directory not found")
            log.error("[INJECT] Please ensure League Client is running or manually set the path in config.ini")
            return False

        # Check if injection already in progress
        if self._injection_in_progress:
            log.warning(f"[INJECT] Injection already in progress - skipping request for: {label}")
            return False
        
        # Try to acquire lock with timeout to prevent indefinite blocking
        lock_acquired = self.injection_lock.acquire(timeout=INJECTION_LOCK_TIMEOUT_S)
        if not lock_acquired:
            log.warning(f"[INJECT] Could not acquire injection lock - another injection in progress")
            report_issue(
                "INJECTION_LOCK_TIMEOUT",
                "warning",
                "Injection skipped (another injection was still running).",
                details={"lock_timeout_s": f"{INJECTION_LOCK_TIMEOUT_S:.1f}", "skin": label},
                hint="Try again in a few seconds.",
            )
            return False

        try:
            self._injection_in_progress = True
            log.debug(f"[INJECT] Injection started - lock acquired for: {label}")
            # What the countdown staged is reused if it matches; nothing more is
            # staged (a staging of this very skin finishes)
            self.cancel_staging(keep=label)

            current_time = time.time()
            elapsed = current_time - self.last_injection_time
            if self.last_injection_time and elapsed < self.injection_threshold:
                remaining = self.injection_threshold - elapsed
                log.debug(f"[INJECT] Skipping immediate injection for '{label}' (cooldown {remaining:.2f}s remaining)")
                report_issue(
                    "INJECTION_SKIPPED_COOLDOWN",
                    "info",
                    "Injection skipped (cooldown still active).",
                    details={
                        "remaining_s": f"{remaining:.2f}",
                        "threshold_s": f"{self.injection_threshold:.2f}",
                        "skin": label,
                    },
                    hint="Wait a bit, or lower the Injection Cooldown/Threshold in Settings.",
                )
                return False

            # Disconnect from UIA window when injection happens
            # (launcher closes when game starts, so the window is gone)
            if self.shared_state and self.shared_state.ui_skin_thread:
                try:
                    self.shared_state.ui_skin_thread.force_disconnect()
                except Exception as e:
                    log.debug(f"[INJECT] Failed to disconnect UIA: {e}")
            
            # LTK Manager takes seconds to start: bring it up now if the
            # countdown did not already (the injection waits for that connect)
            self.start_patcher_in_background()
            
            # Build optional callback to add party member skins to injection
            extra_mods_callback = None
            if self.shared_state:
                party_manager = getattr(self.shared_state, "party_manager", None)
                if party_manager and getattr(party_manager, "enabled", False):
                    try:
                        from party.integration.injection_hook import PartyInjectionHook
                        party_hook = PartyInjectionHook(
                            party_manager, self.shared_state, self
                        )
                        if party_hook.is_enabled():
                            extra_mods_callback = lambda inj: party_hook.prepare_party_mods(inj)
                    except Exception as e:
                        log.debug(f"[INJECT] Party injection hook not used: {e}")

            success = inject(extra_mods_callback)
            if success:
                self.last_injection_time = current_time

            return success
        finally:
            self._injection_in_progress = False
            self.injection_lock.release()
            log.debug(f"[INJECT] Injection completed - lock released")
            
            # The injection took the countdown's session over: staging ends
            self.discard_early_patcher()
    
    def inject_skin_for_testing(self, skin_name: str) -> bool:
        """Inject a skin for testing purposes - stops overlay immediately after mkoverlay"""
        if not skin_name:
            return False
            
        self._ensure_initialized()
        self.refresh_injection_threshold()
        
        # Don't attempt injection if system isn't properly initialized
        if not self._initialized or self.injector is None or self.injector.game_dir is None:
            log.error("[INJECT] Cannot inject - League game directory not found")
            return False
            
        with self.injection_lock:
            current_time = time.time()
            elapsed = current_time - self.last_injection_time
            if self.last_injection_time and elapsed < self.injection_threshold:
                remaining = self.injection_threshold - elapsed
                log.debug(f"[INJECT] Skipping testing injection for '{skin_name}' (cooldown {remaining:.2f}s remaining)")
                return False

            success = self.injector.inject_skin(skin_name)

            if success:
                self.last_skin_name = skin_name
                self.last_injection_time = current_time
                log.info(f"[INJECT] Test injection successful for: {skin_name}")
            return success
    
    def clean_system(self) -> bool:
        """Clean the injection system"""
        if not self._initialized:
            return True  # Nothing to clean if not initialized
        
        with self.injection_lock:
            return self.injector.clean_system()
    
    def initialize_when_ready(self):
        """Initialize the injection system when the app is ready (skins downloaded)"""
        if not self._initialized:
            log.info("[INJECT] App ready - initializing injection system in background...")
            # Initialize in a separate thread to avoid blocking
            def init_thread():
                try:
                    self._ensure_initialized()
                    log.info("[INJECT] Background initialization completed - injection system ready")
                except Exception as e:
                    log.error(f"[INJECT] Background initialization failed: {e}")
            
            threading.Thread(target=init_thread, daemon=True).start()
    
    @property
    def last_injected_skin(self) -> Optional[str]:
        """Get the last successfully injected skin"""
        return self.last_skin_name
    
    def stop_overlay_process(self):
        """Stop the current overlay process"""
        if not self._initialized:
            return  # Nothing to stop if not initialized
            
        try:
            self.injector.stop_overlay_process()
        except Exception as e:
            log.warning(f"[INJECT] Failed to stop overlay process: {e}")
    
    def kill_all_runoverlay_processes(self):
        """Kill all LTK Manager processes (for ChampSelect cleanup)"""
        if not self._initialized:
            return  # Nothing to kill if not initialized
        
        # Leaving champ select: the countdown's staging ends
        self.discard_early_patcher()
        
        # Prevent duplicate cleanup calls from running simultaneously
        if self._cleanup_in_progress:
            log.debug("[INJECT] Cleanup already in progress - skipping duplicate call")
            return
        
        # Try to acquire cleanup lock without blocking
        if not self._cleanup_lock.acquire(blocking=False):
            log.debug("[INJECT] Could not acquire cleanup lock - another cleanup in progress")
            return
        
        # Set flag and release lock immediately so we don't block the caller
        self._cleanup_in_progress = True
        self._cleanup_lock.release()
        
        # Run cleanup in a separate thread to avoid blocking phase transitions
        def cleanup_thread():
            try:
                log.debug("[INJECT] Starting cleanup thread for runoverlay processes")
                self.injector.kill_all_runoverlay_processes()
                log.debug("[INJECT] Cleanup thread completed")
            except Exception as e:
                log.warning(f"[INJECT] Cleanup thread failed: {e}")
            finally:
                # Clear flag when done
                with self._cleanup_lock:
                    self._cleanup_in_progress = False
        
        cleanup = threading.Thread(target=cleanup_thread, daemon=True, name="CleanupThread")
        cleanup.start()
    
    def stop_injection_by_user(self):
        """Stop the patcher so the game can start without mods"""
        if not self._initialized:
            return
        self.discard_early_patcher()
        try:
            self.injector.stop_injection_by_user()
            log.info("[INJECT] Injection stopped by the user")
        except Exception as e:
            log.warning(f"[INJECT] Failed to stop injection: {e}")

    def kill_all_modtools_processes(self):
        """Kill all LTK Manager processes (for application shutdown)"""
        if not self._initialized:
            return  # Nothing to kill if not initialized
        
        try:
            self.injector.kill_all_modtools_processes()
        except Exception as e:
            log.warning(f"[INJECT] Failed to kill LTK Manager processes: {e}")
    
    def _get_injection_dir(self) -> Path:
        """Get the injection directory path (works in both frozen and development environments)"""
        if getattr(sys, 'frozen', False):
            # Running as compiled executable (PyInstaller)
            # Handle both onefile (_MEIPASS) and onedir (_internal) modes
            if hasattr(sys, '_MEIPASS'):
                # One-file mode: tools are in _MEIPASS (temporary extraction directory)
                base_path = Path(sys._MEIPASS)
                injection_dir = base_path / "injection"
            else:
                # One-dir mode: tools are alongside executable
                base_dir = Path(sys.executable).parent
                possible_injection_dirs = [
                    base_dir / "injection",  # Direct path
                    base_dir / "_internal" / "injection",  # _internal folder
                ]
                
                injection_dir = None
                for dir_path in possible_injection_dirs:
                    if dir_path.exists():
                        injection_dir = dir_path
                        break
                
                if not injection_dir:
                    injection_dir = possible_injection_dirs[0]
        else:
            # Running as Python script
            injection_dir = Path(__file__).parent.parent
        
        return injection_dir
