"""Conservative, read-only verification of Pengu loading into the client."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path
import sys
import threading

import psutil

from utils.core.logging import get_logger
from utils.integration import pengu_loader

log = get_logger()
# How long the client gets, once the LCU is up, to load Rose's plugin: it
# reaches the bridge within seconds of the client's UI
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
    """One startup decision per Rose run, taken once.

    Started once the LCU is up. Rose's plugin connects to the bridge as soon as
    Pengu loads it into the client, so the verifier waits for that (an OS wait,
    no polling) and only if it does not happen within the grace takes one
    module snapshot of the client to decide. An unclear answer (a client still
    starting, restarting, in a game, ambiguous) never warns.
    """

    def __init__(self, lcu, state, bridge, on_failure, grace: float = CLIENT_GRACE_SECONDS):
        super().__init__(name="StartupInjectionVerifier", daemon=True)
        self.lcu = lcu
        self.state = state
        self.bridge = bridge
        self.on_failure = on_failure
        self.grace = grace
        self._stop_event = threading.Event()
        # Set by stop() or the plugin's first connection: either ends the wait
        self._wake = threading.Event()
        on_client_seen = getattr(bridge, "on_client_seen", None)
        if on_client_seen is not None:
            on_client_seen(self._wake.set)
        self.finished = False

    def stop(self):
        self._stop_event.set()
        self._wake.set()

    def _stopped(self) -> bool:
        return self._stop_event.is_set() or self.state.stop

    def _client_active(self) -> bool:
        """Rose's plugin reached the bridge: it was loaded, whatever came after."""
        return (self.bridge.plugin_ready_event.is_set() or self.bridge.client_seen_event.is_set()
                or bool(self.bridge.connections))

    def run(self):
        try:
            if not self._client_active():
                self._wake.wait(self.grace)
            self.decide()
        except Exception:
            log.debug("[Pengu] Startup verification unavailable; no failure warning.", exc_info=True)
        finally:
            self.finished = True

    def decide(self) -> bool:
        """Check the client once; True when it warned."""
        if self._stopped():
            return False
        if self._client_active():
            log.info("[Pengu] Startup check: Rose's plugin answered on the bridge.")
            return False
        if not self.bridge.is_responsive:
            log.info("[Pengu] Startup check: the bridge is not responding; no failure warning.")
            return False
        sample = sample_client(self.lcu)
        if sample is None:
            log.info("[Pengu] Startup check: the client could not be checked (starting, restarting, in a game "
                     "or ambiguous); no failure warning.")
            return False
        if sample.core_loaded:
            log.info("[Pengu] Startup check: Pengu is loaded; no injection-failure warning.")
            return False
        if not client_matches_lcu(sample.identity, self.lcu):
            log.info("[Pengu] Startup check: the client checked is not the LCU's; no failure warning.")
            return False
        # The checks above take seconds: the plugin answering, Rose stopping or the
        # client leaving its idle phases meanwhile all cancel the warning
        if self._client_active() or self._stopped() or not self.bridge.is_responsive:
            return False
        if self.lcu.get('/lol-gameflow/v1/gameflow-phase', timeout=2, use_cache=False) not in SAFE_PHASES:
            return False
        if self._client_active() or self._stopped():
            return False
        log.error("[Pengu] Startup injection failure: client PID %s (created %s) has no Pengu module "
                  "%.0fs after the LCU connected, and Rose's plugin never reached the bridge.",
                  sample.identity[0], sample.identity[1], self.grace)
        self.on_failure(sample.identity[0])
        return True
