"""
Simple PyQt6 launcher window for LeagueUnlocked.

Displays a centered UNLOCK button. When clicked, the window closes,
allowing the main application to continue starting up.
"""

from __future__ import annotations

import sys
from typing import Optional, Tuple


def _ensure_application() -> Tuple["QApplication", bool]:
    """Return a running QApplication instance, creating one if needed."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0]])
        return app, True
    return app, False


def run_launcher() -> bool:
    """
    Show the launcher window and return True if the user clicked UNLOCK.

    Returns False when the window is closed via the window controls without
    pressing UNLOCK. On ImportError (PyQt6 missing), the launcher is skipped
    and True is returned so the application can continue.
    """
    try:
        from PyQt6.QtCore import Qt, QEventLoop, QObject, QThread, pyqtSignal
        from PyQt6.QtGui import QIcon, QPixmap
        from PyQt6.QtWidgets import QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget
    except ImportError:
        print("[Launcher] PyQt6 not available; starting LeagueUnlocked directly.")
        return True

    app, created_app = _ensure_application()
    icon = None
    logo_pixmap = None

    try:
        from utils.paths import get_asset_path

        icon_path = get_asset_path("icon.ico")
        if icon_path.exists():
            icon = QIcon(str(icon_path))
        else:
            print(f"[Launcher] Icon file missing at {icon_path}")

        logo_path = get_asset_path("icon.png")
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            if not pixmap.isNull():
                logo_pixmap = pixmap.scaled(
                    210,
                    210,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            else:
                print(f"[Launcher] icon.png at {logo_path} is invalid.")
        else:
            print(f"[Launcher] Icon image missing at {logo_path}")
    except Exception as icon_err:  # noqa: BLE001 - inform but continue without icon
        print(f"[Launcher] Failed to load icon: {icon_err}")

    if icon and created_app:
        app.setWindowIcon(icon)

    class SkinDownloadWorker(QObject):
        progress = pyqtSignal(int)
        status = pyqtSignal(str)
        download_started = pyqtSignal()
        finished = pyqtSignal(bool, bool)  # success, already_ready
        error = pyqtSignal(str)

        def _emit_progress(self, percent: int, message: Optional[str] = None) -> None:
            clamped = max(0, min(percent, 100))
            if message:
                self.status.emit(message)
            self.progress.emit(clamped)

        def run(self) -> None:
            try:
                self.status.emit("Checking installed skins...")
                from state.app_status import AppStatus
                from utils.skin_downloader import download_skins_on_startup

                status_checker = AppStatus()
                have_skins = status_checker.check_skins_downloaded()
                have_previews = status_checker.check_previews_downloaded()

                if have_skins and have_previews:
                    status_checker.mark_download_process_complete()
                    self._emit_progress(100, "Skins already up to date")
                    self.finished.emit(True, True)
                    return

                self.download_started.emit()
                self.status.emit("Downloading skins...")
                success = download_skins_on_startup(progress_callback=self._emit_progress)
                status_checker.update_status(force=True)
                if success:
                    status_checker.mark_download_process_complete()
                    self._emit_progress(100, "Skins ready")
                else:
                    self._emit_progress(0, "Download failed")
                self.finished.emit(success, False)
            except Exception as worker_err:  # noqa: BLE001 - surface error
                self.error.emit(str(worker_err))
                self._emit_progress(0, "Download failed")
                self.finished.emit(False, False)

    class LauncherWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("LeagueUnlocked Launcher")
            self.setFixedSize(1280, 720)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            if icon:
                self.setWindowIcon(icon)

            self._status_text = "Checking skins..."
            self._progress_active = False
            self._progress_value = 0
            self.worker_thread: QThread | None = None
            self.worker: SkinDownloadWorker | None = None

            layout = QVBoxLayout()
            layout.setContentsMargins(32, 32, 32, 32)
            layout.setSpacing(24)

            layout.addStretch(1)

            if logo_pixmap:
                logo_label = QLabel()
                logo_label.setPixmap(logo_pixmap)
                logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(logo_label, alignment=Qt.AlignmentFlag.AlignCenter)

            self.unlock_button = QPushButton("UNLOCK")
            self.unlock_button.setMinimumSize(600, 84)
            layout.addWidget(self.unlock_button, alignment=Qt.AlignmentFlag.AlignCenter)

            layout.addStretch(1)

            self.setLayout(layout)

            self.unlocked = False
            self.unlock_button.clicked.connect(self._handle_unlock)
            self._set_button_enabled(False)
            self.unlock_button.setText(self._status_text)
            self._apply_button_style(None)

            self._start_skin_check()

        def _handle_unlock(self) -> None:
            self.unlocked = True
            self.close()

        def _start_skin_check(self) -> None:
            self.worker_thread = QThread(self)
            self.worker = SkinDownloadWorker()
            self.worker.moveToThread(self.worker_thread)
            self.worker_thread.started.connect(self.worker.run)
            self.worker.progress.connect(self._handle_progress)
            self.worker.status.connect(self._handle_status)
            self.worker.download_started.connect(self._handle_download_started)
            self.worker.finished.connect(self._handle_finished)
            self.worker.error.connect(self._handle_error)
            self.worker.finished.connect(self.worker_thread.quit)
            self.worker_thread.finished.connect(self.worker_thread.deleteLater)
            self.worker_thread.finished.connect(self._cleanup_worker)
            self.worker_thread.start()

        def _cleanup_worker(self) -> None:
            if self.worker:
                self.worker.deleteLater()
                self.worker = None
            self.worker_thread = None

        def _handle_status(self, message: str) -> None:
            self._status_text = message
            if not self.unlock_button.isEnabled() or self._progress_active:
                if self._progress_active:
                    display = f"{message} {self._progress_value}%"
                else:
                    display = message
                self.unlock_button.setText(display)

        def _handle_download_started(self) -> None:
            self._progress_active = True
            self._progress_value = 0
            self._set_button_enabled(False)
            self._apply_button_style(self._progress_value)
            self.unlock_button.setText(self._status_text)

        def _handle_progress(self, value: int) -> None:
            clamped = max(0, min(value, 100))
            self._progress_value = clamped
            if clamped >= 100:
                self._progress_active = False
            else:
                self._progress_active = True

            if self._progress_active:
                self.unlock_button.setText(f"{self._status_text} {clamped}%")
            else:
                self.unlock_button.setText(self._status_text if self.unlock_button.isEnabled() else f"{self._status_text} 100%")

            self._apply_button_style(clamped if self._progress_active else None)

        def _handle_finished(self, success: bool, already_ready: bool) -> None:
            self._progress_active = False
            self._progress_value = 0
            if success:
                self.unlock_button.setText("UNLOCK")
                self._set_button_enabled(True)
                self._apply_button_style(None)
            else:
                self.unlock_button.setText("UNLOCK (Download failed)")
                self._set_button_enabled(True)
                self._apply_button_style(None)

        def _handle_error(self, message: str) -> None:
            print(f"[Launcher] Skin download error: {message}")
            try:
                QMessageBox.warning(self, "Launcher Error", f"Skin download failed:\n{message}")
            except Exception:
                pass

        def _set_button_enabled(self, enabled: bool) -> None:
            self.unlock_button.setEnabled(enabled)
            progress_value = self._progress_value if (self._progress_active and not enabled) else None
            self._apply_button_style(progress_value)

        def _apply_button_style(self, progress: Optional[int]) -> None:
            enabled = self.unlock_button.isEnabled()
            text_color = "#f0f0f0" if enabled else "#9a9a9a"
            if progress is not None:
                stop = max(0.0, min(progress, 100) / 100.0)
                background = (
                    "qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                    f"stop:0 rgba(81,130,244,230), stop:{stop:.3f} rgba(81,130,244,230), "
                    f"stop:{stop:.3f} rgba(45,45,45,255), stop:1 rgba(45,45,45,255))"
                )
            else:
                background = "#2d2d2d"

            stylesheet = f"""
                QPushButton {{
                    font-size: 24px;
                    font-weight: bold;
                    padding: 12px 24px;
                    border-radius: 12px;
                    border: 2px solid #4a4a4a;
                    color: {text_color};
                    background-color: {background};
                }}
                QPushButton:disabled {{
                    color: #8d8d8d;
                }}
            """
            self.unlock_button.setStyleSheet(stylesheet)

        def closeEvent(self, event) -> None:  # type: ignore[override]
            if self.worker_thread and self.worker_thread.isRunning():
                self.worker_thread.quit()
                self.worker_thread.wait(200)
            super().closeEvent(event)

    window = LauncherWindow()
    window.show()
    window.activateWindow()
    window.raise_()

    if created_app:
        app.exec()
    else:
        loop = QEventLoop()
        window.destroyed.connect(loop.quit)
        loop.exec()

    unlocked = getattr(window, "unlocked", False)

    if created_app:
        app.quit()

    return unlocked

