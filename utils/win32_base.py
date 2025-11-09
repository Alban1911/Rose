"""
Utility helpers for creating simple Win32 windows using ctypes.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable, Dict, Optional

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
comctl32 = ctypes.windll.comctl32

# Provide fallbacks for missing Win32 handle types on older Python runtimes.
HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
HICON = getattr(wintypes, "HICON", wintypes.HANDLE)
HBRUSH = getattr(wintypes, "HBRUSH", wintypes.HANDLE)


# ---------------------------------------------------------------------------
# Win32 constants
# ---------------------------------------------------------------------------

WM_NULL = 0x0000
WM_CREATE = 0x0001
WM_DESTROY = 0x0002
WM_MOVE = 0x0003
WM_SIZE = 0x0005
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_HSCROLL = 0x0114
WM_NOTIFY = 0x004E
WM_SETFONT = 0x0030
WM_GETMINMAXINFO = 0x0024
WM_NCCREATE = 0x0081
WM_NCDESTROY = 0x0082

WM_USER = 0x0400

PM_REMOVE = 0x0001

SW_SHOWNORMAL = 1

SM_CXSCREEN = 0
SM_CYSCREEN = 1

IDC_ARROW = 32512

COLOR_WINDOW = 5

WS_OVERLAPPED = 0x00000000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_GROUP = 0x00020000
WS_TABSTOP = 0x00010000

WS_OVERLAPPEDWINDOW = (
    WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
)

WS_EX_APPWINDOW = 0x00040000
WS_EX_CLIENTEDGE = 0x00000200
WS_EX_WINDOWEDGE = 0x00000100

BS_PUSHBUTTON = 0x00000000
BS_DEFPUSHBUTTON = 0x00000001

ES_AUTOHSCROLL = 0x0080

PBM_SETRANGE = WM_USER + 1
PBM_SETPOS = WM_USER + 2
PBM_SETMARQUEE = WM_USER + 10

PBS_MARQUEE = 0x0008

TBM_GETPOS = WM_USER
TBM_SETPOS = WM_USER + 5
TBM_SETRANGE = WM_USER + 6
TBM_SETRANGEMIN = WM_USER + 7
TBM_SETRANGEMAX = WM_USER + 8

DEFAULT_GUI_FONT = 17  # Stock font identifier for GetStockObject

ICC_BAR_CLASSES = 0x00000004
ICC_PROGRESS_CLASS = 0x00000020


# ---------------------------------------------------------------------------
# Helper structures and utility functions
# ---------------------------------------------------------------------------

# Python 3.8 lacks wintypes.LRESULT; fall back to pointer-sized integer.
if hasattr(wintypes, "LRESULT"):
    LRESULT = wintypes.LRESULT  # type: ignore[attr-defined]
else:
    LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == ctypes.sizeof(ctypes.c_longlong) else ctypes.c_long

WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", HICON),
    ]


class CREATESTRUCTW(ctypes.Structure):
    _fields_ = [
        ("lpCreateParams", wintypes.LPVOID),
        ("hInstance", wintypes.HINSTANCE),
        ("hMenu", wintypes.HMENU),
        ("hwndParent", wintypes.HWND),
        ("cy", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("y", ctypes.c_int),
        ("x", ctypes.c_int),
        ("style", ctypes.c_long),
        ("lpszName", wintypes.LPCWSTR),
        ("lpszClass", wintypes.LPCWSTR),
        ("dwExStyle", wintypes.DWORD),
    ]


class INITCOMMONCONTROLSEX(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("dwICC", wintypes.DWORD),
    ]


WNDPROCTYPE = WNDPROC


def HIWORD(value: int) -> int:
    return (value >> 16) & 0xFFFF


def LOWORD(value: int) -> int:
    return value & 0xFFFF


def MAKELPARAM(low: int, high: int) -> int:
    return ((high & 0xFFFF) << 16) | (low & 0xFFFF)


def init_common_controls() -> None:
    """Ensure common controls (progress bar, trackbar) are initialized."""
    icc = INITCOMMONCONTROLSEX()
    icc.dwSize = ctypes.sizeof(INITCOMMONCONTROLSEX)
    icc.dwICC = ICC_BAR_CLASSES | ICC_PROGRESS_CLASS
    comctl32.InitCommonControlsEx(ctypes.byref(icc))


# ---------------------------------------------------------------------------
# Base window class
# ---------------------------------------------------------------------------


class Win32Window:
    """Lightweight helper around a Win32 overlapped window."""

    _registered_classes: Dict[str, wintypes.ATOM] = {}
    _instances: Dict[int, "Win32Window"] = {}
    _wnd_proc: Optional[WNDPROCTYPE] = None

    def __init__(
        self,
        class_name: str,
        window_title: str,
        width: int,
        height: int,
        style: int = WS_OVERLAPPEDWINDOW,
        ex_style: int = WS_EX_APPWINDOW,
    ):
        self.class_name = class_name
        self.window_title = window_title
        self.width = width
        self.height = height
        self.style = style
        self.ex_style = ex_style
        self.hwnd: Optional[wintypes.HWND] = None
        self.h_instance: wintypes.HINSTANCE = kernel32.GetModuleHandleW(None)
        self.default_font = gdi32.GetStockObject(DEFAULT_GUI_FONT)
        self._lp_create_param = ctypes.py_object(self)
        self._lp_create_param_ptr = ctypes.pointer(self._lp_create_param)
        self._register_class()

    # ------------------------------------------------------------------
    # Window class registration and dispatch
    # ------------------------------------------------------------------

    @classmethod
    def _register_class_proc(cls) -> WNDPROCTYPE:
        if cls._wnd_proc is None:
            cls._wnd_proc = WNDPROCTYPE(cls._global_wnd_proc)
        return cls._wnd_proc

    def _register_class(self) -> None:
        if self.class_name in self._registered_classes:
            return

        wnd_class = WNDCLASSEXW()
        wnd_class.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wnd_class.style = 0
        wnd_class.lpfnWndProc = self._register_class_proc()
        wnd_class.cbClsExtra = 0
        wnd_class.cbWndExtra = 0
        wnd_class.hInstance = self.h_instance
        wnd_class.hIcon = None
        wnd_class.hCursor = user32.LoadCursorW(None, IDC_ARROW)
        wnd_class.hbrBackground = user32.GetSysColorBrush(COLOR_WINDOW)
        wnd_class.lpszMenuName = None
        wnd_class.lpszClassName = self.class_name
        wnd_class.hIconSm = None

        atom = user32.RegisterClassExW(ctypes.byref(wnd_class))
        if not atom:
            raise ctypes.WinError(ctypes.get_last_error())

        self._registered_classes[self.class_name] = atom

    @classmethod
    def _global_wnd_proc(
        cls,
        hwnd: wintypes.HWND,
        msg: int,
        w_param: wintypes.WPARAM,
        l_param: wintypes.LPARAM,
    ) -> wintypes.LRESULT:
        if msg == WM_NCCREATE:
            create_struct = ctypes.cast(l_param, ctypes.POINTER(CREATESTRUCTW)).contents
            py_obj = ctypes.cast(create_struct.lpCreateParams, ctypes.POINTER(ctypes.py_object)).contents.value
            cls._instances[int(hwnd)] = py_obj
            py_obj.hwnd = hwnd
        instance = cls._instances.get(int(hwnd))
        if instance is not None:
            result = instance.wnd_proc(hwnd, msg, w_param, l_param)
            if result is not None:
                return result
        if msg == WM_NCDESTROY:
            cls._instances.pop(int(hwnd), None)
        return user32.DefWindowProcW(hwnd, msg, w_param, l_param)

    # ------------------------------------------------------------------
    # Overridables
    # ------------------------------------------------------------------

    def on_create(self) -> Optional[int]:
        return None

    def on_destroy(self) -> Optional[int]:
        return None

    def on_close(self) -> Optional[int]:
        user32.DestroyWindow(self.hwnd)
        return 0

    def on_command(self, command_id: int, notification_code: int, control_hwnd: Optional[wintypes.HWND]) -> Optional[int]:
        return None

    def on_hscroll(self, request_code: int, position: int, trackbar_hwnd: Optional[wintypes.HWND]) -> Optional[int]:
        return None

    def wnd_proc(
        self,
        hwnd: wintypes.HWND,
        msg: int,
        w_param: wintypes.WPARAM,
        l_param: wintypes.LPARAM,
    ) -> Optional[int]:
        if msg == WM_CREATE:
            return self.on_create()
        if msg == WM_DESTROY:
            return self.on_destroy()
        if msg == WM_CLOSE:
            return self.on_close()
        if msg == WM_COMMAND:
            return self.on_command(LOWORD(w_param), HIWORD(w_param), ctypes.cast(l_param, wintypes.HWND))
        if msg == WM_HSCROLL:
            return self.on_hscroll(LOWORD(w_param), HIWORD(w_param), ctypes.cast(l_param, wintypes.HWND))
        return None

    # ------------------------------------------------------------------
    # Window helpers
    # ------------------------------------------------------------------

    def create_window(self) -> wintypes.HWND:
        screen_w = user32.GetSystemMetrics(SM_CXSCREEN)
        screen_h = user32.GetSystemMetrics(SM_CYSCREEN)
        x = max(0, (screen_w - self.width) // 2)
        y = max(0, (screen_h - self.height) // 2)

        hwnd = user32.CreateWindowExW(
            self.ex_style,
            self.class_name,
            self.window_title,
            self.style,
            x,
            y,
            self.width,
            self.height,
            None,
            None,
            self.h_instance,
            ctypes.cast(self._lp_create_param_ptr, wintypes.LPVOID),
        )
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self.hwnd = hwnd
        return hwnd

    def show_window(self, cmd_show: int = SW_SHOWNORMAL) -> None:
        if not self.hwnd:
            self.create_window()
        user32.ShowWindow(self.hwnd, cmd_show)
        user32.UpdateWindow(self.hwnd)

    def destroy_window(self) -> None:
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None

    def pump_messages(self, block: bool = False) -> bool:
        msg = wintypes.MSG()
        if block:
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result == -1:
                return False
            if result == 0:
                return False
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
            return True
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        return True

    def send_message(self, hwnd: wintypes.HWND, message: int, w_param: int, l_param: int) -> int:
        return user32.SendMessageW(hwnd, message, w_param, l_param)

    def set_font(self, hwnd: wintypes.HWND) -> None:
        if hwnd:
            user32.SendMessageW(hwnd, WM_SETFONT, self.default_font, True)

    def create_control(
        self,
        class_name: str,
        text: str,
        style: int,
        ex_style: int,
        x: int,
        y: int,
        width: int,
        height: int,
        control_id: int,
    ) -> wintypes.HWND:
        hwnd = user32.CreateWindowExW(
            ex_style,
            class_name,
            text,
            style,
            x,
            y,
            width,
            height,
            self.hwnd,
            wintypes.HMENU(control_id),
            self.h_instance,
            None,
        )
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self.set_font(hwnd)
        return hwnd


__all__ = [
    "Win32Window",
    "HIWORD",
    "LOWORD",
    "MAKELPARAM",
    "PBM_SETRANGE",
    "PBM_SETPOS",
    "PBM_SETMARQUEE",
    "PBS_MARQUEE",
    "TBM_GETPOS",
    "TBM_SETPOS",
    "TBM_SETRANGE",
    "WM_USER",
    "WM_COMMAND",
    "WM_HSCROLL",
    "WM_CLOSE",
    "WM_DESTROY",
    "WM_CREATE",
    "WM_SETFONT",
    "WS_CHILD",
    "WS_VISIBLE",
    "WS_TABSTOP",
    "WS_EX_CLIENTEDGE",
    "BS_DEFPUSHBUTTON",
    "BS_PUSHBUTTON",
    "ES_AUTOHSCROLL",
    "WS_OVERLAPPEDWINDOW",
    "WS_CAPTION",
    "WS_SYSMENU",
    "WS_MINIMIZEBOX",
    "init_common_controls",
    "user32",
    "gdi32",
    "comctl32",
    "kernel32",
    "SW_SHOWNORMAL",
]

