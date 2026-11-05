#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Whether Windows runs every program as administrator on this account.

Rose starts LTK Manager unelevated, with the Windows shell (explorer.exe) as
its parent and the shell's token. LTK Manager refuses to start its patcher as
administrator, so when the shell itself runs as administrator, no skin can
apply. That happens on the built-in Administrator account (some custom Windows
builds such as KernelOS set it up as the user's account) and with User Account
Control turned off. Rose runs as administrator either way, so its own token
says nothing: the shell's integrity level is what tells.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional

from utils.core.logging import get_logger

log = get_logger()

SECURITY_MANDATORY_HIGH_RID = 0x3000
BUILTIN_ADMINISTRATOR_RID = 500
TOKEN_QUERY = 0x0008
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_USER_CLASS = 1
TOKEN_INTEGRITY_LEVEL_CLASS = 25
UAC_POLICY_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"

REPORT_CODE = "WINDOWS_ADMIN_SHELL"


@dataclass(frozen=True)
class ShellAccount:
    """What the Windows shell runs as."""
    elevated: bool  # high integrity: every program it starts runs as administrator
    builtin_administrator: bool
    uac_disabled: bool

    @property
    def reason(self) -> str:
        if self.builtin_administrator:
            return "builtin"
        if self.uac_disabled:
            return "uac"
        return "other"


def _declare_signatures() -> None:
    """Argument and result types of the calls used here (handles are pointer-sized)."""
    user32, kernel32, advapi32 = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.advapi32
    user32.GetShellWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
    advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]


def _token_sid_last_rid(token, info_class: int) -> Optional[int]:
    """The last sub-authority of the SID a token information class holds
    (TokenUser and TokenIntegrityLevel both start with a SID_AND_ATTRIBUTES)."""
    advapi32 = ctypes.windll.advapi32
    size = wintypes.DWORD()
    advapi32.GetTokenInformation(token, info_class, None, 0, ctypes.byref(size))
    if not size.value:
        return None
    buffer = ctypes.create_string_buffer(size.value)
    if not advapi32.GetTokenInformation(token, info_class, buffer, size, ctypes.byref(size)):
        return None
    sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
    count = advapi32.GetSidSubAuthorityCount(sid)[0]
    if not count:
        return None
    return advapi32.GetSidSubAuthority(sid, count - 1)[0]


def _uac_disabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UAC_POLICY_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "EnableLUA")
        return int(value) == 0
    except (OSError, ValueError, TypeError):
        return False


def shell_account() -> Optional[ShellAccount]:
    """What the Windows shell runs as, or None when it can't be told (no
    shell window, not Windows, an API failure)."""
    if sys.platform != "win32":
        return None
    try:
        user32, kernel32, advapi32 = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.advapi32
        _declare_signatures()
        hwnd = user32.GetShellWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not process:
            return None
        try:
            token = wintypes.HANDLE()
            if not advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
                return None
            try:
                integrity = _token_sid_last_rid(token, TOKEN_INTEGRITY_LEVEL_CLASS)
                user_rid = _token_sid_last_rid(token, TOKEN_USER_CLASS)
            finally:
                kernel32.CloseHandle(token)
        finally:
            kernel32.CloseHandle(process)
        if integrity is None:
            return None
        return ShellAccount(
            elevated=integrity >= SECURITY_MANDATORY_HIGH_RID,
            builtin_administrator=user_rid == BUILTIN_ADMINISTRATOR_RID,
            uac_disabled=_uac_disabled(),
        )
    except Exception as e:  # a diagnostic must never stop Rose
        log.debug(f"[ACCOUNT] Could not read the Windows shell's token: {e}")
        return None


MESSAGES = {
    "builtin": "LTK Manager can't apply skins: this is Windows' built-in Administrator account, "
               "which runs every program as administrator.",
    "uac": "LTK Manager can't apply skins: User Account Control is turned off, "
           "so Windows runs every program as administrator.",
    "other": "LTK Manager can't apply skins: Windows runs every program as administrator on this account.",
}
HINTS = {
    "builtin": "Use Rose, League and LTK Manager from a regular Windows account "
               "(Settings > Accounts > Other users > Add account).",
    "uac": "Turn User Account Control back on (search Windows for \"Change User Account Control settings\" "
           "and move the slider above \"Never notify\"), then restart the PC.",
    "other": "Use a regular Windows account, with User Account Control on.",
}


def check_windows_account() -> Optional[ShellAccount]:
    """Warn (log and Troubleshooting) when Windows runs every program as
    administrator: LTK Manager would then refuse to apply any skin."""
    account = shell_account()
    if account is None or not account.elevated:
        return account
    from utils.core.issue_reporter import report_issue
    message = MESSAGES[account.reason]
    log.warning(f"[ACCOUNT] {message} (built-in Administrator: {account.builtin_administrator}, "
                f"UAC off: {account.uac_disabled})")
    report_issue(
        REPORT_CODE,
        "error",
        message,
        details={"reason": account.reason},
        hint=HINTS[account.reason],
    )
    return account
