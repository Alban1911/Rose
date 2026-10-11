"""Responsive native progress window for a tray diagnostic run."""

import ctypes
import threading
import time
from ctypes import wintypes

from utils.core.logging import get_logger
from utils.core.paths import get_asset_path, open_folder_in_explorer
from utils.system.win32_base import (
    BS_DEFPUSHBUTTON, PBS_MARQUEE, PBM_SETMARQUEE, PBM_SETPOS,
    WS_CAPTION, WS_CHILD, WS_MINIMIZEBOX, WS_SYSMENU, WS_TABSTOP, WS_VISIBLE,
    Win32Window, init_common_controls, user32,
)

log = get_logger()

user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
user32.EnableWindow.restype = wintypes.BOOL


class _ProgressWindow(Win32Window):
    OPEN_ID = 4201
    CLOSE_ID = 4202

    def __init__(self):
        super().__init__(
            class_name="RoseDiagnosticsProgress", window_title="Diagnose Rose startup",
            width=520, height=285, style=WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
        )
        init_common_controls()
        self.closed = threading.Event()
        self.directory = None
        self.finished = False
        self.started = time.monotonic()

    def on_create(self):
        width, _ = self.get_client_size()
        content = width - 40
        self.title_label = self.create_control(
            "STATIC", "Diagnostics started", WS_CHILD | WS_VISIBLE,
            0, 20, 18, content, 24, 4210,
        )
        self.detail_label = self.create_control(
            "STATIC", "Checking Windows and Rose. Keep the League client open.\nThis can take up to 3 minutes.",
            WS_CHILD | WS_VISIBLE, 0, 20, 48, content, 80, 4211,
        )
        self.progress = self.create_control(
            "msctls_progress32", "", WS_CHILD | WS_VISIBLE | PBS_MARQUEE,
            0, 20, 136, content, 18, 4212,
        )
        self.send_message(self.progress, PBM_SETMARQUEE, 1, 35)
        self.elapsed_label = self.create_control(
            "STATIC", "Collecting... 0 seconds", WS_CHILD | WS_VISIBLE,
            0, 20, 162, content, 22, 4213,
        )
        self.open_button = self.create_control(
            "BUTTON", "Open reports", WS_CHILD | WS_VISIBLE | WS_TABSTOP,
            0, width - 258, 196, 116, 28, self.OPEN_ID,
        )
        user32.EnableWindow(self.open_button, False)
        self.close_button = self.create_control(
            "BUTTON", "Run in background", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON,
            0, width - 132, 196, 112, 28, self.CLOSE_ID,
        )
        icon = get_asset_path("icon.ico")
        if icon.is_file():
            self.set_window_icon(str(icon))
        return 0

    def tick(self):
        if not self.finished and not self.closed.is_set():
            self.set_label_text(self.elapsed_label, f"Collecting... {int(time.monotonic() - self.started)} seconds")

    def complete(self, message, directory, succeeded):
        if self.closed.is_set():
            return
        self.finished = True
        self.directory = directory
        self.send_message(self.progress, PBM_SETMARQUEE, 0, 0)
        self.set_window_styles(self.progress, remove=PBS_MARQUEE)
        self.send_message(self.progress, PBM_SETPOS, 100 if succeeded else 0, 0)
        self.set_label_text(self.title_label, "Diagnostics complete" if succeeded else "Diagnostics could not finish")
        self.set_label_text(self.detail_label, message)
        self.set_label_text(self.elapsed_label, "Reports saved." if directory else "Check the Rose logs for details.")
        self.set_label_text(self.close_button, "Close")
        user32.EnableWindow(self.open_button, directory is not None)

    def on_command(self, command_id, notification_code, control_hwnd):
        if notification_code == 0 and command_id == self.CLOSE_ID:
            return self.on_close()
        if notification_code == 0 and command_id == self.OPEN_ID and self.directory:
            try:
                open_folder_in_explorer(self.directory)
            except OSError:
                log.exception("Could not open diagnostic reports")
                self.set_label_text(self.elapsed_label, "Could not open reports. Use Open Diagnostics Folder in the tray.")
            return 0
        return None

    def on_destroy(self):
        self.closed.set()
        self.hwnd = None
        self._free_icons()
        user32.PostQuitMessage(0)
        return 0


class DiagnosticsProgressDialog:
    """Own the window/message loop on a dedicated thread, separate from checks."""

    def __init__(self):
        self._ready = threading.Event()
        self._close_requested = threading.Event()
        self._window = None
        self._error = None

    def start(self):
        threading.Thread(target=self._run, name="RoseDiagnosticsWindow", daemon=True).start()
        if not self._ready.wait(3):
            self.close()
            raise RuntimeError("Diagnostic progress window did not open")
        if self._error:
            raise RuntimeError("Diagnostic progress window could not open") from self._error

    def _run(self):
        try:
            self._window = _ProgressWindow()
            self._window.show_window()
            user32.SetForegroundWindow(self._window.hwnd)
            self._ready.set()
            while not self._window.closed.is_set():
                self._window.pump_messages()
                if self._close_requested.is_set():
                    self._window.destroy_window()
                    break
                self._window.tick()
                self._close_requested.wait(0.05)
        except Exception as error:
            self._error = error
            log.exception("Diagnostic progress window failed")
        finally:
            if self._window:
                self._window.destroy_window()
            self._ready.set()

    def finish(self, message, directory=None, succeeded=False):
        if self._window and not self._window.closed.is_set():
            self._window.invoke(self._window.complete, message, directory, succeeded)

    def close(self):
        self._close_requested.set()
