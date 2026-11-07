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
import re
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import List, Optional, Tuple

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


def _process_token_rids(pid: int) -> Optional[tuple]:
    """(integrity level RID, user RID) of a process's token, or None when it
    can't be read. _declare_signatures() must have run."""
    kernel32, advapi32 = ctypes.windll.kernel32, ctypes.windll.advapi32
    process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
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
    return None if integrity is None else (integrity, user_rid)


def process_elevated(pid: int) -> Optional[bool]:
    """Whether a process runs as administrator (high integrity), or None when
    its token can't be read."""
    if sys.platform != "win32" or not pid:
        return None
    try:
        _declare_signatures()
        rids = _process_token_rids(int(pid))
    except Exception as e:  # a diagnostic must never stop Rose
        log.debug(f"[ACCOUNT] Could not read the token of process {pid}: {e}")
        return None
    return None if rids is None else rids[0] >= SECURITY_MANDATORY_HIGH_RID


def shell_account() -> Optional[ShellAccount]:
    """What the Windows shell runs as, or None when it can't be told (no
    shell window, not Windows, an API failure)."""
    if sys.platform != "win32":
        return None
    try:
        user32 = ctypes.windll.user32
        _declare_signatures()
        hwnd = user32.GetShellWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rids = _process_token_rids(pid.value)
        if rids is None:
            return None
        integrity, user_rid = rids
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


# League started with "Run as administrator" (or from an elevated Riot Client):
# LTK Manager's own check only reads the compatibility settings, so its
# patcher starts, never attaches to the game, and no error shows (#431)
LEAGUE_REPORT_CODE = "LEAGUE_ELEVATED"
LEAGUE_MESSAGE = "LTK Manager can't apply skins: the League client runs as administrator."
LEAGUE_HINT = (
    "Close League and the Riot Client completely (also from the system tray), then start the Riot Client "
    "normally, not with \"Run as administrator\". If it still starts as administrator, untick \"Run this "
    "program as an administrator\" in the Compatibility tab of the Properties of RiotClientServices.exe, "
    "LeagueClient.exe and League of Legends.exe (also under \"Change settings for all users\")."
)


# Windows' compatibility settings ("Run this program as an administrator"):
# one value per program, named by its path, in the user's hive and in the
# machine's ("Change settings for all users")
COMPAT_LAYERS_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
# LTK Manager refuses every patcher start while any program whose file name
# starts with these has a RUNASADMIN layer, wherever it is (also a copy from an
# older install): ltk-manager-runtime diagnostics/compat_flags.rs (#430)
RUN_AS_ADMIN_PREFIXES = ("League", "Riot")
LEAGUE_SETTING_MESSAGE = "LTK Manager can't apply skins: League is set to run as administrator"
LEAGUE_SETTING_HINT = (
    "Untick \"Run this program as an administrator\" in the Compatibility tab of the Properties of each "
    "program listed (for one marked \"all users\", under \"Change settings for all users\"), then restart "
    "League. For a program that no longer exists, delete its value under "
    f"HKEY_CURRENT_USER (or HKEY_LOCAL_MACHINE for \"all users\")\\{COMPAT_LAYERS_KEY} with regedit."
)


def league_run_as_admin_entries() -> List[Tuple[str, str]]:
    """(hive, program path) of every League/Riot program set to run as
    administrator, as LTK Manager reads them."""
    return _run_as_admin_entries(lambda program: program.startswith(RUN_AS_ADMIN_PREFIXES))


# LTK Manager's own programs set to run as administrator: Windows then refuses
# to start them unelevated (error 740), so the launcher cannot start LTK
# Manager as the desktop user and Rose's bridge never reaches its browser
# (#468), or LTK Manager cannot start its patcher host (#456)
LTK_PROGRAMS = ("ltk-manager.exe", "ltk manager.exe", "ltk_patcher_host.exe")
LTK_REPORT_CODE = "LTK_ELEVATED"
LTK_SETTING_MESSAGE = "LTK Manager can't apply skins: LTK Manager is set to run as administrator"
LTK_SETTING_HINT = (
    "Untick \"Run this program as an administrator\" in the Compatibility tab of the Properties of each "
    "program listed (for one marked \"all users\", under \"Change settings for all users\"), then close LTK "
    "Manager (also from the system tray). For a program that no longer exists, delete its value under "
    f"HKEY_CURRENT_USER (or HKEY_LOCAL_MACHINE for \"all users\")\\{COMPAT_LAYERS_KEY} with regedit."
)


def ltk_run_as_admin_entries() -> List[Tuple[str, str]]:
    """(hive, program path) of every LTK Manager program set to run as administrator."""
    return _run_as_admin_entries(lambda program: program.lower() in LTK_PROGRAMS)


def check_ltk_settings() -> bool:
    """Warn when LTK Manager's programs are set to run as administrator,
    naming them; clear the warning once none is. Returns whether any is."""
    from utils.core.issue_reporter import remove_issues, report_issue
    try:
        entries = ltk_run_as_admin_entries()
    except Exception as e:  # a diagnostic must never stop Rose
        log.debug(f"[ACCOUNT] Could not read the compatibility settings: {e}")
        return False
    if not entries:
        remove_issues(lambda line, fix: LTK_SETTING_MESSAGE in line)
        return False
    programs = ", ".join(path + (" [all users]" if hive == "HKLM" else "") for hive, path in entries)
    message = f"{LTK_SETTING_MESSAGE} ({programs})."
    log.warning(f"[ACCOUNT] {message}")
    report_issue(LTK_REPORT_CODE, "error", message, details={"programs": programs}, hint=LTK_SETTING_HINT,
                 dedupe_window_s=600.0)
    return True


def _run_as_admin_entries(matches) -> List[Tuple[str, str]]:
    """(hive, program path) of every program whose file name *matches* and
    that Windows' compatibility settings run as administrator."""
    if sys.platform != "win32":
        return []
    import winreg
    entries = []
    for root, hive in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
        try:
            key = winreg.OpenKey(root, COMPAT_LAYERS_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        except OSError:
            continue
        with key:
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                program = re.split(r"[\\/]", name)[-1]
                if matches(program) and "RUNASADMIN" in str(value).upper():
                    entries.append((hive, name))
    return entries


def _check_league_settings() -> bool:
    """Warn when League/Riot programs are set to run as administrator, naming
    them; clear the warning once none is. Returns whether any is."""
    from utils.core.issue_reporter import remove_issues, report_issue
    try:
        entries = league_run_as_admin_entries()
    except Exception as e:  # a diagnostic must never stop Rose
        log.debug(f"[ACCOUNT] Could not read the compatibility settings: {e}")
        return False
    if not entries:
        remove_issues(lambda line, fix: LEAGUE_SETTING_MESSAGE in line)
        return False
    programs = ", ".join(path + (" [all users]" if hive == "HKLM" else "") for hive, path in entries)
    message = f"{LEAGUE_SETTING_MESSAGE} ({programs})."
    log.warning(f"[ACCOUNT] {message}")
    report_issue(LEAGUE_REPORT_CODE, "error", message, details={"programs": programs}, hint=LEAGUE_SETTING_HINT)
    return True


def check_league_client(pid: int) -> Optional[bool]:
    """Warn (log and Troubleshooting) when League is set to run as
    administrator (LTK Manager refuses to patch then), or when the League
    client runs as administrator although Windows does not run every program
    so (LTK Manager's patcher, unelevated, can't reach the game it starts).
    Each warning goes away once it no longer applies. Returns whether League
    runs or is set to run as administrator (None when that can't be told)."""
    if _check_league_settings():
        return True  # it also elevates the client: the setting is what to fix
    elevated = process_elevated(pid)
    if elevated is None:
        return None
    from utils.core.issue_reporter import remove_issues, report_issue
    if not elevated:
        remove_issues(lambda line, fix: LEAGUE_MESSAGE in line)
        return False
    shell = shell_account()
    if shell is not None and shell.elevated:
        return True  # every program runs as administrator: the startup check says so
    log.warning(f"[ACCOUNT] {LEAGUE_MESSAGE} (pid {pid})")
    report_issue(LEAGUE_REPORT_CODE, "error", LEAGUE_MESSAGE, details={"pid": pid}, hint=LEAGUE_HINT)
    return True
