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
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]


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


def _token_user_sid(token) -> Optional[str]:
    """The string SID ("S-1-5-21-...") of the user a token belongs to."""
    advapi32, kernel32 = ctypes.windll.advapi32, ctypes.windll.kernel32
    size = wintypes.DWORD()
    advapi32.GetTokenInformation(token, TOKEN_USER_CLASS, None, 0, ctypes.byref(size))
    if not size.value:
        return None
    buffer = ctypes.create_string_buffer(size.value)
    if not advapi32.GetTokenInformation(token, TOKEN_USER_CLASS, buffer, size, ctypes.byref(size)):
        return None
    sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
    text = ctypes.c_void_p()
    if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)) or not text.value:
        return None
    try:
        return ctypes.wstring_at(text.value)
    finally:
        kernel32.LocalFree(text)


def _process_user_sid(pid: Optional[int]) -> Optional[str]:
    """The string SID of the user a process runs as (this process when *pid*
    is None), or None when it can't be read. _declare_signatures() must have run."""
    kernel32, advapi32 = ctypes.windll.kernel32, ctypes.windll.advapi32
    own = pid is None
    if own:
        process = kernel32.GetCurrentProcess()
    else:
        process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return None
    try:
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            return _token_user_sid(token)
        finally:
            kernel32.CloseHandle(token)
    finally:
        if not own:
            kernel32.CloseHandle(process)


def _shell_pid() -> int:
    """The Windows shell's (explorer.exe's) process id, 0 without a shell
    window. _declare_signatures() must have run."""
    user32 = ctypes.windll.user32
    hwnd = user32.GetShellWindow()
    if not hwnd:
        return 0
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def desktop_user_sid() -> Optional[str]:
    """The desktop user's SID when Rose runs as another Windows account than
    the one signed in (a standard account, elevated with an administrator's
    password): HKEY_CURRENT_USER is then the administrator's, and the desktop
    user's settings are under HKEY_USERS\\<SID>. None when Rose runs as the
    desktop user, or when it can't be told."""
    if sys.platform != "win32":
        return None
    try:
        _declare_signatures()
        pid = _shell_pid()
        if not pid:
            return None
        shell, own = _process_user_sid(pid), _process_user_sid(None)
    except Exception as e:  # a diagnostic must never stop Rose
        log.debug(f"[ACCOUNT] Could not tell the desktop user from Rose's: {e}")
        return None
    if not shell or not own or shell.upper() == own.upper():
        return None
    return shell


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
        _declare_signatures()
        pid = _shell_pid()
        if not pid:
            return None
        rids = _process_token_rids(pid)
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


# Rose's own launcher set to run as administrator. The elevated launcher
# starts a copy of itself with the desktop user's token, which gives LTK
# Manager explorer.exe as its parent; with that setting, Windows refuses the
# copy (error 740), LTK Manager starts as the launcher's child, and its
# patcher refuses the overlay (VRF00000007). The setting is on Rose's own
# program, so Rose takes it off rather than asking the user to. Only that
# layer goes: any other one on the program (Windows 8 mode...) stays
LAUNCHER_PROGRAMS = ("ltk_launcher.exe",)
LAUNCHER_REPORT_CODE = "LAUNCHER_ELEVATED"
LAUNCHER_SETTING_MESSAGE = "LTK Manager can't apply skins: Rose's ltk_launcher.exe is set to run as administrator"
LAUNCHER_SETTING_HINT = (
    "Rose could not take that setting off by itself. Untick \"Run this program as an administrator\" in the "
    "Compatibility tab of the Properties of ltk_launcher.exe, in Rose's _internal\\injection\\tools folder (for "
    "one marked \"all users\", under \"Change settings for all users\"), then restart Rose. For a program that "
    "no longer exists, delete its value under HKEY_CURRENT_USER (or HKEY_LOCAL_MACHINE for \"all users\")"
    f"\\{COMPAT_LAYERS_KEY} with regedit."
)
RUN_AS_ADMIN_LAYER = "RUNASADMIN"


def without_run_as_admin(value: str) -> Optional[str]:
    """A compatibility setting's value without its RUNASADMIN layer, or None
    when no layer is left (the value then goes: its "~" or "$" flag alone
    means nothing)."""
    kept = [part for part in str(value).split() if part.upper() != RUN_AS_ADMIN_LAYER]
    return " ".join(kept) if any(part[0].isalnum() for part in kept) else None


def clear_launcher_run_as_admin() -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """Take the RUNASADMIN layer off every ltk_launcher.exe in Windows'
    compatibility settings: this account's, the machine's ("all users"), and
    the desktop user's when Rose runs as another account. Returns ((hive,
    program path) taken off, (hive, program path) Rose could not change)."""
    if sys.platform != "win32":
        return [], []
    import winreg
    keys = [
        ("HKCU", winreg.HKEY_CURRENT_USER, COMPAT_LAYERS_KEY),
        ("HKLM", winreg.HKEY_LOCAL_MACHINE, COMPAT_LAYERS_KEY),
    ]
    desktop_sid = desktop_user_sid()
    if desktop_sid:
        keys.append(("HKU", winreg.HKEY_USERS, f"{desktop_sid}\\{COMPAT_LAYERS_KEY}"))
    cleared, left = [], []
    for hive, root, subkey in keys:
        writable = True
        try:
            key = winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY)
        except PermissionError:
            # Rose not elevated: the machine's settings can still be read
            writable = False
            try:
                key = winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
            except OSError:
                continue
        except OSError:
            continue  # no compatibility setting there
        with key:
            # Every value first: a deleted one would shift the indexes
            values, index = [], 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                program = re.split(r"[\\/]", name)[-1].lower()
                if program in LAUNCHER_PROGRAMS and RUN_AS_ADMIN_LAYER in str(value).upper():
                    values.append((name, value))
            for name, value in values:
                if not writable:
                    left.append((hive, name))
                    continue
                kept = without_run_as_admin(value)
                try:
                    if kept is None:
                        winreg.DeleteValue(key, name)
                    else:
                        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, kept)
                except OSError as e:
                    log.debug(f"[ACCOUNT] Could not change the compatibility setting of {name} ({hive}): {e}")
                    left.append((hive, name))
                else:
                    cleared.append((hive, name))
    return cleared, left


def check_launcher_settings() -> bool:
    """Take "Run as administrator" off Rose's own ltk_launcher.exe; warn (log
    and Troubleshooting) about any such setting Rose could not take off, and
    clear the warning once none is left. Returns whether one is still set."""
    from utils.core.issue_reporter import remove_issues, report_issue
    try:
        cleared, left = clear_launcher_run_as_admin()
    except Exception as e:  # a diagnostic must never stop Rose
        log.debug(f"[ACCOUNT] Could not read the compatibility settings: {e}")
        return False
    for hive, path in cleared:
        log.info(f"[ACCOUNT] Took \"Run as administrator\" off {path} ({hive}): Windows refused to start it "
                 "for the desktop user, so LTK Manager could not get explorer.exe as its parent")
    if not left:
        remove_issues(lambda line, fix: LAUNCHER_SETTING_MESSAGE in line)
        return False
    programs = ", ".join(path + (" [all users]" if hive == "HKLM" else "") for hive, path in left)
    message = f"{LAUNCHER_SETTING_MESSAGE} ({programs})."
    log.warning(f"[ACCOUNT] {message}")
    report_issue(LAUNCHER_REPORT_CODE, "error", message, details={"programs": programs}, hint=LAUNCHER_SETTING_HINT,
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
