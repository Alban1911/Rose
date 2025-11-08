"""
Simple PyQt6 launcher window for LeagueUnlocked.

Displays a centered UNLOCK button. When clicked, the window closes,
allowing the main application to continue starting up.
"""

from __future__ import annotations

import os
import sys
from typing import Optional, Tuple

from config import APP_VERSION, get_config_float
from launcher.updater import auto_update
from pathlib import Path
import configparser


def _ensure_application() -> Tuple["QApplication", bool]:
    """Return a running QApplication instance, creating one if needed."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0]])
        return app, True
    return app, False


def run_launcher() -> Tuple[bool, float]:
    """Launch the PyQt6 UI and return (unlocked, injection_threshold)."""
    try:
        from PyQt6.QtCore import Qt, QEventLoop, QObject, QThread, pyqtSignal, QSize
        from PyQt6.QtGui import QIcon, QPixmap
        from PyQt6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QHBoxLayout,
            QLabel,
            QMessageBox,
            QPushButton,
            QSlider,
            QVBoxLayout,
            QWidget,
        )
    except ImportError:
        fallback_threshold = get_config_float("General", "injection_threshold", 0.5)
        print("[Launcher] PyQt6 not available; starting LeagueUnlocked directly.")
        return True, fallback_threshold

    app, created_app = _ensure_application()
    icon = None
    logo_pixmap = None
    settings_icon = None

    config_path = Path("config.ini")
    launcher_threshold = 0.5

    config = configparser.ConfigParser()
    if config_path.exists():
        try:
            config.read(config_path)
        except Exception as config_err:
            print(f"[Launcher] Failed to read config.ini: {config_err}")
    if not config.has_section("General"):
        config.add_section("General")
    if config.has_option("General", "injection_threshold"):
        try:
            launcher_threshold = float(config.get("General", "injection_threshold"))
        except ValueError:
            launcher_threshold = 0.5
    else:
        # Ensure default value is present
        config.set("General", "injection_threshold", f"{launcher_threshold:.2f}")
        with open(config_path, "w", encoding="utf-8") as f:
            config.write(f)

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

        settings_path = get_asset_path("settings.png")
        if settings_path.exists():
            settings_icon = QIcon(str(settings_path))
        else:
            print(f"[Launcher] Settings icon missing at {settings_path}")
    except Exception as icon_err:  # noqa: BLE001 - inform but continue without icon
        print(f"[Launcher] Failed to load icon: {icon_err}")

    if icon and created_app:
        app.setWindowIcon(icon)

    class SettingsDialog(QDialog):
        def __init__(self, parent: QWidget, initial_threshold: float) -> None:
            super().__init__(parent)
            self.setWindowTitle("Launcher Settings")
            self.setModal(True)
            self.value = initial_threshold

            layout = QVBoxLayout(self)
            description = QLabel("Injection Threshold (seconds)")
            layout.addWidget(description)

            self.value_label = QLabel(f"{initial_threshold:.2f}s")
            layout.addWidget(self.value_label)

            self.slider = QSlider(Qt.Orientation.Horizontal)
            self.slider.setRange(30, 200)  # Represents 0.30s to 2.00s (value / 100)
            self.slider.setSingleStep(1)
            self.slider.setValue(int(initial_threshold * 100))
            layout.addWidget(self.slider)

            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            layout.addWidget(buttons)

            self.slider.valueChanged.connect(self._handle_slider_change)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)

        def _handle_slider_change(self, raw_value: int) -> None:
            value = raw_value / 100.0
            self._update_value(value)

        def _update_value(self, value: float) -> None:
            self.value = value
            self.value_label.setText(f"{value:.2f}s")

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
                try:
                    updated = auto_update(self.status.emit, self.progress.emit)
                except Exception as update_err:  # noqa: BLE001
                    self.status.emit(f"Update failed: {update_err}")
                    updated = False

                if updated:
                    self.status.emit("Restarting after update...")
                    self.progress.emit(100)
                    os._exit(0)

                self.progress.emit(0)
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
            self.setWindowTitle(f"LeagueUnlocked Launcher {APP_VERSION}")
            self.setFixedSize(1280, 720)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            if icon:
                self.setWindowIcon(icon)

            self._status_text = "Checking skins..."
            self._progress_active = False
            self._progress_value = 0
            self.worker_thread: QThread | None = None
            self.worker: SkinDownloadWorker | None = None
            self.injection_threshold = launcher_threshold

            layout = QVBoxLayout()
            layout.setContentsMargins(32, 32, 32, 32)
            layout.setSpacing(24)

            header_layout = QHBoxLayout()
            self.settings_button = QPushButton()
            self.settings_button.setFlat(True)
            self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.settings_button.setFixedSize(48, 48)
            self.settings_button.setStyleSheet(
                "QPushButton { background-color: transparent; border: none; }"
                "QPushButton::hover { background-color: rgba(255, 255, 255, 30); border-radius: 6px; }"
            )
            if settings_icon:
                self.settings_button.setIcon(settings_icon)
                self.settings_button.setIconSize(QSize(32, 32))
            else:
                self.settings_button.setText("Settings")
            self.settings_button.clicked.connect(self._open_settings)
            header_layout.addWidget(self.settings_button, alignment=Qt.AlignmentFlag.AlignLeft)
            header_layout.addStretch(1)
            layout.addLayout(header_layout)

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

        def _open_settings(self) -> None:
            dialog = SettingsDialog(self, self.injection_threshold)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.injection_threshold = dialog.value
                config.set("General", "injection_threshold", f"{self.injection_threshold:.2f}")
                try:
                    with open(config_path, "w", encoding="utf-8") as f:
                        config.write(f)
                except Exception as err:
                    print(f"[Launcher] Failed to write config.ini: {err}")

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
    launcher_threshold = getattr(window, "injection_threshold", launcher_threshold)

    if created_app:
        app.quit()

    return unlocked, launcher_threshold

