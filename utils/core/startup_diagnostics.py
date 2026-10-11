"""Run the bundled, read-only Windows collector without blocking Rose's tray."""

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from config import APP_VERSION
from utils.core.paths import get_app_dir, get_asset_path, get_user_data_dir


DIAGNOSTICS_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class DiagnosticsResult:
    directory: Path
    completed: bool
    message: str
    cancelled: bool = False


def get_diagnostics_dir() -> Path:
    return get_user_data_dir() / "logs" / "diagnostics"


def _powershell_path() -> Path:
    # Avoid PATH lookup: broken PATHs are one reason to run this collector.
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    system = windows / "System32"
    if os.environ.get("PROCESSOR_ARCHITEW6432"):
        system = windows / "Sysnative"
    return system / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def run_startup_diagnostics(stop_event: threading.Event) -> DiagnosticsResult:
    """Collect into a unique folder; keep a useful failure note if Windows blocks it.

    PowerShell inherits Rose's account. The explicit data path still points at
    Rose's desktop-user data, including when Rose is elevated as another account.
    Raw PowerShell output is deliberately not copied into shareable logs.
    """
    directory = get_diagnostics_dir() / (
        f"Rose-Diagnostics-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
    )
    directory.mkdir(parents=True, exist_ok=False)
    status_path = directory / "collector-status.txt"

    def finish(message: str, completed: bool = False, cancelled: bool = False):
        status_path.write_text(
            f"Rose {APP_VERSION} startup diagnostics\n{message}\n"
            "Reports stay on this PC. Review them before sharing with support.\n",
            encoding="utf-8",
        )
        return DiagnosticsResult(directory, completed, message, cancelled)

    finish("Collecting. If Rose exits unexpectedly, this run may be incomplete.")
    if stop_event.is_set():
        return finish("Collection cancelled because Rose is stopping.", cancelled=True)
    script = get_asset_path("diagnostics/Diagnose-Rose.ps1")
    if not script.is_file():
        return finish("The bundled diagnostic script is missing. Repair or reinstall Rose.")
    powershell = _powershell_path()
    if not powershell.is_file():
        return finish("Windows PowerShell 5.1 could not be found. Check your Windows installation.")

    command = [
        str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-File", str(script),
        "-RosePath", str(get_app_dir()),
        "-DataPath", str(get_user_data_dir()),
        "-ReportDirectory", str(directory),
        "-RoseVersion", str(APP_VERSION),
    ]
    environment = os.environ.copy()
    # A parent PowerShell 7 session can export incompatible versions of built-in
    # modules. These checks need only the modules shipped with Windows PS 5.1.
    # Preserve PATH and the rest of Rose's environment for the actual diagnostics.
    environment["PSModulePath"] = str(powershell.parent / "Modules")
    try:
        with subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
            env=environment,
        ) as process:
            deadline = time.monotonic() + DIAGNOSTICS_TIMEOUT_SECONDS
            try:
                while process.poll() is None:
                    if stop_event.wait(0.25):
                        return finish("Collection cancelled because Rose is stopping.", cancelled=True)
                    if time.monotonic() >= deadline:
                        return finish(
                            "Collection timed out after 3 minutes. A Windows query may be unresponsive. "
                            "Any existing reports are incomplete; retry and share this status with support."
                        )
            finally:
                if process.poll() is None:
                    process.kill()  # Only our collector, never Rose, League or a security product.
                process.wait()
            if process.returncode != 0:
                return finish(
                    f"The diagnostic collector exited with code {process.returncode}. "
                    "Any existing reports are incomplete. Check Windows PowerShell availability "
                    "and application-control history with support; a collector failure does not "
                    "establish why Rose failed to start."
                )
    except OSError as error:
        # Don't persist exception text: it can contain unredacted profile paths.
        return finish(
            f"Windows could not run the diagnostic collector (error {getattr(error, 'winerror', None) or error.errno}). "
            "Check Windows PowerShell and application-control history with support."
        )

    try:
        report = json.loads((directory / "report.json").read_text(encoding="utf-8-sig"))
        findings = report["findings"]
        if (report.get("complete") is not True or not isinstance(findings, list)
                or not findings or not (directory / "report.txt").is_file()):
            raise ValueError("Missing report content")
        counts = {status: sum(f["status"] == status for f in findings)
                  for status in ("FAIL", "WARN", "UNKNOWN")}
    except (OSError, ValueError, KeyError, TypeError):
        return finish("The collector did not produce complete reports. Retry and share this status with support.")
    return finish(
        f"Collection complete: {counts['FAIL']} FAIL, {counts['WARN']} WARN, "
        f"{counts['UNKNOWN']} UNKNOWN. Read report.txt for evidence and next steps.",
        completed=True,
    )
