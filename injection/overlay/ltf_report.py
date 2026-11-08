#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re

from utils.core.issue_reporter import report_issue
from utils.core.logging import get_logger

log = get_logger()

# Exit code of a process another program terminated (DBG_TERMINATE_PROCESS),
# most often an antivirus
KILLED_EXIT_CODE = 0x40010004

# The patcher's verdict when the game loaded its files before the DLL hooked it
LATE_JOIN_MESSAGE = "joined too late"
# The DLL's host verification refusing the overlay (docs/ltf-vrf-host-verification.md)
OVERLAY_REFUSED_MESSAGE = "host verification failed"
SIGNATURE_FAILURE_MESSAGE = "Windows could not verify the signature of LTK Manager's files"
NOT_ATTACHED_MESSAGE = "LTK Manager's patcher never got into the game"
OVERLAY_DISABLED_MESSAGE = "disabled the overlay"
CDP_FAILURE_MARKER = "cdp unavailable"
CDP_UNREACHABLE_REASON = "Rose's bridge could not reach LTK Manager's built-in browser (CDP unavailable or timed out)"
# Tauri rejecting a command LTK Manager does not declare ("Command
# plugin:library|get_installed_mods not allowed by ACL")
LTK_ACL_REFUSAL = "not allowed by acl"
LTF_LOGS_HINT = "Details are in ltk_api.log and ltk_launcher.log, in the ltk folder of Rose's logs."


def ltk_failure_cause(reason: str) -> str:
    """Why the LTF session failed, from the reason Rose reported: what to do
    about it depends on it (Troubleshooting shows a hint for each)"""
    lowered = reason.lower()
    if CDP_FAILURE_MARKER in lowered or "built-in browser" in lowered:
        return "cdp"
    # LTK Manager refuses to patch across an elevation boundary (ADR-0074):
    # League set to run as administrator, or LTK Manager itself elevated
    if "league_elevated" in lowered or "league is set to run as administrator" in lowered:
        return "league_admin"
    if "manager_elevated" in lowered or "ltk manager is running as administrator" in lowered:
        return "manager_admin"
    # Windows refusing to start one of LTK Manager's programs unelevated: one is
    # set to run as administrator (#456: "os error 740" spawning its host)
    if "os error 740" in lowered or "requires elevation" in lowered:
        return "ltk_admin"
    # LTK Manager could not get its patcher from its delivery service: the
    # service refused it (#482), or the request never reached it, blocked on
    # the user's PC or network (#487: "error sending request for url")
    if "no patcher dll is available" in lowered:
        return "delivery_unreachable" if "error sending request" in lowered else "delivery"
    if "ltk_patcher_host.exe not found" in lowered:
        return "host_missing"
    if OVERLAY_DISABLED_MESSAGE in lowered:
        return "disabled"
    if NOT_ATTACHED_MESSAGE.lower() in lowered:
        return "not_attached"
    if "corruptarchive" in lowered:
        return "corrupt"
    if "recorded an incident" in lowered:
        return "incident"
    # Tauri's answer to a command the app does not declare: an LTK Manager
    # older than the commands Rose drives (its library plugin came in v1.24.1).
    # Before "import": an install refused that way is no disk problem (#473)
    if LTK_ACL_REFUSAL in lowered:
        return "outdated"
    if "import" in lowered:
        return "import"
    if "already open" in lowered:
        return "running"
    if LATE_JOIN_MESSAGE in lowered:
        return "late"
    if SIGNATURE_FAILURE_MESSAGE.lower() in lowered:
        return "signature"
    if OVERLAY_REFUSED_MESSAGE in lowered or "refused the overlay" in lowered:
        return "refused"
    if lowered.startswith("could not start"):
        return "start"
    if "bridge" in lowered:
        return "bridge"
    exit_code = re.search(r"exited with code (-?\d+)", reason)
    if exit_code:
        code = int(exit_code.group(1)) & 0xFFFFFFFF
        if code == KILLED_EXIT_CODE:
            return "killed"
        # NTSTATUS errors (access violation...): LTK Manager itself crashed
        if code >= 0xC0000000:
            return "crashed"
    return "unknown"


def cdp_unreachable(error: BaseException) -> bool:
    """Whether a bridge command failed because LTK Manager's browser did not answer."""
    return CDP_FAILURE_MARKER in str(error).lower()


def cdp_unreachable_reason() -> str:
    """CDP_UNREACHABLE_REASON, with its usual cause when this account has it:
    both PCs where the browser never answered ran every program as
    administrator (#425 built-in Administrator, #426 UAC turned off)."""
    try:
        from utils.system.windows_account import shell_account
        account = shell_account()
    except Exception:
        account = None
    if account is not None and account.elevated:
        return f"{CDP_UNREACHABLE_REASON}; Windows runs every program as administrator on this account"
    return CDP_UNREACHABLE_REASON


def ltk_failure_hint(reason: str) -> str:
    """What the user can do about a session failure, by the cause it reported."""
    logs = LTF_LOGS_HINT
    report = "report it with rose_*.log and those logs"
    cause = ltk_failure_cause(reason)
    if cause == "cdp":
        return ("Rose drives LTK Manager through the debugging port of its built-in browser, which did not "
                "answer. Restart your PC, then retry. If it keeps happening, use a regular Windows account (not "
                f"the built-in Administrator) and check that your antivirus does not block LTK Manager. {logs}")
    if cause == "league_admin":
        return ("League is set to run as administrator, and LTK Manager does not patch it then. Right-click "
                "League of Legends.exe and LeagueClient.exe (in the League of Legends folder) > Properties > "
                'Compatibility, untick "Run this program as an administrator" (also under "Change settings '
                f'for all users"), then restart League. {logs}')
    if cause == "manager_admin":
        return ("LTK Manager runs as administrator, and it does not patch League then. Turn User Account "
                "Control back on, or use a regular Windows account (not the built-in Administrator), then "
                f"restart the PC. {logs}")
    if cause == "host_missing":
        return ("LTK Manager's own patcher (ltk_patcher_host.exe) is missing from its folder, most often "
                "removed by an antivirus. Reinstall LTK Manager, then add its folder (C:\\Program Files\\LTK "
                f"Manager) to your antivirus exclusions. {logs}")
    if cause == "disabled":
        return ("LTK Manager's integrity check turned the overlay off because of a mod: the reason names its "
                "WAD. LTK Manager refuses a skin made of another skin's files. For a custom skin, use another "
                "one; for one of Rose's skins or chromas, the package is at fault: pick another skin or chroma "
                f"and report it at github.com/Alban1911/LeagueSkins/issues. {logs}")
    if cause == "ltk_admin":
        return ("Windows refuses to start one of LTK Manager's programs without administrator rights: it is set "
                "to run as administrator. Untick \"Run this program as an administrator\" in the Compatibility "
                "tab of the Properties of ltk-manager.exe and ltk_patcher_host.exe (also under \"Change settings "
                f"for all users\"), then close LTK Manager (also from the system tray) and retry. {logs}")
    if cause == "delivery":
        return ("LTK Manager could not download its patcher: LTK's delivery service refused the request (the "
                "reason above). Rose cannot change that. Retry later, or from another network (without a VPN "
                f"or proxy). {logs}")
    if cause == "delivery_unreachable":
        return ("LTK Manager could not connect to LTK's delivery service (patcher.leaguetoolkit.dev) to "
                "download its patcher: something on this PC or network blocks it. Allow ltk-manager.exe "
                "through your firewall and antivirus, turn off any VPN, proxy or DNS blocker, then retry. "
                f"{logs}")
    if cause == "corrupt":
        return ("League could not read a file of the overlay, most often a mod made for an older patch. Turn "
                "your mods off, then back on one at a time to find it; LTK Manager's incident file names the "
                f"WAD and the mods that wrote it. {logs}")
    if cause == "incident":
        return (f"LTK Manager's incident file says what went wrong in the game and which mods it suspects. {logs}")
    if cause == "start":
        return ("Rose could not start the LTK patcher. Check that ltk_launcher.exe and LeagueToolFlop.dll "
                f"are still in Rose's tools folder: an antivirus may have removed them. {logs}")
    if cause == "running":
        return ("Close LTK Manager (also from the system tray), then retry: Rose starts it with its "
                f"bridge and closes it again after the game. {logs}")
    if cause == "late":
        return ("The game started before the patcher was scanning: the skin changed in the last seconds "
                "of the countdown and LTK Manager needed longer to build its overlay (a skin that also "
                "changes a map file takes seconds), or LTK Manager was slow to start. Pick the skin a few "
                f"seconds earlier, or retry the next game. {logs}")
    if cause == "signature":
        return ("LTK Manager's patcher checks the digital signature of LTK Manager's own files, and Windows "
                "could not verify it: a file was modified or damaged. Reinstall LTK Manager from its official "
                f"release (github.com/LeagueToolkit/ltk-manager/releases), then retry. {logs}")
    if cause == "refused":
        return ("LTK Manager's patcher refused to apply the overlay. Update Rose (its launcher starts LTK "
                f"Manager the way the patcher expects); if it still happens, {report}. {logs}")
    if cause == "not_attached":
        return ("LTK Manager's patcher found the game but could not get into it, so the game ran without the "
                "overlay. Check that League and the Riot Client are not set to run as administrator and that "
                f"your antivirus does not block LTK Manager, then retry; if it happens every game, {report}. "
                f"{logs}")
    if cause == "bridge":
        return (f"LTK Manager closed while the game was running. Retry the next game; "
                f"if it happens every game, {report}. {logs}")
    if cause == "outdated":
        return ("LTK Manager is too old for Rose: it does not know the commands Rose sends it. Update LTK "
                "Manager (or reinstall it from github.com/LeagueToolkit/ltk-manager/releases), then retry. If "
                "you picked its ltk-manager.exe yourself, check it is the up-to-date install, not an old copy. "
                f"{logs}")
    if cause == "import":
        return f"Rose could not install the mod into LTK Manager. Free some disk space, then retry. {logs}"
    if cause == "killed":
        return ("Another program closed LTK Manager, most often an antivirus. "
                f"Add Rose's folder to its exclusions, then retry. {logs}")
    if cause == "crashed":
        return (f"LTK Manager crashed. Retry the next game; if it crashes every game, {report}. {logs}")
    return f"Retry the next game. If it fails every game, {report}. {logs}"


def report_ltf_failure(reason: str, report: bool = True):
    """Show an LTF session failure in Troubleshooting."""
    if not report:
        log.debug(f"[INJECT] LTF session failure (not reported): {reason}")
        return
    report_issue(
        "LTF_FAILED",
        "error",
        f"Injection failed: {reason}",
        details={"reason": reason, "cause": ltk_failure_cause(reason)},
        hint=ltk_failure_hint(reason),
    )
