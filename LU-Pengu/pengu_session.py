"""EXAMPLE CODE FOR PENGU LOADER, THIS CODE IS PURELY TO SHOW HOW TO USE THE PENGU LOADER API"""

import subprocess
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PENGU_DIR = ROOT_DIR / "Pengu Loader"
PENGU_EXE = PENGU_DIR / "Pengu Loader.exe"


def run_cli(*args: str, ok_codes: tuple[int, ...] = (0,)) -> str:
    if not PENGU_EXE.exists():
        raise FileNotFoundError(f"Pengu Loader not found at {PENGU_EXE}")

    command = [str(PENGU_EXE), *args]
    print(f"Running: {' '.join(command)}")

    result = subprocess.run(
        command,
        cwd=str(PENGU_DIR),
        text=True,
        capture_output=True,
    )

    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip())

    if result.returncode not in ok_codes:
        result.check_returncode()

    return (result.stdout or "").strip()


def parse_status(output: str) -> bool:
    text = output.lower()
    if "inactive" in text:
        return False
    if "active" in text:
        return True
    raise ValueError(f"Unexpected status output: {output!r}")


def activate_then_restart():
    run_cli("--force-activate", "--silent")
    run_cli("--restart-client", "--silent")


def deactivate_then_restart():
    run_cli("--force-deactivate", "--silent")
    run_cli("--restart-client", "--silent")


def main() -> None:
    print("Ensuring no Pengu UI is running ...")
    subprocess.run([
        "taskkill",
        "/IM",
        "Pengu Loader.exe",
        "/F",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    current_status = run_cli("--status", "--silent", ok_codes=(0, 1))
    is_active = parse_status(current_status)
    print(f"Current status: {'ACTIVE' if is_active else 'INACTIVE'}")

    if is_active:
        deactivate_then_restart()
    else:
        activate_then_restart()

    time.sleep(20)

    new_status = run_cli("--status", "--silent", ok_codes=(0, 1))
    is_now_active = parse_status(new_status)
    if is_now_active:
        deactivate_then_restart()
    else:
        activate_then_restart()

    print("Flow complete.")


if __name__ == "__main__":
    main()
