"""Direct Win32 registry access for Rose's IFEO integration."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Protocol


IFEO_PATH = "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Image File Execution Options"
TARGET_NAME = "LeagueClientUx.exe"
DEBUGGER_VALUE = "Debugger"

ERROR_SUCCESS = 0
ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_INVALID_PARAMETER = 87
ERROR_ALREADY_EXISTS = 183

KEY_QUERY_VALUE = 0x0001
KEY_SET_VALUE = 0x0002
KEY_CREATE_SUB_KEY = 0x0004

REG_OPTION_NON_VOLATILE = 0x00000000
REG_SZ = 1
REG_EXPAND_SZ = 2
REG_CREATED_NEW_KEY = 1
REG_OPENED_EXISTING_KEY = 2

_HKEY_LOCAL_MACHINE = ctypes.c_void_p(0x80000002)


class RegistryError(OSError):
    def __init__(self, code: int, operation: str) -> None:
        self.code = int(code)
        self.operation = operation
        message = ctypes.FormatError(self.code) if sys.platform == "win32" else ""
        super().__init__(self.code, f"{operation} failed: {message or self.code}")


class RegistryHandle:
    def __init__(self, api: "Win32RegistryApi", value: ctypes.c_void_p) -> None:
        self._api = api
        self.value = value
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._api.close(self)

    def __enter__(self) -> "RegistryHandle":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


class RegistryApi(Protocol):
    def open_key(self, path: str, access: int) -> Any:
        ...

    def create_subkey(self, parent: Any, name: str, access: int) -> tuple[Any, int]:
        ...

    def query_string(self, key: Any, name: str) -> str | None:
        ...

    def set_string(self, key: Any, name: str, value: str) -> None:
        ...

    def delete_value(self, key: Any, name: str) -> None:
        ...


class Win32RegistryApi:
    """Minimal advapi32 wrapper with explicit access masks."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Direct IFEO access is only available on Windows")

        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self._configure_functions()

    def _configure_functions(self) -> None:
        self._reg_open = self._advapi32.RegOpenKeyExW
        self._reg_open.argtypes = [
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._reg_open.restype = wintypes.LONG

        self._reg_create = self._advapi32.RegCreateKeyExW
        self._reg_create.argtypes = [
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._reg_create.restype = wintypes.LONG

        self._reg_query = self._advapi32.RegQueryValueExW
        self._reg_query.argtypes = [
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._reg_query.restype = wintypes.LONG

        self._reg_set = self._advapi32.RegSetValueExW
        self._reg_set.argtypes = [
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self._reg_set.restype = wintypes.LONG

        self._reg_delete = self._advapi32.RegDeleteValueW
        self._reg_delete.argtypes = [
            ctypes.c_void_p,
            wintypes.LPCWSTR,
        ]
        self._reg_delete.restype = wintypes.LONG

        self._reg_close = self._advapi32.RegCloseKey
        self._reg_close.argtypes = [ctypes.c_void_p]
        self._reg_close.restype = wintypes.LONG

    @staticmethod
    def _check(code: int, operation: str) -> None:
        if code != ERROR_SUCCESS:
            raise RegistryError(code, operation)

    def open_key(self, path: str, access: int) -> RegistryHandle:
        handle = ctypes.c_void_p()
        code = self._reg_open(
            _HKEY_LOCAL_MACHINE,
            path,
            0,
            access,
            ctypes.byref(handle),
        )
        self._check(code, "RegOpenKeyExW")
        return RegistryHandle(self, handle)

    def create_subkey(
        self,
        parent: RegistryHandle,
        name: str,
        access: int,
    ) -> tuple[RegistryHandle, int]:
        handle = ctypes.c_void_p()
        disposition = wintypes.DWORD()
        code = self._reg_create(
            parent.value,
            name,
            0,
            None,
            REG_OPTION_NON_VOLATILE,
            access,
            None,
            ctypes.byref(handle),
            ctypes.byref(disposition),
        )
        self._check(code, "RegCreateKeyExW")
        return RegistryHandle(self, handle), int(disposition.value)

    def query_string(self, key: RegistryHandle, name: str) -> str | None:
        value_type = wintypes.DWORD()
        size = wintypes.DWORD(0)
        code = self._reg_query(
            key.value,
            name,
            None,
            ctypes.byref(value_type),
            None,
            ctypes.byref(size),
        )
        if code == ERROR_FILE_NOT_FOUND:
            return None
        self._check(code, "RegQueryValueExW")
        if value_type.value not in (REG_SZ, REG_EXPAND_SZ):
            return None
        if size.value == 0:
            return ""

        buffer = ctypes.create_string_buffer(size.value)
        code = self._reg_query(
            key.value,
            name,
            None,
            ctypes.byref(value_type),
            buffer,
            ctypes.byref(size),
        )
        self._check(code, "RegQueryValueExW")
        return buffer.raw[: size.value].decode("utf-16-le", errors="replace").rstrip("\x00")

    def set_string(self, key: RegistryHandle, name: str, value: str) -> None:
        data = (value + "\x00").encode("utf-16-le")
        buffer = ctypes.create_string_buffer(data)
        code = self._reg_set(
            key.value,
            name,
            0,
            REG_SZ,
            ctypes.cast(buffer, ctypes.c_void_p),
            len(data),
        )
        self._check(code, "RegSetValueExW")

    def delete_value(self, key: RegistryHandle, name: str) -> None:
        code = self._reg_delete(key.value, name)
        self._check(code, "RegDeleteValueW")

    def close(self, key: RegistryHandle) -> None:
        code = self._reg_close(key.value)
        if code != ERROR_SUCCESS:
            raise RegistryError(code, "RegCloseKey")


@dataclass
class FakeRegistryHandle:
    path: str
    access: int
    closed: bool = False

    def __enter__(self) -> "FakeRegistryHandle":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.closed = True


class FakeRegistryApi:
    """Small in-memory backend used by unit tests."""

    def __init__(self) -> None:
        self.values: dict[str, dict[str, str]] = {}
        self.access_log: list[tuple[str, int]] = []
        self.failures: dict[str, int] = {}

    def _fail(self, operation: str) -> None:
        code = self.failures.get(operation)
        if code is not None:
            raise RegistryError(code, operation)

    def open_key(self, path: str, access: int) -> FakeRegistryHandle:
        self._fail("RegOpenKeyExW")
        if path not in self.values:
            raise RegistryError(ERROR_FILE_NOT_FOUND, "RegOpenKeyExW")
        self.access_log.append((path, access))
        return FakeRegistryHandle(path, access)

    def create_subkey(
        self,
        parent: FakeRegistryHandle,
        name: str,
        access: int,
    ) -> tuple[FakeRegistryHandle, int]:
        self._fail("RegCreateKeyExW")
        path = parent.path + "\\" + name
        disposition = REG_OPENED_EXISTING_KEY if path in self.values else REG_CREATED_NEW_KEY
        self.values.setdefault(path, {})
        self.access_log.append((path, access))
        return FakeRegistryHandle(path, access), disposition

    def query_string(self, key: FakeRegistryHandle, name: str) -> str | None:
        self._fail("RegQueryValueExW")
        return self.values.get(key.path, {}).get(name)

    def set_string(self, key: FakeRegistryHandle, name: str, value: str) -> None:
        self._fail("RegSetValueExW")
        self.values.setdefault(key.path, {})[name] = value

    def delete_value(self, key: FakeRegistryHandle, name: str) -> None:
        self._fail("RegDeleteValueW")
        values = self.values.get(key.path, {})
        if name not in values:
            raise RegistryError(ERROR_FILE_NOT_FOUND, "RegDeleteValueW")
        del values[name]