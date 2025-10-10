#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple test script to display the chroma button
Run this to preview button appearance without starting the full application
"""

import sys
from PyQt6.QtWidgets import QApplication, QWidget, QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette, QColor

# Import the button from chroma wheel
from utils.chroma_wheel import ReopenButton


class InfoWindow(QWidget):
    """Info window to show button is active"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chroma Button Test - Info")
        self.setGeometry(100, 100, 400, 250)
        
        # Set dark background
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(20, 20, 30))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        
        # Add label with instructions
        label = QLabel(self)
        label.setGeometry(20, 20, 360, 210)
        label.setWordWrap(True)
        label.setStyleSheet("color: white; font-size: 12px;")
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        from constants import (
            CHROMA_WHEEL_GOLD_BORDER_PX,
            CHROMA_WHEEL_DARK_BORDER_PX,
            CHROMA_WHEEL_GRADIENT_RING_PX,
            CHROMA_WHEEL_INNER_DISK_RADIUS_PX,
            CHROMA_WHEEL_BUTTON_SIZE
        )
        
        info_text = f"""<h3 style='color: #4CAF50;'>🎨 Chroma Button Test Active</h3>

<p><b>Look for the button in the CENTER of your screen!</b></p>

<p style='color: #FFD700;'><b>Current Settings:</b></p>
<ul style='line-height: 1.6;'>
  <li>Button size: {CHROMA_WHEEL_BUTTON_SIZE}px</li>
  <li>Gold border: {CHROMA_WHEEL_GOLD_BORDER_PX}px</li>
  <li>Dark border: {CHROMA_WHEEL_DARK_BORDER_PX}px</li>
  <li>Gradient ring: {CHROMA_WHEEL_GRADIENT_RING_PX}px</li>
  <li>Inner disk radius: {CHROMA_WHEEL_INNER_DISK_RADIUS_PX}px</li>
</ul>

<p style='color: #888;'><b>Instructions:</b><br>
• Hover over the center button to see the glow effect<br>
• Click the button to test interaction<br>
• Close this window to exit</p>
"""
        label.setText(info_text)
    
    def on_button_click(self):
        """Handle button click"""
        print("✓ Button clicked!")
        print("  If you want different dimensions, modify constants.py and run again.")


def main():
    """Main test function"""
    print("=" * 70)
    print("🎨 Chroma Button Test")
    print("=" * 70)
    from constants import (
        CHROMA_WHEEL_GOLD_BORDER_PX,
        CHROMA_WHEEL_DARK_BORDER_PX,
        CHROMA_WHEEL_GRADIENT_RING_PX,
        CHROMA_WHEEL_INNER_DISK_RADIUS_PX,
        CHROMA_WHEEL_BUTTON_SIZE
    )
    print(f"Button size: {CHROMA_WHEEL_BUTTON_SIZE}px")
    print(f"Gold border: {CHROMA_WHEEL_GOLD_BORDER_PX}px")
    print(f"Dark border: {CHROMA_WHEEL_DARK_BORDER_PX}px")
    print(f"Gradient ring: {CHROMA_WHEEL_GRADIENT_RING_PX}px")
    print(f"Inner disk radius: {CHROMA_WHEEL_INNER_DISK_RADIUS_PX}px")
    print()
    print("✓ Button will appear in the CENTER of your screen")
    print("✓ Hover to see glow effect")
    print("✓ Click to test interaction")
    print("✓ Close info window to exit")
    print("=" * 70)
    
    # Create Qt application
    app = QApplication(sys.argv)
    
    # Create info window
    info_window = InfoWindow()
    
    # Create the chroma button (it's a floating window)
    button = ReopenButton(on_click=info_window.on_button_click)
    button.show()  # Show the button!
    
    # Show info window
    info_window.show()
    
    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

