"""
Simple PyQt6 launcher window for LeagueUnlocked.

Displays a centered UNLOCK button. When clicked, the window closes,
allowing the main application to continue starting up.
"""

from __future__ import annotations

import sys
from typing import Tuple


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
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QIcon, QPixmap
        from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget
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
                    320,
                    320,
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

    class LauncherWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("LeagueUnlocked Launcher")
            self.setFixedSize(1280, 720)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            if icon:
                self.setWindowIcon(icon)

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
            self.unlock_button.setStyleSheet(
                """
                QPushButton {
                    font-size: 24px;
                    font-weight: bold;
                }
                """
            )
            layout.addWidget(self.unlock_button, alignment=Qt.AlignmentFlag.AlignCenter)

            layout.addStretch(1)

            self.setLayout(layout)

            self.unlocked = False
            self.unlock_button.clicked.connect(self._handle_unlock)

        def _handle_unlock(self) -> None:
            self.unlocked = True
            self.close()

    window = LauncherWindow()
    window.show()
    window.activateWindow()
    window.raise_()

    if created_app:
        app.exec()
    else:
        from PyQt6.QtCore import QEventLoop

        loop = QEventLoop()
        window.destroyed.connect(loop.quit)
        loop.exec()

    unlocked = getattr(window, "unlocked", False)

    if created_app:
        app.quit()

    return unlocked

