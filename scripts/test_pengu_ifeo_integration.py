"""Administrator-only integration test for the direct Rose IFEO backend."""

from __future__ import annotations

import ctypes
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pengu.integration.activation import build_debugger_command, is_elevated
from pengu.integration.registry import (
    DEBUGGER_VALUE,
    IFEO_PATH,
    KEY_CREATE_SUB_KEY,
    KEY_QUERY_VALUE,
    KEY_SET_VALUE,
    Win32RegistryApi,
)
from pengu.integration.runtime import get_core_path, prepare_runtime


def _delete_fake_target(target: str) -> None:
    if not target.startswith("RosePenguIntegration-"):
        raise ValueError("Refusing to clean an unguarded IFEO target")

    if sys.platform != "win32":
        return

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    delete_tree = advapi32.RegDeleteTreeW
    delete_tree.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    delete_tree.restype = ctypes.c_long
    path = IFEO_PATH + "\\" + target
    result = delete_tree(ctypes.c_void_p(0x80000002), path)
    if result not in (0, 2, 3):
        raise OSError(result, "RegDeleteTreeW failed during guarded test cleanup")


def run() -> int:
    if sys.platform != "win32":
        print("This test only runs on Windows.")
        return 1
    if not is_elevated():
        print("This test requires an elevated administrator session.")
        return 1

    target = f"RosePenguIntegration-{uuid.uuid4().hex}.exe"
    if not target.startswith("RosePenguIntegration-"):
        return 1

    registry = Win32RegistryApi()
    full_target = IFEO_PATH + "\\" + target
    core_path = get_core_path(prepare_runtime())
    debugger = build_debugger_command(core_path)

    exit_code = 0
    try:
        with registry.open_key(IFEO_PATH, KEY_CREATE_SUB_KEY) as parent:
            target_handle, _ = registry.create_subkey(parent, target, KEY_SET_VALUE)
            with target_handle:
                registry.set_string(target_handle, "RoseSentinel", "preserve-me")
                registry.set_string(target_handle, DEBUGGER_VALUE, debugger)

        with registry.open_key(full_target, KEY_QUERY_VALUE) as target_handle:
            assert registry.query_string(target_handle, DEBUGGER_VALUE) == debugger
            assert registry.query_string(target_handle, "RoseSentinel") == "preserve-me"

        with registry.open_key(full_target, KEY_SET_VALUE) as target_handle:
            registry.delete_value(target_handle, DEBUGGER_VALUE)

        with registry.open_key(full_target, KEY_QUERY_VALUE) as target_handle:
            assert registry.query_string(target_handle, DEBUGGER_VALUE) is None
            assert registry.query_string(target_handle, "RoseSentinel") == "preserve-me"

        print(f"Direct IFEO integration passed for {target}")
    except Exception as exc:
        print(f"Direct IFEO integration failed: {exc}")
        exit_code = 1
    finally:
        try:
            _delete_fake_target(target)
        except Exception as exc:
            print(f"Guarded cleanup failed for {target}: {exc}")
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run())