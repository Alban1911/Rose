#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Process Manager
Handles process management utilities for the LTF session

LTK Manager hosts the LTF bridge and drives the patcher, so Rose stops it
through the session stopper (see overlay_manager.py): the patcher is stopped
and Rose's mods are removed before the manager closes.
"""

import subprocess

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
)

log = get_logger()

# LTK Manager, which hosts the bridge DLL and runs the patcher (lowercase:
# process names are compared lowercased)
LTK_MANAGER_PROCESSES = ("ltk-manager.exe", "ltk manager.exe")


class ProcessManager:
    """Manages overlay process lifecycle"""

    def __init__(self):
        self.current_overlay_process = None
        # Set when the user stops injection so the kill isn't reported as a failure
        self.stopped_by_user = False
        # Set when Rose's own cleanup stops the session (lobby change, shutdown)
        self.stopped_by_rose = False
        # Graceful end of the current LTF session, registered by the overlay manager
        self._session_stopper = None
        # (pid, create time) of the LTK Manager Rose started; a running LTK
        # Manager Rose did not start belongs to the user and is left alone
        self.ltk_manager_process = None

    def set_session_stopper(self, stopper):
        """Register the callable that gracefully ends the current LTF session
        (stop the patcher, remove Rose's mods, close a manager we launched)."""
        self._session_stopper = stopper

    def clear_session_stopper(self, stopper):
        """Unregister *stopper*, unless another session registered its own since."""
        if self._session_stopper is stopper:
            self._session_stopper = None

    def stop_injection_by_user(self):
        """Stop the LTK patcher (e.g. a mod crashes the game on reconnect)."""
        self.stopped_by_user = True
        self._stop_session()
        self.kill_all_runoverlay_processes()

    def _mark_stopped_by_rose(self):
        """Tag the current session before Rose stops it: its failure then
        is not reported as an injection failure"""
        self.stopped_by_rose = True
        self._stop_session()

    def _stop_session(self):
        """End the current LTF session gracefully, if one is running.

        The stopper is cleared first: one stop is enough, and the cleanup
        path can reach here several times in a row.
        """
        stopper = self._session_stopper
        if stopper is None:
            return
        self._session_stopper = None
        try:
            stopper()
        except Exception as e:
            log.debug(f"[INJECT] Could not stop the LTF session gracefully: {e}")

    def stop_overlay_process(self):
        """Stop the current overlay process"""
        self._mark_stopped_by_rose()
        proc = self.current_overlay_process
        if proc is not None and proc.poll() is None:
            try:
                log.info("[INJECT] Stopping current overlay process")
                proc.terminate()
                try:
                    proc.wait(timeout=PROCESS_TERMINATE_TIMEOUT_S)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                self.current_overlay_process = None
                log.info("[INJECT] Overlay process stopped successfully")
            except Exception as e:
                log.warning(f"[INJECT] Failed to stop overlay process: {e}")
        else:
            log.debug("[INJECT] No active overlay process to stop")

    def kill_all_runoverlay_processes(self):
        """Close the LTK Manager Rose started (for ChampSelect cleanup)"""
        self._mark_stopped_by_rose()
        self._close_rose_ltk_manager()
        self.stop_overlay_process()

    def kill_all_modtools_processes(self):
        """Close the LTK Manager Rose started (for application shutdown)"""
        self._mark_stopped_by_rose()
        self._close_rose_ltk_manager()
        self.stop_overlay_process()

    def _close_rose_ltk_manager(self):
        """Terminate the LTK Manager Rose started, if it is still running.

        The session stopper already asked it to exit through the bridge; this
        catches one whose bridge stopped answering. Any other LTK Manager is
        the user's and stays open.
        """
        registered = self.ltk_manager_process
        if registered is None:
            return
        if not PSUTIL_AVAILABLE:
            log.debug("[INJECT] psutil not available, skipping LTK Manager cleanup")
            return
        pid, created = registered
        try:
            proc = psutil.Process(pid)
            # A pid Windows gave to another process since is not Rose's
            if (proc.name() or "").lower() not in LTK_MANAGER_PROCESSES:
                self.ltk_manager_process = None
                return
            if created is not None and abs(proc.create_time() - created) > 1.0:
                self.ltk_manager_process = None
                return
            log.info(f"[INJECT] Closing the LTK Manager Rose started (PID {pid})")
            proc.terminate()
            try:
                proc.wait(timeout=PROCESS_TERMINATE_WAIT_S)
            except psutil.TimeoutExpired:
                proc.kill()
            self.ltk_manager_process = None
        except psutil.NoSuchProcess:
            self.ltk_manager_process = None
        except (psutil.Error, OSError) as e:
            log.debug(f"[INJECT] Could not close the LTK Manager Rose started (PID {pid}): {e}")
