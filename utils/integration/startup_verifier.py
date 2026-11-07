"""Conservative, read-only verification of Pengu loading into the client."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path
import sys
import threading
import time

import psutil

from utils.core.logging import get_logger
from utils.integration import pengu_loader

log = get_logger()
POLL_SECONDS = 5.0
CLIENT_GRACE_SECONDS = 60.0
SAFE_PHASES = {"None", "Lobby", "EndOfGame"}


def _session_id(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    session = wintypes.DWORD()
    if not kernel.ProcessIdToSessionId(wintypes.DWORD(pid), ctypes.byref(session)):
        raise ctypes.WinError(ctypes.get_last_error())
    return session.value


def _module_paths(pid):
    """Return a complete Windows module snapshot or raise; never return partial data."""
    class ModuleEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("GlblcntUsage", wintypes.DWORD),
            ("ProccntUsage", wintypes.DWORD), ("modBaseAddr", ctypes.c_void_p),
            ("modBaseSize", wintypes.DWORD), ("hModule", wintypes.HMODULE),
            ("szModule", wintypes.WCHAR * 256), ("szExePath", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Module32FirstW", "Module32NextW"):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(ModuleEntry)]
        function.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateToolhelp32Snapshot(0x08 | 0x10, pid)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ModuleEntry()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel.Module32FirstW(handle, ctypes.byref(entry)):
            raise ctypes.WinError(ctypes.get_last_error())
        paths = []
        while True:
            if not entry.szExePath or len(entry.szExePath) >= 259:
                raise OSError("Module path unavailable or truncated")
            paths.append(Path(entry.szExePath))
            if not kernel.Module32NextW(handle, ctypes.byref(entry)):
                if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                    raise ctypes.WinError(ctypes.get_last_error())
                return paths
    finally:
        kernel.CloseHandle(handle)


@dataclass(frozen=True)
class ClientSample:
    identity: tuple[int, float]
    core_loaded: bool


def client_matches_lcu(identity, lcu):
    """Require the LCU listener to belong to this UX process or its League parent.

    This is only needed at the final failure check. Ambiguous ownership or an
    inaccessible connection table suppresses the popup instead of guessing.
    """
    try:
        port = lcu.port
        if not isinstance(port, int) or not 1 <= port <= 65535:
            return False
        owners = {connection.pid for connection in psutil.net_connections(kind='tcp')
                  if connection.status == psutil.CONN_LISTEN and connection.laddr
                  and connection.laddr.port == port
                  and connection.laddr.ip in {'127.0.0.1', '::1', '0.0.0.0', '::'}}
        if len(owners) != 1 or None in owners:
            return False
        process = psutil.Process(identity[0])
        if process.create_time() != identity[1]:
            return False
        related = [process, *process.parents()]
        matches = any(p.pid in owners and p.name().lower() in {'leagueclient.exe', 'leagueclientux.exe'}
                      for p in related)
        return matches and process.is_running() and lcu.port == port
    except (psutil.Error, OSError, ValueError):
        return False


def sample_client(lcu):
    """None means unavailable, ambiguous, still starting, or waiting for restart."""
    if sys.platform != "win32" or not lcu.ok:
        return None
    try:
        # Read a fresh phase; cached LCU connection state alone isn't readiness.
        if lcu.get('/lol-gameflow/v1/gameflow-phase', timeout=2, use_cache=False) not in SAFE_PHASES:
            return None
        session = _session_id(os.getpid())
        clients = []
        for process in psutil.process_iter(['name']):
            if (process.info.get('name') or '').lower() == 'leagueclientux.exe':
                if _session_id(process.pid) == session:
                    clients.append(process)
        if len(clients) != 1:
            return None
        process = clients[0]
        identity = (process.pid, process.create_time())
        if pengu_loader.is_client_restart_pending(process.pid):
            return None
        paths = _module_paths(process.pid)
        names = {path.name.lower() for path in paths}
        # Verify the snapshot contains the expected running executable and
        # Windows loader, rather than interpreting an empty/partial list as failure.
        if not {'leagueclientux.exe', 'ntdll.dll', 'kernel32.dll'} <= names:
            return None
        loaded = 'core.dll' in names
        if not loaded:
            # Pengu's symlink mode can be reported as version.dll. If Windows
            # cannot resolve that client-local alias, suppress a failure claim.
            client_dir = Path(process.exe()).parent
            # A client-local version.dll can be Pengu under an alias, including
            # paths Windows reports differently through directory junctions.
            try:
                (client_dir / 'version.dll').lstat()
                return None
            except FileNotFoundError:
                pass
            for path in paths:
                if path.name.lower() == 'version.dll' and path.parent == client_dir:
                    return None
        if (not process.is_running() or process.create_time() != identity[1]
                or pengu_loader.is_client_restart_pending(process.pid)):
            return None
        return ClientSample(identity, loaded)
    except (psutil.Error, OSError, ValueError, TypeError):
        return None


class StartupInjectionVerifier(threading.Thread):
    """One startup decision per Rose run. A timeout alone never triggers a warning."""

    def __init__(self, lcu, state, bridge, on_failure):
        super().__init__(name="StartupInjectionVerifier", daemon=True)
        self.lcu = lcu
        self.state = state
        self.bridge = bridge
        self.on_failure = on_failure
        self._stop_event = threading.Event()
        self._candidate = None
        self._since = 0.0
        self._missing_samples = 0
        self._last_check = None
        self.finished = False

    def stop(self):
        self._stop_event.set()

    def _reset(self):
        self._candidate = None
        self._missing_samples = 0

    def _suppress_for_activity(self):
        if (self.bridge.plugin_ready_event.is_set() or self.bridge.client_seen_event.is_set()
                or self.bridge.connections):
            log.info("[Pengu] Client bridge activity observed; suppressing the startup failure warning for this run.")
            self.finished = True
            return True
        return False

    def check_once(self, now):
        if self.finished or self._stop_event.is_set() or self.state.stop:
            return
        if self._suppress_for_activity():
            return
        if self._last_check is not None and now - self._last_check > POLL_SECONDS * 3:
            self._reset()  # Sleep/resume or a delayed checker isn't a settled client.
        self._last_check = now
        if not self.bridge.is_responsive:
            self._reset()
            return
        sample = sample_client(self.lcu)
        if sample is None:
            self._reset()
            return
        if sample.core_loaded:
            log.info("[Pengu] Startup check: Pengu is loaded; no injection-failure warning.")
            self.finished = True
            return
        if sample.identity != self._candidate:
            self._candidate = sample.identity
            self._since = now
            self._missing_samples = 0
        if now - self._since < CLIENT_GRACE_SECONDS:
            return
        self._missing_samples += 1
        if self._missing_samples < 3:
            return
        if not client_matches_lcu(sample.identity, self.lcu):
            self._reset()
            return
        # Recheck the exact process, readiness, and plugin activity immediately
        # before showing a dialog; late success or a restart cancels the warning.
        confirmation = sample_client(self.lcu)
        if self._suppress_for_activity():
            return
        if confirmation is not None and confirmation.core_loaded:
            # Even a late positive observation must remain sticky for this run.
            self.finished = True
            return
        if (confirmation != sample or not self.bridge.is_responsive
                or self.state.stop or self._stop_event.is_set()
                or self.lcu.get('/lol-gameflow/v1/gameflow-phase', timeout=2, use_cache=False) not in SAFE_PHASES):
            self._reset()
            return
        # A status request can take seconds; recheck activity after it returns.
        if self._suppress_for_activity() or self.state.stop or self._stop_event.is_set():
            return
        if not self.bridge.is_responsive:
            self._reset()
            return
        self.finished = True
        log.error("[Pengu] Startup injection failure confirmed: client PID %s, creation %s; "
                  "Pengu absent in repeated complete module snapshots after %.0fs of ready client state.",
                  sample.identity[0], sample.identity[1], now - self._since)
        self.on_failure(sample.identity[0])

    def run(self):
        while not self.finished and not self._stop_event.is_set() and not self.state.stop:
            try:
                self.check_once(time.monotonic())
            except Exception:
                self._reset()
                log.debug("[Pengu] Startup verification unavailable; no failure warning.", exc_info=True)
            if self._stop_event.wait(POLL_SECONDS):
                break
