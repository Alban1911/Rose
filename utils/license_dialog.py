"""
Simple License Dialog for LeagueUnlocked
Clean, classic Windows-style license activation dialog
"""

import sys
import os
from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon
from utils.logging import get_logger

log = get_logger()


class SimpleLicenseDialog(QDialog):
    """Simple, clean license activation dialog in Windows style"""
    
    def __init__(self, error_message: str = "", parent=None):
        super().__init__(parent)
        self.error_message = error_message
        self.license_key = None
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the user interface"""
        self.setWindowTitle("LeagueUnlocked - License Activation")
        self.setFixedSize(400, 200)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        
        # Set window icon if available
        try:
            from utils.paths import get_asset_path
            icon_path = str(get_asset_path("icon.ico"))
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except (OSError, FileNotFoundError, ImportError) as e:
            log.debug(f"Could not load window icon: {e}")
        except Exception as e:
            log.debug(f"Unexpected error loading icon: {e}")
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Title with LeagueUnlocked branding (shorter)
        title_label = QLabel("LeagueUnlocked - License Activation")
        title_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # Error message (if any)
        if self.error_message:
            error_label = QLabel(f"Error: {self.error_message}")
            error_label.setFont(QFont("Arial", 9))
            error_label.setStyleSheet("color: #d32f2f;")
            error_label.setWordWrap(True)
            layout.addWidget(error_label)
        
        # Input section - label and input on same line
        input_layout = QHBoxLayout()
        input_layout.setSpacing(10)
        
        # Label
        label = QLabel("License Key:")
        label.setFont(QFont("Arial", 10))
        label.setFixedWidth(80)  # Fixed width to align properly
        input_layout.addWidget(label)
        
        # Input field
        self.license_input = QLineEdit()
        self.license_input.setFont(QFont("Consolas", 10))
        self.license_input.setPlaceholderText("Enter your license key...")
        self.license_input.setFixedHeight(30)
        input_layout.addWidget(self.license_input)
        
        layout.addLayout(input_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFixedSize(80, 30)
        self.cancel_button.clicked.connect(self.reject)
        
        # OK button
        self.ok_button = QPushButton("OK")
        self.ok_button.setFixedSize(80, 30)
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self.on_ok_clicked)
        
        button_layout.addStretch()
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.ok_button)
        
        layout.addLayout(button_layout)
        
        # Focus on input field
        self.license_input.setFocus()
        
    def on_ok_clicked(self):
        """Handle OK button click"""
        license_key = self.license_input.text().strip()
        
        if not license_key:
            QMessageBox.warning(self, "Invalid Input", "Please enter a license key.")
            return  # Don't close dialog
            
        # Accept the license key - server will validate it
        self.license_key = license_key
        self.accept()
        
    def accept(self):
        """Accept the dialog (called only after validation passes)"""
        super().accept()
        
    def keyPressEvent(self, event):
        """Handle key press events"""
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self.on_ok_clicked()
        else:
            super().keyPressEvent(event)


def show_enhanced_license_dialog(error_message: str = "", parent=None) -> Optional[str]:
    """
    Show the simple license dialog
    
    Args:
        error_message: Error message to display (if any)
        parent: Parent widget
        
    Returns:
        License key if entered, None if cancelled
    """
    # Ensure we have a QApplication instance
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    
    dialog = SimpleLicenseDialog(error_message, parent)
    
    # Center the dialog
    screen = QApplication.primaryScreen().geometry()
    x = (screen.width() - dialog.width()) // 2
    y = (screen.height() - dialog.height()) // 2
    dialog.move(x, y)
    
    result = dialog.exec()
    
    if result == QDialog.DialogCode.Accepted:
        return dialog.license_key
    else:
        return None


if __name__ == "__main__":
    # Test the dialog
    app = QApplication(sys.argv)
    
    # Test with error message
    license_key = show_enhanced_license_dialog("No license found. Please activate your license.")
    print(f"License key entered: {license_key}")
    
    sys.exit(0)
