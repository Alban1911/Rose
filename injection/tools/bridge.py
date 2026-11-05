#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TCP client for the LeagueToolFlop (LTF) bridge.

Rose builds ``LeagueToolFlop.dll`` (see native/ltf/) and ``ltk_launcher.exe``
starts LTK Manager with that DLL injected into it. The DLL serves a
newline-delimited JSON API on 127.0.0.1 (port 46321-46340, discovered through
the registry, the port files, or a scan) which drives LTK Manager's own
backend over CDP: import/toggle/uninstall mods and start/stop its patcher.

The protocol is the one of ``LeagueFlop_controller.py`` from the LTF project:
one request line per connection, one JSON response line back. Every command
but hello/ping carries the token the DLL publishes in the user's registry
hive and local app data, so a web page posting lines to the port cannot
drive LTK Manager.
"""

from __future__ import annotations

import base64
import errno
import json
import os
import select
import socket
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from utils.core.logging import get_logger

log = get_logger()

PORT_RANGE_START = 46321
PORT_RANGE_END = 46340
REG_PATH = r"Software\LTKBridge"
REG_VALUE = "ApiPort"
REG_TOKEN = "ApiToken"
PORT_FILE = r"C:\Users\Public\LTKBridge.port"
BRIDGE_DIR_NAME = "LTKBridge"

# Windows retries a loopback connect to a closed port for about a second
# before refusing it, so a port that does not connect at once is not a bridge
CONNECT_TIMEOUT_S = 1.0
PROBE_TIMEOUT_S = 0.25
# Commands that only need the DLL itself answer fast; the Tauri-driven ones
# (toggle, patcher) go through CDP and take longer
FAST_TIMEOUT_S = 5.0
DEFAULT_TIMEOUT_S = 60.0
# The DLL gives LTK Manager three minutes to install a mod (a map or a
# voiceover is large): wait for that answer rather than give up first
IMPORT_TIMEOUT_S = 200.0

_IN_PROGRESS = {0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, 10035}


class BridgeUnavailable(RuntimeError):
    """The bridge inside ltk-manager.exe could not be reached."""


class BridgeCommandError(RuntimeError):
    """A bridge command answered with ok=false (or no usable answer)."""


def _bridge_dirs() -> List[Path]:
    """Where the DLL writes its port and token files: the desktop user's
    local app data (LTK Manager runs as that user, an elevated Rose may not),
    then this process's own."""
    dirs: List[Path] = []
    try:
        from utils.core.paths import get_user_data_dir

        dirs.append(get_user_data_dir().parent / BRIDGE_DIR_NAME)
    except Exception:
        pass
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidate = Path(local_appdata) / BRIDGE_DIR_NAME
        if candidate not in dirs:
            dirs.append(candidate)
    return dirs


def _probe(port: int, timeout: float = PROBE_TIMEOUT_S) -> Optional[dict]:
    """The hello response of the bridge on *port*, or None if it is not there."""
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    except OSError:
        return None
    try:
        sock.settimeout(FAST_TIMEOUT_S)
        sock.sendall(b'{"cmd":"hello"}\n')
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                return None
            buf += chunk
        response = json.loads(buf.split(b"\n", 1)[0].decode("utf-8", "replace"))
        if response.get("ok") is True and response.get("service") == "LTKBridge":
            return response
        return None
    except Exception:
        return None
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _listening_ports(ports: List[int], timeout: float = PROBE_TIMEOUT_S) -> List[int]:
    """The ports in *ports* that accept a connection, tried all at once.

    One at a time, every closed port costs the whole connect timeout (Windows
    retries a refused loopback connect), which made a scan of the range take
    eight seconds.
    """
    pending: Dict[socket.socket, int] = {}
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        try:
            code = sock.connect_ex(("127.0.0.1", port))
        except OSError:
            sock.close()
            continue
        if code in _IN_PROGRESS:
            pending[sock] = port
        else:
            sock.close()

    listening: List[int] = []
    deadline = time.monotonic() + timeout
    try:
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            socks = list(pending)
            _, writable, failed = select.select([], socks, socks, remaining)
            if not writable and not failed:
                break
            for sock in set(writable) | set(failed):
                port = pending.pop(sock)
                try:
                    if sock in writable and sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0:
                        listening.append(port)
                except OSError:
                    pass
                sock.close()
    finally:
        for sock in pending:
            sock.close()
    return sorted(listening)


def _port_from_registry() -> Optional[int]:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH)
        try:
            value, _ = winreg.QueryValueEx(key, REG_VALUE)
            return int(value)
        finally:
            winreg.CloseKey(key)
    except Exception:
        return None


def _port_from_file(path) -> Optional[int]:
    try:
        with open(path, "r", encoding="ascii", errors="ignore") as handle:
            return int(handle.read().strip())
    except Exception:
        return None


def token_candidates() -> List[Tuple[str, str]]:
    """(where, token) of every published token Rose can read, without
    duplicates: the token files, then the registry. A stale copy can sit in
    one place while the running bridge wrote another (#443)."""
    found: List[Tuple[str, str]] = []

    def add(where: str, token: Optional[str]) -> None:
        token = (token or "").strip()
        if token and all(token != known for _, known in found):
            found.append((where, token))

    for directory in _bridge_dirs():
        try:
            add(str(directory / "token.txt"),
                (directory / "token.txt").read_text(encoding="ascii", errors="ignore"))
        except OSError:
            continue
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH)
        try:
            value, _ = winreg.QueryValueEx(key, REG_TOKEN)
            add(f"HKCU\\{REG_PATH}", str(value))
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass
    return found


def read_token() -> Optional[str]:
    """The API token the running bridge published, if Rose can read it."""
    found = token_candidates()
    return found[0][1] if found else None


def _unauthorized(response: Dict[str, Any]) -> bool:
    """Whether the bridge refused a command over its token."""
    return response.get("ok") is False and str(response.get("error") or "").startswith("unauthorized")


def find_bridge(expected_pid: Optional[int] = None) -> Optional[Tuple[int, dict]]:
    """The port and hello answer of a bridge, or None.

    The published ports are tried first, then the whole range at once. With
    *expected_pid*, only the bridge inside that LTK Manager counts (a stale
    one, or another program's, is skipped).
    """

    def accept(port: Optional[int]) -> Optional[Tuple[int, dict]]:
        if not port:
            return None
        hello = _probe(port)
        if hello is None:
            return None
        if expected_pid is not None and hello.get("pid") != expected_pid:
            return None
        return port, hello

    seen = set()
    published = [_port_from_registry()]
    published += [_port_from_file(directory / "port.txt") for directory in _bridge_dirs()]
    published.append(_port_from_file(PORT_FILE))
    for port in published:
        if port and port not in seen:
            seen.add(port)
            found = accept(port)
            if found:
                return found

    candidates = [p for p in range(PORT_RANGE_START, PORT_RANGE_END + 1) if p not in seen]
    for port in _listening_ports(candidates):
        found = accept(port)
        if found:
            return found
    return None


def discover_port(expected_pid: Optional[int] = None) -> Optional[int]:
    """The port the bridge listens on, by registry/port file/scan, or None."""
    found = find_bridge(expected_pid)
    return found[0] if found else None


# LTK Manager's IPC errors carry no sentence (its frontend writes them): a
# patcher refusal is {code: "PATCHER", error: {kind: ...}}. LTK's own wording
# for each kind (ltk-manager-runtime patcher/error.rs)
LTK_PATCHER_MESSAGES = {
    "BUSY": "Stop the patcher before modifying mods",
    "ALREADY_RUNNING": "The patcher is already running",
    "NOT_RUNNING": "The patcher is not running",
    "UNSUPPORTED_PLATFORM": "The patcher is not yet available on this platform",
    "LEAGUE_ELEVATED": "League is set to run as administrator. Turn that off, then start the patcher again",
    "MANAGER_ELEVATED": (
        "LTK Manager is running as administrator. Reopen it normally, or turn on User Account Control "
        "if it is off, to start the patcher"
    ),
    "DLL_UNAVAILABLE": "no patcher DLL is available",
}


def _ltk_error_text(error: Dict[str, Any]) -> str:
    """An LTK Manager error ({code, ...its fields}) as one line: its code, then
    what it says (a bare "PATCHER" told nobody why the patcher refused, #430)."""
    code = str(error["code"])
    inner = error.get("error")
    if isinstance(inner, dict) and inner.get("kind"):
        kind = str(inner["kind"])
        text = LTK_PATCHER_MESSAGES.get(kind) or str(inner.get("message") or "")
        reason = inner.get("reason")  # DLL_UNAVAILABLE: why the DLL could not be delivered
        if reason:
            text = f"{text}: {reason if isinstance(reason, str) else json.dumps(reason)}"
        if inner.get("stage"):  # INJECTION_FAILED: the host never came up, or the game was not patched
            kind = f"{kind} ({inner['stage']})"
        return f"{code} {kind}: {text}" if text else f"{code} {kind}"
    detail = error.get("message") or error.get("detail")
    if detail:
        return f"{code}: {detail}"
    rest = {key: value for key, value in error.items() if key != "code"}
    return f"{code} {json.dumps(rest)[:200]}" if rest else code


def _error_text(response: Dict[str, Any]) -> str:
    """The reason a command failed, from wherever the DLL or LTK put it."""
    nested = response.get("response")
    for candidate in (response.get("error"), nested.get("error") if isinstance(nested, dict) else None):
        if isinstance(candidate, dict):
            if candidate.get("code"):
                candidate = _ltk_error_text(candidate)
            else:
                candidate = candidate.get("message") or json.dumps(candidate)
        if candidate:
            return str(candidate)
    return json.dumps(response)[:300]


class LtkBridge:
    """One connection-free session with the bridge (every call opens its own)."""

    def __init__(self, port: Optional[int] = None, pid: Optional[int] = None):
        self._port = port
        # The LTK Manager process the bridge runs in (from its hello)
        self.pid = pid
        self._token: Optional[str] = None

    @property
    def port(self) -> int:
        if self._port is None:
            found = find_bridge(self.pid)
            if found is None:
                raise BridgeUnavailable("LTKBridge API is not reachable")
            self._port, hello = found
            self.pid = hello.get("pid", self.pid)
        return self._port

    def _send(self, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        port = self.port
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=CONNECT_TIMEOUT_S)
        except OSError as exc:
            raise BridgeUnavailable(f"LTKBridge is not reachable on port {port}: {exc}") from exc
        # Once the line is out, the command may run even if no answer comes
        # back: it is never sent again (an import or toggle would repeat)
        try:
            with sock:
                sock.settimeout(timeout)
                sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
                buf = b""
                while b"\n" not in buf:
                    chunk = sock.recv(65536)
                    if not chunk:
                        raise ConnectionError("the bridge closed the connection")
                    buf += chunk
            return json.loads(buf.split(b"\n", 1)[0].decode("utf-8", "replace"))
        except (OSError, ValueError) as exc:
            raise BridgeUnavailable(f"LTKBridge request failed: {exc}") from exc

    def request(self, payload: Dict[str, Any], timeout: float = DEFAULT_TIMEOUT_S) -> Dict[str, Any]:
        """Send one command and return its JSON answer."""
        if payload.get("cmd") in ("hello", "ping"):
            return self._send(payload, timeout)
        if self._token is None:
            self._token = read_token()
        response = self._send({**payload, "token": self._token or ""}, timeout)
        if not _unauthorized(response):
            return response
        # Refused before it ran: the bridge restarted with a new token, or the
        # copy Rose read first is a stale one while the bridge wrote another
        tried = {self._token}
        candidates = [("the token files", read_token())] + token_candidates()
        for where, candidate in candidates:
            if not candidate or candidate in tried:
                continue
            tried.add(candidate)
            retry = self._send({**payload, "token": candidate}, timeout)
            if not _unauthorized(retry):
                log.info(f"[BRIDGE] The bridge accepted the token published in {where}")
                self._token = candidate
                return retry
            response = retry
        log.warning(
            f"[BRIDGE] The bridge refused every published token ({len(tried - {None})} tried, "
            f"{len(candidates) - 1} published copies found)"
        )
        return response

    def _ok(self, payload: Dict[str, Any], timeout: float = DEFAULT_TIMEOUT_S) -> Dict[str, Any]:
        """Send a command and fail when the bridge reports ok=false."""
        response = self.request(payload, timeout=timeout)
        if response.get("ok") is False:
            raise BridgeCommandError(f"{payload.get('cmd')} failed: {_error_text(response)}")
        return response

    # -- session -----------------------------------------------------------
    def hello(self) -> Dict[str, Any]:
        return self.request({"cmd": "hello"}, timeout=FAST_TIMEOUT_S)

    def ping(self) -> Dict[str, Any]:
        return self.request({"cmd": "ping"}, timeout=FAST_TIMEOUT_S)

    def status(self) -> Dict[str, Any]:
        return self.request({"cmd": "status"}, timeout=FAST_TIMEOUT_S)

    def alive(self) -> bool:
        try:
            return self.ping().get("ok") is True
        except BridgeUnavailable:
            return False

    # -- library -----------------------------------------------------------
    def list_mods(self) -> Dict[str, Any]:
        return self.request({"cmd": "list"}, timeout=DEFAULT_TIMEOUT_S)

    def library(self) -> List[Dict[str, Any]]:
        """The installed mods.

        Raises BridgeCommandError when LTK Manager does not answer with its
        library: an empty list would read as "nothing installed", and Rose
        would then take every entry for one it just created.
        """
        response = self.list_mods()
        library = response.get("library")
        if response.get("ok") is False or not isinstance(library, list):
            raise BridgeCommandError(f"list failed: {_error_text(response)}")
        return library

    def import_fantome(self, path: str, name: Optional[str] = None) -> Dict[str, Any]:
        """Install the archive at *path* into LTK Manager's library, as it is."""
        payload: Dict[str, Any] = {"cmd": "import", "path": path}
        if name:
            payload["name"] = name
        return self._ok(payload, timeout=IMPORT_TIMEOUT_S)

    def import_fantome_bytes(self, data: bytes, name: str) -> Dict[str, Any]:
        """Install an archive LTK Manager cannot read from Rose's folder, sent inline."""
        payload: Dict[str, Any] = {
            "cmd": "import",
            "data_b64": base64.b64encode(data).decode("ascii"),
            "name": name,
        }
        return self._ok(payload, timeout=IMPORT_TIMEOUT_S)

    def toggle(self, target: str, enabled: bool = True) -> Dict[str, Any]:
        return self._ok({"cmd": "toggle", "target": target, "enabled": enabled})

    def uninstall(self, target: str) -> Dict[str, Any]:
        return self._ok({"cmd": "uninstall", "target": target})

    # -- patcher -----------------------------------------------------------
    def start_patcher(self) -> Dict[str, Any]:
        return self._ok({"cmd": "start_patcher"})

    def stop_patcher(self) -> Dict[str, Any]:
        return self._ok({"cmd": "stop_patcher"})

    def patcher_status(self) -> Dict[str, Any]:
        return self.request({"cmd": "patcher_status"}, timeout=DEFAULT_TIMEOUT_S)

    def kill(self) -> Dict[str, Any]:
        """Ask ltk-manager.exe to exit (the answer may never arrive)."""
        try:
            return self.request({"cmd": "kill"}, timeout=FAST_TIMEOUT_S)
        except BridgeUnavailable:
            return {"ok": True, "note": "connection dropped - ltk-manager terminating"}

    @classmethod
    def wait_for_bridge(
        cls,
        timeout: float = 30.0,
        expected_pid: Optional[int] = None,
        cancelled: Optional[Callable[[], bool]] = None,
    ) -> "LtkBridge":
        """A usable bridge, waiting up to *timeout* seconds for the DLL to come up.

        *expected_pid* is the LTK Manager the launcher started: a bridge in
        any other process is not this one. *cancelled* ends the wait early.
        """
        deadline = time.monotonic() + timeout
        while True:
            found = find_bridge(expected_pid)
            if found is not None:
                port, hello = found
                return cls(port, pid=hello.get("pid"))
            if cancelled is not None and cancelled():
                raise BridgeUnavailable("the wait for LTKBridge was cancelled")
            if time.monotonic() >= deadline:
                raise BridgeUnavailable(
                    f"LTKBridge did not come up within {timeout:.0f}s "
                    "(the bridge DLL runs inside ltk-manager.exe)"
                )
            time.sleep(0.25)
